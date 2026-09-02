# Organisational structure — parked note

**Status:** 🅿 **PARKED — not in any execution cycle.** Recorded so the need and the shape are not rediscovered later.
**Would be:** `custom_addons/organization` (new module)

---

## Why this note exists

Nothing in Odoo can answer *"who is this person's manager?"* — verified across `custom_addons`: no `hr` dependency, no `hr.employee` reference, no `manager_id` or team model, `res.users` is not extended, and `property_base.rm_user_id` is a flat FK.

Several planned things need that answer (escalation tier routing, per-team dashboards, lead-reassignment eligibility). **None of them are in the current execution cycle**, so this is not being built. It is written down because the gap gets rediscovered every time one of those is planned.

## The minimum it would need

| Piece | Purpose |
|---|---|
| `org.unit` | hierarchical node (region / team), `_parent_store` so `child_of` works in domains |
| `org.role` | `head` / `member`, with a flag marking which role is the escalation target |
| `org.assignment` | person × unit × role, **with `date_from` / `date_to`** |
| One resolver method | `manager_of(user, at=None)` — the only thing consumers call |

## The one design point worth not forgetting

**Membership should be effective-dated, not a field on the person.**

A `user.manager_id` field answers only "who is their manager now". Overwriting it **silently rewrites the past**: reopening a six-month-old escalation would route it to whoever holds the seat today, and the audit trail would name the wrong person. Historical reporting by team changes after every reorg. Once overwritten, the previous state is gone — unrecoverable.

Dated assignment rows cost almost nothing extra at build time and are the difference between a structure that survives a few reorgs and one that has to be rebuilt.

Second, smaller point: any convenience field (`current_manager_id` on `res.users`) should be **computed, not stored**, because the value changes by the mere passage of time when a `date_to` passes. A stored version needs a refresh job, and a failed refresh job leaves stale routing that looks exactly like correct routing.

## Why not `hr`

`addons/hr` and `addons/hr_org_chart` are present and could supply `hr.employee.parent_id`. Not chosen because it means installing HR on production and creating an employee record per person (there are currently zero), and because `parent_id` is a single undated field — the shape the point above argues against, whichever module provides it.

If HR is adopted later for its own reasons, the two can be bridged; the dated assignment table should stay authoritative for routing, since two writable sources of truth for the same question disagree silently.

## The real cost

The model is small. **Keeping it accurate is the actual cost**, and it is the reason this is parked rather than "quick". It needs a named owner and a review cadence, or it becomes stale data that routes cases to people who left — which is worse than having no hierarchy at all, because the failure is invisible.

## Consumers, when it exists

- `escalation_management` — tier ladder L1→L2→L3 and "my team's cases" visibility ([`../escalation_management/README.md`](../escalation_management/README.md) §3)
- `leads` — `lead_bulk_reassign_wizard.new_rm_id` currently has **no domain at all**, so leads can be bulk-moved to a portal or deactivated user
- `cleardeals_dashboards` — per-team rollups instead of per-user lists
