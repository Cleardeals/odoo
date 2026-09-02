# Escalation Management — domain and data model

**Module:** `custom_addons/escalations`
Part of the [Escalation Management System](README.md). Lifecycle and SLA mechanics are in [`02-lifecycle-sla-and-tiers.md`](02-lifecycle-sla-and-tiers.md).

---

## 1. Module layout

A first-class domain module, named like the other domain modules (`leads`, `properties`, `deals`) rather than like a feature add-on:

```
custom_addons/escalations/
  __manifest__.py                 depends: base, web, mail, properties
                                  NOT deals, NOT wa_communication (neither is on
                                  development_19) - both wired via optional seams
  models/
    escalation_case.py            escalation.case            the ticket
    escalation_category.py        escalation.category        taxonomy + SLA + owning team
    escalation_stage.py           escalation.stage           lifecycle stages, immutable codes
    escalation_resolution.py      escalation.resolution.option
    escalation_sla_policy.py      escalation.sla.policy
    escalation_hold_reason.py     escalation.hold.reason
    escalation_event.py           escalation.event           append-only transition log
    escalation_subject_mixin.py   the polymorphic subject resolver (§3)
    property_base_ext.py          smart button + open-case count on property.base
    res_users_ext.py              smart button for RM-subject cases
  wizards/
    escalation_raise_wizard.py    guided intake with dedup check
    escalation_close_wizard.py    coded resolution + mandatory note
    escalation_reassign_wizard.py reason-coded reassignment
    escalation_hold_wizard.py     reason + expected resume
    escalation_tier_wizard.py     manual tier push with justification
  controllers/                    (empty in v1 - the seam for portal/WhatsApp intake)
  data/
    escalation_stage_data.xml
    escalation_category_data.xml
    escalation_resolution_data.xml
    escalation_sla_policy_data.xml
    escalation_cron.xml           SLA sweep + digest
  security/
    escalations_security.xml      groups + record rules
    ir.model.access.csv
  views/  wireframe-backed views, menus last (Odoo 19 load order)
  migrations/19.0.1.0.0/          post-migrate config seeding (the noupdate trap)
  tests/
  docs/README.md                  pointer to docs/escalation_management/
```

**Why a new module and not fields on `property.base`:** a case is about a property *sometimes*. It is also about a deal, or a person. It has its own lifecycle, its own permissions, its own audit requirements, and it outlives the thing it is about. It is an entity, not an attribute.

## 2. `escalation.case` — the ticket

```python
class EscalationCase(models.Model):
    """
    A case: something is wrong, someone owns it, a clock is running.

    Cases are worked, not edited — every judgement call (reassign, hold, tier
    change, close, reopen) goes through a wizard that records a coded reason,
    and every transition appends an immutable escalation.event.
    """

    _name = "escalation.case"
    _description = "Escalation Case"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "priority desc, sla_deadline asc, id desc"
    _rec_name = "reference"
```

### 2.1 Identity

| Field | Type | Notes |
|---|---|---|
| `reference` | Char, `readonly`, `copy=False`, `index=True` | human handle, `ESC/2026/00417`, from an `ir.sequence`. People quote case numbers in conversation; a database id is not quotable |
| `name` | Char, required | one-line summary. The thing that shows in a list |
| `description` | Html, required | what happened |

### 2.2 Subject — polymorphic (§3)

| Field | Type | Notes |
|---|---|---|
| `subject_type` | Selection, required, `index=True` | `property` / `deal` / `rm`. Extensible by other modules |
| `subject_property_id` | Many2one → `property.base`, `ondelete="restrict"`, `index=True` | |
| `subject_user_id` | Many2one → `res.users`, `ondelete="restrict"`, `index=True` | the RM a conduct case is about |
| `subject_deal_ref` | Char, `index=True` | **placeholder until `deals` merges** — §3.3 |
| `subject_display` | Char, compute, stored | one denormalised label so lists, search and exports do not branch on type |

### 2.3 Classification

| Field | Type | Notes |
|---|---|---|
| `category_id` | Many2one → `escalation.category`, required, `index=True` | carries the SLA policy and the owning team |
| `severity` | Selection, required, `index=True` | `low` / `medium` / `high` / `critical` — **asserted by a human**, modifies the SLA (§`02` §4.3) |
| `priority` | Selection, compute, stored, `index=True` | derived from severity + tier + breach state; what the list actually sorts on. Not directly settable — a human sets *severity*, the system computes *priority*, so nobody hand-tunes their way to the top |
| `source` | Selection, required, `readonly` | `internal_ui` / `auto_rule` / `whatsapp` / `portal`. Set at creation, never changed |
| `source_rule_id` | Many2one → `ir.actions.server` or Char code | which rule auto-raised it (§`05`) |

### 2.4 Ownership and tier

| Field | Type | Notes |
|---|---|---|
| `owner_id` | Many2one → `res.users`, required, `index=True` | accountable **now** |
| `tier` | Selection, required, `default="l1"`, `index=True` | `l1` / `l2` / `l3` |
| `tier_changed_at` | Datetime, `readonly` | |
| `watcher_ids` | Many2many → `res.users` | via `message_follower_ids` where possible; explicit m2m for query-ability |
| `team_id` | Many2one → owning team | resolved from category; see `03-ownership-and-routing.md` |

### 2.5 Lifecycle and clocks

Detailed in [`02-lifecycle-sla-and-tiers.md`](02-lifecycle-sla-and-tiers.md); the fields:

| Field | Type | Notes |
|---|---|---|
| `stage_id` | Many2one → `escalation.stage`, required, `index=True` | |
| `opened_at` | Datetime, `readonly`, `default=now` | |
| `first_response_at` | Datetime, `readonly` | set once, by the first owner action |
| `closed_at` | Datetime, `readonly` | |
| `hold_since` / `hold_reason_id` / `hold_total_seconds` | | clock pausing |
| `sla_policy_id` | Many2one, `readonly` | **snapshotted at creation**, never followed live (§4.2) |
| `response_deadline` / `resolution_deadline` | Datetime, stored, recomputed on hold/tier change | |
| `is_breached` / `is_at_risk` | Boolean, **compute + search, not stored** | §4.1 |
| `breached_at` | Datetime, `readonly`, **stored** | §4.1 — the one clock fact that must be recorded, not derived |

### 2.6 Closure

| Field | Type | Notes |
|---|---|---|
| `resolution_id` | Many2one → `escalation.resolution.option` | required to close |
| `resolution_note` | Text | required, minimum length |
| `reopen_count` | Integer, `readonly` | a case reopened three times is a signal about the resolution, not the case |

### 2.7 Relationships

| Field | Notes |
|---|---|
| `parent_case_id` / `child_case_ids` | a listing case spawning a portal-data fix |
| `related_case_ids` | Many2many self, symmetric — "these are the same underlying problem" without merging |
| `merged_into_id` | set when merged; the merged case stays readable and is never deleted |

## 3. The polymorphic subject

### 3.1 Why not three separate models

`property.escalation`, `deal.escalation` and `rm.escalation` would triple the lifecycle, the SLA engine, the views, the permissions and the reporting — and the *only* thing that differs between them is which record the case points at. Every cross-subject question ("show me everything breached") would become a three-way union.

### 3.2 Why not Odoo's generic `res_model` / `res_id`

Tempting, and wrong here:

- **No referential integrity.** A `Char` model name plus an `Integer` id cannot be a foreign key, so a deleted subject leaves a dangling case that reads as valid.
- **Unusable in domains.** `[('subject_property_id.city', '=', 'Ahmedabad')]` is a normal filter; the same question through `res_id` needs Python.
- **Unusable in `read_group`.** Grouping breached cases by property city is a reporting requirement (§`07`), not an edge case.

### 3.3 The design: a discriminator plus real FKs

`subject_type` is the discriminator; one nullable, `restrict`-ed FK per concrete subject; a `@api.constrains` enforcing that **exactly one** matches `subject_type`:

```python
_SUBJECT_FIELDS = {
    "property": "subject_property_id",
    "rm":       "subject_user_id",
    # "deal":   "subject_deal_id",   <- added when the deals module merges
}

@api.constrains("subject_type", "subject_property_id", "subject_user_id")
def _check_exactly_one_subject(self):
    for rec in self:
        expected = _SUBJECT_FIELDS.get(rec.subject_type)
        filled = {f for f in _SUBJECT_FIELDS.values() if rec[f]}
        if expected and filled != {expected}:
            raise ValidationError(_(
                "A %s case must reference exactly one %s and nothing else.",
                rec.subject_type, expected,
            ))
```

Adding a subject is then: one FK, one selection value, one dict entry, one view field. No migration of existing cases.

**The `deals` gap, handled honestly.** `deals` is not on `development_19` — it is unmerged on `deal/odoo`. So:

- `subject_type` **includes `deal` from day one**, so the taxonomy and reporting do not change later.
- The reference is held in `subject_deal_ref` (Char) until the module lands, and the constraint treats `deal` as satisfied by that field.
- When `deals` merges: add `subject_deal_id`, backfill from `subject_deal_ref` in a post-migrate, move the dict entry, keep the Char column for one release as the audit of what was matched.

This is deliberately a **placeholder, not a pretence** — a Char reference has none of §3.2's integrity, and that is the price of not blocking the whole system on an unmerged branch. It is scoped to one field and one migration.

## 4. Clock state: derive it, store only the fact

Two decisions here, and they point in opposite directions on purpose.

### 4.1 `is_breached` is computed; `breached_at` is stored

`is_breached` is a **non-stored computed field with a `search` method**: `now > resolution_deadline AND stage is not closed`. There is no column, and no job maintains it.

> A stored breach flag maintained by a cron fails silently: **when a job that flips flags does not run, the absence of flips is indistinguishable from nothing needing to be flipped.** Cases would quietly stop registering as breached, and the only symptom is a breach dashboard that looks healthier than reality — the exact direction of error nobody investigates.
>
> This repo already has that shape: `properties/data/property_cron.xml` CRON 3 flips `property_base.is_active` off when `service_expiry_date` passes. Fine for that field; not acceptable for the number the firm is judged on.

`breached_at` **is** stored, because it is not derivable after the fact: once a case is closed, `resolution_deadline` and `closed_at` no longer tell you *when* it crossed the line if the deadline was later moved by a hold or a tier change. And a case closed late must read as late forever — §`02` §5.

So: **the boolean is a question about now, the timestamp is a historical fact.** Derive the first, record the second.

### 4.2 The SLA policy is snapshotted, not followed

`sla_policy_id` and the computed deadlines are copied onto the case at creation. If someone later relaxes a category's SLA from 24h to 72h, **cases already open keep the target they were opened under.**

Following the policy live would silently rewrite history: yesterday's breaches would disappear from the dashboard the moment a policy was edited, and the edit is exactly what someone under pressure would reach for. Snapshotting makes SLA changes forward-only, which is the only way breach counts stay comparable across months.

*(Same principle as the ML side's model bundle carrying its own scaler — the parameters that produced a number travel with the number.)*

## 5. Configuration models

All seeded as data, so a new category or resolution reason is a data change, not a deploy.

### 5.1 `escalation.category`

| Field | Notes |
|---|---|
| `name`, `code` | `code` **immutable after create**, per the `lead.site.visit.status` convention |
| `subject_type` | which subjects this category applies to — a "registration delayed" category is meaningless on an RM case |
| `sla_policy_id` | default policy |
| `team_id` / `default_owner_id` | who owns cases here — **the fallback when no hierarchy resolves** (README §3) |
| `is_restricted` | conduct categories need their own record rule (README §7.3) |
| `requires_attachment` | some categories are not credible without evidence |
| `active` | archivable; never deleted, since closed cases reference it |

### 5.2 `escalation.stage`

| Field | Notes |
|---|---|
| `code` | immutable; the state machine keys off code, never off name or id |
| `sequence` | kanban order |
| `is_open` / `is_hold` / `is_closed` / `is_cancelled` | behaviour flags — **exactly one must be true**, enforced by constraint, the same guard `lead.site.visit.status` uses for its type flags |
| `stops_clock` | whether SLA pauses here |
| `requires_resolution` | whether leaving to this stage needs a coded resolution |

Behaviour lives in **flags on data**, not in a hardcoded list of stage names. Adding a stage must not require a code change.

### 5.3 `escalation.resolution.option`

Mirrors `lead.site.visit.feedback.option` deliberately — the firm already reads outcomes in this shape:

| Field | Notes |
|---|---|
| `code` | immutable, globally unique |
| `category` | `pricing` / `property` / `process` / `conduct` / `client` / `other` — *what kind of thing was wrong* |
| `management_signal` | `resolved` / `mitigated` / `not_our_fault` / `loss` / `no_action` — *what it means to management* |
| `requires_note` | as on the existing feedback option |
| `counts_as_success` | separates "we fixed it" from "we closed it" — the distinction that makes closure rates honest |

`counts_as_success` is the load-bearing one. Without it, closure rate measures **activity**, and the fastest way to a good number is to close cases with `no_action`.

### 5.4 `escalation.sla.policy`

| Field | Notes |
|---|---|
| `response_hours` / `resolution_hours` | targets |
| `severity_multipliers` | how `critical` compresses the target (§`02` §4.3) |
| `calendar_id` | business hours — a Sunday should not burn SLA (README §7.2) |
| `tier_escalation_hours` | per-tier dwell before auto-push |

## 6. `escalation.event` — the audit trail

Every transition appends one row. Never updated, never deleted.

| Field | Notes |
|---|---|
| `case_id` | required, `ondelete="restrict"` |
| `event_type` | `created` / `assigned` / `stage_changed` / `tier_changed` / `held` / `resumed` / `breached` / `closed` / `reopened` / `merged` |
| `from_value` / `to_value` | Char, rendered labels — readable without joining to config that may since have been archived |
| `reason_code` / `reason_text` | the coded justification the wizard captured |
| `actor_id`, `occurred_at` | `create_uid` / `create_date` mirrors |
| `is_system` | true when a rule or the SLA sweep acted, not a person |

### 6.1 Why not rely on `mail.thread` tracking

`mail.thread` gives chatter, and chatter is genuinely useful for narrative. It is not an audit trail:

- Tracked values are stored as rendered message bodies — **not queryable**. "Median time from L1 to L2 by category" is not answerable from chatter.
- Messages can be deleted by users with the right permissions.
- Tracking records *that* a field changed, not the **reason code** attached to the change, which is the whole point of forcing wizards.

So: **both.** `mail.thread` for the human narrative, `escalation.event` for the queryable, immutable record. `escalation.event` is what §`07`'s reporting reads.

### 6.2 Immutability, enforced twice

```python
def write(self, vals):
    raise UserError(_("Escalation events are immutable — they are the audit trail."))

def unlink(self):
    raise UserError(_("Escalation events are never deleted."))
```

…plus `perm_write = 0`, `perm_unlink = 0` in the ACL **for every group, with no exception** — including the actor who created the row and including administrators. The code override catches ORM calls; the ACL catches paths the override does not sit on (`sudo()` from another module, bulk operations, uninstall cleanup). Neither alone is sufficient.

## 7. Sequence and dedup

**Reference** comes from an `ir.sequence` with a yearly prefix (`ESC/%(year)s/`). Cases are never renumbered, and a merged case keeps its reference — people have quoted it.

**Deduplication happens in the raise wizard, not in a constraint.** Before creating, the wizard searches open cases on the same subject and category and shows them:

```
2 open cases already exist on this property:
  ESC/2026/00391  Owner unhappy with portal listing   L2  breached
  ESC/2026/00402  Photos not updated                  L1  due in 6h
  [ Add to ESC/2026/00391 ]  [ Raise a separate case ]  [ Cancel ]
```

A uniqueness constraint would be wrong: two genuinely different things can go wrong on one property at once. The duplicate problem is a **human** one — someone not knowing a case exists — so the fix is showing them, not refusing them.

## 8. What is deliberately not modelled in v1

| Not building | Why |
|---|---|
| Client-visible replies on a case | changes tone, audit and permission requirements sharply. Internal-only for v1; revisit with the WhatsApp channel (README §7.4) |
| Buyer lead / inquiry as a subject | buyer complaints arrive as property or RM cases until there is a reason to split them |
| Time-tracking / billing | no consumer for it |
| Per-case custom fields | categories cover the variation; custom fields become an unqueryable dumping ground |
| A satisfaction survey loop | worth doing, needs the client channel first |
