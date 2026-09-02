# Scope and sequencing — what is actually being built

**Branch:** `feature/ml-matching-integration`
**Read this before opening any other doc on this branch.**

---

## The execution cycle

**Get the property-matching model working, plus the Odoo tasks it directly needs.** Nothing else.

Everything on this branch is either in that cycle or explicitly parked. The distinction is stated on every document's first line.

| Area | In the cycle? | Where |
|---|---|---|
| The model itself — training, eval, promotion gate, serving | ✅ — the point | ML repo (`Property Matching Model V2`) |
| **Odoo read API** the pipeline pulls from | ✅ | [`01-read-contract.md`](01-read-contract.md) — drafted |
| **Buyer engagement state** — the eligibility filter needs it | ✅ | [`02-buyer-engagement-state.md`](02-buyer-engagement-state.md) — drafted |
| **RM-assist serving (mode 1)** | ✅ | [`03-rm-assist-integration.md`](03-rm-assist-integration.md) — drafted · provider: ML repo `docs/05-rm-assist-serving.md` |
| **Lead provenance + write contract** | ✅ | [`04-lead-provenance.md`](04-lead-provenance.md) — drafted |
| **Autonomous mode (mode 2)** — admission, routing | ✅ | [`06-autonomous-mode-integration.md`](06-autonomous-mode-integration.md) — drafted · provider: ML repo `docs/06-autonomous-generation-pipeline.md` |
| **Runtime / infrastructure** — what runs where | ✅ | [`07-odoo-runtime-and-services.md`](07-odoo-runtime-and-services.md) — drafted · counterpart: ML repo `docs/07-gcp-infrastructure-and-runtime.md` |
| Manager boost | 🅿 parked | not needed for a working model |
| **Escalation management** | 🅿 parked, planning only | [`../escalation_management/`](../escalation_management/README.md) |
| **Organisation structure** | 🅿 parked, note only | [`../organization/`](../organization/README.md) |

## Why escalation and org structure are parked

Both are real systems the firm needs. Neither is needed for a working model.

The escalation signal is **one of four** inputs to the activation score, weighted `0.30`, and the other three — starvation, expiry urgency, newness — are all derived from data Odoo already holds. **The model trains, evaluates and serves with the escalation term simply reading zero for every property.** It costs some targeting quality, nothing structural.

So the sequencing is: model first, escalation later, and the activation score picks up a signal it was already designed to accept.

Org structure is parked one level further out, because it is a dependency *of* escalation routing rather than of the model.

## What "planning only" means for those docs

They exist to stop the design being re-derived, and to record decisions made with evidence in hand — measured findings, existing-code constraints, gaps found by reading the actual modules. That work does not repeat cheaply, so it is written down.

They deliberately contain **no execution-level breakdown**: no task split, no estimates, no sprint mapping. Adding that now would produce a plan that is stale before it is used, and would create the impression that work is queued when it is not.

When one is picked up, its remaining docs get written then — against the codebase as it is at that point, not as it was today.

## Incremental order

1. **Model working end to end** — trains, passes the promotion gate, serves embeddings
2. **Odoo read contract** — the endpoints the nightly pipeline pulls ([drafted](01-read-contract.md))
3. **Buyer engagement state** — the one Odoo schema gap the eligibility filter genuinely cannot work around ([drafted](02-buyer-engagement-state.md))
4. **RM-assist serving** — the model as a tool inside the recommend-property wizard ([drafted](03-rm-assist-integration.md))
5. **Write path / provenance** — the contract, the schema, the immutable provenance record ([drafted](04-lead-provenance.md))
6. **Autonomous mode** — admission controller, routing engine, RM surfaces, the ramp ([drafted](06-autonomous-mode-integration.md))
7. *(later, separately)* escalation management, and org structure ahead of its routing

Each step is usable on its own. Nothing above requires anything below it.
