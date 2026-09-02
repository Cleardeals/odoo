# Autonomous mode in Odoo — admission, routing, and the people side

**Branch:** `feature/ml-matching-integration` · **Status:** design · **Date:** 2026-07-31
**Depends on:** [`04-lead-provenance.md`](04-lead-provenance.md) — the contract and the schema this operates on.
**Provider side:** ML repo `docs/06-autonomous-generation-pipeline.md` (propose) and `docs/04-autonomous-lead-generation.md` (why).

Serving mode 2. The pipeline proposes; **this is everything that happens after the POST lands.**

---

## 1. The admission controller is the safety boundary

The pipeline is a pure function of a snapshot up to 24 hours old. Everything that must be true *at the moment a real person is contacted* is checked here, on live data, or it is not guaranteed at all.

Stated plainly, because it determines where every check belongs:

> **The pipeline's filters exist to make the candidate set small and the allocation honest. The admission controller's filters exist to make promises true.** They look like the same list. They are not the same thing, and the second one is not optional because the first one ran.

The gate order is specified in [`04-lead-provenance.md`](04-lead-provenance.md) §6.2. This document covers what the controller does *with* an admitted proposal — above all, choosing a person.

**When it runs.** A cron, ten minutes after the expected batch arrival, not a synchronous handler on the POST. Three reasons: a 60-proposal admission with per-row transactions and RM selection is not an HTTP-request-shaped workload; a submit that times out mid-admission would leave the pipeline unsure what happened; and a batch that arrives while the kill switch is on must sit and wait rather than fail.

---

## 2. Routing: the deliberate departure

**AI-suggested leads route by load, not by property ownership.** This inverts the firm's normal rule and it is the whole point.

Normally the RM who owns a listing handles enquiries on it. Under that rule an RM with 40 starved listings would receive every lead the system generates for those listings — and starved inventory is not evenly distributed, so the system would systematically bury exactly the RMs whose portfolios need the most help. The mechanism intended to relieve them would be the mechanism that swamps them.

So routing is by capacity. This is a real change to how work is distributed, and it will be felt, which is why §5.4 and §6 exist.

---

## 3. Who is eligible to receive a lead

Three conditions, all necessary, evaluated live:

| Condition | Source | Why |
|---|---|---|
| **Covers the metro** | RM's city assignment | the metro gate is a hard pair-level constraint everywhere else; routing does not get to relax it |
| **Covers the segment** | RM's segment coverage | a residential RM handed a warehouse lead will not work it, and the buyer's experience is the cost |
| **Available** | not on leave, active user, logged in within `max_idle_days` | an unavailable RM is a lead that dies quietly — the "high RM action, low contact" symptom in doc 04 §11 |

Ahmedabad + Gandhinagar count as **one metro**, consistent with the pair gate — 93.5% of cross-city baskets are that pair.

**Coverage data does not exist yet in a queryable form.** Today it is implicit in assignment habits. The minimum viable version is two many2many fields on `res.users` (`ml_metro_ids`, `ml_segment_ids`) with a manager-editable form — deliberately not a new org-structure model, which is parked (`../organization/README.md`). If the fields are empty for everyone, **routing must fail closed**: every proposal rejects with `no_eligible_rm` rather than routing to anyone at all. A misconfiguration that silently routes leads to whoever happens to be first alphabetically is worse than a batch that produces nothing and says so.

---

## 4. Choosing among the eligible

```
1. eligible = RMs covering (metro, segment), available
2. under_cap = eligible where open_ai_leads_today < per_rm_daily_cap
3. if under_cap is empty  → reject: no_eligible_rm
4. sort by:  (a) open AI leads       ascending   ← the real load signal
             (b) total open leads    ascending   ← organic work is still work
             (c) AI leads received in the last 7 days ascending  ← the fairness floor
             (d) user id             ascending   ← deterministic tie-break
5. take the first
```

**(a) before (b)** because the cap being enforced is on AI leads, and an RM with a heavy organic pipeline should still not be first in line for more AI work — which is why (b) is there at all rather than absent.

**(c) is the fairness floor** doc 04 §9 requires. Without it, an RM who closes leads fast always looks least-loaded and receives a permanently larger share — the system quietly converts speed into volume, then into burnout. The 7-day window puts a ceiling on how skewed distribution can get regardless of momentary load.

**(d) is not a detail.** Without a deterministic final tie-break, two runs of the same batch route differently, and "why did this go to me" has no stable answer.

### 4.1 Load is derived, never stored

`open_ai_leads_today` is a query, not a counter column.

A maintained counter is wrong here for the reason this repo keeps running into: **a counter that drifts fails silently.** A lead closed by a path that forgets to decrement leaves an RM permanently looking busier than they are, and they stop receiving work with nothing anywhere reporting a fault. The query costs an indexed count against a table we already index by `user_id`.

The same reasoning as `active` being a read-time predicate on escalations, and `is_breached` not being a cron-maintained flag.

### 4.2 Nobody is eligible

`no_eligible_rm` is a **first-class outcome, not an error**. It means the firm has demand it cannot staff, in a specific metro and segment, on a specific day. The reconciliation report surfaces it as a coverage number.

The proposal is **not** held for tomorrow. Rolling it over would build an invisible queue whose age nobody tracks — V1's 17,000 untouched suggestions, rebuilt from the other end. Tomorrow's batch regenerates against tomorrow's state, and if the property is still starved it will be proposed again.

### 4.3 The owning RM — doc 04's open decision #1

**Recommendation: the owning RM becomes a follower on the lead, not its owner.**

They hold the seller relationship, so they must know a buyer is being worked on their listing — and they will find out anyway, from the seller, which is the worst possible way. Making them a follower gives visibility through the mechanism Odoo already has, without giving them the lead or a notification burst on a night when 20 land at once.

*Rejected:* full ownership (defeats §2 entirely), and a per-lead notification (an RM with many starved listings gets a nightly alert storm and mutes it, losing the signal).

---

## 5. What the RM actually sees

This is where V1 died, and none of the machinery above matters if this part is wrong.

V1 pushed 22,381 suggestions into `property.lead.suggestion` — a separate list, disconnected from the RM's workflow — and **more than 17,000 were never touched**. The engine was not the problem; the delivery was.

Mode 2 is a *push* system, so it cannot use Mode 1's escape route of being strictly pull. It has to solve the delivery problem head-on.

### 5.1 An AI lead is a lead

It lands in `leads_new`, in the RM's normal lead list, in their normal workflow, with their normal statuses and their normal form. **There is no separate AI queue, no separate menu, no separate list to work through.**

A second inbox is a second thing to abandon, and abandonment is the failure mode with direct evidence behind it in this system's own history.

What distinguishes it is a **badge and an explanation**, not a location.

### 5.2 The explanation is mandatory

Every AI lead's chatter carries, at creation, one plain sentence:

> **Suggested by property matching · model 2026-08-03.2**
> Tirthbhumi Apartment, Maninagar — this buyer visited *Shree Ganesh Residency* in March, which is **79% similar**. This listing has had 2 enquiries in 90 days.

Three facts, in the order an RM needs them: *what to offer*, *why this buyer*, *why this listing needs it*. The similarity number is the model's own output (`top_basket_contribution`), not a rounded invention.

**Volume control is the honest part of the argument.** At R0 an RM receives at most a handful of AI leads a day against a cap of 5. That is what makes reading the explanation realistic. The explanation quality and the volume cap are the same design decision viewed twice — a good explanation on 200 leads a day gets skipped exactly like a bad one.

### 5.3 Disposition must be capturable in one action

V1's feedback was optional free text (`rm_feedback`) and the loop never closed — hence *"feedback unreliable, do not use"* in `CLAUDE.md`.

So the AI badge carries **coded** dispositions as buttons, and reuses the existing status vocabulary wherever it can rather than inventing a parallel one:

| Action | Records |
|---|---|
| Worked it (any status change) | implicit — no extra click, and this is the common case |
| **Not a fit** → one coded reason (wrong area / wrong budget / wrong type / buyer inactive / already handled) | the reason code, routed to the responsible embedding aspect |
| Not mine | a routing error, distinct from a match error — **the two must never be conflated** |

That last row is the distinction V1's free-text field made impossible. *"Bad lead"* means either the model matched badly or the router assigned badly, and those go to different fixes. A system that cannot tell them apart improves neither.

### 5.4 The manager view

One dashboard, and it exists because §2 changes how work is distributed and people will reasonably want to check it is fair:

- leads created per RM per day, AI vs organic
- the disposition mix per RM
- **rejection reasons for the last batch** — the diagnostic from `04-lead-provenance.md` §3.2
- coverage: what share of starved properties received demand this week
- the ramp phase, the caps, and the kill switch, with the change log

The kill switch and rollback are **on this dashboard**, operable by an ops manager. The people who will need to stop this at 9am on a Saturday are the people who cannot deploy anything, and a kill switch that requires engineering is a kill switch that gets used hours late.

---

## 6. Rollout and the automatic halts

The ramp (doc 04 §10) is enforced by `ml.generation.policy.global_daily_cap`, moved by a person with a recorded reason. Nothing advances automatically.

**Halts, by contrast, are automatic** — they fire without a human, because the situations they cover are exactly the ones where waiting for a human is the problem:

| Condition | Action |
|---|---|
| Disposition "not a fit" rate above ceiling over a rolling window | kill switch on, alert |
| Any complaint logged against an AI-originated lead | kill switch on, alert — **a hard halt on the first one**, not a rate |
| Batch `model_version` older than `max_model_age_hours` | reject the batch, alert |
| Admitted count zero on N consecutive days | alert (not a halt — this is silence, and silence should be noticed rather than acted on) |

The complaint rule is deliberately stricter than a rate. At R0 volumes, a rate-based trigger on complaints would need dozens before it fired, and by then the thing you were trying to prevent has happened dozens of times.

---

## 7. Coexistence with `lead_suggestor`

V1's `property.lead.suggestion` still exists with 22,381 rows and an active cron.

**It is switched off, not deleted, at R1.** Its rows are the evidence base for the delivery argument that shaped both serving modes, and its 17k-untouched figure is cited in four documents across two repos. Deleting the table to tidy up would delete the reason the new design looks the way it does.

The cron stops at R1 — running two suggestion engines at once means neither can be evaluated, and the old one is already known not to work.

---

## 8. Tests

| Test | Asserts |
|---|---|
| `test_admission_preserves_rank_order` | leads are created in submitted `rank` order; no re-sort by score |
| `test_kill_switch_blocks_admission` | switch on → zero created, all rejected `killed`, batch retained |
| `test_holdout_control_never_creates` | a control buyer produces a proposal row and no lead, ever |
| `test_holdout_checked_before_budget` | control rejections do not consume the global cap |
| `test_provenance_is_atomic` | no `leads.new` with `inquiry_type='ai_suggested'` exists without provenance |
| `test_provenance_is_immutable` | write to any provenance field raises, including as admin |
| `test_suppression_rechecked_live` | suppression added after generation still blocks |
| `test_routing_fails_closed` | no coverage configured → `no_eligible_rm`, not a fallback RM |
| `test_routing_is_deterministic` | same live state → same RM |
| `test_rm_cap_is_hard` | an RM at cap is never chosen, even if uniquely eligible |
| `test_rollback_skips_touched_leads` | a lead with a status change survives rollback and is reported |
| `test_no_pii_in_payload` | submit containing a phone-shaped value is rejected and alerts |
| `test_owning_rm_is_follower_not_owner` | ownership is unchanged by routing |

---

## 9. Sequencing

| Step | Gate to the next |
|---|---|
| 1. Schema + migration (`04-lead-provenance.md`) | backfill verified complete on prod |
| 2. Write endpoints, kill switch **on** | contract tests pass end to end |
| 3. Routing engine + coverage config | `test_routing_fails_closed` passes with real config |
| 4. RM surfaces: badge, explanation, disposition buttons | reviewed with RMs before any lead exists |
| 5. Manager dashboard + kill switch in the UI | ops can stop it without engineering |
| 6. **R0** — switch off the kill switch, cap 20 | provenance and holdout verified on live rows |

Steps 4 and 5 are before R0, not after. A system that can create leads before its operators can see or stop them is not at R0; it is unsupervised.

---

## 10. Open decisions

1. **Where RM metro/segment coverage lives.** Two fields on `res.users` is the minimum. It overlaps the parked org-structure work, and the risk is building the wrong small thing twice.
2. **`max_idle_days` for availability** — a genuine ops input; too tight excludes RMs who work mostly by phone.
3. **Does an AI lead show the buyer's prior properties to the RM?** Useful context, and a broader view of one buyer's history than the RM would normally have. A privacy call, not a technical one.
4. **Weekend and holiday generation.** Leads created Saturday night sit until Monday, ageing against the buyer's interest. Probably skip, and it is one line of config — but skipping silently changes weekly volume in a way the ramp evidence must account for.
5. **What happens to an AI lead an RM never touches for N days** — recycle to another RM, or close it? Recycling risks rebuilding a queue; closing discards real demand.
