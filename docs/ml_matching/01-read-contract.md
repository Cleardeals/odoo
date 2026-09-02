# Odoo read contract for the ML pipeline

**Scope:** ✅ **in the current execution cycle** — see [`00-scope-and-sequencing.md`](00-scope-and-sequencing.md)
**Module:** `ml_api` (new, thin — §11)
**Consumer:** the nightly training/serving pipeline in the `Property Matching Model V2` repo (its doc 03 §4.2)
**Direction:** Odoo → ML, **read-only**. The write path is deferred and is not in this document.

---

## 1. What this replaces

Analysis so far has reached prod through `gcloud compute ssh → docker exec → psql`. That is correct for ad-hoc validation and **wrong for a pipeline**: it needs an interactive gcloud token that cannot refresh non-interactively, it couples the pipeline to the container layout, it bypasses every access control, and it hands the ML side raw `phone` values it must never hold.

This contract replaces it with three versioned HTTP endpoints that pseudonymise the buyer key **at source**.

## 2. Division of labour — Odoo is not the feature source

Worth stating first because it bounds the whole contract:

| Data | Source | Why |
|---|---|---|
| Rich property features — facing, furnishing, floor, amenities, carpet vs SBU area, description, images, lat/lon | **website API** `api.cleardeals.cc/api/v1/properties` | they exist only there; Odoo's mirror is light |
| **Behavioural signals** — inquiries, site visits, outcomes | **Odoo** | the interaction log lives here |
| **Light inventory** — segment, city, locality, price, BHK, dates, active flag | **Odoo** | needed for the pair gate and eligibility, and must agree with what staff see |

Join key: `property.base.uuid` ↔ the website API's `id`. So `uuid` is mandatory in every payload here, and a property with no `uuid` is unjoinable — §7 makes that visible rather than silent.

## 3. Endpoints

Three GETs, `auth="public"` with an API-key check, JSON, paginated.

```
GET /ml/v1/inventory?page=&limit=1000&updated_since=
GET /ml/v1/interactions?page=&limit=5000&since=&until=
GET /ml/v1/site_visits?page=&limit=5000&since=&until=
```

### 3.1 `/ml/v1/inventory`

From `property.base`. Fields verified against `properties/models/property_base.py` on `development_19`:

```json
{
  "uuid": "…", "prop_id": "NWWFWT4B",
  "prop_type": "residential", "prop_sub_type": "apartment",
  "for_sell": true,
  "state": "Gujarat", "city": "Ahmedabad", "location": "Isanpur",
  "bhk": "3 BHK", "bedroom_count": 3,
  "pricing": 5800000.0, "pricing_unit": "rupees",
  "reg_date": "2025-05-14",
  "service_expiry_date": "2026-11-30",
  "is_active": true,
  "gmaps_url": "https://…"
}
```

**Excluded, permanently:** `owner_name`, `owner_phone`, `owner_email` (PII), and `rm_user_id` (staff identity — the model has no use for it; RM routing happens on the Odoo side).

Two field-level cautions the model side must know:

- **`bhk` is a `Char`** (`"3 BHK"`), computed from `bedroom_count`, and `bedroom_count` is an `Integer` — so the fractional `2.5 BHK` values present in the website API cannot be represented here. Take BHK from the website API; treat Odoo's as a cross-check, not a source.
- **`pricing_unit` is a free `Char`**, not a selection. Validate on arrival, never trust — a unit mix-up is the exact failure the ML side's range gates exist to catch.

### 3.2 `/ml/v1/interactions`

From `leads.new`. The co-inquiry supervision source.

```json
{
  "interaction_id": 918273,
  "buyer_key": "7c1e…",              // HMAC-SHA256, see §4
  "property_uuid": "…",
  "inquiry_type": "primary",          // primary | recommended
  "parent_interaction_id": 918001,    // null unless recommended
  "current_status": "site_visit_done",
  "created_on": "2026-03-11"
}
```

`inquiry_type` and `parent_inquiry_id` **do exist**, declared on the `leads.new` extension in `leads/models/leads_new_inquiry.py` — not in `new_portal_leads.py` where most fields live. Both indexed; `inquiry_type` is required with `default="primary"`.

`created_on` maps to `create_date_only` (stored computed `Date`), not `create_date` — the date is what the ML side buckets on, and the stored version is indexed.

### 3.3 `/ml/v1/site_visits`

From `lead.site.visit`. The strong-intent tier and the source of the graded reward.

```json
{
  "visit_id": 4412,
  "buyer_key": "7c1e…",
  "property_uuid": "…",
  "interaction_id": 918273,
  "inquiry_type": "primary",
  "scheduled_date": "2026-03-18",
  "status_code": "completed",
  "feedback_code": "price_too_high",
  "feedback_category": "pricing",
  "management_signal": "loss_reason"
}
```

`status_code` from `status_id.code`, `feedback_*` from `feedback_option_id` — **codes, not ids and not names**. Ids are meaningless across environments; names get edited. Both `lead.site.visit.status.code` and `lead.site.visit.feedback.option.code` are enforced immutable after create by `write()` overrides in `leads/models/lead_site_visit.py`, which is exactly what makes them safe as a stable contract vocabulary.

`inquiry_phone` and `inquiry_type` on the visit are **stored `related` fields** off `inquiry_id`, already denormalised and indexed — no join needed to derive the buyer key.

## 4. The PII boundary — HMAC-SHA256 with a server-side pepper

**Decision:** the buyer key is `HMAC-SHA256(pepper, canonical_10_digit_phone)`, computed inside Odoo, in the same query that reads the phone. **Raw phone never crosses the boundary.**

```python
from odoo.addons.leads.controllers.shared.phone_utils import normalize_phone_to_10_digit

canonical = normalize_phone_to_10_digit(phone)     # existing helper — see §4.5
if canonical is None:
    return None                                    # counted in excluded.unparseable_phone (§7)

buyer_key = hmac.new(
    key=_pepper(),                                 # never leaves Odoo — §4.3
    msg=canonical.encode(),
    digestmod=hashlib.sha256,
).hexdigest()
```

### 4.1 Why not md5

md5 of a 10-digit number is **trivially reversible by brute force** — the Indian mobile keyspace is ~10⁹ candidates, minutes of compute. An unkeyed digest of a phone number is not pseudonymisation in any meaningful sense; it is an encoding. Anyone holding the ML dataset could recover every phone number in it.

HMAC with a secret pepper removes that: without the pepper there is no dictionary to build, because candidate digests cannot be computed.

**And md5 is not cheaper.** Same code path, same call site, one different function — no schema change either way. The only reason to prefer md5 would be implementation cost, and there is none, so there is no case for taking the reversible option.

### 4.2 What this does and does not achieve

Stated precisely, because "hashed" is often treated as a stronger claim than it is:

| Achieves | Does not achieve |
|---|---|
| The ML store cannot be reversed to phone numbers by anyone without the pepper | **Anonymity.** Cleardeals holds the pepper, so Cleardeals can re-identify. Under DPDP that keeps this personal data, and the ML store stays in scope for purpose limitation, retention and security obligations |
| Accidental leakage — logs, screenshots, a mis-shared bucket — does not expose contact details | Freedom from a data-principal rights request. Erasure still has to reach the ML artifacts, which is a real operational requirement, not a theoretical one |
| Analysts and the pipeline work without ever seeing contact data | Protection against someone with *both* the dataset and the pepper |

So the honest framing: this is **strong pseudonymisation and a defensible data-minimisation measure** — the right thing to build and a clear improvement on both raw phone and md5. It is not a route to treating the training data as out of scope. Two things follow from that and should be planned, not assumed:

- **Erasure has to be executable.** A deletion request must be satisfiable in the ML store, which means the buyer key has to be *derivable on demand* from the phone (it is — same pepper, same input) so the affected rows can be found and dropped. Recording this now is cheap; discovering it during a request is not.
- **Retention needs a stated period** for raw interaction extracts, distinct from the trained model's lifetime.

### 4.3 Where the pepper lives — **not** in the database

This is the part that differs from the existing API keys, and the reason matters:

| Secret | Rotatable? | Storage |
|---|---|---|
| `properties.api_key`, `track_api.secret_key` | yes, freely — rotate and update the caller | `ir.config_parameter` (existing pattern) |
| **The buyer-key pepper** | **effectively never** — rotating it changes every buyer key and orphans all historical baskets | **`odoo.conf` / environment variable** |

Two concrete reasons to keep it out of `ir.config_parameter`:

1. **This repo copies the production database to laptops.** The `odoo-prod-migration-check` workflow streams a prod snapshot locally to rehearse upgrades. A pepper in `ir_config_parameter` travels in that snapshot — and then into every developer's Docker volume and every staging DB. It would be the one secret that leaks by following the normal, correct development process.
2. **A pepper in the DB sits in every backup**, alongside the very data it protects. Storing the key with the ciphertext defeats the point.

**Preferred: GCP Secret Manager.** The firm already runs on GCP (`odoo-472708`), so this needs no new infrastructure and gives what a file cannot: IAM-scoped access, an audit log of every retrieval, versioning, and survival across VM rebuilds. Fetched once at worker startup and held in memory.

**Acceptable fallback: `odoo.conf` / environment variable.** Simpler, and it still satisfies both reasons above.

```ini
; odoo.conf — fallback form. NOT in ir_config_parameter, NOT in git
ml_api_buyer_key_pepper = <32+ random bytes, base64>
```

Either way the pepper is read through **one** accessor (`_pepper()`), so moving from file to Secret Manager later is a single function.

**Fail closed.** If the pepper is missing, the endpoints return `503` and serve nothing. They must **never** fall back to an unpeppered digest — that would silently emit keys that match nothing and are indistinguishable from correct output until months of training data have been built on them. This is the single most important failure mode in this document, and it has a test (§12).

**The pepper must be backed up and escrowed** somewhere other than the server. Losing it does not expose anything, but it permanently disconnects future extracts from every historical basket — a data-loss event with no error message.

### 4.4 Consequence: existing extracts are orphaned

The validation extracts in the ML repo (`data_prep/validation/data/*.csv`) carry md5 buyer keys. Those keys **will not match** anything produced by this contract.

They are analysis artifacts, not training inputs, so the resolution is to **regenerate them through this API once it exists** and treat the md5 versions as superseded. Numbers derived from them (basket counts, co-visit pairs) are unaffected — the *grouping* is identical because the same phones map one-to-one onto the new keys; only the key strings differ.

### 4.5 Normalisation is part of the contract — reuse the existing helper

**Use `leads/controllers/shared/phone_utils.normalize_phone_to_10_digit()`.** Do not reimplement.

It already handles every real Indian format and returns a canonical 10-digit string, or `None` when the number cannot be resolved:

| Input | Output |
|---|---|
| `9876543210` | `9876543210` |
| `919876543210` | `9876543210` |
| `+919876543210` | `9876543210` |
| `09876543210` | `9876543210` |
| `"  98765 43210 "` | `9876543210` |

> **A naive digit-strip is wrong, and wrong in the silent direction.** `re.sub(r"\D", "", phone)` maps `+919876543210` to the 12-digit `919876543210` while the same person's `9876543210` maps to itself — **two different buyer keys for one buyer.** The basket splits, the co-inquiry pair is never formed, and nothing errors. Given the country code appears inconsistently across portal sources, this would silently weaken the largest supervision tier (177,682 pairs).

The `None` return is the source of `excluded.unparseable_phone` in §7 — a phone that cannot be canonicalised yields no buyer key and the row is reported, not guessed at.

**Normalisation is version-locked with the contract: changing it is as breaking as changing the pepper.** Both alter every downstream key. If `phone_utils` is ever revised, this contract's version must move with it and the change must be treated as a re-key, not a bug fix.

### 4.6 Considered and deferred: tokenisation

The alternative was a buyer entity holding a random opaque token, with the phone→token mapping never leaving Odoo. It is stronger in two ways: no cryptographic secret to escrow, and **erasure of one buyer becomes a single row delete** that renders the ML store permanently unlinkable without touching any training artifact — versus HMAC, where satisfying a deletion request means locating and rewriting parquet files in GCS.

**Deferred because it requires a buyer master model, which does not exist** (no `res.partner` link, no buyer table — a buyer is only a repeated phone string on `leads.new`), and building one purely for this is disproportionate.

Worth revisiting **when the buyer entity is built for `02-buyer-engagement-state.md`**, since the token would then be one extra column on a table needed anyway. Note the cost of that path honestly: switching later **re-keys every buyer** and orphans historical baskets, exactly as switching hash functions would. The decision here accepts that cost in exchange for not blocking the pipeline on a schema change.

## 5. Authentication

Reuse the established pattern — `X-API-Key` header, expected value in `ir.config_parameter`, `hmac.compare_digest` — as implemented in `properties/controllers/auth.py` and `leads/controllers/shared/auth.py`.

**A distinct parameter: `ml_api.read_key`.** Not `properties.api_key`, not `track_api.secret_key`. Different consumer, independent rotation, and a leak of one does not extend to the others. Unlike the pepper (§4.3), this *is* a rotatable secret and `ir.config_parameter` is the right home.

Two additions over the existing helpers:

- **Reject when unset** rather than defaulting to open. `properties/controllers/auth.py` already does this (503 when the parameter is missing) — preserve it; the opposite default is how a staging key ends up serving prod.
- **Log every call** with caller IP, endpoint, page and row count. This is the only audit trail for data leaving the system, and DPDP-wise it is the record that shows what was disclosed and when.

## 6. Pagination, filtering and reproducibility

```
page             1-based
limit            default 1000, hard max 5000
since / until    inclusive date bounds
updated_since    inventory only, on write_date
```

Every response carries the paging envelope:

```json
{ "page": 3, "limit": 5000, "total": 118422, "pages": 24, "generated_at": "2026-07-30T18:30:00Z" }
```

### 6.1 Ordering must be total and stable

**`ORDER BY id`, always.** Not `create_date`, not `write_date`.

A non-unique sort key lets rows with equal values land on either side of a page boundary between requests, so a 24-page pull can silently duplicate one row and drop another. With `id` as a unique tiebreaker that cannot happen. This is the class of defect that produces a training set wrong by 0.001% and never gets found.

### 6.2 The catalogue is live

`property.base` grows during a multi-page pull, so paginated reads are not a snapshot. Two cheap mitigations:

- **`generated_at` in every page**, recorded by the pipeline in its run manifest — a run is at least *described* by a timestamp.
- **A row-count check**: re-request page 1 at the end and compare `total`. A change means the pull straddled a write, and the run is retried rather than trusted.

Full transactional snapshotting is deliberately not built. At ~2.3k properties and ~123k inquiries the pull takes seconds, the straddle window is tiny, and the check detects it. Revisit if volume grows an order of magnitude.

## 7. Data-quality reporting, not silent filtering

The endpoints must **not** quietly drop rows they consider bad. A filtered row is a row the ML side cannot count, and unexplained gaps become an unfalsifiable *"the data is weird"*.

Each response carries an `excluded` block:

```json
"excluded": { "no_uuid": 4, "no_property": 118, "unparseable_phone": 27 }
```

| Excluded | Why |
|---|---|
| `no_uuid` | unjoinable to the website API — §2 |
| `no_property` | inquiry with `property_base_id` empty; nothing to pair |
| `unparseable_phone` | no digits after normalisation, so no buyer key |

Counts only, never the rows. **`no_uuid` rising is an inventory-hygiene problem in Odoo**, and it should surface as a number the Odoo team can act on rather than as missing rows in a GCS bucket nobody on the Odoo side reads.

## 8. Brokers are not filtered here

The ML side de-brokers by excluding buyers with 11+ properties (446 buyers, 0.7%). That threshold is a **modelling decision** and belongs where it can be tuned against the eval.

So the API sends everything and the pipeline filters. Baking the threshold in would mean an Odoo deployment to retune a hyperparameter, and would hide the broker population from the ML side entirely.

Same for the segment pair gate, the recency window and the reward mapping: **the API supplies facts, the pipeline applies policy.** The one exception is PII (§4) — that is a boundary, not a policy, and boundaries belong at the source.

## 9. What this contract does *not* carry

| Not included | Because |
|---|---|
| Escalations | parked; the model's activation term reads zero meanwhile ([`00-scope-and-sequencing.md`](00-scope-and-sequencing.md)) |
| Buyer engagement state | needs a schema change first — `02-buyer-engagement-state.md`, next in the cycle |
| Manager boosts | parked |
| `property_lead_suggestion` | the old engine's output; 17k+ untouched rows, unreliable feedback. Deliberately not exposed so it cannot be mistaken for a label source |
| Anything writable | the write path is deferred |

## 10. Performance

Known volumes: ~2.3k inventory rows, ~123k inquiries, ~18k visits. A full pull is a handful of paged queries over indexed columns.

- Filter columns are already indexed: `leads.new.create_date_only`, `phone`, `property_base_id`; `lead.site.visit.inquiry_phone`, `scheduled_datetime`, `status_id`; `property.base.uuid`, `is_active`.
- Use `search_read` with an explicit field list — never `read()` on full records, which triggers every stored compute, including the HTML timeline computes on `leads.new` in `leads_new_inquiry.py`.
- **Avoid `all_associated_properties`.** It is tempting — a stored computed m2m of primary + recommended properties — but it is scoped *per lead*, while the ML side needs baskets per **buyer** (grouped across leads by buyer key). It would have to be regrouped anyway. Send raw rows.
- HMAC per row is negligible (~µs), but compute it in Python over a `search_read` result rather than in SQL, so the pepper never appears in a query string or a slow-query log.

## 11. Where the code lives

A thin **`ml_api`** module depending on `properties` + `leads`, containing only controllers, serialisers, the shared normalisation/HMAC helper and its own auth helper.

The alternative — controllers inside `properties` and `leads` — follows existing structure but spreads one versioned contract across two modules, so versioning becomes a coordination problem. A single module means one manifest version tracks the contract, `/ml/v1/` route registration, the key parameter and the access log all sit together, and it can be uninstalled without touching the domain modules.

It also puts the pepper handling in exactly one place, which is what makes §4.3's fail-closed guarantee auditable.

## 12. Tests

| Test | Asserts |
|---|---|
| `test_no_pii_in_any_payload` | asserts on the **serialised JSON**, not the field list: no key or value matching a phone, email or `owner_*`. Never weaken this one |
| `test_missing_pepper_fails_closed` | pepper absent → `503`, and **no** unpeppered fallback. The most important test here (§4.3) |
| `test_buyer_key_matches_reference_hmac` | a known phone + known pepper → a fixed expected digest, pinning normalisation *and* algorithm together |
| `test_buyer_key_normalisation` | `9876543210`, `919876543210`, `+919876543210`, `09876543210`, `"  98765 43210 "` → **one identical key** (§4.5) |
| `test_unresolvable_phone_yields_no_key` | `normalize_phone_to_10_digit` returning `None` → row reported in `excluded.unparseable_phone`, never a key derived from a partial number |
| `test_pepper_never_logged` | the pepper appears in no log record and no exception message |
| `test_pagination_is_total_ordered` | a full pull contains every id exactly once, with a concurrent insert mid-pull |
| `test_codes_not_ids` | status and feedback arrive as `code`; renaming a label does not change the payload |
| `test_excluded_counts_reported` | a row with no `uuid` appears in `excluded.no_uuid` and **not** in `rows` |
| `test_missing_api_key_is_503_not_open` | unset parameter refuses, never serves |
| `test_wrong_key_is_403_and_logged` | |
| `test_limit_capped` | `limit=999999` clamps to the max |
| `test_no_write_route_exists` | route-table introspection: nothing under `/ml/v1/` accepts POST/PUT/PATCH/DELETE |

## 13. Open decisions

1. **Pepper storage** — GCP Secret Manager (preferred) vs `odoo.conf` (§4.3), and where the escrow copy lives. Losing the pepper is silent and permanent: nothing is exposed, but every future extract disconnects from all historical baskets, with no error message.
2. **Retention period** for raw interaction extracts in GCS, distinct from model lifetime (§4.2).
3. **Erasure runbook** — the concrete steps to satisfy a deletion request across the ML store. Derivable now; should be written before the first production pull.
4. **Does the pipeline pull inventory from Odoo at all**, given the website API is richer? Yes, for `is_active` and `service_expiry_date` — but the overlapping fields need a field-by-field owner so the two sources never disagree silently.
5. **`updated_since` semantics** — `write_date` changes on any write, including unrelated ones, so incremental inventory pulls will over-fetch. Acceptable at this size; noted so it is not mistaken for a change log.
6. **Rate limiting** — probably unnecessary for one nightly consumer, but these are public-auth routes and a runaway retry loop is the realistic risk.
