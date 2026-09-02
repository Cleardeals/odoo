# Buyer engagement state

**Scope:** ✅ **in the current execution cycle** — see [`00-scope-and-sequencing.md`](00-scope-and-sequencing.md)
**Depends on:** [`01-read-contract.md`](01-read-contract.md) — this document **extends** it (§6)
**Consumer:** the eligibility filter in the ML repo's `docs/04-autonomous-lead-generation.md` §5

---

## 1. The problem in one line

**Status lives on the inquiry. The question is about the buyer.**

The lead-generation system must answer four things before contacting anyone:

| State | Effect on eligibility |
|---|---|
| **transacted** — bought through us | permanently excluded |
| **actively negotiating** | excluded until the deal closes or dies |
| **explicitly not interested** | excluded, or a long cooldown |
| **dormant / cold** | **eligible — this is the target population** |

`leads.new.current_status` is a `Selection` on the *inquiry*. A buyer holding five inquiries can simultaneously be `site_visit_done` on one, `no_requirements` on another, and `budget_not_sufficient` on a third. None of those is the buyer's state, and there is **no buyer entity anywhere** in the schema — no `res.partner` link, no buyer table. A buyer is a repeated phone string.

So the buyer's state has to be **derived by aggregating across their rows**, with an explicit precedence and explicit recency. This document specifies that derivation, and the one small thing that must actually be stored.

## 2. What Odoo actually records — three surfaces, not one

Verified on `development_19`. This is the part that most changes the design: the signals are spread across three models, and the strongest ones are **not** on `current_status`.

### 2.1 `leads.new.current_status` — 17 values, and none of them means "bought"

```
busy · lead · ringing · call_back_later · site_visit_scheduled
option_not_matching_requirements · details_shared_of_property · no_requirements
detail_shared_and_interested_for_site_visit · switched_off · requirement_closed
property_sold_out · rescheduled · budget_not_sufficient · site_visit_done
number_not_in_use_wrong_number · other
```

> **There is no closed-won value.** `requirement_closed` is ambiguous — it covers *bought elsewhere*, *gave up*, and *we stopped chasing*. `property_sold_out` is a fact about the **property**, not about this buyer buying it.
>
> The ML repo's doc 04 §5 states transacted is *"derived from the funnel state on `leads_new.current_status`"*. **That is not achievable** — the vocabulary has no such state. §3 covers what to do instead.

The same 17-value selection is duplicated verbatim on **`lead.property.interest.current_status`** (`leads/models/lead_property_interest.py`), which holds the *recommended* properties for a lead. So a buyer's outcome may be recorded on the primary inquiry **or** on a recommendation row. Reading only `leads.new` silently misses the second.

### 2.2 `feedback_site_visit_done` — where intent actually lives

On **both** `leads.new` and `lead.property.interest`:

```
buyer_liked_property · buyer_requirement_closed · buyer_visit_from_outside
buyer_not_pickup_call · planning_for_second_visit · negotiation_stage
visit_done_confirmed_by_owner · looking_for_more_options · price_is_high
location_mismatch · deal_closed · other
```

Three of these carry most of the signal this document needs: **`deal_closed`**, **`negotiation_stage`**, and **`looking_for_more_options`** — the last being a near-literal description of the population this whole system exists to serve.

`feedback_general` adds `buyer_not_interested`, `buyer_not_picking_call`.

### 2.3 `lead.site.visit.feedback_option_id` — the properly modelled surface

Unlike the two above, this is a real config model (`lead.site.visit.feedback.option`) with an immutable `code`, a `category`, and a `management_signal`. Seeded in `leads/data/lead_site_visit_status_data.xml`:

| code | category | management_signal |
|---|---|---|
| `negotiation_started` | intent | positive_intent |
| `deal_closed` | intent | positive_intent |
| `buyer_cancelled_interest` | intent | loss_reason |
| `location_mismatch` | property | loss_reason |
| `rejected_price_high` | pricing | loss_reason |

**Prefer this surface wherever it is populated.** Its codes are immutable by a `write()` override, its taxonomy is two-dimensional (`category` = what, `management_signal` = what it means), and it is extensible as data rather than as a code change. The two selection fields in §2.1–§2.2 are hardcoded lists: adding a value there requires a deploy.

## 3. ⚠ "Transacted" cannot be answered reliably today

This is the gap to state plainly, because the requirement is a **hard exclusion** and the data does not support one.

Best available signals, all weak:

| Signal | Why it is not enough |
|---|---|
| `feedback_site_visit_done = deal_closed` | an **optional free-choice field on one inquiry row**. Nothing requires it. A deal closed after a phone negotiation, or recorded only in `remarks`, leaves no trace here |
| `lead.site.visit.feedback_option_id.code = deal_closed` | better modelled, but only exists if a **site visit** was logged and then dispositioned |
| `deals` module | **not on `development_19`** — unmerged on `deal/odoo`. This is where a real transaction record would live |

So v1 must accept **false negatives**: some buyers who bought through us will not be detectable, and will be eligible for suggestions. Doc 04 calls that *"wasteful, and embarrassing in front of a customer"* — correctly.

**Position taken:**

1. **Exclude on any `deal_closed` evidence from any of the three surfaces.** Union, not precedence — this is a hard exclusion, so any single positive is sufficient and a false *positive* here costs almost nothing (one buyer not contacted).
2. **Do not attempt to infer transacted from anything else.** Treating `requirement_closed` as "bought" would exclude large numbers of genuinely dormant buyers — the exact population this system targets. That trade is strongly asymmetric: a missed exclusion is one awkward call; an over-broad one silently deletes the opportunity.
3. **Record the residual risk and measure it.** The rate of "suggested to someone who had bought" is a monitored failure mode, reported from RM feedback rather than assumed to be zero.
4. **The real fix is the `deals` module.** When it merges, transacted becomes a lookup on a transaction record and this section is deleted. Until then this is a known, bounded gap — not a solved problem.

## 4. The derivation

### 4.1 Precedence, highest first

The first matching rule wins:

| # | State | Trigger | Window |
|---|---|---|---|
| 1 | **suppressed** | manual do-not-contact (§5) | as configured |
| 2 | **transacted** | `deal_closed` on any surface (§3) | **forever** |
| 3 | **negotiating** | `negotiation_stage`, `negotiation_started`, `planning_for_second_visit`, or a visit with `management_signal = positive_intent` | **recent only** — 90 days |
| 4 | **not_interested** | `buyer_not_interested`, `buyer_cancelled_interest`, `buyer_requirement_closed`, `no_requirements`, `requirement_closed` | cooldown — 180 days |
| 5 | **uncontactable** | `number_not_in_use_wrong_number`, `switched_off`, `buyer_not_picking_call` | cooldown — 90 days |
| 6 | **dormant** | everything else, last activity inside the recency window | **eligible** |
| 7 | **stale** | last activity older than the recency window | excluded — closer to cold-calling than reactivation |

### 4.2 Recency is not optional

**A status is a point-in-time observation, not a standing property of a person.** `negotiation_stage` recorded fourteen months ago does not mean someone is negotiating now — it almost certainly means the negotiation died and nobody updated the row.

Without windows, precedence produces the wrong answer in the most common case: a buyer with a stale hot status is excluded forever, and the more engaged a buyer once was, the more permanently they are locked out. That inverts the intent of the whole system.

**Only `transacted` is permanent** (§4.1 row 2), because buying is a fact about the past that stays true. Every other exclusion decays.

### 4.3 The signals are unioned, not ranked, within a state

A buyer's rows are read across `leads.new`, `lead.property.interest` and `lead.site.visit`. Within one state, **any** matching row triggers it. Across states, §4.1's precedence resolves the conflict.

Worked example — one buyer, four rows:

| Row | Surface | Signal | Age |
|---|---|---|---|
| A | `leads.new` | `no_requirements` | 14 months |
| B | `lead.property.interest` | `looking_for_more_options` | 5 months |
| C | `lead.site.visit` | `rejected_price_high` (loss_reason) | 5 months |
| D | `leads.new` | `budget_not_sufficient` | 5 months |

Rules 1–3 do not match. Rule 4 matches on row A — but A is 14 months old, outside the 180-day cooldown, so it does not apply. Nothing else matches an exclusion. **Result: dormant, eligible** — and correctly so: this is a real buyer who was actively comparing five months ago, was priced out of one property, and has not been offered an alternative since. Exactly the §1 target population.

Note what would happen with a naive "latest status wins" rule: row D is one of three tied on recency, and the answer would depend on `id` ordering. Precedence plus windows makes the outcome deterministic and explicable.

### 4.4 `looking_for_more_options` is a priority signal, not just an eligibility one

It is the strongest *positive* marker available: a buyer who explicitly said they want more options. It should raise priority in the ML side's stage-2 scoring, not merely fail to exclude.

Passing it through as a distinct flag rather than folding it into "dormant" is the difference between a system that avoids annoying people and one that reaches the people who asked.

## 5. The one thing that must be stored: suppression

Everything in §4 is **derived**. One thing cannot be: an RM's judgement that a specific buyer must not be contacted.

Doc 04 §5.2 requires it — *"an RM must be able to override it manually… the RM often knows things the funnel does not, and needs a way to protect a delicate deal without waiting for a schema change."*

### 5.1 Minimal model — a suppression list, not a buyer master

```python
class BuyerContactSuppression(models.Model):
    """Do-not-contact entries for AI-originated outreach, keyed on the
    canonical 10-digit phone. Deliberately NOT a buyer master."""

    _name = "buyer.contact.suppression"
    _inherit = ["mail.thread"]

    phone_canonical = fields.Char(required=True, index=True)   # normalize_phone_to_10_digit()
    scope           = fields.Selection([("ai_only", "AI outreach only"),
                                        ("all", "All outreach")], required=True)
    reason_code     = fields.Selection([("delicate_deal", …), ("buyer_request", …),
                                        ("legal", …), ("other", …)], required=True)
    reason_text     = fields.Text(required=True)
    expires_on      = fields.Date()                            # null = permanent
    raised_by_uid   = fields.Many2one("res.users", readonly=True, default=lambda s: s.env.user)
```

Keyed on the **canonical phone**, using the same `normalize_phone_to_10_digit()` the buyer key uses — otherwise a suppression entered as `+91…` fails to match an inquiry stored as `0…`, and the suppression silently does nothing. That is the failure mode to design against here.

`scope` distinguishes *"do not let the robot contact them"* from *"do not contact at all"*. Conflating them means an RM protecting a delicate deal accidentally blocks their own follow-up call.

**Active is a read-time predicate** — `expires_on IS NULL OR expires_on >= today` — not a cron-cleared flag. A failed cron that does not clear expiry keeps suppressing someone indefinitely, and nothing about that looks wrong. Same reasoning as `is_breached` in the escalation docs.

### 5.2 Why not a full buyer entity

It would be the natural home for engagement state, and it is what the tokenisation option in [`01-read-contract.md`](01-read-contract.md) §4.6 wanted. It is out of scope here: the derivation in §4 needs no stored state, and building a buyer master to hold one boolean is disproportionate.

**When a buyer entity does get built**, this suppression model folds into it and the token becomes available in the same change. Recorded so that decision is made once, deliberately, rather than arrived at by accretion.

## 6. Read-contract additions

The derivation is **policy**, so it belongs in the pipeline, per [`01-read-contract.md`](01-read-contract.md) §8 — *the API supplies facts, the pipeline applies policy.* But the current contract does not carry the facts it needs. Three additions:

**6.1 Extend `/ml/v1/interactions`** with the two feedback fields:

```diff
  "current_status": "site_visit_done",
+ "feedback_general": null,
+ "feedback_site_visit_done": "looking_for_more_options",
```

**6.2 New `/ml/v1/interests`** — `lead.property.interest` rows, currently not exposed at all:

```json
{ "interest_id": 5512, "buyer_key": "7c1e…", "property_uuid": "…",
  "current_status": "site_visit_done",
  "feedback_general": null, "feedback_site_visit_done": "negotiation_stage",
  "created_on": "2026-02-14" }
```

This endpoint pays for itself twice: it supplies the missing status surface, **and** `lead.property.interest` is the RM-recommendation structure — its model description is literally *"Lead Recommended Property Interests"* — so it is a cleaner source for the expert supervision tier than a self-join on `parent_inquiry_id`.

**6.3 New `/ml/v1/suppressions`** — canonical, hashed:

```json
{ "buyer_key": "7c1e…", "scope": "ai_only", "reason_code": "delicate_deal" }
```

**Hashed, and `reason_text` omitted.** The pipeline needs to know *that* a buyer is suppressed, not why in prose. Sending the note would put unreviewed free text about a named individual into an ML artifact store for no modelling benefit.

## 7. Suppression must be re-checked at write time

The nightly pipeline scores against a snapshot up to 24 hours old. Someone can ask not to be contacted at 09:00 and be in last night's eligible set.

So suppression is enforced **twice**:

| Gate | When | Purpose |
|---|---|---|
| Pipeline filter | scoring, on snapshot data | keeps suppressed buyers out of candidate generation |
| **Odoo re-check at lead creation** | the write path | the actual guarantee |

**The second is the one that counts**, and it belongs on the Odoo side of the write contract ([`04-lead-provenance.md`](04-lead-provenance.md)) because Odoo holds live state. A single gate on stale data is not a do-not-contact guarantee — it is a do-not-contact tendency.

**Now specified:** it is gate #5 in the admission controller, [`04-lead-provenance.md`](04-lead-provenance.md) §6.2.

## 8. What changes in Odoo

Deliberately small:

| Change | Size | Required for |
|---|---|---|
| `buyer.contact.suppression` model + views + security | small | §5 |
| `feedback_general` / `feedback_site_visit_done` added to the interactions payload | trivial | §6.1 |
| `/ml/v1/interests` endpoint | small | §6.2 |
| `/ml/v1/suppressions` endpoint | small | §6.3 |
| Re-check hook at lead creation | small, but **on the deferred write path** | §7 |

**Not proposed:** changing `current_status`'s selection vocabulary. Adding a closed-won value would be the clean fix for §3, but it touches a required, tracked field on ~123k rows used across dashboards, controllers and reporting — and the `deals` module is the correct home for transactions anyway. Flagged as an open decision rather than done quietly.

## 9. Tests

| Test | Asserts |
|---|---|
| `test_state_precedence_order` | each of the 7 rules wins over every lower one, with a fixture per pair |
| `test_stale_hot_status_does_not_exclude` | `negotiation_stage` at 14 months → **dormant, eligible** (§4.2). The regression test for the inverted-intent bug |
| `test_transacted_is_permanent` | `deal_closed` at 3 years → still excluded |
| `test_transacted_union_across_surfaces` | evidence on `lead.site.visit` alone is sufficient, and on `lead.property.interest` alone |
| `test_interest_rows_are_read` | a buyer whose only exclusion signal is on `lead.property.interest` is excluded — the §2.1 trap |
| `test_suppression_matches_across_phone_formats` | suppression entered as `+91…` blocks an inquiry stored as `0…` (§5.1) |
| `test_suppression_expiry_needs_no_cron` | past `expires_on` → not suppressed, no job having run |
| `test_suppression_scope_respected` | `ai_only` does not block RM outreach |
| `test_suppression_payload_omits_reason_text` | §6.3 |
| `test_looking_for_more_options_flagged` | surfaced as a distinct positive signal, not folded into dormant |
| `test_ambiguous_status_not_treated_as_transacted` | `requirement_closed` and `property_sold_out` → **not** transacted (§3.2) |

## 10. Open decisions

1. **Window values** — 90/180/90 days and the recency window are placeholders. They should be calibrated against outcomes, like every other prior in this project, not fixed by assertion.
2. **Should `current_status` gain a closed-won value** (§8), or does that wait for `deals`? Recommend waiting — a second, weaker transaction record competing with the real one is worse than a known gap.
3. **`stale` boundary** (§4.1 row 7) — where reactivation becomes cold-calling. Has a compliance dimension as well as a taste one.
4. **Does `switched_off` deserve a cooldown at all?** A switched-off phone is often a transient state, and a 90-day exclusion on it may discard genuinely reachable buyers.
5. **Who may create suppressions** — any RM for their own buyers, or a narrower group? Permissive is right for a protective control, but it is also a lever for quietly opting out of a system someone dislikes, so the volume needs watching.
