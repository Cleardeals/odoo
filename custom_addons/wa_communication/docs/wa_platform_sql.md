# ClearDeals WhatsApp Automation
## SQL Database Design Reference

**13 Tables · Every Column · All Eight Design Decisions Applied · Part A & Part B**

Proptech Cleardeals Pvt. Ltd. | April 2026

---

## Table of Contents

1. [Corrections Applied in This Version](#1-corrections-applied-in-this-version)
   - [1.1 Design Decisions Summary](#11-design-decisions-summary-all-six)
   - [1.2 Complete Table List](#12-complete-table-list--14-tables)
2. [Table: workflows](#2-table-workflows)
3. [Table: workflow_enrollments](#3-table-workflow_enrollments)
4. [Table: outbound_messages](#4-table-outbound_messages)
5. [Table: inbound_messages](#5-table-inbound_messages)
6. [Table: conversation_context](#6-table-conversation_context)
7. [Table: workflow_opt_outs](#7-table-workflow_opt_outs)
8. [Table: actor_timeline](#8-table-actor_timeline)
9. [Table: rm_assignments](#9-table-rm_assignments)
10. [Table: scheduled_reminders](#10-table-scheduled_reminders)
11. [Table: dead_letter_queue](#11-table-dead_letter_queue)
12. [Table: workflow_step_log](#12-table-workflow_step_log)
13. [Part B Tables](#13-part-b-tables)
    - [13.1 Table: odoo_send_requests](#131-table-odoo_send_requests)
    - [13.2 Table: rm_reply_analytics](#132-table-rm_reply_analytics)
14. [User Stories](#14-user-stories)
    - [US-01: Buyer inquiry enrolled, first-touch message delivered](#us-01-buyer-inquiry-enrolled-first-touch-message-delivered)
    - [US-02: Double button tap — branch lock prevents duplicate](#us-02-double-button-tap--branch-lock-prevents-duplicate)    - [US-03: Workflow-scoped STOP opt-out](#us-03-workflow-scoped-stop-opt-out)

---

## 1. Corrections Applied in This Version

> **Three corrections from review**
>
> **Correction 1 — Missing tables restored:** `rm_assignments`, `scheduled_reminders`, `dead_letter_queue`, and `workflow_step_log` were absent from the previous revision. All four are fully documented here.
>
> **Correction 2 — No customer table, no BQ sync:** Customer data now comes from Odoo via events (`actor.created`, `actor.status_changed`) exactly like inquiry data. `actor_type='customer'` on `workflow_enrollments` distinguishes the two, but both are sourced identically from Odoo event payloads. The `customers` table is removed.
>
> **Correction 4 — Universal actor identifier and future lead-identity support:** `inquiry_id` is renamed to `actor_id` across all tables — it was never only an inquiry identifier (customers also use it). A `lead_id UUID` column is added to `workflow_enrollments` and `actor_timeline` as a forward-compatibility slot for the future CRM's person-level identifier. In the current Odoo system this column is always NULL — Odoo's `crm.lead` does not expose a separate person concept. When the new CRM goes live, `lead_id` will carry the `leads.lead_id` UUID, shared across all inquiries (buyer and seller) and the owner record for the same person, enabling a fully unified cross-role timeline. The `actor_type` enumeration is expanded from `('inquiry','customer')` to `('buyer_inquiry','seller_inquiry','customer')` — `seller_inquiry` is scaffolded for the upcoming seller workflow. The `lead_timeline` table is renamed to `actor_timeline` since it serves all actor types equally.
>
> **Correction 3 — Branch lock as columns, not a table:** The `enrollment_branch_decisions` table is removed. Two columns (`branch_locked_at`, `branch_locked_path`) are added directly to `workflow_enrollments`. `reply-router` checks `branch_locked_at` before processing any button reply. Simpler, faster, no table join required.

### 1.1 Design Decisions Summary (all six)

| # | Decision | Schema change |
|---|----------|---------------|
| 1 | `actor_id` as universal actor identifier | `actor_id` column name everywhere (replaces `inquiry_id`). For `buyer_inquiry`: Odoo `crm.lead.id`. For `customer`: Odoo `owner_id` (future) or current customer record ID. For `seller_inquiry`: Odoo seller inquiry record ID (future). For `customer` actors, `actor_property_id` carries the Odoo property ID to scope the enrollment to a specific property (Decision #8) |
| 2 | Context fields in meta JSONB | `portal_source`, `property_id`, `assigned_rm_id`, `assigned_rm_email` removed as columns from `workflow_enrollments`. `meta` JSONB stores them based on `config.yaml` `meta_fields` declaration |
| 3 | Double-tap guard as columns | `branch_locked_at` + `branch_locked_path` on `workflow_enrollments`. No separate table |
| 4 | Multi-enrollment routing — actor-type aware | `active_enrollment_count` on `conversation_context`. For `buyer_inquiry` actors, count > 1 is **expected and normal** (one enrollment per property inquiry). For `customer` (owner) actors, count > 1 is also **expected and normal** when the owner has multiple properties onboarded. Routing falls back to most recent `last_activity_at` in both cases. `routing_method='ambiguous_multi_enrollment'` is reserved for genuinely unresolvable cases |
| 5 | Workflow-scoped opt-out | `workflow_opt_outs` table replaces `opted_out BOOLEAN` on `conversation_context` |
| 6 | Three actor types | `actor_type IN ('buyer_inquiry','seller_inquiry','customer')` on all tables. `buyer_inquiry` = property buyer (current primary use). `seller_inquiry` = seller/owner inquiry (future). `customer` = paid service customer (property owner receiving lead reports, visit coordination). Odoo publishes events for all three types |
| 7 | Future-ready person-level identity (`lead_id`) | `lead_id UUID` column (nullable) added to `workflow_enrollments` and `actor_timeline`. **Currently always NULL** — the present Odoo system has no separate person-level concept; `actor_id` (= `crm.lead.id`) and `phone` serve as the de-facto actor and person keys today. **Future (new CRM):** populated from `leads.lead_id` — the UUID of the person record in the new system. A buyer who creates 5 property inquiries gets 5 `actor_id` values but one `lead_id`. A seller who lists a property also gets a `lead_id`; if they later buy, the same `lead_id` links both roles. A paid customer (property owner) will also carry the same `lead_id` from the new system. This enables a unified timeline across all actor types for a single person: `SELECT * FROM actor_timeline WHERE lead_id=$1 ORDER BY happened_at DESC`. Phone number remains the interim cross-inquiry grouping key until `lead_id` is live |
| 8 | Owner × property scoping via `actor_property_id` | `actor_property_id INTEGER` column (nullable) added to `workflow_enrollments` and `actor_timeline`. **For `customer` actors only** — stores the Odoo property ID so that one owner with 3 properties can have 3 independent enrollment rows in the same workflow (one per property). The `UNIQUE(workflow_id, actor_id)` constraint is replaced by two partial unique indexes: one on `(workflow_id, actor_id)` where `actor_property_id IS NULL` (covers buyer and seller actors), and one on `(workflow_id, actor_id, actor_property_id)` where `actor_property_id IS NOT NULL` (covers customer actors). For `buyer_inquiry` and `seller_inquiry` actors `actor_property_id` is always NULL — those actor types already encode the property relationship inside `actor_id` (`crm.lead.id` is inherently one buyer × one property). Today: `actor_property_id` is populated from `event.payload.property_id` for customer enrollments. Future: remains the same — the Odoo property ID is a stable FK into the property inventory regardless of CRM migration |

### 1.2 Complete Table List — 14 tables

| # | Table | Part | Primary purpose |
|---|-------|------|-----------------|
| 1 | `workflows` | Both | Registry of all automation campaigns |
| 2 | `workflow_enrollments` | Both | State machine — one row per actor per workflow run |
| 3 | `outbound_messages` | Both | Every template message sent via Interakt API |
| 4 | `inbound_messages` | Both | Every message received from any actor |
| 5 | `conversation_context` | Both | Per-phone routing context and multi-enrollment awareness |
| 6 | `workflow_opt_outs` | Both | Workflow-scoped opt-outs (Decision #5) |
| 7 | `actor_timeline` | Both | Append-only chronological event log per actor |
| 8 | `rm_assignments` | Both | Current and historical RM assignments per actor |
| 9 | `scheduled_reminders` | Both | Future-dated events for CronJob processing |
| 10 | `dead_letter_queue` | Both | Messages that exhausted all retries |
| 11 | `workflow_step_log` | Both | Step-level execution audit trail |
| 12 | `odoo_send_requests` | Part B | Queue of messages initiated from Odoo WA-05 interface |
| 13 | `rm_reply_analytics` | Part B | Daily aggregated RM performance metrics |

---

## 2. Table: `workflows`

Registry of every automation campaign. Seeded at deploy time. Never written to at runtime except when a manager toggles `is_active`.

```sql
CREATE TABLE workflows (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    slug         TEXT        UNIQUE NOT NULL,
    name         TEXT        NOT NULL,
    description  TEXT,
    campaign_id  TEXT        NOT NULL,
    pubsub_topic TEXT        NOT NULL,
    trigger_type TEXT        NOT NULL CHECK (trigger_type IN ('event_driven','scheduled','batch')),
    actor_scope  TEXT        NOT NULL DEFAULT 'buyer_inquiry'
                 CHECK (actor_scope IN ('buyer_inquiry','seller_inquiry','customer','both')),
    is_active    BOOLEAN     NOT NULL DEFAULT true,
    version      INTEGER     NOT NULL DEFAULT 1,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by   TEXT
);
```

| Column | Type | Req | Source | What it stores | Why it exists |
|--------|------|-----|--------|----------------|---------------|
| `id` | UUID | R | `gen_random_uuid()` on insert | Globally unique identifier for this workflow. Referenced as FK in every other table | Primary key. Used in cost grouping queries, execution history filtering, and all cross-table FK links |
| `slug` | TEXT | R | `configs/workflows.yaml` at deploy time. E.g. `'nurturing_v2'` | Short machine identifier. Segment 0 of `callback_data`: `slug:step_id:enrollment_uuid` | Must never change after enrollments exist. Embedded in `callback_data` that Interakt echoes back on button replies. Changing it breaks routing for all in-flight enrollments |
| `name` | TEXT | R | `configs/workflows.yaml`. E.g. `'Lead Nurturing'` | Human-readable display name shown in Odoo WA-02 dashboard | Managers see this, not the slug. Safe to change at any time |
| `description` | TEXT | O | `configs/workflows.yaml` | One-sentence description of the campaign shown in WA-02 detail view | Informational. No business logic depends on this |
| `campaign_id` | TEXT | R | Seeded at deploy time. C1–C7 | Campaign grouping. C1=Lead Nurturing, C2=Portal Lead, etc. | Enables per-campaign cost reporting: `SELECT campaign_id, SUM(cost_total_inr) FROM outbound_messages GROUP BY campaign_id` |
| `pubsub_topic` | TEXT | R | `configs/topics.yaml` resolved at deploy time. E.g. `'lead-events'` | The Pub/Sub topic this workflow subscribes to | Shown in WA-02 dashboard. Validated by `config-sync` service before deployment |
| `trigger_type` | TEXT | R | Seeded at deploy time. `'event_driven'` / `'scheduled'` / `'batch'` | How this workflow starts. `event_driven`=Odoo Pub/Sub event. `scheduled`=CronJob fires. `batch`=reads from queue table | Informs dashboard display. Config-sync validator checks this matches the workflow config structure |
| `actor_scope` | TEXT | R | Seeded at deploy time. `'buyer_inquiry'` / `'seller_inquiry'` / `'customer'` / `'both'` | Which actor type(s) this workflow serves. `'buyer_inquiry'` = nurturing, portal-lead, post-visit. `'seller_inquiry'` = future seller workflows. `'customer'` = expiry alerts, renewal. `'both'` = workflows handling multiple actor types | `workflow_engine` uses this to build the correct enrollment meta. `'buyer_inquiry'` workflows expect `property_id`, `portal_source`. `'customer'` workflows expect `service_plan_name`, `expiry_date` |
| `is_active` | BOOLEAN | R | Default `true`. Updated by Odoo WA-02 manager toggle | Whether this workflow is currently processing events | Workflow services check this flag at the start of each message cycle. `false`=skip processing, ack the Pub/Sub message without action |
| `version` | INTEGER | R | Default 1. Incremented each time a config change is deployed | The config version currently deployed | Shown in WA-02. Recorded in `workflow_step_log` so each execution is traceable to a specific config version |
| `created_at` | TIMESTAMPTZ | R | `NOW()` on insert | When this workflow was first deployed | Audit column |
| `updated_at` | TIMESTAMPTZ | R | `NOW()` on any UPDATE | When this workflow was last changed | Shown in dashboard: "last updated 3 days ago" |
| `updated_by` | TEXT | O | Odoo username when a manager changes `is_active`. NULL for system changes | Who last modified this workflow | Audit trail |

---

## 3. Table: `workflow_enrollments`

One row per actor per workflow run. The central state machine. Incorporates all seven design decisions.

> **Multi-enrollment note:** Multiple active enrollments from the same phone are expected and normal in two cases: (a) a buyer with 5 property inquiries has 5 `actor_id` values and up to 5 active enrollments; (b) an owner (customer) with 3 onboarded properties has 3 `actor_property_id` values and up to 3 active enrollments. In both cases `reply-router` routes to the enrollment with the most recent `last_activity_at`. See Decision #4 and Decision #8.

```sql
CREATE TABLE workflow_enrollments (
    id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id          UUID        NOT NULL REFERENCES workflows(id),
    actor_type           TEXT        NOT NULL DEFAULT 'buyer_inquiry'
                         CHECK (actor_type IN ('buyer_inquiry','seller_inquiry','customer')),
    actor_id             INTEGER     NOT NULL,
    actor_property_id    INTEGER,
    lead_id              UUID,
    phone                TEXT        NOT NULL,
    status               TEXT        NOT NULL DEFAULT 'active'
                         CHECK (status IN (
                           'active','waiting','paused','completed','failed','unenrolled'
                         )),
    current_step         TEXT,
    waiting_for          TEXT,
    wait_until           TIMESTAMPTZ,
    current_branch_path  TEXT        CHECK (current_branch_path IN ('A','B',NULL)),
    branch_locked_at     TIMESTAMPTZ,
    branch_locked_path   TEXT        CHECK (branch_locked_path IN ('A','B',NULL)),
    enrolled_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at         TIMESTAMPTZ,
    disengagement_score  NUMERIC(4,2) NOT NULL DEFAULT 0.0,
    meta                 JSONB        NOT NULL DEFAULT '{}'
);

-- Two partial unique indexes replace a single UNIQUE(workflow_id, actor_id):
-- Buyer/seller actors: unique per workflow + actor (property already encoded in actor_id)
CREATE UNIQUE INDEX idx_enroll_uq_no_prop
    ON workflow_enrollments(workflow_id, actor_id)
    WHERE actor_property_id IS NULL;

-- Customer (owner) actors: unique per workflow + actor + property
CREATE UNIQUE INDEX idx_enroll_uq_with_prop
    ON workflow_enrollments(workflow_id, actor_id, actor_property_id)
    WHERE actor_property_id IS NOT NULL;

CREATE INDEX idx_enroll_actor    ON workflow_enrollments(actor_id);
CREATE INDEX idx_enroll_prop     ON workflow_enrollments(actor_id, actor_property_id) WHERE actor_property_id IS NOT NULL;
CREATE INDEX idx_enroll_phone    ON workflow_enrollments(phone, status);
CREATE INDEX idx_enroll_waiting  ON workflow_enrollments(wait_until) WHERE status='waiting';
CREATE INDEX idx_enroll_active   ON workflow_enrollments(phone) WHERE status IN ('active','waiting');
```

| Column | Type | Req | Source | What it stores | Why it exists |
|--------|------|-----|--------|----------------|---------------|
| `id` | UUID | R | `gen_random_uuid()` on insert | Primary key. Also segment 2 of `callback_data`: `workflow_slug:step_id:enrollment_uuid` | The routing UUID. Button replies encode this and `reply-router` does a direct lookup — single row, no scan |
| `workflow_id` | UUID | R | Set by `workflow_engine` at enrollment from the event's target workflow | Which workflow this actor is enrolled in | FK to `workflows`. Enables "all enrollments for workflow X" queries |
| `actor_type` | TEXT | R | Set by `workflow_engine` from the Odoo event payload field `actor_type`. Default `'buyer_inquiry'` | `'buyer_inquiry'` = property buyer inquiry (`crm.lead`). `'seller_inquiry'` = seller/owner inquiry (future). `'customer'` = paid service customer receiving lead reports and visit coordination | Tells `workflow_engine` which Odoo REST endpoint to call for variable resolution: `/crm.lead` for buyer and seller inquiries, `/res.partner` or service customer endpoint for customers. Determines how `lead_id` will be sourced when the future CRM goes live |
| `actor_id` | INTEGER | R | From Odoo event payload: `event.actor_id`. For `buyer_inquiry`: Odoo `crm.lead.id`. For `customer`: Odoo `owner_id` (future) or current customer record ID. For `seller_inquiry`: seller inquiry record ID | The Odoo record ID for this specific actor instance | Join key back to Odoo for the dashboard. For `buyer_inquiry`/`seller_inquiry`: together with `workflow_id` this is unique (partial index `idx_enroll_uq_no_prop`). For `customer`: unique only in combination with `actor_property_id` (partial index `idx_enroll_uq_with_prop`) |
| `actor_property_id` | INTEGER | O | From Odoo event payload: `event.payload.property_id`. Set **only for `customer` actors**. NULL for `buyer_inquiry` and `seller_inquiry` | The Odoo property ID that scopes this enrollment to a specific property. Decision #8 | Enables an owner with 3 onboarded properties to have 3 independent enrollments in the same workflow — one per property. Per-property automation (expiry alerts, lead report nudges, visit coordination) runs independently. Timeline query: `SELECT * FROM actor_timeline WHERE actor_id=$owner_id AND actor_property_id=$property_id ORDER BY happened_at DESC` |
| `lead_id` | UUID | O | **Currently always NULL.** Future: from the new CRM event payload as `event.lead_id` = `leads.lead_id`. For `buyer_inquiry`: the person who created the inquiry. For `seller_inquiry`: the person listing the property (same `lead_id` may also be an owner). For `customer`: the property owner's person record. Decision #7 | The future-system person-level UUID. Shared across all roles a person plays: buyer inquiries, seller inquiries, owner/customer records | Forward-compatibility slot. Today: phone is the de-facto person grouping key. Future: `SELECT * FROM workflow_enrollments WHERE lead_id=$1` returns every enrollment for a person across all roles and properties |
| `phone` | TEXT | R | From Odoo event payload: `event.phone`. Normalised to E.164 without plus | The WhatsApp phone number for this actor | Stored for fast reply routing fallback. Denormalised from the event to avoid re-fetching Odoo on every inbound message |
| `status` | TEXT | R | Default `'active'`. State machine driven by `workflow_engine`, `reply-router`, and `reminder-scheduler` | `'active'`=processing. `'waiting'`=paused for reply or timer. `'paused'`=manager halted. `'completed'`=all steps done. `'failed'`=step failed with stop_workflow fallback. `'unenrolled'`=opted out or manual removal | Primary state flag. All services check this before acting on an enrollment. Decision #5: `'opted_out'` removed — now in `workflow_opt_outs` table |
| `current_step` | TEXT | O | Set by `workflow_engine` to the `step_id` from `config.yaml` on each step execution | The most recently executed step. E.g. `'first_touch'`, `'ringing_followup'` | Shown in WA-02 and WA-03 dashboards. Used in idempotency check: if `current_step` already matches the step about to execute, skip it |
| `waiting_for` | TEXT | O | Set by `workflow_engine` when a Wait step executes. E.g. `'any_reply'`, `'button:plan_site_visit'`, `'status:ringing'` | What condition will resume this enrollment from `'waiting'` status | `reply-router` checks this after routing an inbound. If the reply satisfies `waiting_for`, publishes `workflow.resume` event |
| `wait_until` | TIMESTAMPTZ | O | Set by `workflow_engine` for timed Wait steps. NULL for reply-triggered waits | Timeout timestamp after which `reminder-scheduler` fires the timeout action | Queried by `wait-step-timeouts` CronJob: `WHERE status='waiting' AND wait_until <= NOW() FOR UPDATE SKIP LOCKED` |
| `current_branch_path` | TEXT | O | Set by `workflow_engine` when a Branch step executes. `'A'` or `'B'` | Which branch path is currently active for this enrollment | Tells `workflow_engine` which downstream steps to execute after a branch |
| `branch_locked_at` | TIMESTAMPTZ | O | Set by `workflow_engine` when a Branch step fires. Cleared after lock window expires. Correction #3: replaces `enrollment_branch_decisions` table | The timestamp when the branch decision was made and locked | `reply-router` checks: if `branch_locked_at IS NOT NULL AND NOW() < branch_locked_at + INTERVAL '30 seconds'` → ignore this button tap. Simple column check, no JOIN needed |
| `branch_locked_path` | TEXT | O | Set by `workflow_engine` alongside `branch_locked_at`. E.g. `'A'` | Which path was chosen when the branch locked | Used by `reply-router` to report which path was already taken when blocking a second tap |
| `enrolled_at` | TIMESTAMPTZ | R | `NOW()` on insert | When this actor was first enrolled in this workflow | Analytics: time from enrollment to first message, time to completion |
| `last_activity_at` | TIMESTAMPTZ | R | Default `NOW()`. Updated on every send, reply, or step execution | Timestamp of any recent activity for this enrollment | Multi-enrollment fallback routing: when free-text reply is ambiguous, pick most recent `last_activity_at`. Also powers stale-conversation detection |
| `completed_at` | TIMESTAMPTZ | O | Set when `status` changes to `'completed'` | When this enrollment finished all steps | Completion rate and time-to-completion analytics |
| `disengagement_score` | NUMERIC(4,2) | R | Default 0.0. Updated nightly by disengagement-scorer CronJob from `actor_timeline` data | Score: `(reads with no reply within 48h × 0.3) + (not_interested taps × 1.0)`. At 2.0+ the actor is excluded from batch sends | Batch campaigns C3, C4, C6 check this before sending. `wa-sender` skips with `skip_reason='disengaged'` if score ≥ 2.0 |
| `meta` | JSONB | R | Default `{}`. Written by `workflow_engine` at enrollment from `meta_fields` declared in `config.yaml` | Workflow-specific context. For buyer_inquiry workflows: `{portal_source, property_id, assigned_rm_email}`. For customer workflows: `{service_plan_name, assignee_email}`. Decision #2: replaces explicit context columns | Config-driven flexibility. Adding a new workflow that needs different context fields does not require a schema migration — only a `config.yaml` change |

### Branch lock check in reply-router — Decision #3 implementation

```python
# reply-router/router.py — branch lock check
def is_branch_locked(enrollment_id: str) -> tuple[bool, str | None]:
    """
    Returns (is_locked, locked_path).
    locked_path is the path that was already chosen.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT branch_locked_path
                FROM workflow_enrollments
                WHERE id = %s
                  AND branch_locked_at IS NOT NULL
                  AND branch_locked_at > NOW() - INTERVAL '30 seconds'
            """, (enrollment_id,))
            row = cur.fetchone()
            if row:
                return True, row[0]
            return False, None

# In handle_inbound_message():
if inbound.message_content_type == 'Button':
    locked, path = is_branch_locked(enrollment_id)
    if locked:
        # Record but do not resume workflow
        write_timeline(actor_id, 'branch_second_tap_blocked',
            f'Second tap ignored — branch already locked on path {path}')
        return  # Do not publish workflow.resume

# If not locked: proceed with normal routing and workflow.resume
```

---

## 4. Table: `outbound_messages`

Every message sent via the Interakt Template Send API. Inserted by `wa-sender` before the API call. Updated by `event-archiver` as delivery/read/failed webhooks arrive. The source of all delivery tracking data.

```sql
CREATE TABLE outbound_messages (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    enrollment_id         UUID        NOT NULL REFERENCES workflow_enrollments(id),
    workflow_id           UUID        NOT NULL REFERENCES workflows(id),
    step_id               TEXT        NOT NULL,
    phone                 TEXT        NOT NULL,
    campaign_id           TEXT,
    actor_type            TEXT        NOT NULL DEFAULT 'buyer_inquiry',
    actor_id              INTEGER,
    template_name         TEXT        NOT NULL,
    template_language     TEXT        NOT NULL DEFAULT 'en',
    body_values           JSONB,
    header_values         JSONB,
    button_values         JSONB,
    callback_data         TEXT,
    interakt_msg_id       TEXT        UNIQUE,
    send_api_result       BOOLEAN,
    send_api_message      TEXT,
    status                TEXT        NOT NULL DEFAULT 'queued'
                          CHECK (status IN (
                            'queued','sent','delivered','read',
                            'failed','meta_blocked','invalid_number',
                            'opted_out','rate_limited','template_error',
                            'skipped','expired'
                          )),
    skip_reason           TEXT,
    failure_reason        TEXT,
    failure_code          TEXT,
    queued_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at               TIMESTAMPTZ,
    interakt_received_at  TIMESTAMPTZ,
    delivered_at          TIMESTAMPTZ,
    read_at               TIMESTAMPTZ,
    failed_at             TIMESTAMPTZ,
    cost_whatsapp_inr     NUMERIC(8,4),
    cost_interakt_markup  NUMERIC(8,4),
    cost_total_inr        NUMERIC(8,4),
    interakt_customer_id  TEXT,
    interakt_campaign_id  TEXT,
    chat_message_type     TEXT,
    retry_count           INTEGER     NOT NULL DEFAULT 0,
    -- Part B additional columns
    message_kind          TEXT        NOT NULL DEFAULT 'template'
                          CHECK (message_kind IN ('template','text','image','document','audio','video')),
    message_text          TEXT,
    sent_by_rm_id         INTEGER,
    sent_by_rm_name       TEXT,
    raw_interakt_payload  JSONB
);

CREATE INDEX idx_out_interakt_id ON outbound_messages(interakt_msg_id);
CREATE INDEX idx_out_enrollment  ON outbound_messages(enrollment_id);
CREATE INDEX idx_out_phone       ON outbound_messages(phone);
CREATE INDEX idx_out_status      ON outbound_messages(status) WHERE status IN ('queued','sent','failed');
CREATE INDEX idx_out_campaign    ON outbound_messages(campaign_id, queued_at DESC);
```

| Column | Type | Req | Source | What it stores | Why it exists |
|--------|------|-----|--------|----------------|---------------|
| `id` | UUID | R | `gen_random_uuid()` | Primary key | Referenced by `actor_timeline.outbound_msg_id` and `dead_letter_queue.outbound_msg_id` |
| `enrollment_id` | UUID | R | `wa-sender` from `WaSendPayload` | The enrollment this message belongs to | Join key for "all messages for this enrollment". Also used in idempotency check |
| `workflow_id` | UUID | R | `wa-sender`, denormalised from enrollment | The workflow that produced this message | Enables direct cost/volume `GROUP BY workflow_id` without joining through enrollments |
| `step_id` | TEXT | R | `wa-sender` from `WaSendPayload`. The `step_id` from `config.yaml` | Which config step produced this message. E.g. `'first_touch'` | Idempotency key: check `(enrollment_id, step_id)` before sending. Per-step delivery rate analytics |
| `phone` | TEXT | R | `wa-sender` from `WaSendPayload` | Destination phone number | Denormalised for phone-based history queries without joining through enrollments |
| `campaign_id` | TEXT | O | Copied from `workflow.campaign_id` by `wa-sender` | Campaign category C1–C7 | Per-campaign cost reports without joining through `workflows` |
| `actor_type` | TEXT | R | `wa-sender` from `enrollment.actor_type`. Default `'buyer_inquiry'` | `'buyer_inquiry'`, `'seller_inquiry'`, or `'customer'` | Enables actor-type segmented analytics |
| `actor_id` | INTEGER | O | `wa-sender` from `enrollment.actor_id` | The Odoo record ID for this actor | Links outbound message to the Odoo record for the timeline JOIN |
| `template_name` | TEXT | R | `wa-sender` from `WaSendPayload` | Exact Interakt/Meta template name used. E.g. `'welcome_message_v3'` | "What did we send?" question. Per-template delivery rate analysis |
| `template_language` | TEXT | R | `wa-sender`. Default `'en'` | Language code sent to Interakt API | Required by Interakt API. Stored for future multi-language support |
| `body_values` | JSONB | O | `wa-sender` from `WaSendPayload`. Array of resolved variable values | The exact strings substituted into `{{1}}`, `{{2}}` etc. E.g. `['Ankit Mehta','https://...']` | Allows WA-05 timeline to reconstruct the exact message without re-fetching Odoo |
| `header_values` | JSONB | O | `wa-sender` from `WaSendPayload`. Only for image/document header templates | Array of header variable values. Typically `['https://image-url']` for image templates | Needed for templates with a property photo header. Stored for timeline image display |
| `button_values` | JSONB | O | `wa-sender` from `WaSendPayload`. Only for Dynamic CTA templates | Button variable values for dynamic URL CTAs | Required for Dynamic CTA templates with variable URLs |
| `callback_data` | TEXT | O | `wa-sender`: `workflow_slug + ':' + step_id + ':' + enrollment_uuid` | The routing string sent to Interakt as `callbackData`. Echoed back on button replies | The cornerstone of deterministic reply routing. Without this, all replies require heuristic routing |
| `interakt_msg_id` | TEXT | O | Interakt send API `response[0].id` — set by `wa-sender` after successful call | Interakt's UUID for this message | UNIQUE FK for all delivery/read/failed webhook lookups. `event-archiver` does `UPDATE WHERE interakt_msg_id=$1` |
| `send_api_result` | BOOLEAN | O | Interakt send API `response[0].result` | Whether Interakt accepted the message at the API level | Distinguishes immediate API rejection from later delivery failure |
| `send_api_message` | TEXT | O | Interakt send API `response[0].message` | Text confirmation from Interakt. E.g. `'Message queued for sending via Interakt'` | Debugging for immediate API failures |
| `status` | TEXT | R | Default `'queued'`. Updated by `wa-sender` and `event-archiver` as webhooks arrive | Full lifecycle status. Mapped from Interakt error codes: `131026`→`meta_blocked`, `131047`→`opted_out`, `131052`→`invalid_number`, `130429`→`rate_limited`, `132000/132001`→`template_error` | Primary delivery tracking field. Powers the status indicators in WA-05 timeline |
| `skip_reason` | TEXT | O | Set by `wa-sender` when `status='skipped'`. Values: `'workflow_opted_out'`, `'meta_blocked'`, `'disengaged'`, `'already_sent'`, `'workflow_inactive'` | Why this send was skipped without calling Interakt | Actionable for managers: `'opted_out'` → use another channel. `'disengaged'` → suppression working |
| `failure_reason` | TEXT | O | Interakt webhook: `data.message.channel_failure_reason` | Human-readable failure description from Meta. E.g. `'Phone number not on WhatsApp'` | Shown in WA-01 recent failures table and WA-05 timeline without needing to decode error codes |
| `failure_code` | TEXT | O | Interakt webhook: `data.message.channel_error_code` | Meta numeric error code. E.g. `'131052'` | Drives status mapping in `event-archiver`. Per-failure-code aggregate reports |
| `queued_at` | TIMESTAMPTZ | R | `NOW()` on insert by `wa-sender` | When this message entered our pipeline | Baseline for latency calculations. Date range filter for message log |
| `sent_at` | TIMESTAMPTZ | O | Set by `wa-sender` after successful Interakt API response | When Interakt accepted the message | `sent_at - queued_at` = `wa-sender` processing latency |
| `interakt_received_at` | TIMESTAMPTZ | O | Interakt webhook: `data.message.received_at_utc` | When Interakt received our send request | Cross-reference with our `sent_at` for discrepancy debugging |
| `delivered_at` | TIMESTAMPTZ | O | Interakt webhook: `data.message.delivered_at_utc` from `message_api_delivered` | When WhatsApp confirmed delivery to the lead's device | Timeline display. Delivery rate analytics |
| `read_at` | TIMESTAMPTZ | O | Interakt webhook: `data.message.seen_at_utc` from `message_api_read` | When the lead opened the message | Read rate analytics. NULL for leads with read receipts disabled |
| `failed_at` | TIMESTAMPTZ | O | Set by `event-archiver` when `message_api_failed` webhook arrives | When the failure was confirmed | Failed message time-range filtering |
| `cost_whatsapp_inr` | NUMERIC(8,4) | O | Interakt webhook: `meta_data.message_cost.whatsapp_cost` | Base Meta WhatsApp charge for this message | Separates Meta costs from Interakt markup for cost negotiation |
| `cost_interakt_markup` | NUMERIC(8,4) | O | Interakt webhook: `meta_data.message_cost.interakt_markup` | Interakt's fee on top of the WhatsApp cost | Tracks Interakt-specific spend separately |
| `cost_total_inr` | NUMERIC(8,4) | O | Interakt webhook: `meta_data.message_cost.actual_message_cost` | Total cost of this message. 0 for failed | Primary column for all cost reporting: `SUM(cost_total_inr) GROUP BY campaign_id` |
| `interakt_customer_id` | TEXT | O | Interakt webhook: `data.customer.id` | Interakt's UUID for this actor | Stored for potential future Interakt customer API use |
| `interakt_campaign_id` | TEXT | O | Interakt webhook: `data.message.campaign_id`. NULL for API sends | Interakt campaign ID if message was sent via Interakt Campaigns rather than API | Distinguishes API sends from Campaigns sends for hybrid deployments |
| `chat_message_type` | TEXT | O | Interakt webhook: `data.message.chat_message_type` | Interakt classification. `'PublicApiMessage'` for all our API sends | Debugging. Unexpected values indicate Interakt webhook structure changes |
| `retry_count` | INTEGER | R | Default 0. Incremented by `error-handler` on each retry | Number of retry attempts for this message | `error-handler` enforces max 3 retries. Shown in DLQ panel |
| `message_kind` | TEXT | R | Default `'template'`. Set to `'text'`/`'image'` etc. for Part B RM-initiated sends | Type of message. `'template'` for all automated sends. Other values for Part B RM sends | Part B column. Determines timeline rendering: `template`=show `body_values`, `text`=show `message_text` |
| `message_text` | TEXT | O | Part B: the text the RM typed in Odoo WA-05. NULL for template sends | The actual text content for non-template RM-initiated messages | Part B column. Stored for timeline display of RM replies |
| `sent_by_rm_id` | INTEGER | O | Part B: Odoo user ID of the RM who sent this. NULL for automated sends | Which RM manually sent this message | Part B column. Per-RM reply volume analytics. Timeline label differentiation |
| `sent_by_rm_name` | TEXT | O | Part B: RM display name from Odoo session. NULL for automated sends | RM's display name | Part B column. Timeline bubble header: `'Priya Sharma sent: ...'` |
| `raw_interakt_payload` | JSONB | O | Full Interakt webhook body for the most recent webhook for this message | Complete verbatim webhook for debugging | Never used in application logic. Allows exact reconstruction of what Interakt sent |

---

## 5. Table: `inbound_messages`

Every message received from any actor. Populated exclusively from Interakt `message_received` webhooks. `reply-router` adds routing outcome columns after processing.

```sql
CREATE TABLE inbound_messages (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    phone                 TEXT        NOT NULL,
    actor_type            TEXT        NOT NULL DEFAULT 'buyer_inquiry',
    actor_id              INTEGER,
    enrollment_id         UUID        REFERENCES workflow_enrollments(id),
    workflow_id           UUID        REFERENCES workflows(id),
    interakt_msg_id       TEXT        UNIQUE NOT NULL,
    message_content_type  TEXT,
    message_text          TEXT,
    button_reply_id       TEXT,
    button_reply_title    TEXT,
    callback_data         TEXT,
    media_url             TEXT,
    is_stop_message       BOOLEAN     NOT NULL DEFAULT false,
    routing_method        TEXT
                          CHECK (routing_method IN (
                            'callback_data',
                            'conversation_context',
                            'enrollment_scan',
                            'ambiguous_multi_enrollment',
                            'unrouted'
                          )),
    branch_blocked        BOOLEAN     NOT NULL DEFAULT false,
    routed_at             TIMESTAMPTZ,
    interakt_customer_id  TEXT,
    customer_name         TEXT,
    chat_assignee_email   TEXT,
    contact_owner_email   TEXT,
    received_at           TIMESTAMPTZ NOT NULL,
    inserted_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_interakt_payload  JSONB       NOT NULL
);

CREATE INDEX idx_in_phone       ON inbound_messages(phone, received_at DESC);
CREATE INDEX idx_in_enrollment  ON inbound_messages(enrollment_id);
CREATE INDEX idx_in_callback    ON inbound_messages(callback_data) WHERE callback_data IS NOT NULL;
CREATE INDEX idx_in_stop        ON inbound_messages(phone) WHERE is_stop_message=true;
CREATE INDEX idx_in_unrouted    ON inbound_messages(received_at DESC)
    WHERE routing_method IN ('unrouted','ambiguous_multi_enrollment');
```

| Column | Type | Req | Source | What it stores | Why it exists |
|--------|------|-----|--------|----------------|---------------|
| `id` | UUID | R | `gen_random_uuid()` | Primary key | Referenced by `actor_timeline.inbound_msg_id` and `workflow_opt_outs.triggering_inbound` |
| `phone` | TEXT | R | Interakt webhook: `data.customer.channel_phone_number` normalised | Phone that sent this message | Primary lookup for reply routing. Index on `(phone, received_at DESC)` |
| `actor_type` | TEXT | R | Set by `reply-router` after routing. Default `'buyer_inquiry'`. Decision #6 | `'buyer_inquiry'`, `'seller_inquiry'`, or `'customer'` | Timeline display differentiation. Analytics split by actor type |
| `actor_id` | INTEGER | O | Set by `reply-router` after routing from `enrollment.actor_id`. NULL if unrouted | The Odoo record ID for this actor | FK to correct Odoo record for `odoo-bridge` activity creation |
| `enrollment_id` | UUID | O | Set by `reply-router` after routing. NULL if unrouted or ambiguous | The enrollment this reply was matched to | Used to resume Wait step enrollments and to write timeline entries for the correct enrollment |
| `workflow_id` | UUID | O | Set by `reply-router` after routing. Denormalised from enrollment | The workflow this reply was routed to | Reply rate reports grouped by workflow without joining enrollments |
| `interakt_msg_id` | TEXT | R | Interakt webhook: `data.message.id` | Interakt's UUID for this inbound message | UNIQUE guard: prevents inserting the same webhook twice if Interakt retries delivery |
| `message_content_type` | TEXT | O | Interakt webhook: `data.message.message_content_type` | Type of message: `Text`, `Button`, `Image`, `Document`, `Audio`, `Video`, `Sticker`, `Reaction` | Determines which columns are populated. `Button`→`button_reply_id`. `Text`→`message_text`. `Image`→`media_url` |
| `message_text` | TEXT | O | Interakt webhook: `data.message.message` for `Text` type only | The actual text the actor typed | Displayed as speech bubble in WA-05 timeline. Used for STOP detection |
| `button_reply_id` | TEXT | O | Parsed from Interakt webhook message JSON for `Button` type → `button_reply.id` | The button ID that was tapped. E.g. `'plan_site_visit'` | Intent signal for workflow branching. Stable even if button text changes — managers can rename buttons without breaking routing |
| `button_reply_title` | TEXT | O | Parsed from Interakt webhook message JSON for `Button` type → `button_reply.title` | The display text of the tapped button. E.g. `'Plan Site Visit'` | Displayed as a blue pill in the WA-05 timeline. Readable by managers |
| `callback_data` | TEXT | O | Interakt webhook: `data.message.meta_data.source_data.callback_data` — button replies only | The full `callback_data` string from our outbound message, echoed back. Format: `workflow_slug:step_id:enrollment_uuid` | Primary routing key for button replies. Split to extract `enrollment_uuid` for direct lookup |
| `media_url` | TEXT | O | Interakt webhook: `data.message.media_url` for Image/Document/Audio/Video types | URL of media file sent by the actor | Stored for completeness. Future: RM can view images from WA-05 timeline |
| `is_stop_message` | BOOLEAN | R | Set by `webhook-gateway` if `message_text.upper().strip()=='STOP'`. Default `false` | Whether this is a WhatsApp opt-out request | Triggers scoped opt-out processing in `reply-router`. Decision #5 |
| `routing_method` | TEXT | O | Set by `reply-router`. Decision #4 adds `'ambiguous_multi_enrollment'` | How this reply was routed. `'callback_data'`=deterministic. `'conversation_context'`=recency. `'enrollment_scan'`=scanned active. `'ambiguous_multi_enrollment'`=multiple active enrollments, not routed. `'unrouted'`=no active enrollment | Audit and alerting. The `INDEX WHERE routing_method IN ('unrouted','ambiguous_multi_enrollment')` enables fast count for the manager alert badge |
| `branch_blocked` | BOOLEAN | R | Set by `reply-router` if the branch lock check fired. Default `false`. Decision #3 | Whether this button tap was blocked by the branch lock on the enrollment | Records that a second tap occurred but was intentionally ignored. Displayed in timeline as "Second tap blocked — branch already decided" |
| `routed_at` | TIMESTAMPTZ | O | Set by `reply-router` when routing is complete | When routing finished | Processing latency monitoring: `received_at` to `routed_at` |
| `interakt_customer_id` | TEXT | O | Interakt webhook: `data.customer.id` | Interakt's UUID for this actor | Stored for cross-reference with `outbound_messages` |
| `customer_name` | TEXT | O | Interakt webhook: `data.customer.traits.name` | Actor's name as stored in Interakt | Displayed in WA-03 inbox and WA-05 timeline |
| `chat_assignee_email` | TEXT | O | Interakt webhook: `data.customer.traits.chat_assignee.email` | The Interakt chat assignee at message time | Cross-reference with `rm_assignments` to detect Interakt-side assignment drift |
| `contact_owner_email` | TEXT | O | Interakt webhook: `data.customer.traits.contact_owner.email` | Interakt contact owner email | Additional RM context. Audit column |
| `received_at` | TIMESTAMPTZ | R | Interakt webhook: `data.message.received_at_utc` | When Interakt received this message from the actor | Authoritative message timestamp. Used for `actor_timeline.happened_at` on reply events |
| `inserted_at` | TIMESTAMPTZ | R | `NOW()` on insert by `reply-router` | When our system stored this row | Latency: `received_at` to `inserted_at` = webhook processing delay |
| `raw_interakt_payload` | JSONB | R | Full `message_received` webhook body | Complete verbatim webhook | **Required** (not optional) for inbound — `Button` type has nested JSON that we partially parse. Full payload needed for future message types and debugging |

---

## 6. Table: `conversation_context`

One row per phone. Updated on every outbound send. First lookup for free-text reply routing. Contains `active_enrollment_count` for Decision #4 (multi-enrollment ambiguity detection). `opted_out` removed per Decision #5.

```sql
CREATE TABLE conversation_context (
    phone                      TEXT        PRIMARY KEY,
    actor_type                 TEXT        NOT NULL DEFAULT 'buyer_inquiry'
                               CHECK (actor_type IN ('buyer_inquiry','seller_inquiry','customer')),
    actor_id                   INTEGER     NOT NULL,
    active_enrollment_id       UUID        REFERENCES workflow_enrollments(id),
    active_enrollment_count    INTEGER     NOT NULL DEFAULT 0,
    last_outbound_step         TEXT,
    last_outbound_workflow_id  UUID        REFERENCES workflows(id),
    last_outbound_at           TIMESTAMPTZ,
    last_callback_data         TEXT,
    pending_button_reply       BOOLEAN     NOT NULL DEFAULT false,
    last_inbound_at            TIMESTAMPTZ,
    last_inbound_text          TEXT,
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

| Column | Type | Req | Source | What it stores | Why it exists |
|--------|------|-----|--------|----------------|---------------|
| `phone` | TEXT | R | E.164 without plus. PRIMARY KEY | The phone number. One row per unique phone across all campaigns and actor types | O(1) lookup by `reply-router`: `SELECT * FROM conversation_context WHERE phone=$1` |
| `actor_type` | TEXT | R | Set at first UPSERT from `enrollment.actor_type` | `'buyer_inquiry'`, `'seller_inquiry'`, or `'customer'`. Decision #6 | `reply-router` uses this to fetch actor data after routing |
| `actor_id` | INTEGER | R | From `enrollment.actor_id` at first UPSERT | The Odoo record ID for the actor associated with this phone. For `buyer_inquiry`: `crm.lead.id`. For `customer`/`seller_inquiry`: the respective Odoo record ID | One phone maps to one primary actor record per active enrollment context. Used for `actor_timeline` writes without a second lookup into `workflow_enrollments`. Stable for routing as long as the enrollment is active |
| `active_enrollment_id` | UUID | O | Updated by `wa-sender` to the most recently active enrollment | The enrollment that sent the most recent outbound message. Decision #4: used when `active_enrollment_count=1` | Routing answer when count=1. Not used when count>1 (ambiguous case) |
| `active_enrollment_count` | INTEGER | R | Default 0. Incremented by `wa-sender` on new enrollment, decremented on completion/unenrollment. Decision #4 | How many active enrollments currently exist for this phone across all workflows | The multi-enrollment routing gate. For `buyer_inquiry` actors: count > 1 is **expected** (one per property inquiry) — `reply-router` routes to the enrollment with the most recent `last_activity_at`, not to `ambiguous_multi_enrollment`. `ambiguous_multi_enrollment` is reserved for cases where two enrollments have identical `last_activity_at` or conflicting `waiting_for` states |
| `last_outbound_step` | TEXT | O | Updated by `wa-sender` to the `step_id` of the most recent send | The `step_id` of the last message sent to this phone | Context for "Needs Reply" detection and fallback routing |
| `last_outbound_workflow_id` | UUID | O | Updated by `wa-sender` to the `workflow_id` of the most recent send | Which workflow sent the most recent message | When count=1, unambiguous. When count>1, shows most recently active workflow |
| `last_outbound_at` | TIMESTAMPTZ | O | Updated by `wa-sender` on every outbound send | When the most recent outbound message was sent | Context freshness: if > 48h, treat as stale for free-text routing |
| `last_callback_data` | TEXT | O | Updated by `wa-sender` to the `callback_data` of the most recent send | Full `callback_data` from last sent message | Fallback routing for free-text: carries enrollment context even when no button was tapped |
| `pending_button_reply` | BOOLEAN | R | Set `true` by `wa-sender` when outbound contained buttons. Set `false` by `reply-router` on any reply | Whether the last message had quick-reply buttons | Contextual signal: free text while `pending_button_reply=true` may mean actor is confused |
| `last_inbound_at` | TIMESTAMPTZ | O | Updated by `reply-router` on every inbound | When this phone last sent any message | "Needs Reply" detection: `last_inbound_at > last_outbound_at` means actor replied |
| `last_inbound_text` | TEXT | O | Updated by `reply-router` to a snippet of the most recent reply | Short snippet of most recent inbound text or button title | WA-03 inbox "Last message" column rendered without JOIN to `inbound_messages` |
| `updated_at` | TIMESTAMPTZ | R | `NOW()` on every UPSERT | When this context row was last modified | Cache freshness indicator |

---

## 7. Table: `workflow_opt_outs`

Workflow-scoped opt-outs. Decision #5. One row per `(phone, workflow_id)`. NULL `workflow_id` = global opt-out. Replaces the single `opted_out BOOLEAN` on `conversation_context`.

```sql
CREATE TABLE workflow_opt_outs (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    phone               TEXT        NOT NULL,
    workflow_id         UUID        REFERENCES workflows(id),
    opted_out_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    triggering_inbound  UUID        REFERENCES inbound_messages(id),
    confirmation_sent   BOOLEAN     NOT NULL DEFAULT false,
    confirmation_text   TEXT,
    UNIQUE (phone, workflow_id)
);

CREATE INDEX idx_optout_phone  ON workflow_opt_outs(phone);
CREATE INDEX idx_optout_global ON workflow_opt_outs(phone) WHERE workflow_id IS NULL;
```

| Column | Type | Req | Source | What it stores | Why it exists |
|--------|------|-----|--------|----------------|---------------|
| `id` | UUID | R | `gen_random_uuid()` | Primary key | Standard PK |
| `phone` | TEXT | R | From `inbound_messages.phone` where STOP was detected | The phone that opted out | Lookup key: `wa-sender` checks `WHERE phone=$1 AND (workflow_id=$2 OR workflow_id IS NULL)` |
| `workflow_id` | UUID | O | Set by `reply-router` to the `workflow_id` the STOP message was routed to. NULL = global opt-out | Which workflow this opt-out applies to. NULL means opt-out from all WhatsApp communication | `UNIQUE(phone, workflow_id)` = one opt-out record per workflow per phone. Scoped opt-out preserves other workflows |
| `opted_out_at` | TIMESTAMPTZ | R | `NOW()` on insert | When this opt-out was recorded | Compliance audit trail. WhatsApp Business policy requires opt-out records |
| `triggering_inbound` | UUID | O | Set to `inbound_messages.id` of the STOP message | FK to the inbound message that triggered the opt-out | Evidence record. Links to `raw_interakt_payload` in `inbound_messages` for compliance verification |
| `confirmation_sent` | BOOLEAN | R | Default `false`. Set `true` by `wa-sender` after confirmation message is sent | Whether the scoped opt-out confirmation was sent | Tracks compliance requirement. `wa-sender` sends the confirmation as a bypass — it sends even though the phone just opted out, because the confirmation IS the opt-out response |
| `confirmation_text` | TEXT | O | Set to the confirmation message text by `wa-sender` | Exact text of the opt-out confirmation sent | Records what we told the actor. Useful if they later dispute the scope of their opt-out |

---

## 8. Table: `actor_timeline`

Append-only chronological event log for every actor across all campaigns. The single source of truth for the Odoo WA-05 Lead WhatsApp Tab. Never updated — only inserted.

```sql
CREATE TABLE actor_timeline (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id        INTEGER     NOT NULL,
    actor_property_id INTEGER,
    lead_id         UUID,
    phone           TEXT        NOT NULL,
    actor_type      TEXT        NOT NULL DEFAULT 'buyer_inquiry'
                    CHECK (actor_type IN ('buyer_inquiry','seller_inquiry','customer')),
    campaign_id     TEXT,
    event_type      TEXT        NOT NULL,
    workflow_id     UUID        REFERENCES workflows(id),
    enrollment_id   UUID        REFERENCES workflow_enrollments(id),
    outbound_msg_id UUID        REFERENCES outbound_messages(id),
    inbound_msg_id  UUID        REFERENCES inbound_messages(id),
    actor_type_who  TEXT        NOT NULL DEFAULT 'system'
                    CHECK (actor_type_who IN ('system','rm','actor','scheduler','manager')),
    actor_name      TEXT,
    title           TEXT        NOT NULL,
    detail          TEXT,
    meta            JSONB       NOT NULL DEFAULT '{}',
    happened_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tl_actor     ON actor_timeline(actor_id, happened_at DESC);
CREATE INDEX idx_tl_actor_prop ON actor_timeline(actor_id, actor_property_id, happened_at DESC) WHERE actor_property_id IS NOT NULL;
CREATE INDEX idx_tl_lead      ON actor_timeline(lead_id, happened_at DESC) WHERE lead_id IS NOT NULL;
CREATE INDEX idx_tl_phone     ON actor_timeline(phone, happened_at DESC);
CREATE INDEX idx_tl_event     ON actor_timeline(event_type);
CREATE INDEX idx_tl_campaign  ON actor_timeline(campaign_id, happened_at DESC);
CREATE INDEX idx_tl_enroll    ON actor_timeline(enrollment_id, happened_at DESC);
```

| Column | Type | Req | Source | What it stores | Why it exists |
|--------|------|-----|--------|----------------|---------------|
| `id` | UUID | R | `gen_random_uuid()` | Primary key | Standard append-only PK. Grows indefinitely |
| `actor_type` | TEXT | R | Set by the writing service from `enrollment.actor_type`. Default `'buyer_inquiry'` | `'buyer_inquiry'`, `'seller_inquiry'`, or `'customer'`. Decision #6 | Timeline display differentiation. Analytics split by actor type |
| `actor_id` | INTEGER | R | Set by the writing service. The Odoo record ID for this actor instance. Decision #1 | The actor's Odoo ID. Primary read key for WA-05 | INDEX on `(actor_id, happened_at DESC)` is the primary WA-05 read path |
| `actor_property_id` | INTEGER | O | From `enrollment.actor_property_id`. Set only for `customer` actors. Decision #8 | The Odoo property ID for this event. NULL for buyer and seller actors | Enables property-scoped owner timeline: `SELECT * FROM actor_timeline WHERE actor_id=$owner_id AND actor_property_id=$prop_id ORDER BY happened_at DESC`. INDEX `idx_tl_actor_prop` covers this query efficiently |
| `lead_id` | UUID | O | **Currently always NULL.** Future: from `enrollment.lead_id` (= `leads.lead_id` in the new CRM). Decision #7 | The future-system person-level UUID, shared across all roles (buyer inquiries, seller inquiries, owner/customer) | Enables the unified person-level timeline: `SELECT * FROM actor_timeline WHERE lead_id=$1 ORDER BY happened_at DESC` — one query returns all WhatsApp events for a person across every role they have ever played. INDEX with `WHERE lead_id IS NOT NULL` keeps it efficient once populated |
| `phone` | TEXT | R | Set by the writing service from the enrollment or inbound message | The actor's phone number | Phone-based history query without knowing `actor_id` |
| `campaign_id` | TEXT | O | Set from `enrollment.campaign_id` | Campaign grouping C1–C7 | Campaign-level engagement reports |
| `event_type` | TEXT | R | Set by the writing service from the event_type registry | The event category. E.g. `'message_delivered'`, `'lead_replied_button'`, `'branch_second_tap_blocked'` | Primary filter key. WA-05 tab filters `event_type` for display |
| `workflow_id` | UUID | O | Set by the writing service from the enrollment | Which workflow produced this event | Workflow-specific timeline filter |
| `enrollment_id` | UUID | O | Set by the writing service from the active enrollment | Which enrollment instance this event belongs to | Drill-down to enrollment's full step log |
| `outbound_msg_id` | UUID | O | Set by `wa-sender` for message events | FK to `outbound_messages` for message detail | WA-05 JOINs here for template name, body values, cost, and delivery status |
| `inbound_msg_id` | UUID | O | Set by `reply-router` for reply events | FK to `inbound_messages` for reply content | WA-05 JOINs here for `button_reply_title` or `message_text` |
| `actor_type_who` | TEXT | R | Set by the writing service. `'system'`=automated. `'rm'`=RM action. `'actor'`=the lead/customer replied. `'scheduler'`=CronJob. `'manager'`=config change | Who caused this event | Timeline bubble rendering: `'system'` pill vs `'actor'` left-aligned bubble vs `'rm'` right-aligned bubble. "Needs Reply" query: last event has `actor_type_who='actor'` |
| `actor_name` | TEXT | O | For `'rm'` events: RM display name. For `'system'`: service name. For `'actor'`: phone. For `'manager'`: Odoo username | Specific name of who caused this event | Shown in timeline: `'Priya Sharma sent:'` or `'System: welcome message sent'` |
| `title` | TEXT | R | Constructed by writing service as a plain-English one-liner | The display string in WA-05 timeline. E.g. `'Welcome message delivered'`, `'Lead tapped: Plan Site Visit'` | Primary display field. Always set. Must be meaningful to a non-technical manager |
| `detail` | TEXT | O | Set by writing service for events that need extra context | Extended description. E.g. full failure reason, which branch path was taken | Shown on expand in WA-05. Not all events need this |
| `meta` | JSONB | R | Default `{}`. Event-specific structured data from the writing service | Key-value store for event-specific data. E.g. `{"delivery_time_ms":1800}` or `{"button_id":"plan_site_visit","routing":"callback_data"}` | Queryable with JSONB operators. Future-proof for new event types |
| `happened_at` | TIMESTAMPTZ | R | For message events: Interakt webhook timestamp (not `NOW()`). For other events: `NOW()` | When this event actually occurred. Critical: uses Interakt timestamps for delivery/read events | Preserves real delivery times. If webhook processing is delayed, the timeline still shows when Interakt actually delivered the message |

---

## 9. Table: `rm_assignments`

History of all RM assignments per actor. Partial UNIQUE index ensures one current assignment per actor. Used by `odoo-bridge` to call the Interakt Chat Assignment API.

```sql
CREATE TABLE rm_assignments (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id          INTEGER     NOT NULL,
    phone             TEXT        NOT NULL,
    actor_type        TEXT        NOT NULL DEFAULT 'buyer_inquiry'
                      CHECK (actor_type IN ('buyer_inquiry','seller_inquiry','customer')),
    rm_odoo_id        INTEGER,
    rm_name           TEXT        NOT NULL,
    rm_email          TEXT,
    rm_phone          TEXT,
    assigned_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    assigned_by       TEXT,
    assigned_by_type  TEXT        CHECK (assigned_by_type IN ('system','manager','odoo_trigger')),
    unassigned_at     TIMESTAMPTZ,
    is_current        BOOLEAN     NOT NULL DEFAULT true,
    reason            TEXT
);

CREATE UNIQUE INDEX idx_rm_current    ON rm_assignments(actor_id) WHERE is_current=true;
CREATE INDEX idx_rm_email             ON rm_assignments(rm_email) WHERE is_current=true;
CREATE INDEX idx_rm_phone_curr        ON rm_assignments(phone) WHERE is_current=true;
```

| Column | Type | Req | Source | What it stores | Why it exists |
|--------|------|-----|--------|----------------|---------------|
| `id` | UUID | R | `gen_random_uuid()` | Primary key. Assignment history = multiple rows, `is_current=false` for old, `true` for current | Standard PK |
| `actor_id` | INTEGER | R | From `enrollment.actor_id` at assignment time | The Odoo record ID of the actor being assigned | Primary lookup: `SELECT rm_email FROM rm_assignments WHERE actor_id=$1 AND is_current=true` |
| `phone` | TEXT | R | From `enrollment.phone` | Actor's phone number | Phone-based RM lookup when `actor_id` is not known, e.g. from an inbound message context |
| `actor_type` | TEXT | R | From `enrollment.actor_type`. Decision #6 | `'buyer_inquiry'`, `'seller_inquiry'`, or `'customer'` | Different actor types may use different assignment flows. Informational for audit |
| `rm_odoo_id` | INTEGER | O | From Odoo event payload: `event.payload.assigned_rm_id`. NULL for customers if RM is email-only | The Odoo user ID of the assigned RM | Used by `odoo-bridge` to create Odoo activities: `mail.activity.create(user_id=rm_odoo_id)` |
| `rm_name` | TEXT | R | From Odoo event payload or Odoo REST API fetch | Display name of the assigned RM | Shown in timeline: "Assigned to Priya Sharma". Used in template variables for visit confirmations |
| `rm_email` | TEXT | O | From Odoo event payload: `event.payload.assigned_rm_email`. Must match Interakt agent email exactly (case-sensitive) | The RM's email in both Odoo and Interakt | Used by `odoo-bridge` to call `POST /v1/public/assignment/` with `agent_email=rm_email`. If NULL, assignment step is skipped but confirmation message still sends |
| `rm_phone` | TEXT | O | From Odoo REST API fetch of the RM's user record | The RM's phone number | Used in visit notification templates: "RM Priya will contact you at +91 98765 XXXXX" |
| `assigned_at` | TIMESTAMPTZ | R | `NOW()` on insert | When this assignment was created | Assignment duration analytics. Timeline display |
| `assigned_by` | TEXT | O | Odoo username for manager assignments. Service name for automatic assignments | Who created this assignment | Audit: if an assignment is wrong, shows who made it |
| `assigned_by_type` | TEXT | O | `'system'`=automatic workflow. `'manager'`=manual in Odoo. `'odoo_trigger'`=Odoo CRM assignment event | How this assignment was created | Analytics: what % of assignments are automatic vs manual |
| `unassigned_at` | TIMESTAMPTZ | O | Set when a new assignment is created for the same `actor_id` — old row gets `unassigned_at=NOW()` | When this assignment ended | Assignment duration analytics |
| `is_current` | BOOLEAN | R | Default `true`. Set to `false` when superseded by a new assignment | Whether this is the currently active assignment | Partial UNIQUE INDEX on `(actor_id) WHERE is_current=true` enforces exactly one active assignment per actor |
| `reason` | TEXT | O | Entered by manager in Odoo WA-03 when reassigning | Free-text reason for this assignment. E.g. `'RM on leave'` | Shown in timeline when assignment change is recorded |

---

## 10. Table: `scheduled_reminders`

Future-dated events processed by the `reminder-scheduler` CronJob every 5 minutes. Covers site visit reminders (T-24h, T-1h), expiry goodwill nudges, and Wait-step timeouts.

```sql
CREATE TABLE scheduled_reminders (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    reminder_type   TEXT        NOT NULL,
    actor_id        INTEGER     NOT NULL,
    phone_primary   TEXT        NOT NULL,
    phone_secondary TEXT,
    enrollment_id   UUID        REFERENCES workflow_enrollments(id),
    campaign_id     TEXT,
    actor_type      TEXT        NOT NULL DEFAULT 'buyer_inquiry'
                    CHECK (actor_type IN ('buyer_inquiry','seller_inquiry','customer')),
    meta            JSONB       NOT NULL DEFAULT '{}',
    remind_at       TIMESTAMPTZ NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','processing','sent','cancelled','failed')),
    sent_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_remind_pending ON scheduled_reminders(remind_at) WHERE status='pending';
```

| Column | Type | Req | Source | What it stores | Why it exists |
|--------|------|-----|--------|----------------|---------------|
| `id` | UUID | R | `gen_random_uuid()` | Primary key | Standard PK |
| `reminder_type` | TEXT | R | Set at insert time by the `schedule_reminder` workflow step or by `visit-orchestration` service | The dispatch key. Tells the CronJob which Pub/Sub topic to publish to and how to build the payload. See reference below | Each `reminder_type` maps to exactly one downstream handler (workflow engine step, or dedicated service) |
| `actor_id` | INTEGER | R | From `enrollment.actor_id` | The Odoo record ID for this actor | Included in the published event payload so the downstream workflow knows which Odoo record to act on |
| `phone_primary` | TEXT | R | From `enrollment.phone` | The primary phone to notify. For inquiry actors: the buyer. For customer actors: the property owner | The send target for the reminder message |
| `phone_secondary` | TEXT | O | Set for site visit reminders: the property owner's phone. NULL for non-visit reminders | Secondary phone for the property owner (paid customer) notifications. Visit-related reminders: the owner receives a WhatsApp update that a visit has been scheduled. The RM coordinates the visit by phone call — no physical accompaniment. | Site visit reminders notify both the buyer (primary) and the owner (secondary). A single reminder row triggers two sends |
| `enrollment_id` | UUID | O | From the triggering enrollment | The enrollment that created this reminder | Published in the event payload so `workflow_engine` can resume the correct enrollment |
| `campaign_id` | TEXT | O | Copied from `enrollment.campaign_id` | Campaign grouping | Analytics: reminders sent per campaign per month |
| `actor_type` | TEXT | R | From `enrollment.actor_type`. Decision #6 | `'buyer_inquiry'`, `'seller_inquiry'`, or `'customer'` | Informs the CronJob and downstream workflow how to fetch actor details |
| `meta` | JSONB | R | Default `{}`. Set at insert with reminder-specific data | Context needed when the reminder fires. E.g. `{"visit_id":88,"property_name":"Vedant Kingstone"}` for visit reminders. `{"step_id":"wait_for_reply","timeout_action":"send_nudge"}` for wait timeouts | The CronJob builds the Pub/Sub event payload from this. Without `meta`, it cannot construct the correct event for the downstream workflow |

**`reminder_type` dispatch reference:**

| `reminder_type` | Actor type | Pub/Sub topic published | Handled by | Message sent to |
|---|---|---|---|---|
| `visit_reminder_24h` | `buyer_inquiry` | `workflow.reminder.fire` | `workflow-engine-visit` — resumes the visit step at the T−24h node | Buyer (`phone_primary`) + owner (`phone_secondary`) |
| `visit_reminder_1h` | `buyer_inquiry` | `workflow.reminder.fire` | `workflow-engine-visit` — resumes at the T−1h node | Buyer (`phone_primary`) + owner (`phone_secondary`) |
| `expiry_goodwill_nudge` | `customer` | `workflow.reminder.fire` | `workflow-engine-customer` — resumes the expiry-nudge step | Owner / customer (`phone_primary`) |
| `service_renewal_reminder` | `customer` | `workflow.reminder.fire` | `workflow-engine-customer` — resumes the renewal-reminder step | Owner / customer (`phone_primary`) |
| `wait_step_timeout` | any | `workflow.resume` | `workflow-engine` (any instance matching the `workflow_id`) — forces the wait step to resolve via `wait_resolved_by='timeout'` | No direct message — engine decides what to send based on `timeout_action` in `meta` |
| `followup_poll` | `buyer_inquiry` | `workflow.reminder.fire` | `workflow-engine-nurturing` — resumes at the post-visit feedback step | Buyer (`phone_primary`) |

> The CronJob does **not** send messages directly. It only publishes a Pub/Sub event. The downstream workflow engine or service receives that event, resolves the correct template and variables from Odoo, and calls `wa-sender`. This means adding a new reminder type never requires changes to the CronJob — only a new `schedule_reminder` step in the workflow config and a handler in the appropriate workflow engine.
| `remind_at` | TIMESTAMPTZ | R | Set at insert to the future fire time | UTC timestamp when this reminder should be processed | CronJob query: `WHERE status='pending' AND remind_at <= NOW()`. INDEX on this column with `WHERE status='pending'` makes the query efficient |
| `status` | TEXT | R | Default `'pending'`. CronJob claims rows by setting `'processing'` (FOR UPDATE SKIP LOCKED), then `'sent'` on success, `'failed'` on error, `'cancelled'` if visit is cancelled before firing | State machine preventing duplicate sends | `'processing'` status + `SKIP LOCKED` prevents two CronJob instances processing the same reminder simultaneously |
| `sent_at` | TIMESTAMPTZ | O | Set to `NOW()` when `status`→`'sent'` | When the CronJob successfully published the event | Reminder punctuality monitoring: `sent_at - remind_at` should be < 5 minutes |
| `created_at` | TIMESTAMPTZ | R | `NOW()` on insert | When this reminder was scheduled | Audit. If a reminder never fires, `created_at` and `remind_at` show how long it has been pending |

---

## 11. Table: `dead_letter_queue`

Messages that exhausted all retry attempts. Requires manual admin action via Odoo WA-06. Count of unresolved rows shows as badge on WA-01 dashboard.

```sql
CREATE TABLE dead_letter_queue (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    outbound_msg_id   UUID        REFERENCES outbound_messages(id),
    enrollment_id     UUID        REFERENCES workflow_enrollments(id),
    original_payload  JSONB       NOT NULL,
    failure_reason    TEXT        NOT NULL,
    failure_code      TEXT,
    retry_count       INTEGER     NOT NULL DEFAULT 0,
    last_error        TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at       TIMESTAMPTZ,
    resolved_by       TEXT,
    resolution_note   TEXT
);

CREATE INDEX idx_dlq_unresolved ON dead_letter_queue(created_at DESC) WHERE resolved_at IS NULL;
```

| Column | Type | Req | Source | What it stores | Why it exists |
|--------|------|-----|--------|----------------|---------------|
| `id` | UUID | R | `gen_random_uuid()` | Primary key | Standard PK |
| `outbound_msg_id` | UUID | O | Set by `error-handler` to `outbound_messages.id` of the failed message | The failed outbound message | WA-06 JOINs here for the full message payload without re-storing it |
| `enrollment_id` | UUID | O | From the failed message's enrollment | The enrollment this failure belongs to | Used by admin Force Retry action: re-publish `original_payload` to `wa-send` with this enrollment context |
| `original_payload` | JSONB | R | The full `WaSendPayload` at the time of final failure | Complete send payload: template, `body_values`, phone, `callback_data`, `retry_count` | Needed for Force Retry: re-publish exactly this payload to `wa-send`. Without storing it here, retry would require reconstructing from multiple table joins |
| `failure_reason` | TEXT | R | From `outbound_messages.failure_reason` at final failure | Human-readable failure explanation | Shown in WA-06 list view so admin immediately understands why without opening the detail panel |
| `failure_code` | TEXT | O | From `outbound_messages.failure_code` | Meta/Interakt error code | DLQ failure type grouping: how many are invalid numbers vs template errors? |
| `retry_count` | INTEGER | R | Set to the number of retries attempted before DLQ | How many send attempts were made | Confirms retry policy was applied correctly. Should be 3 for retryable, 0 for permanent |
| `last_error` | TEXT | O | The error text from the final retry attempt | Specific error from the last attempt | Additional debugging context beyond `failure_reason` |
| `created_at` | TIMESTAMPTZ | R | `NOW()` when `error-handler` inserts this row | When this message entered the DLQ | The DLQ badge count query: `SELECT COUNT(*) WHERE resolved_at IS NULL`. The INDEX `WHERE resolved_at IS NULL` makes this fast |
| `resolved_at` | TIMESTAMPTZ | O | Set by Odoo WA-06 "Mark Resolved" action. NULL until resolved | When an admin resolved this DLQ item | Separates pending from resolved. The partial INDEX makes pending-count queries efficient |
| `resolved_by` | TEXT | O | Set to logged-in admin's Odoo username | Which admin resolved this | Audit trail for DLQ resolution |
| `resolution_note` | TEXT | O | Free-text entered by admin in WA-06 | What action was taken | Context for future reference. E.g. `'Lead confirmed new number — updated in Odoo'` |

---

## 12. Table: `workflow_step_log`

Step-level execution audit trail. One row per step execution per enrollment. The Odoo WA-02 execution history view reads this. Enables per-step debugging and performance analysis.

```sql
CREATE TABLE workflow_step_log (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    enrollment_id     UUID        NOT NULL REFERENCES workflow_enrollments(id),
    workflow_id       UUID        NOT NULL REFERENCES workflows(id),
    step_id           TEXT        NOT NULL,
    step_type         TEXT        NOT NULL
                      CHECK (step_type IN (
                        'trigger','send_message','wait_for_reply',
                        'wait_and_send','branch','assign_rm',
                        'schedule_reminder','update_odoo_status',
                        'notify_rm','end'
                      )),
    status            TEXT        NOT NULL
                      CHECK (status IN (
                        'success','failed','skipped','waiting','timeout','retrying'
                      )),
    input_event       JSONB,
    resolved_vars     JSONB,
    output_payload    JSONB,
    branch_path_taken TEXT        CHECK (branch_path_taken IN ('A','B',NULL)),
    wait_resolved_by  TEXT        CHECK (wait_resolved_by IN (
                        'actor_reply','timeout','manual_resume',NULL
                      )),
    error_message     TEXT,
    duration_ms       INTEGER,
    workflow_version  INTEGER,
    executed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sl_enrollment ON workflow_step_log(enrollment_id, executed_at DESC);
CREATE INDEX idx_sl_workflow   ON workflow_step_log(workflow_id, executed_at DESC);
CREATE INDEX idx_sl_failed     ON workflow_step_log(status, executed_at DESC) WHERE status='failed';
```

| Column | Type | Req | Source | What it stores | Why it exists |
|--------|------|-----|--------|----------------|---------------|
| `id` | UUID | R | `gen_random_uuid()` | Primary key | Standard PK |
| `enrollment_id` | UUID | R | Set by `workflow_engine` when writing the log row | The enrollment this step execution belongs to | Primary read key: `SELECT * FROM workflow_step_log WHERE enrollment_id=$1 ORDER BY executed_at ASC` |
| `workflow_id` | UUID | R | From `enrollment.workflow_id`. Denormalised for query convenience | The workflow that was executing | Direct `GROUP BY workflow_id` for per-workflow failure rate analytics without joining through enrollments |
| `step_id` | TEXT | R | The `step_id` from `config.yaml` | Which step executed. E.g. `'first_touch'`, `'branch_after_details'` | Per-step failure rate analysis: if `ringing_followup` step fails more than `first_touch`, may indicate data quality issues |
| `step_type` | TEXT | R | From `config.yaml` `step_type` field | The type of step. See reference below | Shown in WA-02 execution history for non-technical managers to understand what type of action occurred |

**Step type reference:**

| `step_type` | What it does | Produces |
|---|---|---|
| `trigger` | Entry point. Validates the Odoo event and starts the enrollment | Enrollment row created |
| `send_message` | Sends a WhatsApp template via Interakt API | `outbound_messages` row, `actor_timeline` event |
| `wait_for_reply` | Pauses enrollment until actor replies or timeout fires | Sets `enrollment.status='waiting'`, `waiting_for`, `wait_until` |
| `wait_and_send` | Timer-based send. Waits N hours/days then sends without requiring a reply | `scheduled_reminders` row with `reminder_type='wait_step_timeout'` |
| `branch` | Conditional fork based on button reply or actor status. Chooses path A or B | Sets `branch_locked_at`, `branch_locked_path` |
| `assign_rm` | Assigns or reassigns an RM for this actor via `odoo-bridge` | `rm_assignments` row, Interakt chat assignment API call |
| `schedule_reminder` | Creates a future-dated row in `scheduled_reminders` for the CronJob to fire | `scheduled_reminders` row with the specified `reminder_type` and `remind_at` |
| `update_odoo_status` | Pushes a status update back to Odoo via `odoo-bridge` (e.g. mark lead as `Ringing`, update service record) | Odoo REST PATCH call; `actor_timeline` event |
| `notify_rm` | Sends a WhatsApp or email notification to the assigned RM (not the actor) | `outbound_messages` row with `phone=rm_phone`; `actor_timeline` event with `actor_type_who='system'` |
| `end` | Marks the enrollment complete | Sets `enrollment.status='completed'`, `completed_at` |

| Column | Type | Req | Source | What it stores | Why it exists |
|--------|------|-----|--------|----------------|---------------|
| `status` | TEXT | R | Set by `workflow_engine` on step completion | Outcome: `success`, `failed`, `skipped`, `waiting`, `timeout`, `retrying` | Primary outcome indicator. `'failed'` entries are indexed for fast failure rate queries |
| `input_event` | JSONB | O | Set to the Pub/Sub event that triggered this step | The complete event payload the engine received | Debugging: if a step behaved unexpectedly, shows exactly what data it received. Enables reproduction by re-publishing the same event |
| `resolved_vars` | JSONB | O | Set to the variable values resolved for this step | Actual substituted values. E.g. `{"1":"99acres","2":"Sola","3":"3 BHK","4":"https://..."}` | Debugging: if wrong values were sent, shows what the engine resolved without needing to re-run the Odoo fetch |
| `output_payload` | JSONB | O | Set to the `WaSendPayload` or `assign_rm` result published by this step | What this step produced and passed on | Debugging: reconstruct what was sent to `wa-sender` or `odoo-bridge` |
| `branch_path_taken` | TEXT | O | Set for branch step executions. `'A'` or `'B'` | Which path was chosen | Path A vs path B split rate analytics. Shown in WA-02 as "Branch: path A taken" |
| `wait_resolved_by` | TEXT | O | Set when a wait step resolves. `'actor_reply'`, `'timeout'`, or `'manual_resume'` | How the wait was resolved | Metrics: what % of waits resolve via actor reply vs timeout? High timeout rate may indicate template ineffectiveness |
| `error_message` | TEXT | O | Set by `workflow_engine` when `status='failed'` | The exception message or error description | First thing a developer reads when debugging a failed step. Shown in WA-02 execution detail |
| `duration_ms` | INTEGER | O | Set by `workflow_engine`: `end_time - start_time` in milliseconds | How long this step took to execute | Performance monitoring. Slow steps may indicate Odoo REST API latency |
| `workflow_version` | INTEGER | O | Copied from `workflows.version` at execution time | Which version of the workflow config was running when this step executed | Enables comparison across config versions: did the new button text improve the path A rate? |
| `executed_at` | TIMESTAMPTZ | R | `NOW()` at writing time | When this step executed | Primary sort key for execution history. Time-series execution volume analysis |

---

## 13. Part B Tables

### 13.1 Table: `odoo_send_requests`

Part B only. Queue of messages initiated from Odoo WA-05 interface by RMs. Provides send status feedback to the Odoo UI without polling `outbound_messages` directly.

```sql
CREATE TABLE odoo_send_requests (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    enrollment_id   UUID        REFERENCES workflow_enrollments(id),
    actor_id        INTEGER     NOT NULL,
    phone           TEXT        NOT NULL,
    rm_odoo_id      INTEGER     NOT NULL,
    rm_name         TEXT        NOT NULL,
    message_kind    TEXT        NOT NULL
                    CHECK (message_kind IN ('text','image','document','audio','video')),
    message_text    TEXT,
    media_url       TEXT,
    media_filename  TEXT,
    status          TEXT        NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','published','sent','failed')),
    outbound_msg_id UUID        REFERENCES outbound_messages(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at    TIMESTAMPTZ,
    error_text      TEXT
);

CREATE INDEX idx_osr_pending ON odoo_send_requests(created_at) WHERE status='pending';
```

| Column | Type | Req | Source | What it stores | Why it exists |
|--------|------|-----|--------|----------------|---------------|
| `id` | UUID | R | `gen_random_uuid()` | Primary key | Standard PK |
| `enrollment_id` | UUID | O | Set from the lead's active enrollment in WA-05. NULL if no active enrollment | The enrollment context for this RM send | Allows `wa-sender` to attribute the send to the correct enrollment and workflow in cost reporting |
| `actor_id` | INTEGER | R | From the Odoo lead form context | The Odoo record ID for this actor | Used for `actor_timeline` writes: the correct `actor_id` without a second lookup |
| `phone` | TEXT | R | From the lead's phone in Odoo | The destination phone number | Send target for the Interakt Non-Template API call |
| `rm_odoo_id` | INTEGER | R | From the Odoo session: logged-in user ID | Odoo user ID of the RM sending this message | Included in `WaSendPayload` so `wa-sender` writes `sent_by_rm_id` on `outbound_messages` |
| `rm_name` | TEXT | R | From the Odoo session: logged-in user display name | RM's display name | Included in `WaSendPayload` to populate `outbound_messages.sent_by_rm_name` without a second Odoo fetch |
| `message_kind` | TEXT | R | Set by Odoo WA-05 controller based on what the RM sent | Type of message: `text`, `image`, `document`, `audio`, or `video` | Determines Interakt API payload structure for the Non-Template Send API |
| `message_text` | TEXT | O | The text the RM typed in the WA-05 reply input. NULL for media | The message body for text sends | Passed to Interakt as `data.message`. Also copied to `outbound_messages.message_text` |
| `media_url` | TEXT | O | URL of the uploaded media file. NULL for text | File URL for image/document/audio/video sends | Passed to Interakt as `data.mediaUrl` |
| `media_filename` | TEXT | O | Original filename for documents. NULL for non-document types | Document display filename | Passed to Interakt as `data.fileName` for document messages |
| `status` | TEXT | R | Default `'pending'`. Updated by Odoo controller then by `wa-sender` | Send pipeline state: `pending`→`published`→`sent`/`failed` | RM sees real-time status in WA-05 UI: spinning→sent→delivered (when webhook arrives) |
| `outbound_msg_id` | UUID | O | Set by `wa-sender` after creating the `outbound_messages` row. NULL until processed | FK to the `outbound_messages` row created for this send | Join key: `odoo_send_requests` → `outbound_messages` → delivery status from webhooks |
| `created_at` | TIMESTAMPTZ | R | `NOW()` on insert | When the RM clicked Send | The message send time shown in the timeline |
| `published_at` | TIMESTAMPTZ | O | Set by Odoo controller after publishing to `wa-send` Pub/Sub | When this was published to the send queue | Monitoring: `created_at` to `published_at` = Odoo controller latency |
| `error_text` | TEXT | O | Set if the send fails before reaching Interakt | Why the send failed pre-Interakt | Shown to RM in WA-05 if message could not be sent |

### 13.2 Table: `rm_reply_analytics`

Part B only. Daily aggregated RM performance metrics. Populated nightly by analytics CronJob. Used by Odoo WA-01 dashboard RM performance section.

```sql
CREATE TABLE rm_reply_analytics (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    rm_odoo_id              INTEGER     NOT NULL,
    rm_name                 TEXT        NOT NULL,
    report_date             DATE        NOT NULL,
    messages_sent_count     INTEGER     NOT NULL DEFAULT 0,
    replies_received_count  INTEGER     NOT NULL DEFAULT 0,
    reply_rate_pct          NUMERIC(5,2),
    avg_reply_time_min      NUMERIC(8,2),
    median_reply_time_min   NUMERIC(8,2),
    fastest_reply_min       NUMERIC(8,2),
    leads_responded         INTEGER     NOT NULL DEFAULT 0,
    leads_no_response       INTEGER     NOT NULL DEFAULT 0,
    calculated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (rm_odoo_id, report_date)
);
```

| Column | Type | Req | Source | What it stores | Why it exists |
|--------|------|-----|--------|----------------|---------------|
| `id` | UUID | R | `gen_random_uuid()` | Primary key | Standard PK |
| `rm_odoo_id` | INTEGER | R | From `rm_assignments` data at calculation time | Odoo user ID of the RM | Primary lookup for RM-filtered dashboard queries |
| `rm_name` | TEXT | R | From `rm_assignments` at calculation time | RM's display name | Denormalised for dashboard without joining to Odoo |
| `report_date` | DATE | R | The date being reported. Combined with `rm_odoo_id` as UNIQUE key | The calendar date this row covers | Date-range filtering: show this RM's reply rate trend over 30 days |
| `messages_sent_count` | INTEGER | R | `COUNT outbound_messages WHERE sent_by_rm_id=$rm AND date=$date` | Messages this RM manually sent on this date | RM activity numerator. Excludes automated sends |
| `replies_received_count` | INTEGER | R | `COUNT inbound_messages WHERE contact_owner_email=rm_email AND date=$date` | Replies received from actors assigned to this RM on this date | Reply volume for this RM |
| `reply_rate_pct` | NUMERIC(5,2) | O | `replies_received_count / messages_sent_count * 100`. NULL if no messages sent | % of sent messages that received a reply | Headline RM performance metric |
| `avg_reply_time_min` | NUMERIC(8,2) | O | `AVG(inbound.received_at - outbound.delivered_at)` for matched pairs | Average minutes from delivery to first reply | Measures message effectiveness |
| `median_reply_time_min` | NUMERIC(8,2) | O | `PERCENTILE_CONT(0.5)` of reply times | Median reply time in minutes | Robust measure, less affected by outliers than average |
| `fastest_reply_min` | NUMERIC(8,2) | O | `MIN` of reply times for this RM on this date | Fastest reply received on this date | Shows best-case responsiveness |
| `leads_responded` | INTEGER | R | `COUNT DISTINCT actor_id` where at least one reply followed this RM's outbound | Distinct actors who replied to this RM | More meaningful than raw reply count: one actor replying 10 times counts as 1 |
| `leads_no_response` | INTEGER | R | `COUNT DISTINCT actor_id` where messages sent but no reply within 48h | Actors who did not respond to this RM's messages | Identifies follow-up candidates. High ratio may indicate message fatigue |
| `calculated_at` | TIMESTAMPTZ | R | `NOW()` when the analytics CronJob ran | When this row was computed | Freshness check: if > 26h ago, CronJob may have failed |

---

## 14. User Stories

### US-01: Buyer inquiry enrolled, first-touch message delivered

**Actor:** Odoo event → workflow-engine → wa-sender → Interakt → delivery webhook

1. Odoo creates inquiry 4521 (Ankit Mehta, phone `919876543210`, property 6369, portal 99acres, assigned RM Priya). `crm_lead_events` module publishes `lead.created` event: `{actor_type:'buyer_inquiry', actor_id:4521, phone:'919876543210', payload:{portal_source:'99acres',property_id:6369,assigned_rm_email:'priya@cleardeals.co.in'}}`. (`lead_id` is absent — not yet in Odoo system.)
2. `workflow-engine-nurturing` receives. Matches step `'first_touch'`. Fetches inquiry data from Odoo REST. Builds `meta` from config `meta_fields`: `{portal_source:'99acres', property_id:6369, assigned_rm_email:'priya@cleardeals.co.in'}`.
3. `INSERT workflow_enrollments`: `actor_type='buyer_inquiry'`, `actor_id=4521`, `lead_id=null`, `phone='919876543210'`, `status='active'`, `current_step='first_touch'`, `meta=<above>`. `INSERT actor_timeline`: `event_type='workflow_enrolled'`.
4. Resolves `body_values=['Ankit Mehta','https://cleardeals.co.in/property/...']`. `callback_data='nurturing_v2:first_touch:enroll-uuid'`. Publishes `WaSendPayload` to `wa-send`.
5. `wa-sender`: all pre-send checks pass (no opt-out, not blocked, not disengaged, not already sent). `INSERT outbound_messages`: `status='queued'`. Calls Interakt API. Response: `[{id:'1a993fe2-...'}]`. `UPDATE outbound_messages SET interakt_msg_id='1a993fe2-...', status='sent', sent_at=NOW()`.
6. `UPSERT conversation_context`: `active_enrollment_count=1`, `active_enrollment_id=enroll-uuid`, `last_callback_data='nurturing_v2:first_touch:enroll-uuid'`, `pending_button_reply=true`.
7. `INSERT actor_timeline`: `event_type='message_sent'`, `actor_type_who='system'`, `outbound_msg_id=<row>`.
8. ~1.8s: Interakt delivers `message_api_delivered` webhook. `event-archiver`: `UPDATE outbound_messages SET status='delivered', delivered_at='2026-04-13T10:32:05.410Z', cost_total_inr=0.9494 WHERE interakt_msg_id='1a993fe2-...'`. `INSERT actor_timeline`: `event_type='message_delivered'`, `happened_at='2026-04-13T10:32:05.410Z'` (webhook timestamp, not `NOW()`).

---

### US-02: Double button tap — branch lock prevents duplicate

**Actor:** `reply-router` + `branch_locked_at` column on `workflow_enrollments`

1. Lead has enrollment `enroll-uuid` in nurturing, currently on branch step `'branch_after_details'`. `current_branch_path=NULL`, `branch_locked_at=NULL`.
2. T+0: Lead taps "Plan Site Visit". `message_received` webhook. `callback_data='nurturing_v2:branch_after_details:enroll-uuid'`. `reply-router` routes to `enroll-uuid`.
3. `INSERT inbound_messages`: `button_reply_id='plan_site_visit'`, `branch_blocked=false`.
4. `workflow-engine` executes Branch step. Writes: `UPDATE workflow_enrollments SET current_branch_path='A', branch_locked_at=NOW(), branch_locked_path='A' WHERE id='enroll-uuid'`. Continues execution on path A (assign_rm step).
5. T+2s: Lead taps "See Similar Options". Second `message_received` webhook. Same `callback_data`. `reply-router` routes to same `enroll-uuid`.
6. `reply-router` checks: `SELECT branch_locked_at, branch_locked_path FROM workflow_enrollments WHERE id='enroll-uuid' AND branch_locked_at > NOW()-INTERVAL '30 seconds'`. Returns `branch_locked_at=T+0`, `branch_locked_path='A'`. Lock active.
7. `INSERT inbound_messages`: `button_reply_id='see_similar'`, `branch_blocked=true`. No `workflow.resume` published.
8. `INSERT actor_timeline`: `event_type='branch_second_tap_blocked'`, `title='Second tap (See Similar) blocked — branch already decided: path A (Plan Site Visit)'`.
9. Workflow continues on path A only. No duplicate RM assignment. No confusion.
https://www.odoo.com/documentation/19.0/developer/reference.html
---

### US-03: Workflow-scoped STOP opt-out

**Actor:** `webhook-gateway` → `reply-router` → `workflow_opt_outs`

1. Lead 4521 sends `'STOP'`. Interakt webhook: `message_content_type='Text'`, `message='STOP'`. `webhook-gateway` sets `is_stop_message=true`.
2. `reply-router` receives. `callback_data='nurturing_v2:first_touch:enroll-uuid'`. Routes to `workflow_id='nurturing-v2-uuid'`.
3. `INSERT workflow_opt_outs (phone='919876543210', workflow_id='nurturing-v2-uuid', triggering_inbound=<inbound row id>) ON CONFLICT DO NOTHING`.
4. `UPDATE workflow_enrollments SET status='unenrolled' WHERE id='enroll-uuid'`.
5. `UPDATE conversation_context SET active_enrollment_count=active_enrollment_count-1 WHERE phone='919876543210'`.
6. `INSERT actor_timeline`: `event_type='workflow_opted_out'`, `title='Lead sent STOP — opted out of Lead Nurturing. Visit notifications continue.'`
7. `wa-sender` sends confirmation (bypass — sends despite opt-out): `'You will no longer receive Lead Nurturing messages from ClearDeals. Site visit reminders and other communications continue. Reply START to re-subscribe.'`
8. Two days later: RM sets up a property visit for actor_id 4521 (coordinates over phone with buyer and owner). `visit_orchestration` workflow enrols actor_id 4521. `wa-sender` pre-send check: `SELECT 1 FROM workflow_opt_outs WHERE phone='919876543210' AND (workflow_id='visit-orch-uuid' OR workflow_id IS NULL)`. No row. Send proceeds. Visit confirmation delivered.

---

*ClearDeals WhatsApp Automation — SQL Database Design Reference | April 2026*
*Proptech Cleardeals Pvt. Ltd. | 13 tables · All eight decisions applied · Part A + Part B*
