# Odoo runtime and services — what runs where, and how

**Branch:** `feature/ml-matching-integration` · **Status:** design · **Date:** 2026-08-05
**Counterpart:** ML repo `docs/07-gcp-infrastructure-and-runtime.md` — the other half of the system, across the network boundary.
**Depends on:** [`01-read-contract.md`](01-read-contract.md) · [`04-lead-provenance.md`](04-lead-provenance.md) · [`06-autonomous-mode-integration.md`](06-autonomous-mode-integration.md)

Written so that a person who has read nothing else finishes it knowing **what runs on the machine, what each process does, what the database holds, when the crons fire, and what happens when something breaks.**

---

## 1. The whole Odoo side on one page

```
                        Internet
                            │  HTTPS :443
                            ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  GCE VM  odoo-19-prod   ·  e2-medium (2 vCPU shared, 4 GiB)      │
   │  us-central1-f  ·  project odoo-472708  ·  Docker Compose        │
   │                                                                  │
   │  ┌────────────┐   ┌──────────────────────┐   ┌────────────────┐  │
   │  │  traefik   │──▶│  odoo  (Odoo 19)     │──▶│  db            │  │
   │  │  v2.10     │   │  2 HTTP workers      │   │  postgres:17   │  │
   │  │  LE certs  │   │  1 cron worker       │   │  cleardeals_   │  │
   │  │  :80 :443  │   │  :8069  :8072 gevent │   │  19_prod       │  │
   │  └────────────┘   └──────────────────────┘   └────────────────┘  │
   │        odoo.cleardeals.xyz          ./odoo-db-data (host volume) │
   └──────────────────────────────────────────────────────────────────┘
        ▲              ▲                 │                    │
        │              │                 │                    │
   RMs / managers   ML pipeline      ML serving          Google Pub/Sub
   browser          GET  /ml/v1/*    POST /v1/similar     POST /wa/pubsub/push
                    POST /ml/v1/     (ID token + IAM)     (WhatsApp, existing)
                         suggestions/*
```

**One machine, three containers, one database.** Everything Odoo-side lives here. Nothing about the ML work adds a server, a queue, or a datastore.

---

## 2. The machine, exactly as configured

| | Value | Consequence |
|---|---|---|
| Instance | `odoo-19-prod`, **e2-medium** — 2 shared vCPU, 4 GiB | RAM is the binding constraint, not CPU |
| Zone | `us-central1-f`, project `odoo-472708` | same region as the ML Cloud Run workloads, so the round trip stays local |
| Orchestration | Docker Compose, `~/odoo-project` | `traefik`, `odoo`, `db` on one bridge network |
| Reverse proxy | Traefik v2.10, Let's Encrypt TLS-ALPN | `odoo.cleardeals.xyz` → `:8069`, `/longpolling` → `:8072` |
| Database | `postgres:17`, db `cleardeals_19_prod` | host volume `./odoo-db-data` |
| HTTP workers | **2** | ≈350 MiB each |
| Cron workers | **1** | **everything scheduled shares one process — see §9** |
| Worker memory | soft 1.25 GiB, hard 1.75 GiB | raised from 1 GiB after workers recycled every 30–60 s under media traffic |
| Request limits | `limit_time_real` 120 s, **`limit_time_real_cron` 0** | cron jobs may legitimately run for minutes |
| Multi-db | `list_db=False`, `dbfilter=^cleardeals_19_prod$` | database-management routes are off |

**The memory story matters for this work.** A worker recycle drops whatever it was doing — that is how a reassignment silently went missing on 2026-07-28, mid-Pub/Sub-publish. Anything the ML integration adds to a request path must be small and bounded, and anything long-running belongs in cron, not HTTP.

---

## 3. The five request paths

Everything that reaches this VM is one of five things. Knowing which one you are looking at determines the credential, the worker, and the failure behaviour.

| # | Path | Who | Auth | Runs in | If it fails |
|---|---|---|---|---|---|
| 1 | `GET /web/...` | RMs, managers | session | HTTP worker | people cannot work |
| 2 | `GET /ml/v1/{inventory,interactions,site_visits,interests,suppressions}` | ML train + generate jobs | `X-API-Key` read key | HTTP worker | tonight's training aborts |
| 3 | `POST /ml/v1/suggestions/*` | ML generate job | `X-API-Key` **write** key | HTTP worker | no leads tonight |
| 4 | **outbound** `POST /v1/similar`, `/v1/pair_scores` | Odoo → `ml-serve` | GCE metadata **ID token** + IAM | HTTP worker | the recommend wizard runs unranked |
| 5 | `POST /wa/pubsub/push` | Google Pub/Sub | Pub/Sub push auth | HTTP worker | WhatsApp messages queue and retry |

Path 4 is the only **outbound** one, and it is the only one with no stored secret anywhere: Odoo fetches a Google-signed, audience-scoped, one-hour ID token from the instance metadata server.

```python
# custom_addons/ml_suggest/services/ml_client.py
METADATA = ("http://metadata.google.internal/computeMetadata/v1/instance/"
            "service-accounts/default/identity?audience={aud}")

def _id_token(audience):
    # Cached until ~5 minutes before expiry. Nothing is stored on disk or
    # in ir.config_parameter — so it cannot travel inside a DB snapshot.
    return requests.get(METADATA.format(aud=audience),
                        headers={"Metadata-Flavor": "Google"}, timeout=2).text

def call(path, payload, timeout=2.0):
    url = ICP().get_param("ml_serve.base_url")
    try:
        r = requests.post(url + path, json=payload, timeout=timeout,
                          headers={"Authorization": f"Bearer {_id_token(url)}"})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        # NEVER raise into the RM's workflow. The model is an accelerator
        # on an existing flow, never a gate in front of it.
        _logger.warning("ml-serve unavailable: %s", e)
        return None
```

---

## 4. Modules

### 4.1 What exists

| Module | Role |
|---|---|
| `leads` | `leads.new`, `lead.site.visit`, `lead.property.interest`, the wizards, `phone_utils` |
| `properties` | `property.base`, the public property API, `validate_api_key` |
| `wa_communication` | WhatsApp, the Pub/Sub push endpoint, the lead tab |
| `lead_suggestor` | **V1's engine.** 22,381 rows, 17,000+ never opened. Switched off at R1, *not deleted* — see §12 |

### 4.2 What this work adds — three modules, deliberately separate

| Module | Direction | Credential | Can it create a lead? |
|---|---|---|---|
| **`ml_api`** | outbound reads | `ml_api.read_key` | **no, structurally** |
| **`ml_suggest`** | outbound calls to `ml-serve` | metadata ID token | no |
| **`ml_suggest_write`** | inbound writes | `ml_api.write_key` | yes, only via the admission controller |

**Why `ml_api` and `ml_suggest_write` are not one module.** `ml_api` ships a test — `test_no_write_route_exists` — that introspects the route table and asserts nothing under its routes accepts `POST/PUT/PATCH/DELETE`. That makes *"the ML pipeline cannot write"* a mechanically enforced fact rather than a convention. Adding write routes to that module deletes the test and the guarantee together.

Two modules, opposite directions, opposite permissions, separately uninstallable. **Uninstalling `ml_suggest_write` is a complete and verifiable stop** — stronger than any flag.

---

## 5. The database

### 5.1 Existing, and their size

| Table | Rows | Note |
|---|---|---|
| `leads_new` | ~123k | the interaction log; the most-edited record in the system |
| `lead_site_visit` | ~18k | strong-intent tier |
| `lead_property_interest` | — | the RM-recommendation tier |
| `property_base` | ~2.3k (924 active) | light mirror; rich features live in the website API |
| `mail_message` / `mail_tracking_value` | large | chatter; `current_status` changes are 76,886 tracked values |

### 5.2 What this work adds

**One column on a hot table**, and it is the only intrusion into existing schema:

```python
# leads.new
buyer_key = fields.Char(index=True, readonly=True, copy=False)
```

Written in `create()` and in `write()` when `phone` changes — **not** a stored compute, because a recompute triggered by an unrelated ORM event would silently rewrite the join key of 123k rows. It exists because the pipeline identifies buyers by `HMAC-SHA256(pepper, canonical_phone)` and **HMAC cannot be inverted**, so Odoo needs an indexed reverse lookup.

Plus five new models:

| Model | Rows/year at R3 | Holds |
|---|---|---|
| `ml.suggestion.batch` | ~365 | one night's submission: model version, policy snapshot, state |
| `ml.suggestion.proposal` | ~164k | **every proposal, including every rejected one** |
| `ml.lead.provenance` | ~55k | one row per AI lead; every field immutable |
| `ml.buyer.holdout` | ~50k | the control/treatment draw, made once, never recomputed |
| `ml.generation.policy` | 1 | the live control surface: kill switch, ramp, caps |

**Indexes that must exist**

```sql
CREATE UNIQUE INDEX ON ml_suggestion_proposal (batch_id, proposal_uid);
CREATE INDEX        ON ml_suggestion_proposal (buyer_key);
CREATE INDEX        ON ml_suggestion_proposal (state, create_date);
CREATE UNIQUE INDEX ON ml_buyer_holdout (buyer_key);
CREATE INDEX        ON leads_new (buyer_key);
CREATE INDEX        ON leads_new (user_id, current_status);   -- routing load query
```

**Storing rejected proposals is the most consequential decision in this schema.** It looks like debris; it is the measurement instrument. A control-group buyer's rejected row *is* the counterfactual — without it the holdout measures *"control got nothing"* rather than *"control did not get **this**, which treatment did."* It is also what separates *the model found nothing* from *budgets bound* from *everyone was suppressed*: three unrelated problems that are indistinguishable if you keep only the successes.

At ~450 rows a night this is trivial for Postgres. **Retention is a policy question, not a capacity one** — these are hashed-key rows about real people, so the measurement window sets the floor and data-minimisation sets the ceiling.

---

## 6. Crons

All of these share **one cron worker**. See §9.

| Cron | Schedule | Runtime | What it does |
|---|---|---|---|
| `ml_admission_controller` | every 10 min, 04:40–06:00 | seconds | admits pending batches |
| `ml_reconcile_stale_batches` | hourly | ms | marks abandoned batches failed |
| `ml_policy_halt_check` | every 15 min | ms | trips the kill switch on breach conditions |
| existing Odoo + WhatsApp crons | various | — | already there |

**Why admission is a cron and not the POST handler.** Three reasons: a 60-proposal admission with per-row transactions and RM selection is not an HTTP-request-shaped workload; a submit that timed out mid-admission would leave the pipeline genuinely unsure whether real people had been contacted; and **a batch arriving while the kill switch is on must sit and wait**, not fail — the pipeline did nothing wrong, policy just said not tonight.

---

## 7. The read contract — pseudocode

```python
# custom_addons/ml_api/controllers/ml_read.py

@http.route("/ml/v1/interactions", auth="public", methods=["GET"], csrf=False)
def interactions(self, page=1, limit=1000, since=None, until=None):
    _require_read_key()                       # 503 if unset — never default open

    domain = _date_domain(since, until)
    Lead   = request.env["leads.new"].sudo()

    rows = Lead.search_read(
        domain,
        fields=["id", "phone", "property_base_id", "inquiry_type",
                "parent_inquiry_id", "current_status", "create_date_only",
                "feedback_general", "feedback_site_visit_done"],
        # Total and stable. NOT create_date: a non-unique sort key lets rows
        # with equal values land on either side of a page boundary between
        # requests, so a 24-page pull silently duplicates one row and drops
        # another. That is the defect that makes a training set wrong by
        # 0.001% and is never found.
        order="id asc",
        offset=(int(page) - 1) * int(limit), limit=int(limit),
    )

    out, excluded = [], Counter()
    for r in rows:
        canonical = normalize_phone_to_10_digit(r["phone"])   # the existing helper
        if not canonical:
            excluded["unparseable_phone"] += 1; continue      # counted, never silent
        if not r["property_base_id"]:
            excluded["no_property"] += 1;      continue
        out.append({
            # HMAC computed in Python over the search_read result, never in
            # SQL — so the pepper cannot appear in a query string or a
            # slow-query log. Raw phone never crosses the boundary.
            "buyer_key": hmac_buyer_key(canonical),
            "property_uuid": _uuid_of(r["property_base_id"]),
            "inquiry_type": r["inquiry_type"],
            "parent_interaction_id": r["parent_inquiry_id"],
            "current_status": r["current_status"],
            "feedback_general": r["feedback_general"],
            "feedback_site_visit_done": r["feedback_site_visit_done"],
            "created_on": r["create_date_only"],
        })

    _log_disclosure(request, "/ml/v1/interactions", page, len(out))  # DPDP record
    return {"page": page, "limit": limit, "total": Lead.search_count(domain),
            "generated_at": utcnow(), "rows": out,
            # Counts only, never the rows. A filtered row is a row the ML
            # side cannot count, and unexplained gaps become an
            # unfalsifiable "the data is weird". `no_uuid` rising is an
            # inventory-hygiene problem for the Odoo team to act on.
            "excluded": dict(excluded)}
```

**The governing rule: the API supplies facts, the pipeline applies policy.** Broker exclusion, the recency window, the segment gate and the reward mapping all live on the ML side where they can be tuned against the eval — baking the broker threshold in here would mean an **Odoo deployment to retune a hyperparameter**. The single exception is PII, because that is a boundary, not a policy, and boundaries belong at the source.

---

## 8. The write path — pseudocode

### 8.1 Submission: accepting is not admitting

```python
@http.route("/ml/v1/suggestions/batch", auth="public", methods=["POST"], csrf=False)
def submit_batch(self, **payload):
    _require_write_key()                       # a DIFFERENT key from the read one
    body_hash = sha256(request.httprequest.data)

    existing = Batch.search([("batch_id", "=", payload["batch_id"])], limit=1)
    if existing:
        if existing.body_sha256 == body_hash:
            return _state_of(existing)         # 200 — idempotent retry
        # Silently accepting changed content under a used batch_id would
        # overwrite the record of what was actually sent to real people,
        # and that record is the audit trail. Regenerating means a NEW id.
        return _err(409, "batch_id_reused_with_different_content")

    errors = _validate(payload)                # ranks contiguous from 1; uids
                                               # unique; no phone/email/name
                                               # patterns anywhere in the body
    if errors:
        if "pii_pattern" in errors:
            _alert_security(payload["batch_id"])   # a breach, not a typo
        # Whole batch rejected. A partial accept leaves holes in the rank
        # sequence, and every guarantee rests on that sequence being intact.
        return _err(422, errors)

    batch = Batch.create({... , "state": "received", "body_sha256": body_hash})
    Proposal.create([_row(batch, p) for p in payload["proposals"]])
    return {"batch_id": batch.batch_id, "state": "received",
            "accepted": len(payload["proposals"])}
```

### 8.2 The admission controller

```python
def _cron_admit_pending_batches():
    for batch in Batch.search([("state", "=", "received")]):
        policy = Policy.singleton()

        if policy.kill_switch:
            continue                            # wait, do not fail the batch
        if _model_age_hours(batch) > policy.max_model_age_hours:
            batch.reject_all("stale_model");  continue

        batch.state = "admitting"
        # rank IS the allocation order from the pipeline's coverage rounds.
        # Walking it in order and only ever DROPPING preserves the coverage
        # property. Re-sorting by match_score would silently hand the whole
        # budget back to listings that were never starved.
        for p in batch.proposal_ids.sorted("rank"):
            _admit_one(p, policy)
        batch.state = "admitted"
```

```python
def _admit_one(proposal, policy):
    """One transaction per proposal. A 60-proposal batch that fails on #47
       must keep 1-46."""
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        env.cr.execute("SELECT id FROM ml_generation_policy "
                       "WHERE id=%s FOR UPDATE", (policy.id,))   # cap counters

        buyer = _resolve(proposal.buyer_key)     # indexed reverse lookup
        if not buyer:            return proposal.reject("buyer_not_found")

        # --- gates, in this order, and the order is load-bearing ----------
        # Holdout is checked BEFORE every budget. After budgets, control
        # buyers would consume the day's cap and produce nothing, so the
        # treatment arm would receive ~10% fewer leads than policy intends
        # and the arms would differ by more than the treatment.
        if _holdout(buyer) == "control":        return proposal.reject("holdout_control")
        if _suppressed_live(buyer):             return proposal.reject("suppressed")
        if _engagement(buyer) in BLOCKED:       return proposal.reject("ineligible_state")
        if _in_cooldown(buyer, proposal):       return proposal.reject("duplicate_cooldown")
        if not _property_available(proposal):   return proposal.reject("property_unavailable")
        if _buyer_month_count(buyer) >= policy.per_buyer_monthly_cap:
                                                return proposal.reject("cap_buyer_monthly")
        if _property_day_count(proposal) >= policy.per_property_daily_cap:
                                                return proposal.reject("cap_property")
        if _global_day_count() >= policy.global_daily_cap:
                                                return proposal.reject("cap_global")

        # Last, because it is the most expensive AND because recording it as
        # the reason lets the report distinguish "we chose not to" from
        # "we had nobody to give it to" — a staffing problem no model fixes.
        rm = _route(proposal)
        if not rm:                              return proposal.reject("no_eligible_rm")

        lead = env["leads.new"].create({
            "name": buyer.name, "phone": buyer.phone,
            "property_base_id": proposal.property_base_id.id,
            "user_id": rm.id,
            "inquiry_type": "ai_suggested",
            "current_status": "lead",
            "buyer_key": proposal.buyer_key,
        })
        # These two writes are ONE transaction and must stay that way. A lead
        # without provenance is the unrecoverable failure: an AI lead
        # indistinguishable from an organic one, forever.
        env["ml.lead.provenance"].create({
            "lead_id": lead.id, "model_version": proposal.batch_id.model_version,
            "suggestion_batch_id": proposal.batch_id.id,
            "proposal_uid": proposal.proposal_uid,
            "source_property_id": proposal.source_property_id.id,
            "match_score": proposal.match_score,
            "activation_reason": proposal.activation_reason,
            "holdout_group": "treatment",
            "routed_to_uid": rm.id, "routing_reason": rm.reason,
        })
        lead.message_post(body=_explanation(proposal))   # the RM-facing "why"
        _owning_rm(proposal).subscribe(lead)             # follower, not owner
        proposal.write({"state": "admitted", "lead_id": lead.id})
```

### 8.3 Routing

```python
def _route(proposal):
    """AI leads route by LOAD, not by property ownership. Under ownership,
       an RM with 40 starved listings would receive every lead those
       listings generate — the mechanism meant to relieve them would be
       the one that buries them."""
    eligible = Users.search([
        ("ml_metro_ids",   "in", proposal.metro_id.id),
        ("ml_segment_ids", "in", proposal.segment_id.id),
        ("active", "=", True),
        ("login_date", ">=", now() - timedelta(days=policy.max_idle_days)),
    ])
    # Fails CLOSED. If coverage is unconfigured, nobody is eligible and the
    # proposal is rejected — routing to whoever is first alphabetically is
    # worse than a batch that produces nothing and says so.
    under_cap = [u for u in eligible
                 if _open_ai_leads_today(u) < policy.per_rm_daily_cap]
    if not under_cap:
        return None

    chosen = sorted(under_cap, key=lambda u: (
        _open_ai_leads_today(u),        # the real load signal
        _open_leads_total(u),           # organic work is still work
        _ai_leads_last_7_days(u),       # the fairness floor: without this,
                                        # an RM who closes fast always looks
                                        # least-loaded and gets a permanently
                                        # larger share — speed becomes volume,
                                        # then burnout
        u.id,                           # deterministic tie-break: without it,
                                        # two runs of one batch route
                                        # differently and "why me" has no
                                        # stable answer
    ))[0]
    chosen.reason = (f"{_open_ai_leads_today(chosen)} open AI leads · "
                     f"covers {proposal.metro_id.name}")
    return chosen


def _open_ai_leads_today(user):
    """Derived, never a stored counter. A counter that drifts fails
       SILENTLY — a lead closed by a path that forgets to decrement leaves
       an RM permanently looking busier than they are, and they stop
       receiving work with nothing anywhere reporting a fault."""
    return Lead.search_count([
        ("user_id", "=", user.id),
        ("inquiry_type", "=", "ai_suggested"),
        ("current_status", "in", OPEN_STATUSES),
        ("create_date", ">=", start_of_today()),
    ])
```

---

## 9. Capacity — the constraint nobody should discover in production

**One cron worker.** `max_cron_threads = 1`, and it already runs the existing Odoo crons plus the WhatsApp batch work. The admission controller joins that queue.

Sizing says this is fine: ~60 proposals, per-row transactions of a handful of indexed queries each — **seconds, once a night, at 04:40, when nobody is working.** But the constraint is real and must be respected:

| Rule | Why |
|---|---|
| Admission runs **04:40–06:00 only** | outside office hours; never contends with an RM's request |
| `_admit_one` is **one short transaction per proposal** | a long one would hold the policy row lock and block everything |
| **No ML call in an HTTP request path without a 2 s timeout** | `limit_time_real` is 120 s; a hung outbound call burns a worker, and there are only two |
| The recommend wizard **degrades to unranked** on timeout | never a blocking error in front of an RM |
| Nothing new is added to `leads_new` **compute chains** | one indexed column, written explicitly |

**On memory:** worker RSS is the historical failure here — recycles at 1 GiB were dropping in-flight Pub/Sub publishes. The ML additions are deliberately small: one outbound JSON call with a 2 s timeout, no large payload buffering, no image handling. If `workers` is ever raised to 3, re-check RAM against the 4 GiB ceiling first.

---

## 10. Security

**Record rules, already correct and unchanged:**

```
leads.new · RM      →  [('user_id', '=', user.id)]     — own leads only
leads.new · Manager →  [(1, '=', 1)]                   — everything
```

The new models follow the same shape: RMs read provenance for their own leads; **nobody** may write it.

| Model | Read | Write |
|---|---|---|
| `ml.lead.provenance` | RM (own), manager | **nobody, including admins** |
| `ml.buyer.holdout` | manager | **nobody** — moving a buyer between arms by hand is unblinding the experiment |
| `ml.generation.policy` | manager | manager, with a **required written reason**, fully tracked |
| `ml.suggestion.*` | manager | system only |

**Provenance that can be edited is not provenance.** If a value is wrong, the fix is a new lead and a corrected batch — not a quiet `UPDATE` that leaves the training-exclusion set and the holdout alterable after the fact with no trace.

**Credentials**

| Secret | Where | Why there |
|---|---|---|
| `ml_api.read_key` | `ir.config_parameter` | rotatable, read-only scope |
| `ml_api.write_key` | **Secret Manager**, env var | it can create leads against real buyers |
| buyer-key **pepper** | **Secret Manager**, env var | `ir.config_parameter` travels inside a prod DB snapshot |
| ML serve base URL | `ir.config_parameter` | not a secret |

**Rotating the pepper invalidates every stored `buyer_key` and every in-flight proposal.** It is a planned migration — drain open batches, recompute the column, resume — not an ops action. Done casually it would not error; generation would just quietly stop matching buyers and fall to zero.

---

## 11. Deploy and migrations

**The existing pipeline, unchanged:**

```
push to 19.0
   └─▶ GitHub Actions: "Run Odoo Tests"           ← must pass
          └─▶ GitHub Actions: "Deploy Odoo 19"     ← only on success
                 SSH to the VM
                 git reset --hard origin/19.0
                 write odoo.conf from the ODOO_CONF secret
                 docker compose build odoo
                 docker compose up -d --force-recreate odoo
```

**Migrations** ship as `migrations/19.0.x.y.z/post-*.py`, idempotent, with a docstring saying why they exist, and are rehearsed against a prod snapshot (`odoo-prod-migration-check`) before going near production.

**One backfill, with an ordering constraint that matters:**

```python
# migrations/19.0.1.0.0/post-backfill-buyer-key.py
def migrate(cr, version):
    """Populate leads_new.buyer_key. ~123k HMACs plus an indexed update.
       Batched and RESTARTABLE: a migration that half-populates a join key
       and then dies does not fail — it silently narrows the buyer pool to
       whoever happened to be backfilled, and nothing reports it."""
    while True:
        cr.execute("SELECT id, phone FROM leads_new "
                   "WHERE buyer_key IS NULL AND phone IS NOT NULL LIMIT 5000")
        rows = cr.fetchall()
        if not rows: break
        ...
```

> **This backfill must complete before the kill switch is ever turned off.** A partially-backfilled key column looks healthy and quietly halves the reachable buyer pool.

---

## 12. Coexistence with V1

`property_lead_suggestion` still exists: **22,381 rows, 17,000+ never touched**, with an active cron.

**Switched off at R1, not deleted.** Those rows are the evidence base for the delivery argument that shaped both serving modes, and the 17k figure is cited across four documents in two repos. Deleting the table to tidy up would delete the reason the new design looks the way it does. The cron stops at R1 — running two suggestion engines at once means neither can be evaluated, and the old one is already known not to work.

---

## 13. Observability

Odoo logs to stdout; Docker forwards to Cloud Logging. Traefik logs HTTP separately.

| Watch | Signal |
|---|---|
| `/ml/v1/*` disclosure log | the only audit trail for data leaving the system |
| `excluded.no_uuid` climbing | inventory hygiene — **an Odoo-side problem, surfaced as a number** |
| admission `rejections` breakdown | `cap_global` = widen the ramp · `no_eligible_rm` = staffing · nothing = the model found nothing |
| `admitted == 0` with no rejections | **the failure that looks like silence** — alert on it |
| worker recycles / RSS | the 2026-07-28 class of bug |
| `ml-serve` timeouts from Odoo | wizard degrading; not urgent, but a trend is |

---

## 14. Failure modes

| Failure | Effect | Recovery |
|---|---|---|
| `ml-serve` unreachable | recommend wizard unranked | none needed — by design |
| Read API returns partial pages | training aborts | pipeline retries tomorrow |
| Write API rejects a batch | no leads tonight | one night against a 21-day coverage cycle |
| Kill switch on when a batch lands | batch waits | admits when switched off |
| Bad batch admitted | real leads to real buyers | **rollback by `batch_id`** — archives untouched leads, **keeps** any an RM has worked. You cannot un-happen a phone call |
| Cron worker wedged | admission does not run | batch stays `received`; hourly reconcile flags it |
| Odoo VM down | everything stops | Docker `restart: unless-stopped`; VM restart |
| DB volume lost | catastrophic | host volume `./odoo-db-data` — **see §15** |

---

## 15. Two findings that are not about the ML work

Surfaced here because this document is where someone will look for how the machine is configured.

1. **`odoo.conf` is committed to the repository with a plaintext `admin_passwd` and `db_password`.** The deploy overwrites it from the `ODOO_CONF` GitHub secret, so the running config may differ — but if those values are or ever were real, they are in git history and readable by anyone with repo access. Recommend replacing the values in the committed file with placeholders and treating the current ones as compromised.
2. **The database is a host bind-mount (`./odoo-db-data`) on a single VM.** There is no `pg_dump` schedule visible in the compose file or the deploy workflow. Before this work adds provenance and holdout rows that **cannot be reconstructed from anywhere** — the holdout draw in particular exists nowhere else — a scheduled off-VM backup should be confirmed to exist.

Neither blocks the ML work. Both get worse once it ships.

---

## 16. Build order

| # | Step | Gate to the next |
|---|---|---|
| 1 | `ml_api` module + read endpoints | pipeline pulls a full extract; `test_no_write_route_exists` passes |
| 2 | `buyer_key` column + backfill migration | rehearsed on a prod snapshot; backfill verified **complete** |
| 3 | `ml_suggest` client + recommend wizard | works with `ml-serve` switched off |
| 4 | Schema: five models, security, immutability | `test_provenance_is_immutable` passes as admin |
| 5 | `ml_suggest_write` endpoints, **kill switch on** | contract tests green end to end |
| 6 | Routing engine + RM coverage fields | `test_routing_fails_closed` passes with real config |
| 7 | RM surfaces: badge, explanation, disposition | reviewed with RMs **before any AI lead exists** |
| 8 | Manager dashboard + kill switch in the UI | ops can stop it without engineering |
| 9 | **R0** — kill switch off, cap 20/day | provenance and holdout verified on live rows |

Steps 7 and 8 come before R0, not after. **A system that can create leads before its operators can see or stop them is not at R0; it is unsupervised.**
