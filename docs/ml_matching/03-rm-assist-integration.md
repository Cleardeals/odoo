# RM-assist integration — the Odoo side

**Scope:** ✅ **in the current execution cycle** — the first serving mode
**Module:** `ml_suggest` (new — the *client*; distinct from `ml_api`, §2)
**Provider contract:** ML repo `docs/05-rm-assist-serving.md`. That document specifies the service; this one specifies how Odoo uses it. Neither repeats the other.
**Surface inventory:** [`03a-lead-form-full-surface.md`](03a-lead-form-full-surface.md) — every field, button, tab and wizard in the live form and its disposition.
**Design:** [Figma — RM Assist (Mode 1)](https://www.figma.com/design/HGQW9SgUL37RmL8apoPsiD) · 3 pages: principles + problem/fix teardown + tokens · redesigned lead form (desktop 1440 + mobile 390) · recommend panel in six states (default, loading, service-unavailable, thin-segment, first-inquiry, chose-nothing).

---

## 1. What is being built

An RM is mid-task — looking at an inquiry, or a property — and wants to know *"what else would this buyer accept?"* or *"who else might want this listing?"*. Today they answer from memory, which reaches perhaps 50 properties. The model ranks all 2,133.

**The model is an accelerator on an existing workflow, never a gate in front of it.** Every insertion point below must remain fully usable with the service switched off.

## 2. Two modules, opposite directions

| Module | Direction | Role |
|---|---|---|
| `ml_api` ([`01-read-contract.md`](01-read-contract.md)) | Odoo → ML | Odoo is the **server**; the pipeline pulls training data |
| **`ml_suggest`** (this doc) | Odoo → ML | Odoo is the **client**; it calls the serving API |

Kept separate because they fail differently, are secured differently (§6), and have different blast radius: `ml_api` going wrong leaks data; `ml_suggest` going wrong shows an RM a bad list. Merging them would put an outbound HTTP client inside the module that holds the PII boundary.

## 3. Why there is no suggestions table

The instinct is to precompute suggestions nightly into a table and show RMs a list. **That is exactly what V1 did, and it is why V1 failed.**

`property.lead.suggestion` (module `lead_suggestor`, populated from BigQuery by `_cron_sync_suggestions`) holds **22,381 rows, of which 17,000+ are still `status = 'new'`** — generated, never looked at. The model was not the problem:

- suggestions arrived in a **separate list**, competing with the RM's real task rather than serving it
- **~22k rows against ~900 active listings** — a list that can never be finished gets abandoned, not triaged
- feedback was **optional free text** (`rm_feedback`), so nothing usable came back

So `ml_suggest` stores **no suggestion rows**. The RM asks, the model answers, the answer is rendered and discarded. What *is* stored is the **query event and its disposition** (§8) — a few hundred bytes recording that a question was asked and what happened, not a backlog to work through.

> A suggestion the RM did not ask for competes for attention. A suggestion they asked for is already wanted.

## 4. Insertion points, in priority order

### 4.1 The recommend-property wizard — build this first

`leads/wizard/lead_recommend_property_wizard.py` already exists and is the RM's real workflow for *"offer this buyer another property"*. Today:

```python
property_base_id = fields.Many2one(
    "property.base", string="Recommended Property", required=True,
    context={"search_all_properties_for_lead": True},
)
```

One required Many2one, filled from memory. On confirm, `action_create_recommended_inquiry()` creates a `leads.new` row with `inquiry_type='recommended'` (with a duplicate guard on phone + property).

**The change:** add a ranked candidate list above that field, fetched on wizard open. The RM either picks from it — one click, the Many2one is set — or ignores it and types as before. The field stays required and stays free; the wizard's existing validation and dedup are untouched.

This is the highest-value insertion point because it needs **no new RM behaviour**. The tool appears inside a screen they already open, at the exact moment the question is live.

**How candidates are ranked here** — this is the buyer-scoring decomposition, and it runs in Odoo:

```
1. Assemble the buyer's basket: every property this phone has inquired about,
   across leads.new AND lead.property.interest      (both surfaces - see 02 §2.1)
2. POST /v1/pair_scores  { left: [candidates], right: [basket] }
3. score(candidate) = Σ w_q · sim(candidate, q) / Σ w_q
   w_q from GET /v1/version -> basket_weights   (NOT Odoo config - see below)
4. Exclude: already in the basket, already recommended, inactive listings
5. Rank, take top k
```

**No buyer identifier leaves Odoo** — not even a hashed one. The service receives property uuids only. See the provider doc §3.

**The tier weights come from `GET /v1/version`, never from Odoo config.** Odoo does the arithmetic, but the model owns the weights — they were fitted alongside it. Duplicating them here would let them drift out of step with training, silently and retrospectively.

Because they arrive with `model_version`, and `model_version` is stored on every query row (§8.3), the weights behind any historical ranking are always recoverable. Cache per `model_version`, not per request. No fallback is required: weights only combine `/v1/pair_scores` output, so if the service is unreachable there is no ranking to weight (§7).

### 4.2 Property form → "Find interested buyers"

The reverse direction, for a starved or expiring listing. Same decomposition run the other way: for each candidate buyer, score their basket against this property.

More expensive (many buyers × their baskets) and needs eligibility applied ([`02-buyer-engagement-state.md`](02-buyer-engagement-state.md)), so it comes second. It is also the surface closest to Mode 2, which makes it the natural proving ground before anything autonomous ships.

### 4.3 Expired / unavailable listing → "suggest alternatives"

Direct `/v1/similar` on the property, no buyer involved. The simplest call in the system and a genuinely common need — a buyer asks about a listing that is gone.

## 5. What the RM sees

Per candidate: property identity, **similarity as a coarse band** rather than a raw decimal, the key comparison facts (price, BHK, locality, area), and *why it surfaced*.

**Bands, not decimals.** `0.871` invites an RM to treat the fourth digit as meaningful and to compare it against last month's `0.863` — across a retrain, where the scale has shifted. Bands (`strong` / `good` / `possible`) survive rescaling and carry the information the RM actually needs. The raw value is logged, never displayed.

**Context, always:** *"ranked against 1,746 comparable listings"*, from `candidates_considered`. When that number is small the ranking is not meaningful and the UI must say so rather than presenting three results with the same confident framing — the same refusal principle as `starvation: unmeasurable`.

**The model version is visible**, in a footer. When an RM says "it was better last week", the version is the first question and it must not require a log dig.

## 5a. Design reference

The Figma file is the visual source of truth for everything in §4, §5, §7 and §8.3. Three decisions in it are worth carrying into build, because they are easy to lose:

- **Multi-select.** The current wizard takes one property per dialog, so offering three alternatives is three round trips. RMs offer two or three in one message; the panel matches that, and the primary button carries the count ("Recommend 2 properties").
- **Why-chips instead of a score.** Each candidate states its trade-off in the buyer's terms — *₹3.5L cheaper*, *+1 BHK for ₹5.5L more*, *0.8 km away* — which is what an RM actually says on a call. The band is the only ranking signal shown.
- **Every failure state is drawn.** Service-unavailable, thin-segment and first-inquiry are designed screens, not error handling added later. §7 is a design requirement precisely because it was designed.

## 6. Authentication — no stored secret

Odoo runs on GCE (`odoo-19-prod`) in the same project as the service (`odoo-472708`), so `ml_suggest` fetches a **Google-signed ID token from the instance metadata server** with the service URL as audience, and sends it as a bearer token:

```
GET http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/
    default/identity?audience=<service-url>
Header: Metadata-Flavor: Google
```

No API key, nothing in `ir.config_parameter`, nothing in `odoo.conf`. Tokens are cached in memory until ~5 minutes before expiry.

Only the **service URL** is configuration (`ml_suggest.service_url`) — not a secret, and it needs to differ between staging and prod. Access is granted by an IAM invoker binding, so revoking Odoo's access is one binding change with no deploy.

*(Contrast with `ml_api`, which authenticates the pipeline with `X-API-Key` because that path terminates on Odoo's own HTTP layer, which has no IAM concept. Different constraints, not an inconsistency.)*

## 7. Degradation is a feature requirement

| Condition | Behaviour |
|---|---|
| Service unreachable, 5xx, or **> 2 s** | wizard opens **unranked**, with a quiet inline notice. The RM proceeds exactly as today |
| Property not in the embedding table | ranked list omitted for that query; no error dialog |
| Empty basket (buyer's first inquiry) | fall back to `/v1/similar` on the one property they did ask about |
| Thin segment | show results without the confidence framing (§5) |

**Never a blocking error dialog, never a disabled Confirm button.** An interactive tool that intermittently prevents work gets routed around within a week, and then the adoption this mode exists to build is gone. The timeout is enforced Odoo-side rather than trusted to the service.

## 8. Feedback capture — the V1 failure to not repeat

V1's `rm_feedback` was an optional free-text field. The result, per the project notes: *"feedback unreliable — do not use."* Two fixes, both structural.

**8.1 Disposition is captured as a side effect, not as a separate task.** The RM's existing click *is* the signal:

| What the RM did | Recorded |
|---|---|
| Picked a ranked candidate | `chose_suggested`, plus its rank and similarity |
| Typed a different property | `chose_other`, plus whether it appeared in the list at all and at what rank |
| Closed without recommending | `chose_none` |

Nobody fills in a form. The V1 mistake was making feedback an extra step, which meant it was only done when someone felt like it — producing a biased sample, which is worse than no sample because it looks usable.

**8.2 A coded reason, only when it is cheap to ask.** If the RM rejects a top-3 candidate, one optional single-click chip: `wrong_area` · `price_off` · `wrong_size` · `wrong_type` · `sold_or_stale` · `other`. Skippable. Coded reasons route corrections to the responsible embedding aspect; free text cannot be aggregated.

**8.3 `chose_none` gets its own one-click form.** It is the most ambiguous disposition and the one most worth resolving — the RM saw a ranked list and took nothing from it.

**Buttons only. No text field. One click saves and closes.**

```
 You didn't pick any of the 12 suggestions. Quick reason?

 ┌─────────────────────┐ ┌─────────────────────┐ ┌─────────────────────┐
 │  Nothing suitable   │ │  Prices all wrong   │ │  Areas all wrong    │
 └─────────────────────┘ └─────────────────────┘ └─────────────────────┘
 ┌─────────────────────┐ ┌─────────────────────┐
 │ Buyer not interested│ │  Deciding later     │              [ Skip ]
 └─────────────────────┘ └─────────────────────┘
```

The buttons are deliberately split into two kinds, because collapsing them makes the resulting metric uninterpretable:

| Button | `reason_scope` | Reads as |
|---|---|---|
| Nothing suitable | `model` | the set was wrong |
| Prices all wrong | `model` | price axis is off for this buyer |
| Areas all wrong | `model` | geo axis is off |
| Buyer not interested | `workflow` | **nothing to do with the model** — the buyer conversation ended |
| Deciding later | `workflow` | the RM was interrupted or is waiting |

Without `reason_scope`, a rising `chose_none` rate is unreadable: it could mean the model is degrading or simply that RMs are opening the tool earlier in more conversations. Separating them keeps §9's metrics honest — only `model`-scoped reasons belong in a quality trend.

Four rules on the form itself:

- **Never blocking.** It is a dismissible bar, not a modal over the Confirm button. `Skip` is one click and the disposition still records as `chose_none` with no reason. A required form here would teach RMs not to open the tool at all, which costs far more than the missing reason.
- **Only shown when a list was actually rendered.** If the query degraded, returned nothing, or the segment was too thin (§7), asking why nothing was picked is nonsense — and would pollute the model-quality signal with service failures.
- **Once per query.** Not re-prompted if the RM reopens the wizard.
- **Same treatment for `chose_other`** when the chosen property was absent from the list — that is the §9 signal that matters most, and it deserves the same single click.

**8.4 What is stored:**

```
ml.suggest.query        one row per question asked
  rm_user_id · asked_at · surface (wizard/property/expired)
  subject_property_uuid · basket_size · model_version
  candidates_considered · results_shown · latency_ms · degraded
  disposition · chosen_property_uuid · chosen_rank
  reason_code · reason_scope (model | workflow | null)
  chosen_was_in_list      (false when the RM picked something absent - §9)
```

Append-only. This is the entire measurement basis for §9, and **it is the thing V1 never had** — 22,381 suggestions with no record of whether anyone looked.

`model_version` on every row is non-negotiable: dispositions arrive weeks before the outcome, and without it feedback cannot be attributed to the model that produced it.

## 9. The three signals that matter

| Signal | Reads on |
|---|---|
| **Query rate per RM** | whether the tool is reached for at all — never measured in V1 |
| **Chosen rank distribution** | if RMs consistently pick rank 8, the *ranking* is wrong even when the *set* is right |
| **`chose_other` where the property was not in the list** (`chosen_was_in_list = false`) | the model missed something an expert knew. **The most informative event available** |

**Only `reason_scope = 'model'` rows belong in a quality trend** (§8.3). A `chose_none` because the buyer lost interest says nothing about the ranking, and mixing the two produces a metric that moves with RM behaviour rather than model quality.

The third row is the point. Agreement with RM judgement is explicitly *not* a success criterion — it would cap the system at human performance and inherit the coverage blind spots it exists to fix. The value is in the disagreements, so they are surfaced for examination rather than treated as defects.

## 10. Contamination — assist mode is not passive

If the model surfaces property B, the RM recommends it, and `action_create_recommended_inquiry()` writes a `leads.new` row with `inquiry_type='recommended'` — then the next training run reads that row as evidence A and B are substitutes. **It is the model's own output, laundered through an RM's click.**

This matters more here than anywhere else: RM recommendation is the **expert** supervision tier, weighted above co-inquiry. Contaminating it makes the model most confident about exactly the pairs it invented.

So recommended inquiries created through this path carry provenance from the very first one:

| Field | Value |
|---|---|
| `ai_assisted` | true when the chosen property came from the ranked list |
| `ai_model_version` | which model |
| `ai_suggested_rank` | where it sat in the list |
| `ai_query_id` | FK to the `ml.suggest.query` row |

**Three cases must stay distinguishable**, and a naive "was the tool open?" flag destroys the most valuable one:

| Case | Flag | Training |
|---|---|---|
| Chose from the ranked list | `ai_assisted = true` | AI-influenced — down-weight and ablate |
| Opened the tool, chose something else | `ai_assisted = false`, query row exists | **genuine expert signal** — the RM disagreed |
| Never opened the tool | no query row | genuine expert signal |

Retroactively marking which recommendations the model caused is impossible, which is why these fields ship with the first version rather than the second.

## 11. Permissions

`ml_suggest` adds no new visibility. Candidates are fetched by uuid and then **re-read through the requesting user's own access**, so `properties.rule_property_base_rm_own_only` still applies — an RM cannot see a property through the suggestion list that they could not see through search.

This matters because the service is uuid-based and has no concept of Odoo record rules. Filtering must happen on return, in Odoo, under the user's own credentials — not with `sudo()` for convenience.

Reading the query log is a manager-level right, since it shows per-RM usage.

## 12. Coexistence with `lead_suggestor`

`lead_suggestor` and its BigQuery cron stay untouched for now. `ml_suggest` neither reads nor writes `property.lead.suggestion`.

**Do not migrate the 22,381 old rows.** Their scores come from a different model on a different scale, and their `status` values are 77% untouched default. Importing them would carry V1's noise into V2's measurement and make the `ml.suggest.query` log dishonest from row one.

Retiring `lead_suggestor` is a separate decision, and it has an external dependency: the seller-facing `/api/track/property/ai-suggestions` endpoint serves from that model, so switching it off is a product change, not a cleanup.

## 13. Tests

| Test | Asserts |
|---|---|
| `test_wizard_works_with_service_down` | service unreachable → wizard opens, Confirm works, inquiry created. **The most important test here** |
| `test_wizard_respects_timeout` | a 5 s stub → degraded at 2 s, no user-visible error |
| `test_no_buyer_identifier_in_request` | asserts on the serialised request body: no phone, no name, no buyer key, hashed or otherwise |
| `test_basket_includes_interest_rows` | basket assembly reads `lead.property.interest`, not only `leads.new` |
| `test_candidates_filtered_by_record_rules` | an RM does not see another RM's property via suggestions |
| `test_disposition_recorded_for_all_three_cases` | chose_suggested / chose_other / chose_none |
| `test_chose_other_records_absence` | picking an unlisted property records that it was absent, not rank 0 |
| `test_provenance_on_created_inquiry` | `ai_assisted`, version, rank, query FK all set — and **false** when the RM overrode |
| `test_similarity_not_displayed_raw` | the UI renders a band; the decimal is stored only |
| `test_no_suggestion_rows_created` | `ml_suggest` writes query rows only, never a suggestion backlog |
| `test_metadata_token_cached_and_refreshed` | one fetch per window, refresh before expiry |
| `test_thin_segment_suppresses_confidence` | low `candidates_considered` → no confident framing |
| `test_basket_weights_come_from_service` | weights are read from `/v1/version`, cached per `model_version`, and **not** present in Odoo config |
| `test_none_form_never_blocks` | `Skip` closes in one click; the disposition still records `chose_none` with a null reason |
| `test_none_form_hidden_when_no_list_shown` | degraded or empty result → form not offered (§8.3) |
| `test_reason_scope_separates_model_from_workflow` | `buyer_not_interested` is `workflow` and is excluded from the quality trend |

## 14. Open decisions

1. **Does assist honour buyer suppression?** A human is making the call, so showing a suppressed buyer's property may be correct — recommend showing it **with the suppression reason visible** rather than filtering silently.
2. **`k` for the UI** — whatever fits one screen without scrolling, then validated against the chosen-rank distribution.
3. **Which RMs get it first?** Not a holdout (§9 explains why that does not transfer), but a small first group is still how the UX problems get found cheaply.
4. **Button labels in §8.3** — the five are a first cut. They should be reviewed with two or three RMs before build, since a label nobody recognises gets answered at random, which is worse than `Skip`.
