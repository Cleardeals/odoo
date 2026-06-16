# Code Smells — Diagnosis Patterns

Every smell has a name, a diagnosis test, and a prescription.
Examples are drawn from the actual Cleardeals codebase.

---

## Smell 1 — Long method

**Diagnosis test:** Method exceeds 20 lines, or requires a mental context
switch mid-reading (you finish one section and have to remember what the
outer method was doing).

**Example from codebase — `_process_lead_logic()`:**
```python
def _process_lead_logic(self):
    # 60+ lines doing: property lookup, RM lookup, fallback RM by portal,
    # state write, error handling — all in one method
```

**Why it hurts:** When something breaks in lead assignment, the developer
must read all 60 lines to understand which part failed. The method cannot
be unit tested in parts — only the whole thing can be tested.

**Prescription — extract named sub-tasks:**
```python
def _process_lead_logic(self):
    """Entry point — orchestrates lead assignment."""
    if self.state != STATE_NEW:
        return
    try:
        property_rec = self._find_property()
        rm_user = self._resolve_rm(property_rec)
        self._assign_lead(property_rec, rm_user)
    except Exception as e:
        self._mark_failed(e)

def _resolve_rm(self, property_rec):
    """Find the RM — from property if found, else portal default."""
    if property_rec:
        return self._find_rm(property_rec)
    return self._find_default_rm_for_portal()

def _find_default_rm_for_portal(self):
    """Return the configured default RM for this lead's portal."""
    portal_rm_map = self._get_portal_rm_config()
    target_name = portal_rm_map.get(self.source)
    rm = self.env["res.users"].search([("name", "ilike", target_name)], limit=1)
    if not rm:
        _logger.error("Default RM '%s' not found. Falling back to admin.", target_name)
        return self.env.ref("base.user_admin")
    return rm

def _assign_lead(self, property_rec, rm_user):
    """Write the assignment fields and transition to assigned state."""
    notes = (
        f"Assigned to RM {rm_user.name} "
        f"for property {property_rec.property_tag}."
        if property_rec else
        f"No property found. Assigned to default RM {rm_user.name}."
    )
    self.write({
        "property_base_id": property_rec.id if property_rec else False,
        "user_id": rm_user.id,
        "state": STATE_ASSIGNED,
        "process_notes": notes,
    })

def _mark_failed(self, error):
    """Transition lead to failed state with error details."""
    _logger.error("Lead %d assignment failed: %s", self.id, error, exc_info=True)
    self.write({
        "state": STATE_FAILED,
        "process_notes": f"Processing failed: {error!s}",
    })
```

The orchestrating method now reads as a specification. Each helper
can be tested and understood independently.

---

## Smell 2 — Magic values

**Diagnosis test:** A string literal or number appears in logic without
a name explaining what it means. Reading the code requires knowing the
domain to understand what the value represents.

**Example from codebase:**
```python
# Three separate smells:
if self.portal_name == "99acres":          # magic string — what is this?
    target_name = "Pratham Bhandari"       # magic string — who is this?
elif self.portal_name == "MagicBricks":
    target_name = "Mayuri Malivad"
else:
    target_name = "Naresh Rojiya"

# In migration scripts:
if source_col not in ("ninety_nine_acres_id", "housing_id", ...):  # inline tuple
```

**Why it hurts:**
- Changing a default RM requires a code deployment
- Typo in a portal name causes silent misrouting
- The meaning of the strings is invisible without domain knowledge

**Prescription — extract to named constants:**
```python
# At module level — visible, named, single place to change
PORTAL_99ACRES = "99acres"
PORTAL_MAGICBRICKS = "MagicBricks"
PORTAL_HOUSING = "Housing.com"
PORTAL_OLX = "OLX"

PORTAL_SELECTION = [
    (PORTAL_99ACRES, "99acres"),
    (PORTAL_MAGICBRICKS, "MagicBricks"),
    (PORTAL_HOUSING, "Housing.com"),
    (PORTAL_OLX, "OLX"),
]

# For configurable values — put in ir.config_parameter, not code
def _get_portal_rm_config(self):
    """Return portal → default RM name mapping from system parameters."""
    config = self.env["ir.config_parameter"].sudo()
    return {
        PORTAL_99ACRES:    config.get_param("leads.default_rm.99acres", "Pratham Bhandari"),
        PORTAL_MAGICBRICKS: config.get_param("leads.default_rm.magicbricks", "Mayuri Malivad"),
        PORTAL_HOUSING:    config.get_param("leads.default_rm.housing", "Naresh Rojiya"),
        PORTAL_OLX:        config.get_param("leads.default_rm.olx", "Naresh Rojiya"),
    }
```

Now changing a default RM is a configuration change, not a code deployment.

---

## Smell 3 — Duplication

**Diagnosis test:** The same block of code (more than 5 lines) appears in
two or more places. When you fix a bug in one, you must remember to fix
the others.

**Example from codebase — `property_sync.py` and `property_inventory.py`:**
```python
# property_sync.py lines ~767:
if row.ninety_nine_acres_id:
    vals["ninety_nine_acres_id"] = str(row.ninety_nine_acres_id)
if row.housing_id and row.housing_id not in ("None", "nan"):
    vals["housing_id"] = row.housing_id
# ... identical pattern repeated

# property_inventory.py lines ~321:
"ninety_nine_acres_id": row.ninety_nine_acres_id if row.ninety_nine_acres_id else False,
"housing_id": row.housing_id if row.housing_id else False,
# ... identical pattern repeated
```

**Why it hurts:** CDLS-121 required updating both files. Every future
BQ sync change will require updating both. One will inevitably drift
from the other over time.

**Prescription — single canonical helper:**
```python
# In a shared utility: custom_addons/properties/utils/bq_sync.py

def build_portal_listing_commands(env, property_id, bq_row):
    """
    Build ORM Command list for portal_listing_ids from a BigQuery result row.

    Used by both property_sync.py and property_inventory.py to ensure
    identical portal listing upsert behaviour.

    Args:
        env: Odoo environment
        property_id (int): The property.base record ID
        bq_row: A BigQuery row object with portal ID attributes

    Returns:
        list: ORM Command objects for portal_listing_ids field, or []
    """
    portal_data = [
        (PORTAL_99ACRES,     str(bq_row.ninety_nine_acres_id) if bq_row.ninety_nine_acres_id else None),
        (PORTAL_HOUSING,     bq_row.housing_id if bq_row.housing_id not in (None, "None", "nan", "") else None),
        (PORTAL_MAGICBRICKS, bq_row.magicbricks_id if bq_row.magicbricks_id not in (None, "None", "nan", "") else None),
        (PORTAL_OLX,         bq_row.olx_id if bq_row.olx_id not in (None, "None", "nan", "") else None),
    ]

    Listing = env["property.portal.listing"]
    commands = []

    for portal_name, listing_id in portal_data:
        if not listing_id:
            continue
        existing = Listing.search([
            ("portal_name", "=", portal_name),
            ("portal_listing_id", "=", listing_id),
        ], limit=1)
        if not existing:
            commands.append(fields.Command.create({
                "portal_name": portal_name,
                "portal_listing_id": listing_id,
                "active": True,
            }))
        elif existing.property_base_id.id != property_id:
            _logger.warning(
                "BQ sync conflict: listing %s/%s already on property %s",
                portal_name, listing_id, existing.property_base_id.id,
            )
    return commands
```

Both `property_sync.py` and `property_inventory.py` import and call
`build_portal_listing_commands`. One fix propagates to both.

---

## Smell 4 — Deep nesting

**Diagnosis test:** Code reaches 4+ levels of indentation. The "pyramid
of doom" pattern where each if-clause adds another level of nesting,
making the happy path invisible.

**Example:**
```python
def _process_lead_logic(self):
    if self.state == 'new':
        try:
            property_rec = self._find_property()
            if property_rec:
                rm_user = self._find_rm(property_rec)
                if rm_user:
                    self.write({...})
                else:
                    # fallback...
                    if self.portal_name == '99acres':
                        # even deeper...
```

**Prescription — early returns and guard clauses:**
```python
def _process_lead_logic(self):
    # Guard: only process new leads
    if self.state != STATE_NEW:
        _logger.info("Lead %d skipped — state is %s", self.id, self.state)
        return

    # Guard: must be called on a single record
    self.ensure_one()

    try:
        property_rec = self._find_property()
        rm_user = self._resolve_rm(property_rec)
        self._assign_lead(property_rec, rm_user)
    except Exception as e:
        self._mark_failed(e)
```

The guard clauses handle the exception cases at the top, leaving the
main flow unindented and readable.

---

## Smell 5 — Explaining comment (WHAT instead of WHY)

**Diagnosis test:** A comment that, if removed, would not change your
understanding of the code at all — because the code already says the
same thing.

**Examples:**
```python
# BAD — the comment is just the code in English
# Search for property with domain
domain = [(field_to_search, "=", portal_pid)]
return self.env["property.base"].search(domain, limit=1)

# BAD — the comment restates what the line obviously does
# Create new lead
new_lead = self.create(lead_vals)

# GOOD — the comment explains WHY, not WHAT
# Context must be set on `self` before super() — calling
# super().with_context().create() returns the same overridden method
# and causes infinite recursion.
new_leads = super(
    NewPortalLead,
    self.with_context(mail_create_nolog=True),
).create(vals_list)
```

**Prescription:** Delete comments that restate the code. If you feel the
code needs explanation, rename the variable or method so the code
explains itself. If you still feel the need to explain after renaming,
then write a WHY comment — explaining the reason for the approach,
not the mechanics.

---

## Smell 6 — Inconsistent abstraction level

**Diagnosis test:** A method mixes high-level intent (what the system
is trying to do) with low-level mechanics (how to do it in SQL or ORM).
You cannot skim the method — you have to read every line to understand
the overall purpose.

**Example:**
```python
def _cron_reprocess_unassigned_leads(self):
    _logger.info("CRON: Starting re-process for unassigned leads...")
    domain = [
        ("state", "=", "new"),
        ("create_date", "<", fields.Datetime.now() - timedelta(hours=1)),
    ]
    leads_to_retry = self.search(domain)
    _logger.info(f"CRON: Found {len(leads_to_retry)} unassigned leads to reprocess.")
    for lead in leads_to_retry:
        _logger.info(f"CRON: Re-processing lead {lead.id} synchronously...")
        try:
            lead._process_lead_logic()
        except Exception as e:
            _logger.error(...)
```

This is actually reasonably clean. The smell occurs when the search
domain is 15 lines long and inline SQL starts appearing alongside
high-level ORM calls.

**Prescription — extract the domain to a named method:**
```python
def _cron_reprocess_unassigned_leads(self):
    """Retry assignment for leads stuck in 'new' state."""
    leads_to_retry = self._find_stale_unassigned_leads()
    _logger.info("CRON: Found %d leads to reprocess.", len(leads_to_retry))
    for lead in leads_to_retry:
        self._safe_reprocess(lead)

def _find_stale_unassigned_leads(self):
    """Return 'new' leads older than the processing grace period."""
    grace_period = timedelta(hours=UNASSIGNED_LEAD_GRACE_PERIOD_HOURS)
    return self.search([
        ("state", "=", STATE_NEW),
        ("create_date", "<", fields.Datetime.now() - grace_period),
    ])

def _safe_reprocess(self, lead):
    """Reprocess one lead, logging but not propagating errors."""
    try:
        lead._process_lead_logic()
    except Exception as e:
        _logger.error("CRON: Failed to reprocess lead %d: %s",
                      lead.id, e, exc_info=True)
```

---

## Smell 7 — Primitive obsession

**Diagnosis test:** Domain concepts are represented as raw strings,
booleans, or integers when a named type (Selection field, constant,
or small class) would communicate their meaning and prevent invalid values.

**Example:**
```python
# 'new', 'assigned', 'failed' appear as raw strings throughout the codebase
if self.state == 'new':  # is this the right string? check the Selection...
    ...
if self.state == 'assigned':
    ...

# portal names appear as raw strings in 6 different files
if self.portal_name == "99acres":   # capitalisation? exact string?
    ...
if self.portal_name == "MagicBricks":   # is it "Magicbricks" or "MagicBricks"?
```

**Prescription — module-level constants:**
```python
# In new_portal_leads.py or a shared constants module:
STATE_NEW = "new"
STATE_ASSIGNED = "assigned"
STATE_FAILED = "failed"

# In property_portal_listing.py:
PORTAL_99ACRES = "99acres"
PORTAL_MAGICBRICKS = "MagicBricks"
PORTAL_HOUSING = "Housing.com"
PORTAL_OLX = "OLX"
```

Import the constants instead of spelling the strings each time. A typo
in a constant definition is caught immediately. A typo in a string literal
is caught only when that specific code path runs.