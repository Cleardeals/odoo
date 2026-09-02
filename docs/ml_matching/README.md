# Odoo work for the Property Matching Model (V2)

**Branch:** `feature/ml-matching-integration` (off `development_19`)
**Status:** design / documentation — no module code committed yet
**Counterpart repo:** `Property Matching Model V2` — the ML side. Its design docs are the source of truth for *why*; these docs are the source of truth for *what changes in Odoo*.

---

## What this folder is

The ML repo specifies a property-similarity model and an autonomous lead-generation system built on it. That system cannot exist without Odoo changes: it **reads** state Odoo does not currently express, and it **writes** leads that must be distinguishable from organic ones forever after.

This folder specifies the Odoo half. One document per subsystem, each covering: the data model, security, lifecycle, views/UX, migration, and tests.

## The boundary, stated once

| Direction | What moves | Who initiates |
|---|---|---|
| **Odoo → ML** | inventory, inquiries, site visits, escalations, boosts, buyer engagement state | ML pipeline pulls, nightly, read-only, over a versioned HTTP API |
| **ML → Odoo** | ranked *proposals*; Odoo admits and creates the leads | ML pipeline pushes to `/ml/v1/suggestions/batch` ([`04-lead-provenance.md`](04-lead-provenance.md)) |

**The ML system never writes escalations, boosts, or property fields.** It reads them. This is not a policy that can be relaxed later without redesign — it is the reason the human controls are trustworthy at all. See [`../escalation_management/`](../escalation_management/).

## Documents

| Doc | Covers | Status |
|---|---|---|
| [`00-scope-and-sequencing.md`](00-scope-and-sequencing.md) | **what is in the execution cycle and what is parked — read first** | drafted |
| [`01-read-contract.md`](01-read-contract.md) | the three `/ml/v1/` read endpoints, the HMAC buyer-key boundary, pagination, data-quality reporting | drafted |
| [`02-buyer-engagement-state.md`](02-buyer-engagement-state.md) | the buyer-level state the eligibility filter needs (transacted / negotiating / not-interested / dormant), derived across three status surfaces + the suppression list | drafted |
| [`03-rm-assist-integration.md`](03-rm-assist-integration.md) | **serving mode 1** — the `ml_suggest` client, insertion points in the RM workflow, degradation, feedback capture, contamination flags | drafted |
| [`03a-lead-form-full-surface.md`](03a-lead-form-full-surface.md) | complete field/button/tab/wizard inventory of the live lead form and what happens to each; specs for the frames Figma writes couldn't reach | drafted |
| [`04-lead-provenance.md`](04-lead-provenance.md) | **the write contract** — `POST /ml/v1/suggestions/*`, the five new models, the immutable provenance record, buyer-key resolution, the gate order | drafted |
| `05-manager-boost.md` | the boost control — a commercial preference, distinct from an escalation | parked |
| [`06-autonomous-mode-integration.md`](06-autonomous-mode-integration.md) | **serving mode 2** — the admission controller, the routing engine, what the RM sees, the ramp and the automatic halts | drafted |
| [`07-odoo-runtime-and-services.md`](07-odoo-runtime-and-services.md) | **the machine** — VM, containers, the five request paths, modules, tables, crons, pseudocode for the read/write/admission/routing paths, capacity, security, deploy | drafted |
| [`wireframes/`](wireframes/) | UI mockups for the above | — |

### Escalation is *not* specified here

The ML activation score takes an **escalation** signal, and the first draft of this folder tried to specify escalation as an ML input. That was the wrong boundary.

**Escalation management is a firm-wide system in its own right** — client complaints, service failures, how a case is raised, owned, worked, closed and reviewed. It has to exist whether or not the matching model is ever built. The ML system is *one read-only consumer* of one derived fact from it (*"does this property currently have an open, qualifying escalation?"*).

Specified separately in [`../escalation_management/`](../escalation_management/), and **parked** — see [`00-scope-and-sequencing.md`](00-scope-and-sequencing.md). The model trains, evaluates and serves with the escalation term reading zero for every property, so nothing here is blocked on it.

## Conventions followed

Same as the rest of the repo, so these specs are directly implementable:

- New models live in a new module under `custom_addons/`, never bolted onto `properties`.
- `security/ir.model.access.csv` + `security/<module>_security.xml`; groups declared inside `<data noupdate="1">`, record rules **outside** it so domain changes apply on upgrade (the pattern in `properties/security/property_security.xml`).
- Schema changes ship with `migrations/19.0.x.y.z/post-*.py`, idempotent, with a docstring explaining why the migration exists.
- API controllers use the established `validate_api_key` / `X-API-Key` / `ir.config_parameter` pattern (`properties/controllers/auth.py`).
- Tests under `tests/`, tagged, runnable via `run_tests.sh`.

## Working on this branch

Docs and module code both land here. Nothing merges to `development_19` until the module passes tests and a migration rehearsal against a prod snapshot (`odoo-prod-migration-check`).
