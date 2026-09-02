# The write contract, provenance, and the schema behind it

**Branch:** `feature/ml-matching-integration` · **Status:** design · **Date:** 2026-07-31
**Provider side:** ML repo `docs/06-autonomous-generation-pipeline.md` — what the pipeline proposes and why.
**Consumer side:** [`06-autonomous-mode-integration.md`](06-autonomous-mode-integration.md) — admission, routing, and what people see.

This document specifies **the endpoints Odoo exposes for writing, the tables that hold the result, and the provenance every AI-originated lead carries forever.**

---

## 1. Why provenance comes first, before any of it works

Doc 04 in the ML repo names three rules as *unrecoverable if skipped*. Two of them are schema:

> **Provenance tags on every AI-created lead from the very first one.** You cannot retroactively mark which leads the system caused.
> **A buyer-level holdout from lead one.** You cannot retroactively build a control group.

Everything else in this branch can be revised later. These two cannot: the information simply does not exist afterwards. If the first AI lead is created without them, the question *"did this system work?"* becomes permanently unanswerable, and every subsequent conversation about it is an argument about attribution.

So the schema lands **before** the first generated lead, not alongside it.

The third rule — AI-originated activity must be excluded or ablated in training — is a consequence of the first: it is only possible if the flags exist.

---

## 2. Module and boundaries

New module `custom_addons/ml_suggest_write/`, sibling to the read module **`ml_api`** (`01-read-contract.md` §11).

**Why not extend the read module.** `01-read-contract.md` §12 lists a test — `test_no_write_route_exists` — asserting that *nothing* under the read module's routes accepts POST/PUT/PATCH/DELETE. That test is a real safety property: it makes "the ML pipeline cannot write" a mechanically enforced fact rather than a convention. Adding write routes to that module deletes the test and the guarantee with it.

Two modules, opposite directions, opposite permissions, separately uninstallable. The read key and the write key are **different credentials with different scopes**, so a leaked read key cannot create leads.

| | `ml_api` (read) | `ml_suggest_write` (write) |
|---|---|---|
| Routes | `GET /ml/v1/*` | `POST /ml/v1/suggestions/*` |
| Credential | read API key | **separate** write API key |
| Can it create a lead? | no, structurally | yes, only via the admission controller |

---

## 3. The write contract

### 3.1 `POST /ml/v1/suggestions/batch`

Submits one night's ranked proposals. **Accepting is not admitting** — this endpoint validates and stores; admission runs after (§4 of `06-autonomous-mode-integration.md`).

```json
{
  "batch_id": "gen-2026-08-04-0430",
  "model_version": "2026-08-03.2",
  "generated_at": "2026-08-04T04:31:12Z",
  "policy_snapshot": { "global_daily_cap": 20, "oversupply_factor": 3.0 },
  "proposals": [
    {
      "proposal_uid": "gen-2026-08-04-0430:00001",
      "rank": 1,
      "buyer_key": "7c1e…",
      "property_uuid": "…",
      "match_score": 0.7412,
      "activation_reason": "starved",
      "activation_score": 0.81,
      "source_property_uuid": "…",
      "basket_size": 3,
      "top_basket_contribution": { "property_uuid": "…", "similarity": 0.79 }
    }
  ]
}
```

**`rank` is the allocation order, not a score sort.** The pipeline's coverage-round allocation (ML doc 06 §4.4) is expressed entirely in this field, and the admission controller's walk preserves it. If a future change sorts by `match_score` on either side, the system silently reverts to giving its whole budget to properties that were never starved — the exact failure the allocation exists to prevent. Asserted by `test_admission_preserves_rank_order`.

**`top_basket_contribution` exists for one reason: the RM has to be told *why*.** A lead with no explanation is a lead an RM distrusts, and doc 04 §9 makes explainability a design requirement rather than a nicety. It renders as *"matched to a property they visited in March, 0.79 similar."*

**Validation, before anything is stored:**

| Check | Failure |
|---|---|
| `batch_id` well-formed and unseen, or seen with an identical body hash | `409` on a changed body (§3.4) |
| `model_version` non-empty | `422` |
| `rank` values contiguous from 1, no duplicates | `422` — a gap means the pipeline dropped rows after allocating |
| `proposal_uid` unique within batch | `422` |
| no field matches phone/email/name patterns | `422`, and **alert** — this is a boundary breach, not a typo |
| batch size ≤ `max_batch_size` | `413` |

The whole batch is rejected on any failure. A partially-accepted batch would have a rank sequence with holes, and every guarantee above rests on that sequence being intact.

### 3.2 `GET /ml/v1/suggestions/batch/{batch_id}`

The reconciliation endpoint. Returns per-proposal outcome and the aggregate the pipeline writes to `admission.parquet`:

```json
{ "batch_id": "gen-2026-08-04-0430",
  "state": "admitted",
  "counts": { "submitted": 60, "admitted": 19, "rejected": 41 },
  "rejections": { "holdout_control": 6, "suppressed": 2, "cap_global": 28,
                  "cap_buyer_monthly": 3, "no_eligible_rm": 1, "duplicate_cooldown": 1 },
  "created_lead_ids": [123456, …] }
```

The `rejections` breakdown is the single most useful diagnostic the system produces, and it is why rejected proposals are stored rather than dropped. *"19 leads created"* tells you nothing. *"19 created, 28 blocked by the global cap"* says the ramp is the binding constraint and the model is producing more usable demand than policy allows — an argument to widen. *"19 created, 28 below the quality floor"* would say the opposite.

### 3.3 `POST /ml/v1/suggestions/batch/{batch_id}/rollback`

Doc 04 §8 requires batch-level rollback. What it does:

| Lead state | Action |
|---|---|
| Untouched by any human (no chatter, no status change, not opened) | **archived**, with a chatter entry naming the rollback |
| Touched — an RM called, changed status, or scheduled anything | **kept**, flagged `rollback_skipped` |

**Never hard-delete, and never revoke a lead a human has already worked.** An RM who called a buyer this morning cannot have that conversation un-happened by a batch rollback, and a lead vanishing from under someone is a far worse failure than a bad lead surviving. The response names every skipped lead so the operator knows exactly what the rollback did not undo.

Rollback is also available to a manager in the UI. It is not an ML-only capability — the people who will need it at 9am are the ones who cannot deploy anything.

### 3.4 Idempotency

Keyed on `(batch_id, proposal_uid)` with a unique constraint, so retries are safe at the row level, and on a stored `body_sha256` at the batch level.

| Situation | Behaviour |
|---|---|
| Same `batch_id`, identical body | `200`, current state, nothing created |
| Same `batch_id`, **different** body | `409 batch_id_reused_with_different_content` |
| Odoo committed, response lost, pipeline retries | `200` with the committed result |

The `409` matters more than it looks. Silently accepting changed content under a used `batch_id` would let a re-run overwrite the record of what was actually sent to real people — and that record is the audit trail. Regenerating means a **new** `batch_id`, always.

### 3.5 Authentication

`X-API-Key`, same mechanism as the read contract (`01-read-contract.md` §5), **different key**, stored in Secret Manager and not in `ir.config_parameter` — the same reasoning that moved the buyer-key pepper out of the database, since `ir.config_parameter` travels inside a prod DB snapshot.

Direction determines the mechanism, deliberately: **Odoo→ML uses GCE metadata ID tokens + IAM** (both inside GCP, no secret exists); **ML→Odoo uses an API key** because Odoo's HTTP layer has no IAM concept. Consistent reasoning, different constraints.

---

## 4. Resolving a buyer — the problem the HMAC creates

The pipeline identifies buyers by `buyer_key = HMAC-SHA256(pepper, canonical_phone)`. HMAC is one-way. **Odoo must therefore be able to go from `buyer_key` back to a phone number, and it cannot invert the function.**

This is a real consequence of the DPDP-driven design in `01-read-contract.md` §4, and it has to be solved deliberately rather than discovered during implementation.

**Decision: store the key, indexed, computed once at write time.**

```python
# on leads.new
buyer_key = fields.Char(
    "Buyer Key (HMAC)", index=True, readonly=True, copy=False,
    help="HMAC-SHA256 of the canonical phone. Written on create/phone-change; "
         "the join key for ML proposals. Never displayed to users.",
)
```

Computed in `create()` and in `write()` when `phone` changes, using the **same** `normalize_phone_to_10_digit()` the read contract uses. Not a `compute` field with `store=True`: a recompute triggered by an unrelated ORM event would silently rewrite the join key of 130k rows.

| Alternative | Why not |
|---|---|
| Rainbow table of all 10-digit numbers | 10¹⁰ entries, and it defeats the pepper entirely |
| Pipeline sends phone numbers back | throws away the whole PII boundary at the last step |
| Odoo computes the HMAC per lookup and scans | full-table HMAC per proposal; unusable |
| A buyer master with a stable token | the right long-term answer — see `02-buyer-engagement-state.md` §5.2. Disproportionate to build now |

**The pepper-rotation consequence, stated now so it is not discovered later.** Rotating the pepper invalidates every stored `buyer_key` and every in-flight proposal. Rotation is therefore a **planned migration**, not an ops action: drain open batches → recompute the column → resume. A rotation performed casually would not error; it would just stop matching buyers, and generation would quietly fall to zero. That is the failure mode to design the runbook against.

**Resolution can be ambiguous, and ambiguity is not an error.** One `buyer_key` maps to every lead sharing that phone — which is correct, since the buyer *is* the phone (`CLAUDE.md`: 99.8% clean 10-digit, baskets are reliable). The controller resolves to the **buyer**, and separately decides which lead record the new suggestion attaches to. Zero matches is a genuine anomaly — a buyer proposed from a snapshot whose leads have since been deleted — and is recorded as `rejected_buyer_not_found` rather than swallowed.

---

## 5. Tables

Five new models. Deliberately small: nothing here duplicates state that already exists in `leads_new`.

### 5.1 `ml.suggestion.batch`

```python
_name = "ml.suggestion.batch"
_inherit = ["mail.thread"]

batch_id        = fields.Char(required=True, index=True, copy=False)   # unique
model_version   = fields.Char(required=True, index=True)
generated_at    = fields.Datetime(required=True)
received_at     = fields.Datetime(readonly=True)
body_sha256     = fields.Char(readonly=True)
policy_snapshot = fields.Json(readonly=True)     # caps in force AT ADMISSION, not at generation
state           = fields.Selection([("received","Received"), ("admitting","Admitting"),
                                    ("admitted","Admitted"), ("failed","Failed"),
                                    ("rolled_back","Rolled Back")], default="received", tracking=True)
```

`policy_snapshot` records the caps **as the admission controller saw them**, not as the pipeline proposed them. When someone asks in November why only 19 leads were created on 4 August, the answer has to be readable without reconstructing what the config was that day.

### 5.2 `ml.suggestion.proposal`

One row per proposed pair — **including every rejected one**.

```python
proposal_uid      = fields.Char(required=True, index=True)
batch_id          = fields.Many2one("ml.suggestion.batch", ondelete="cascade", index=True)
rank              = fields.Integer(required=True)
buyer_key         = fields.Char(required=True, index=True)
property_base_id  = fields.Many2one("property.base", index=True)
match_score       = fields.Float(digits=(4, 4))
activation_reason = fields.Selection([("starved",…), ("escalated",…), ("expiring",…),
                                      ("new",…), ("boosted",…)])
state             = fields.Selection([("pending",…), ("admitted",…), ("rejected",…)],
                                     default="pending", index=True)
rejection_reason  = fields.Selection([...])      # §6.2 — the full ordered list
lead_id           = fields.Many2one("leads.new", index=True)   # set only when admitted
explanation       = fields.Json()                # top_basket_contribution, for the RM-facing why
```

> **Storing rejections is the single most consequential decision in this schema.**
>
> It looks like debris. It is the measurement instrument. A control-group buyer's rejected row *is* the counterfactual — the record of what the holdout did **not** receive — and without it the experiment measures "control got nothing" instead of "control did not get this, which treatment did." It is also what separates *the model found nothing* from *budgets bound* from *everyone was suppressed*: three completely different problems that are indistinguishable if you only keep the successes.
>
> V1 kept 22,381 rows of output and no record of what it declined to output, which is one reason nobody could ever say what it was doing.

Volume: at 3× oversupply on a 150/day cap, ~450 rows/day, ~164k/year. Trivial. Retention is a policy question in §9, not a capacity one.

### 5.3 `ml.lead.provenance`

One-to-one with the created lead. Doc 04 §8's fields, minus the ones that belong elsewhere.

```python
lead_id           = fields.Many2one("leads.new", required=True, ondelete="cascade",
                                    index=True, readonly=True)
model_version     = fields.Char(required=True, readonly=True, index=True)
suggestion_batch_id = fields.Many2one("ml.suggestion.batch", readonly=True, index=True)
proposal_uid      = fields.Char(readonly=True)
source_property_id= fields.Many2one("property.base", readonly=True)   # what triggered the match
match_score       = fields.Float(digits=(4, 4), readonly=True)
activation_reason = fields.Selection([...], readonly=True)
holdout_group     = fields.Selection([("treatment",…), ("control",…)], readonly=True)
was_boosted       = fields.Boolean(readonly=True)
boost_owner_uid   = fields.Many2one("res.users", readonly=True)
routed_to_uid     = fields.Many2one("res.users", readonly=True)
routing_reason    = fields.Char(readonly=True)
```

**Every field is `readonly=True` at the ORM level and enforced by an `ir.rule` denying write to everyone including admins.** Provenance that can be edited is not provenance. If a value is wrong the fix is a new lead and a corrected batch, not a quiet UPDATE — otherwise the training-exclusion set and the holdout can both be altered after the fact by anyone with access, and neither would show a trace.

**Why a side table rather than columns on `leads_new`:**

| | Side table | Columns on `leads_new` |
|---|---|---|
| Rows carrying it | ~thousands | 130k, 99% of them null |
| Read contract exposure | opt-in | every field must be reviewed for accidental export |
| `tracking=True` noise on a hot table | none | 11 more tracked fields on the most-edited record in the system |
| Join cost for the analyses that need it | one indexed join | none |

The **one** exception is `inquiry_type`, which extends the existing selection with `ai_suggested`. It stays on `leads_new` because it is the filter every downstream consumer needs — training exclusion, dashboards, the RM's list view — and it must be cheap and impossible to miss.

### 5.4 `ml.buyer.holdout`

```python
buyer_key      = fields.Char(required=True, index=True)   # unique
holdout_group  = fields.Selection([("treatment",…), ("control",…)], required=True, readonly=True)
assigned_at    = fields.Datetime(required=True, readonly=True)
assignment_version = fields.Char(required=True, readonly=True)   # which draw produced this
```

**The draw happens once, in Odoo, at the moment a buyer is first considered — and the stored value always wins.**

Computing it deterministically from `hash(buyer_key + salt)` and never storing it is the tempting alternative and it is dangerous: the day the salt changes, the hash function changes, or the buyer key changes for any reason, buyers silently swap arms. Nothing errors. Every conclusion drawn from the experiment up to that point becomes retrospectively meaningless, and there is no way to detect that it happened.

`assignment_version` exists so that if a **deliberate** re-randomisation is ever needed, it is a visible, dated event with both arms reconstructable — rather than an accident.

No write access for anyone. Moving a buyer between arms by hand is unblinding the experiment.

### 5.5 `ml.generation.policy`

Singleton. **The live control surface — everything an operator needs to change at 11am without a deploy.**

```python
kill_switch          = fields.Boolean(default=True, tracking=True)  # starts OFF (safe)
ramp_phase           = fields.Selection([("r0",…), ("r1",…), ("r2",…), ("r3",…)], tracking=True)
global_daily_cap     = fields.Integer(default=20, tracking=True)
per_buyer_monthly_cap= fields.Integer(default=2,  tracking=True)
per_rm_daily_cap     = fields.Integer(default=5,  tracking=True)
per_property_daily_cap = fields.Integer(default=3, tracking=True)
cooldown_days        = fields.Integer(default=45, tracking=True)
holdout_fraction     = fields.Float(default=0.10, tracking=True)
max_model_age_hours  = fields.Integer(default=30, tracking=True)
change_reason        = fields.Text()   # required on every change
```

Three properties, each load-bearing:

- **`kill_switch` defaults to enabled (generation off).** A fresh install, a restored snapshot, or a migration that fails halfway must not start contacting people. The safe state is the default state.
- **Everything is `tracking=True` and `change_reason` is required.** Caps are the ramp; the ramp is the safety argument. *"Who raised the cap to 150 and why"* must be answerable from the record — doc 04 §10 treats safety as mechanism rather than as phases, and an untracked cap change is a hole straight through it.
- **The pipeline reads this but does not enforce it.** A cap the pipeline enforced at 04:30 cannot stop a batch admitted at 05:00, and the kill switch has to work *after* generation, not only before.

---

## 6. What gets written when a proposal is admitted

### 6.1 The transaction

One transaction per proposal, not per batch. A 60-proposal batch that fails on #47 must keep 1–46.

```
1. lock the policy singleton row (cap counters must not race)
2. re-check every live gate (§6.2)
3. resolve buyer_key → lead history → routing input
4. choose an RM (06-autonomous-mode-integration.md §5)
5. create leads.new     — inquiry_type='ai_suggested', user_id=routed RM
6. create ml.lead.provenance
7. update ml.suggestion.proposal → admitted, lead_id set
8. post the chatter entry carrying the explanation
9. commit
```

**Steps 5 and 6 are in one transaction and must stay there.** A lead created without provenance is exactly the unrecoverable failure §1 is about, and a crash between two commits would produce one — an AI lead indistinguishable from an organic one, forever.

The policy lock in step 1 is what stops two concurrent admissions both seeing 19/20 used and both writing.

### 6.2 The gate order, and why it is this order

Checks run in this sequence. The order is not cosmetic — it is chosen so that the **cheapest and most absolute** checks run first, and so that the rejection reason recorded is the *most meaningful* one rather than whichever happened to fire first.

| # | Gate | Rejection reason | Why here |
|---|---|---|---|
| 1 | Kill switch on | `killed` | absolute; nothing else matters |
| 2 | Batch model version stale | `stale_model` | a whole-batch halt, not a per-row one |
| 3 | Buyer resolvable | `buyer_not_found` | everything downstream needs the buyer |
| 4 | **Holdout = control** | `holdout_control` | **before budgets** — see below |
| 5 | Suppression, live | `suppressed` | the guarantee `02` §7 requires |
| 6 | Engagement state (transacted / negotiating / not-interested) | `ineligible_state` | live, not snapshot |
| 7 | Duplicate — same buyer+property inside cooldown | `duplicate_cooldown` | cheap, and prevents pestering |
| 8 | Property still active and unsold | `property_unavailable` | it may have sold since 03:00 |
| 9 | Per-buyer monthly cap | `cap_buyer_monthly` | protects the person |
| 10 | Per-property daily cap | `cap_property` | protects the listing |
| 11 | Global daily cap | `cap_global` | the ramp dial |
| 12 | An eligible RM exists | `no_eligible_rm` | last, because it is the most expensive |

**Why holdout is checked at #4, before every budget.** If control buyers were dropped *after* budget allocation, they would consume the day's cap and produce nothing — the treatment arm would receive ~10% fewer leads than policy intends, and the two arms would differ by more than the treatment. Dropping them first means the cap governs *leads actually created*, which is what a cap is for, and the arms differ only in whether they were contacted.

**Why `no_eligible_rm` is last.** It is the only gate that is a *staffing* fact rather than a *policy* fact. Recording it as the reason means the reconciliation report can distinguish "we chose not to" from "we had nobody to give it to" — and the second is an operations problem no model change will fix.

**Every rejection is written to the proposal row.** None is silent. Silence here is what made V1 unauditable.

---

## 7. Contamination — the flag that protects the next model

Doc 04 §8 and `05-rm-assist-serving.md` §10: the system must not train on its own output.

`inquiry_type = 'ai_suggested'` makes AI-*originated* leads excludable. That is necessary and not sufficient, because a suggested lead that a buyer then acts on produces **downstream** rows — a site visit, an RM recommendation — which are ordinary-looking evidence generated by the system's own intervention.

So the read contract must be able to mark the descendants, not just the root:

- `/ml/v1/interactions` gains `inquiry_type` (already present) **and** `is_ai_originated`, true for the lead and for anything created under it.
- `/ml/v1/site_visits` gains `is_ai_originated`, derived from the parent lead.

**The three-way distinction from `05` §10 applies unchanged**, and it is the part a naive flag destroys:

| Case | Training treatment |
|---|---|
| Lead created by the autonomous system | AI-originated — down-weight and ablate |
| RM opened the assist tool and chose from its list | AI-influenced — down-weight and ablate |
| **RM opened the tool and chose something else** | **genuine expert signal — the RM disagreed, which is real information** |

A flag that just records "the tool was involved" would throw away the third row, which is the most valuable of the three: it is the only place the system learns where it is wrong.

---

## 8. Migration

`migrations/19.0.1.0.0/post-backfill-buyer-key.py`, idempotent, batched.

Computes `buyer_key` for all existing `leads_new` rows. ~130k HMAC operations plus an indexed update — a few minutes, and it must be **restartable**, because a migration that half-populates a join key and then dies leaves generation matching a random subset of buyers with nothing anywhere reporting a problem.

Rehearsed against a prod snapshot (`odoo-prod-migration-check`) before it goes near production, per the branch convention.

**Ordering constraint:** the backfill must complete *before* `kill_switch` is ever turned off. A partially-backfilled key column does not fail — it just silently narrows the buyer pool to whoever happened to be backfilled.

---

## 9. Open decisions

1. **Retention on `ml.suggestion.proposal`.** These rows are hashed-key records about real people and they are also the experiment's evidence. The measurement window sets the floor; DPDP minimisation sets the ceiling. Needs a stated policy before R2, not after.
2. **Where the write key lives operationally** — Secret Manager is decided; the rotation runbook is not written.
3. **Does a rolled-back lead's proposal return to `pending` or terminate as `rolled_back`?** Terminating is cleaner for audit; returning would let the next batch retry the pair. Recommend terminate, and let the normal cooldown decide.
4. **`per_buyer_monthly_cap = 2`** is a prior with no evidence behind it. It is the cap most likely to be felt by an actual person, so it should be calibrated first.
5. **Buyer master.** Both this document (§4) and `02-buyer-engagement-state.md` §5.2 route around the absence of one. The workarounds are each small; the third one to appear is the signal that it should be built.
