# Automation Design Standards

The goal of automation is to eliminate the gap between "what a user must do
manually" and "what the system already knows how to do". Every manual step that
can be automated is a mistake waiting to happen — either the user forgets it,
does it wrong, or does it inconsistently.

---

## The automation decision framework

For every step in a user's workflow, ask this sequence:

```
1. Can the system derive this value from existing data?
   YES → use a computed field (compute=)

2. Can the system set a sensible default that is correct 90%+ of the time?
   YES → use field default= or default_get() override

3. Does this happen when a record is created or updated?
   YES → use create() or write() override

4. Is this triggered by a specific field changing value?
   YES → use @api.onchange() for UI feedback, write() override for persistence

5. Does this involve notifying someone or sending data externally?
   YES → use message_post() in write() or a short-interval cron

6. Does this need to run on a schedule regardless of user action?
   YES → use a cron job

7. Does this require human judgment before executing?
   YES (and only then) → use a manual button action
```

Work through this sequence for every step. If you reach step 7, ask
again whether the judgment can be encoded as a rule. "An RM must decide
which default RM to assign" is often really "assign based on portal type"
— which is step 3, not step 7.

---

## The Cleardeals automation reference — lead pipeline

This is the gold standard for automation in this codebase. Every new
feature should aspire to this ratio of automated vs manual steps.

```
WHAT HAPPENS AUTOMATICALLY:
━━━━━━━━━━━━━━━━━━━━━━━━━━
Portal lead arrives
  → create() called with state='new', source='MagicBricks'
  → create_lead_if_not_duplicate() deduplicates in same transaction
  → _process_lead_logic() finds property via resolve_property()
  → _find_rm() assigns the property's RM
  → write() sets state='assigned', user_id, property_base_id, process_notes
  → first_contact_datetime stamped by write() on first status change
  → _cron_reprocess_unassigned_leads() retries failures every 4 hours
  → _cron_send_new_lead_webhooks() dispatches to n8n every minute
  → n8n sends WhatsApp notification to the RM

WHAT THE RM DOES MANUALLY:
━━━━━━━━━━━━━━━━━━━━━━━━━━
  → Opens the lead (already assigned to them, property already linked)
  → Calls the client (WhatsApp button is one click)
  → Updates current_status and remarks (2 field changes)
  → Schedules site visit if relevant (1 field change)
```

The RM's cognitive load is minimal because the system handled everything
that could be inferred. The RM only contributes the judgment that only
they can provide: the client conversation outcome.

---

## Automation patterns with code

### Pattern 1: Field defaults

Use when the value is correct in the vast majority of cases without
any user input.

```python
# Simple scalar default
state = fields.Selection(
    ...,
    default="new",           # portal leads always start new
)

is_active = fields.Boolean(
    default=True,            # new listings are active
)

# Dynamic default using a lambda
user_id = fields.Many2one(
    "res.users",
    default=lambda self: self.env.uid,  # assign to current user
)

# Default from system parameter
@api.model
def _default_source(self):
    return self.env["ir.config_parameter"].sudo().get_param(
        "leads.default_source", default=False
    )
source = fields.Char(default=_default_source)
```

### Pattern 2: default_get() for conditional defaults

Use when the default depends on context or other field values
that are not available via lambda.

```python
@api.model
def default_get(self, fields_list):
    """
    Override to set state=assigned and user_id=current user
    for manually created leads (not portal leads).

    Portal leads pass context={'portal_lead_creation': True} to opt out.
    Manual leads (no context) get the RM pre-filled and start assigned.
    """
    defaults = super().default_get(fields_list)

    if not self.env.context.get("portal_lead_creation"):
        # Manual lead: pre-fill the creating RM and start assigned
        if "user_id" not in defaults or not defaults.get("user_id"):
            defaults["user_id"] = self.env.uid
        if "state" not in defaults:
            defaults["state"] = "assigned"

    return defaults
```

### Pattern 3: Computed fields (automatic derivation)

Use when a value can always be calculated from other fields.

```python
@api.depends("site_visit_date")
def _compute_site_visit_date_only(self):
    """
    Extract the date portion from site_visit_date Datetime.
    Stored for use in list view filters and group-by.
    Without store=True, filtering by date would require a function domain.
    """
    for rec in self:
        rec.site_visit_date_only = (
            rec.site_visit_date.date() if rec.site_visit_date else False
        )

@api.depends("property_base_id", "interest_ids.property_base_id")
def _compute_all_associated_properties(self):
    """
    Combine the primary property and all recommended properties into
    a single Many2many for search and reporting purposes.
    This powers the 'associated with property X' filter across all leads.
    """
    for lead in self:
        properties = lead.property_base_id
        if lead.interest_ids:
            properties |= lead.interest_ids.mapped("property_base_id")
        lead.all_associated_properties = properties
```

### Pattern 4: write() override for business logic

Use when a value must be stamped or triggered on specific field changes.

```python
def write(self, vals):
    """
    Override write to:
    1. Stamp first_contact_datetime when status changes from 'lead'
    2. Send bus notification for live list updates
    """

    # Capture leads to stamp BEFORE super() — we need the old value
    leads_to_stamp = self.env["leads.new"]
    if "current_status" in vals and vals["current_status"] != "lead":
        # Only stamp if this is the first non-lead status change
        leads_to_stamp = self.filtered(lambda r: not r.first_contact_datetime)

    res = super().write(vals)

    # Stamp after super() so the write succeeds before the stamp
    if leads_to_stamp:
        leads_to_stamp.write({"first_contact_datetime": fields.Datetime.now()})
        # NOTE: This recursive write() is safe because first_contact_datetime
        # is not in the condition that triggers leads_to_stamp. No infinite loop.

    # Bus notification for real-time list refresh
    self.env["bus.bus"]._sendone(
        "leads.new",
        "bus_notification",
        {"ids": self.ids, "model": "leads.new", "event": "write"},
    )

    return res
```

### Pattern 5: create() override for mandatory post-creation logic

Use when something must happen for every new record regardless of source.

```python
@api.model_create_multi
def create(self, vals_list):
    """
    Override create to:
    1. Force state=assigned for manual leads (no portal source)
    2. Suppress chatter noise on creation
    3. Send bus notification
    """
    for vals in vals_list:
        # Belt-and-suspenders guard: if default_get didn't run
        # (programmatic create, not form create), enforce manually.
        if not vals.get("source") and vals.get("state", "new") == "new":
            vals["state"] = "assigned"
            if not vals.get("user_id"):
                vals["user_id"] = self.env.uid

    new_records = super(
        NewPortalLead,
        self.with_context(mail_create_nolog=True),
        # mail_create_nolog=True: suppress the "Record created" chatter
        # message — it adds noise without information for this model
    ).create(vals_list)

    # Real-time notification
    self.env["bus.bus"]._sendone(
        "leads.new",
        "bus_notification",
        {"ids": new_records.ids, "model": "leads.new", "event": "create"},
    )

    return new_records
```

### Pattern 6: Cron jobs for periodic automation

Use when the automation must run on a schedule regardless of user action.

```python
@api.model
def _cron_reprocess_unassigned_leads(self):
    """
    Retry lead assignment for leads stuck in state='new'.

    Runs every 4 hours. Targets leads older than 1 hour to give the
    synchronous _process_lead_logic() time to complete first.

    Design intent: the 1-hour grace period prevents the cron from
    competing with the synchronous path on fresh leads. The 4-hour
    frequency means no lead waits more than 5 hours for assignment
    in the worst case (created just after a cron run).
    """
    _logger.info("CRON: Starting re-process for unassigned leads...")

    domain = [
        ("state", "=", STATE_NEW),
        ("create_date", "<", fields.Datetime.now() - timedelta(hours=1)),
    ]
    leads_to_retry = self.search(domain)
    _logger.info("CRON: Found %d unassigned leads.", len(leads_to_retry))

    for lead in leads_to_retry:
        try:
            lead._process_lead_logic()
        except Exception as e:
            _logger.error(
                "CRON: Failed to reprocess lead %d: %s",
                lead.id, e, exc_info=True,
            )
```

---

## What automation cannot replace

Never automate:
- The content of a client conversation (current_status, remarks)
- The judgment of whether a property matches a buyer's needs
- The decision to escalate a lead to a senior RM
- Actions with irreversible consequences (deletion, external payments)

These require human judgment. Design the UI to make human judgment
fast and well-informed — not to replace it.

---

## The automation anti-patterns

**Anti-pattern: automating without logging**
Every automated action must log what it did and why. A cron that runs
silently gives you nothing to debug when it goes wrong.

```python
# BAD
self.write({"state": STATE_ASSIGNED, "user_id": rm_user.id})

# GOOD
notes = f"Assigned to RM {rm_user.name} for property {property_rec.property_tag}."
_logger.info("Lead %d: %s", self.id, notes)
self.write({
    "state": STATE_ASSIGNED,
    "user_id": rm_user.id,
    "process_notes": notes,
})
```

**Anti-pattern: automating the wrong default**
A default that is wrong 30% of the time is worse than no default.
The user corrects the wrong default, creating an extra step.
Only use defaults when they are correct 90%+ of the time.

**Anti-pattern: automating without a fallback**
Every automated path needs a graceful failure state that a human can act on.

```python
# BAD — fails silently, lead disappears
if not rm_user:
    return

# GOOD — failure is visible and actionable
if not rm_user:
    _logger.error("No RM found for property %s", property_rec.id)
    self.write({
        "state": STATE_FAILED,
        "process_notes": f"No RM assigned to property {property_rec.property_tag}.",
    })
```