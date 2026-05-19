# ClearDeals WhatsApp Automation
## Services Architecture Reference

**7 Services · 10 Pub/Sub Topics · All Event Schemas · Config Patterns · Pseudocode Logic**

Proptech Cleardeals Pvt. Ltd. | April 2026

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Pub/Sub Topics and Event Schemas](#2-pubsub-topics-and-event-schemas)
   - [2.1 Standard Event Envelope](#21-standard-event-envelope)
   - [2.2 WaSendPayload — the wa-send topic schema](#22-wasendpayload--the-wa-send-topic-schema)
3. [Service S1 — webhook-gateway](#3-service-s1--webhook-gateway)
4. [Service S2 — workflow-engine (7 variants)](#4-service-s2--workflow-engine-7-variants)
   - [4.1 The WorkflowEngine class — core execution logic](#41-the-workflowengine-class--core-execution-logic)
   - [4.2 Example config.yaml — nurturing workflow](#42-example-configyaml--nurturing-workflow)
5. [Service S3 — wa-sender](#5-service-s3--wa-sender)
6. [Service S4 — reply-router](#6-service-s4--reply-router)
7. [Service S5 — error-handler](#7-service-s5--error-handler)
8. [Service S6 — reminder-scheduler (5 CronJobs)](#8-service-s6--reminder-scheduler-5-cronjobs)
9. [Service S7 — odoo-bridge](#9-service-s7--odoo-bridge)
10. [Shared Library — shared/](#10-shared-library--shared)
11. [CI/CD Pipeline](#11-cicd-pipeline)
12. [Kubernetes Manifests — Key Patterns](#12-kubernetes-manifests--key-patterns)
    - [12.1 workflow-engine ConfigMap pattern](#121-workflow-engine-configmap-pattern)
    - [12.2 KEDA ScaledObject — autoscaling on Pub/Sub backlog](#122-keda-scaledobject--autoscaling-on-pubsub-backlog)

---

## 1. System Overview

The ClearDeals WhatsApp Automation platform runs as a set of seven services on Google Kubernetes Engine (GKE). Each service is a Python 3.12 container with a single responsibility. Services communicate exclusively through Google Cloud Pub/Sub — no service calls another service's HTTP endpoint directly, except for the Interakt-facing HTTP server and the Odoo-facing HTTP consumers.

The system handles seven distinct campaigns across two actor types (inquiries and customers). All actor data originates from Odoo events — no BigQuery source tables are polled in the hot path. Interakt is used as the WhatsApp Business API provider: messages are sent via its API and status updates (delivered/read/failed) and inbound replies arrive via Interakt webhooks.

| Service | K8s type | Min pods | Trigger | Core responsibility |
|---------|----------|----------|---------|---------------------|
| S1: webhook-gateway | Deployment | 2 | HTTP POST from Interakt | Receive all Interakt webhooks, verify signature, publish to Pub/Sub |
| S2: workflow-engine | Deployment × 7 variants | 1 per variant | Pub/Sub pull per variant | Execute config-driven workflow steps for each campaign |
| S3: wa-sender | Deployment | 2 | Pub/Sub pull (wa-send, wa-status-updates) | Call Interakt send API; archive delivery status, cost, and actor_timeline |
| S4: reply-router | Deployment | 2 | Pub/Sub pull (wa-inbound) | Route inbound messages to correct enrollment, handle STOP, branch lock |
| S5: error-handler | Deployment | 1 | Pub/Sub pull (wa-failed) | Classify failures, retry with backoff, write DLQ |
| S6: reminder-scheduler | CronJob × 5 jobs | 0 (scheduled) | Kubernetes cron | Query due reminders and timeouts, publish events |
| S7: odoo-bridge | Deployment | 1 | Pub/Sub pull (rm-alerts) | Write activities and assignments back to Odoo |

> **One Docker image for workflow-engine:** All seven workflow-engine variants (nurturing, portal-lead, property-promotion, lead-scoring, expiry-alert, renewal, post-visit) use a single Docker image. Each variant is a separate Kubernetes Deployment injecting a different ConfigMap: `WORKFLOW_CONFIG_PATH` and `PUBSUB_SUBSCRIPTION`. No recompilation when adding a new campaign — only a new ConfigMap and a new Deployment manifest.

---

## 2. Pub/Sub Topics and Event Schemas

Ten topics carry all inter-service communication. Every event has a standard envelope with `event_type`, `actor_type`, `inquiry_id`, `phone`, `payload`, and `published_at`. Services deserialise events using Pydantic models defined in `shared/models.py`.

| Topic | Publisher(s) | Subscriber(s) | Key event_types | Retention / notes |
|-------|-------------|---------------|-----------------|-------------------|
| actor-events | Odoo crm_lead_events module | workflow-engine (nurturing, portal-lead, lead-scoring, post-visit) | actor.created · actor.status_changed · actor.post_visit | 24h. Covers both inquiry and customer events from Odoo. |
| visit-events | Odoo visit model · reminder-scheduler | workflow-engine-visit-orch · workflow-engine-post-visit | visit.scheduled · visit.done · visit.rescheduled · scheduler.visit_reminder_due | 24h |
| property-events | reminder-scheduler (reads property_promotion_queue) | workflow-engine-property-promo | property_promotion.lead_queued | 24h. Batch campaign trigger. |
| customer-events | Odoo (customer events) · reminder-scheduler (expiry CronJob) | workflow-engine-expiry-alert · workflow-engine-renewal | customer.expiry_approaching · scheduler.goodwill_nudge | 24h |
| wa-send | All workflow-engine variants · error-handler (retries) | wa-sender | (Payload is WaSendPayload — not event_type based) | 7 days. Longer retention for retry window. |
| wa-inbound | webhook-gateway | reply-router | (Raw Interakt message_received webhook body) | 24h |
| wa-status-updates | webhook-gateway | wa-sender | (Raw Interakt delivery/read/failed webhook bodies) | 24h |
| wa-failed | wa-sender | error-handler | (WaFailedPayload — extends WaSendPayload + failure fields) | 7 days |
| rm-alerts | reply-router · error-handler | odoo-bridge | alert.lead_replied · alert.ambiguous_reply · alert.permanent_failure · alert.retry_exhausted | 48h |
| workflow-resume | reply-router · reminder-scheduler | Each variant via its own filtered subscription | workflow.resume (enrollment_id, step_id, reply_context) | 24h. Each variant's subscription filters on `attributes.workflow_slug`. Only the correct variant receives each message — no fan-out waste. |

### 2.1 Standard Event Envelope

```
// Standard event envelope — all Odoo-originated events on actor/visit/customer topics

FIELDS:
  event_type   : string   — e.g. "actor.created", "actor.status_changed"
  actor_type   : string   — "inquiry" | "customer"
  inquiry_id   : integer  — Odoo record ID (crm.lead.id for inquiries; customer record ID for customers)
  phone        : string   — E.164 without '+', e.g. "919876543210"
  payload      : object   — event-specific data (portal_source, new_status, property_id, etc.)
  published_at : datetime — ISO-8601 UTC

PHONE VALIDATION ON INGEST:
  Strip all '+', spaces, dashes
  Reject if length < 10 or > 13 characters

EXAMPLE — actor.created for a new portal inquiry:
{
  "event_type":   "actor.created",
  "actor_type":   "inquiry",
  "inquiry_id":   4521,
  "phone":        "919876543210",
  "payload": {
    "portal_source":      "99acres",
    "assigned_rm_email":  "priya@cleardeals.co.in",
    "assigned_rm_id":     12,
    "actor": {
      "id":             4521,
      "actor_type":     "buyer_inquiry",
      "name":           "Ankit Mehta",
      "phone":          "9876543210",
      "current_status": "lead",
      "inquiry_type":   "primary",
      "rm": {
        "id":    12,
        "name":  "Priya Singh",
        "email": "priya@cleardeals.co.in",
        "phone": "9876500001"
      },
      "property": {
        "id":              123,
        "prop_id":         "GBH75X0K",
        "tag":             "B-505, Green Heights",
        "bhk":             "3 BHK",
        "location":        "Bopal",
        "city":            "Ahmedabad",
        "link":            "https://www.cleardeals.in/property/green-heights-GBH75X0K",
        "owner_name":      "Mr. Patel",
        "pricing_display": "48 Lakh",
        "is_active":       true
      }
    }
  },
  "published_at": "2026-04-13T10:32:00Z"
}
```

### 2.2 WaSendPayload — the wa-send topic schema

```
// WaSendPayload — published to wa-send by all workflow-engine variants
  enrollment_id   : UUID    — row ID from workflow_enrollments
  step_id         : string  — step identifier from config.yaml
  phone           : string  — destination phone
  template_name   : string  — Interakt template name
  body_values     : list    — ordered variable values for template body
  header_values   : list    — variable values for template header (optional)
  button_values   : object  — button config (optional)
  callback_data   : string  — "workflow_slug:step_id:enrollment_uuid"
                              echoed back in Interakt reply webhooks for deterministic routing
  retry_count     : integer — default 0; incremented by error-handler on each retry
  message_kind    : string  — default "template"; "text"|"image"|"document" for RM sends
  message_text    : string  — body for non-template RM sends (optional)
  sent_by_rm_id   : integer — Odoo user ID for RM-initiated sends (optional)
  sent_by_rm_name : string  — RM display name (optional)

// WaFailedPayload — published to wa-failed by wa-sender
  All WaSendPayload fields, plus:
  failure_reason  : string
  failure_code    : string (optional)

// WaResumePayload — published to workflow-resume by reply-router and reminder-scheduler
  enrollment_id   : UUID
  step_id         : string  — step being resumed
  workflow_slug   : string  — identifies which variant should consume this message
                             also set as Pub/Sub message attribute for subscription filtering
  resume_reason   : string  — "actor_reply" | "timeout"
  button_reply_id : string  (optional)
  reply_text      : string  (optional)
  inbound_msg_id  : string  (optional — not present for timeout resumes)

// RmAlertPayload — published to rm-alerts by reply-router and error-handler
  alert_type          : string  — "lead_replied" | "ambiguous_reply" | "permanent_failure" | "retry_exhausted"
  inquiry_id          : integer
  actor_type          : string
  phone               : string
  rm_odoo_id          : integer (optional)
  rm_email            : string  (optional)
  message_text        : string  (optional)
  button_reply_id     : string  (optional)
  failure_code        : string  (optional)
  failure_reason      : string  (optional)
  active_enrollments  : list    — populated for ambiguous_reply alerts
```

---

## 3. Service S1 — webhook-gateway

**`S1` — webhook-gateway**
*HTTP FastAPI server · receives all Interakt webhooks · publishes to Pub/Sub · handles STOP*

| Config | Value |
|--------|-------|
| Image | asia-south1-docker.pkg.dev/cleardeals-prod/wa/webhook-gateway:latest |
| Replicas | 2 min, autoscales on HTTP request rate > 50/min |
| Port | 8000 (exposed via GKE Ingress) |
| Public URL | https://wa-webhook.cleardeals.co.in/webhook/interakt |
| Secret: INTERAKT_WEBHOOK_SECRET | From Secret Manager: interakt-webhook-secret |
| DB writes | Only one: UPDATE conversation_context SET opted_out=true on STOP — no other DB writes in hot path |
| Publishes to | wa-inbound (message_received events), wa-status-updates (all other webhook types) |

```
// INITIALISATION (once at startup)
Load INTERAKT_WEBHOOK_SECRET from GCP Secret Manager (cached after first load)
Initialise Pub/Sub publisher client (cached after first use)

// ON EVERY INCOMING POST /webhook/interakt
FUNCTION receive_webhook(request):
  raw_body  ← read request body as raw bytes
  signature ← read "interakt-signature" header
  expected  ← "sha256=" + HMAC_SHA256(secret_key, raw_body)

  IF constant_time_compare(expected, signature) FAILS:
    RETURN HTTP 401 Unauthorized

  events ← parse raw_body as JSON array

  FOR EACH event IN events:
    event_type ← event.body.type

    IF event_type == "message_received":
      text ← event.body.data.message.message (uppercase, strip whitespace)
      IF text == "STOP":
        SET event._is_stop = true          // flag for reply-router to handle opt-out
      ENQUEUE background task: publish("wa-inbound", event)

    ELSE:
      ENQUEUE background task: publish("wa-status-updates", event)

  RETURN HTTP 200 { "status": "ok" }

// BACKGROUND PUBLISH
FUNCTION publish(topic_alias, data):
  Resolve full topic name: "wa-inbound" → "cd-{env}-wa-inbound"
  Serialise data as JSON bytes
  Publish to Pub/Sub; wait for delivery acknowledgement

// HEALTH CHECK
GET /health → return { "status": "healthy" }
```

---

## 4. Service S2 — workflow-engine (7 variants)

**`S2` — workflow-engine**
*Config-driven Pub/Sub worker · executes workflow steps · one image, seven ConfigMaps*

| Variant | Subscription | Config file | Trigger events | actor_scope |
|---------|-------------|-------------|----------------|-------------|
| workflow-engine-nurturing | cd-prod-actor-events-nurturing-sub | configs/nurturing.yaml | actor.created, actor.status_changed (ringing) | inquiry |
| workflow-engine-portal-lead | cd-prod-actor-events-portal-sub | configs/portal_lead.yaml | actor.created (portal leads) | inquiry |
| workflow-engine-property-promo | cd-prod-property-promo-sub | configs/property_promotion.yaml | property_promotion.lead_queued | inquiry |
| workflow-engine-lead-scoring | cd-prod-actor-events-scoring-sub | configs/lead_scoring.yaml | actor.status_changed (scheduled batch) | inquiry |
| workflow-engine-expiry-alert | cd-prod-customer-events-sub | configs/expiry_alert.yaml | customer.expiry_approaching | customer |
| workflow-engine-renewal | cd-prod-customer-events-renewal-sub | configs/renewal.yaml | customer.expiry_approaching, actor.status_changed | both |
| workflow-engine-post-visit | cd-prod-visit-events-sub | configs/post_visit.yaml | visit.done, actor.post_visit | inquiry |

### 4.1 The WorkflowEngine class — core execution logic

```
// INITIALISATION
Load workflow config from YAML file at path given by WORKFLOW_CONFIG_PATH env var
Extract: workflow_id, workflow_slug, steps list, meta_fields list
Connect to Cloud SQL and initialise Pub/Sub client

// MAIN PROCESSING FUNCTION (called once per Pub/Sub message)
FUNCTION process(event):

  // 1. Guard: skip if workflow is paused
  IF workflows.is_active == false for this workflow_slug:
    Discard event; return

  // 2. Parse and validate the incoming event
  Parse event fields; reject malformed events

  // 3. Match the event to a workflow step
  //    Steps are evaluated in YAML order (top to bottom).
  //    The FIRST step where all of the following hold wins:
  //      a) trigger.event_type matches the incoming event_type
  //      b) trigger.condition (if present) evaluates to true against the event payload
  //    A step with NO condition is a catch-all for that event_type — it matches
  //    any event that earlier, more-specific steps did not claim.
  //    YAML order is the author's responsibility: put most-specific conditions first.
  FOR EACH step IN config.steps (in order):
    IF step.trigger.event_type != event.event_type: CONTINUE
    IF step.trigger.condition EXISTS AND condition evaluates FALSE against event: CONTINUE
    matched_step ← step; BREAK
  IF no step matched: discard and return

  // 4. Extract actor snapshot from event payload
  //    Odoo embeds the full actor context in every event it publishes.
  //    No REST call to Odoo is ever made from the WA platform.
  actor_snapshot ← event.payload.get("actor")   // dict or None
  //    If actor_snapshot is None (Odoo publishing bug), actor.* vars resolve to ""

  // 5. Upsert enrollment
  enrollment ← INSERT into workflow_enrollments:
                  (workflow_id, actor_type, inquiry_id, phone, status='active', current_step)
                ON CONFLICT (workflow_id, inquiry_id):
                  UPDATE current_step, status='active', last_activity_at=NOW()
                Store meta_fields from event payload in enrollment.meta
                Store actor_snapshot in enrollment.meta["actor"]   // ← key addition

  // 6. Idempotency check
  IF workflow_step_log already has a successful row for (enrollment_id, step_id):
    Discard — already processed; return

  // 7. Execute step based on step_type
  SWITCH step_type:

    CASE "trigger":
      Log step start; no external action

    CASE "send_message":
      vars ← CALL resolve_vars(step.vars, actor, event, enrollment.meta)
      Build WaSendPayload:
        phone, template_name, body_values, header_values
        callback_data = "{workflow_slug}:{step_id}:{enrollment_id}"
      Publish WaSendPayload to wa-send topic
      Write workflow_step_log row: step_type='send_message', status='success'

    CASE "wait_for_reply":
      wait_until ← NOW() + step.wait_timeout_h (null if no timeout)
      UPDATE workflow_enrollments:
        status='waiting', waiting_for=step.wait_for, wait_until=wait_until
      Write workflow_step_log: step_type='wait_for_reply', status='waiting'

    CASE "wait_and_send":
      Same as wait_for_reply but wait_for is always a timer (no reply expected)

    CASE "branch":
      // Only reached via workflow.resume after a button reply
      button_id ← resume context button_reply_id
      path ← "A" if button_id matches step.branch_condition_A, else "B"
      UPDATE workflow_enrollments:
        current_branch_path=path, branch_locked_at=NOW(), branch_locked_path=path
      Write workflow_step_log: step_type='branch', branch_path_taken=path

    CASE "assign_rm":
      target_rm ← resolve dot-path (e.g. "meta.assigned_rm_email") against enrollment.meta
      Publish RmAlertPayload (alert_type='lead_assigned') to rm-alerts topic
      Write workflow_step_log: step_type='assign_rm'

    CASE "end":
      UPDATE workflow_enrollments: status='completed', completed_at=NOW()
      Write workflow_step_log: step_type='end'

// VARIABLE RESOLUTION
FUNCTION resolve_vars(var_configs, event, meta):
  // actor_snapshot is read from meta["actor"] — stored at enrollment time from event.payload.actor
  // For timer/reply resumes, this is the snapshot from the last Odoo event that updated this enrollment
  actor_snapshot ← meta.get("actor") or {}
  FOR EACH var IN var_configs (sorted by position ascending):
    Traverse dot-path source against available data sources:
      "actor.*"  → actor_snapshot (e.g. "actor.property.link" → meta["actor"]["property"]["link"])
      "event.*"  → event payload fields
      "meta.*"   → enrollment.meta fields (excluding the actor sub-key)
    IF traversal yields None or KeyError: value ← ""
    Assign resolved string to body list or header list based on var.header flag
  RETURN { body: [...ordered values...], header: [...] }
```

### 4.2 Example config.yaml — nurturing workflow

```yaml
# services/workflow_engine/configs/nurturing.yaml
workflow_id:   nurturing-v2-uuid
workflow_slug: nurturing_v2
campaign_id:   C1
actor_scope:   inquiry

# meta_fields: which fields from the Odoo event payload to store in enrollment.meta
meta_fields:
  - portal_source
  - property_id
  - assigned_rm_email
  - assigned_rm_id

steps:
  - id: first_touch
    step_type: send_message
    display_name: 'First touch — welcome message'
    trigger:
      event_type: actor.created
    template: welcome_message_v3
    vars:
      - position: 1
        source: actor.name
        label: 'Actor name'
        editable: true
      - position: 2
        source: actor.property_url
        label: 'Property link'
        editable: true
    buttons:
      - id: plan_site_visit
        text: 'Plan Site Visit'
        text_editable: true
      - id: see_similar
        text: 'See Similar Properties'
        text_editable: true
    failure_action: skip_step

  - id: wait_for_ringing
    step_type: wait_for_reply
    display_name: 'Wait until RM marks inquiry as Ringing'
    wait_for: status:ringing
    wait_timeout_h: 168
    wait_timeout_action: next_step

  - id: ringing_followup
    step_type: send_message
    display_name: 'Property details follow-up'
    trigger:
      event_type: actor.status_changed
      condition: "event.payload.new_status == 'ringing'"
    template: property_detail_v2
    vars:
      - position: 1
        source: meta.portal_source
        label: 'Portal source'
        editable: true
      - position: 2
        source: actor.property_locality
        label: 'Locality'
        editable: true
      - position: 3
        source: actor.property_config
        label: 'Configuration (3 BHK etc.)'
        editable: true
      - position: 4
        source: actor.property_url
        label: 'Property link'
        editable: true
    buttons:
      - id: plan_site_visit
        text: 'Plan Site Visit'
        text_editable: true
      - id: see_similar
        text: 'See Similar Options'
        text_editable: true
    failure_action: retry_3x

  - id: branch_after_details
    step_type: branch
    display_name: 'Branch by what actor tapped'
    branch_condition_A: plan_site_visit
    branch_condition_B: see_similar
    branch_lock_seconds: 30

  - id: assign_rm_site_visit
    step_type: assign_rm
    display_name: 'Assign to RM — site visit intent'
    branch_path: A
    assign_to: meta.assigned_rm_email
    send_confirmation: true
    failure_action: skip_step
```

---

## 5. Service S3 — wa-sender

**`S3` — wa-sender**
*Only service that calls Interakt API · handles delivery/read/fail webhooks · 5 pre-send checks*

| Config | Value |
|--------|-------|
| Subscribes to | wa-send (send payloads) and wa-status-updates (delivery/read/fail webhooks) |
| Replicas | 2 min, autoscales to 8 on wa-send backlog depth |
| Secret: INTERAKT_API_KEY | From Secret Manager: interakt-api-key |
| Rate limit | Token bucket: 30 API calls/second (configurable) |
| Max retries | 3 (controlled by error-handler, not wa-sender itself) |

```
// PRE-SEND CHECKS (run in order; first failure short-circuits the whole send)
  1. opt-out check      — query workflow_opt_outs: is this phone opted out of this workflow?
  2. meta-blocked check — query outbound_messages history: has Meta previously blocked this phone?
  3. disengagement check— is enrollment.disengagement_score ≥ 2.0? (batch campaigns only)
  4. already-sent check — does outbound_messages have a non-failed row for (enrollment_id, step_id)?
  5. workflow-active    — is workflows.is_active = true for this workflow?

// HANDLE SEND MESSAGE (wa-send topic)
FUNCTION handle_send(message):
  payload ← deserialise WaSendPayload from message

  FOR EACH check IN pre_send_checks:
    skip_reason ← run check(payload)
    IF skip_reason IS NOT NULL:
      INSERT outbound_messages row with status='skipped', skip_reason
      Ack message and RETURN

  INSERT outbound_messages row with status='queued'
    ← this is the idempotency anchor: if the process crashes after this, already-sent check catches the retry

  TRY:
    Call Interakt Send Template API:
      phone, template_name, body_values, header_values, callback_data
    UPDATE outbound_messages: status='sent', interakt_msg_id=response.id
    UPSERT conversation_context: phone → active_enrollment_id, last_outbound_at=NOW()
    Write actor_timeline event: "message_sent"
    Ack message

  ON FAILURE:
    Publish WaFailedPayload to wa-failed topic
    Nack message (Pub/Sub redelivers; error-handler controls retry logic)

// HANDLE STATUS UPDATE (wa-status-updates topic)
// Note: wa-sender is the sole subscriber to wa-status-updates. All archival
//       (cost, raw payload, actor_timeline) is handled here.
FUNCTION handle_status_update(message):
  webhook    ← deserialise Interakt status webhook from message
  event_type ← webhook.body.type
  msg_id     ← webhook.body.data.message.id

  IF msg_id is null:
    Ack and RETURN

  IF event_type == "message_api_delivered":
    cost ← extract actual_message_cost from webhook metadata
    UPDATE outbound_messages WHERE interakt_msg_id = msg_id:
      status='delivered', delivered_at, cost_total_inr=cost,
      interakt_customer_id, raw_interakt_payload=full webhook JSON
    IF row found:
      Write actor_timeline event: "message_delivered" at delivered_at

  ELSE IF event_type == "message_api_read":
    UPDATE outbound_messages WHERE interakt_msg_id = msg_id:
      status='read', read_at=seen_at_utc
      delivered_at = COALESCE(existing delivered_at, delivered_at_utc)
    IF row found:
      Write actor_timeline event: "message_read" at read_at

  ELSE IF event_type == "message_api_failed":
    Map Interakt error code to internal status:
      131026 → 'meta_blocked' | 131047 → 'opted_out'    | 131052 → 'invalid_number'
      130429 → 'rate_limited' | 132000/132001 → 'template_error' | else → 'failed'
    UPDATE outbound_messages WHERE interakt_msg_id = msg_id:
      status, failure_code, failure_reason, failed_at=NOW()
    IF row found:
      Write actor_timeline event: "message_{status}"
    IF status is permanent (meta_blocked / opted_out / invalid_number):
      Publish WaFailedPayload to wa-failed ← triggers RM alert in error-handler

  Ack message
```

---

## 6. Service S4 — reply-router

**`S4` — reply-router**
*Routes all inbound messages · branch lock check · STOP handler · multi-enrollment awareness*

```
// HANDLE INBOUND MESSAGE (wa-inbound topic)
FUNCTION route_inbound(message):
  webhook    ← deserialise Interakt webhook from message
  phone      ← extract customer phone (webhook.body.data.customer.channel_phone_number)
  callback   ← extract callback_data from button reply metadata (null if free-text reply)
  button_id  ← extract button reply ID (null if not a button reply)
  is_stop    ← read _is_stop flag set by webhook-gateway

  // ── STOP path ──────────────────────────────────────────────────
  IF is_stop:
    CALL handle_stop(phone, callback)
    Write inbound_messages row (is_stop_message=true)
    Ack message and RETURN

  // ── Priority 1: callback_data (deterministic — button replies) ──
  IF callback IS NOT NULL:
    Parse callback as "workflow_slug:step_id:enrollment_uuid"
    enrollment ← look up active enrollment by enrollment_uuid
    IF found:
      IF button_id IS NOT NULL AND enrollment.branch_locked_at IS NOT NULL:
        IF (NOW() - branch_locked_at) < 30 seconds:
          Record branch-blocked event; Ack and RETURN  // duplicate tap
      workflow_slug ← first segment of callback (already parsed above)
      Publish WaResumePayload to workflow-resume
        SET Pub/Sub message attribute: workflow_slug = workflow_slug
        ← Subscription filter routes this to the correct variant only
      Write inbound_messages row; write actor_timeline event
      Ack and RETURN

  // ── Priority 2: conversation_context (single active, fresh) ─────
  ctx ← query conversation_context by phone
  IF ctx.active_enrollment_count == 1 AND ctx.last_outbound_at < 48h ago:
    enrollment ← look up workflow_enrollments row by ctx.active_enrollment_id
    workflow_slug ← enrollment.workflow_slug
    Publish WaResumePayload to workflow-resume
      SET Pub/Sub message attribute: workflow_slug = workflow_slug
    Write inbound_messages row; write actor_timeline event
    Ack and RETURN

  // ── Priority 3: ambiguous (multiple active enrollments) ─────────
  IF ctx.active_enrollment_count > 1:
    Write inbound_messages row (routing_status='ambiguous')
    Publish RmAlertPayload (alert_type='ambiguous_reply') to rm-alerts
    Ack and RETURN

  // ── Priority 4: full scan fallback (stale context) ───────────────
  enrollment ← scan workflow_enrollments for active/waiting rows WHERE phone=phone
  IF found:
    workflow_slug ← enrollment.workflow_slug
    Publish WaResumePayload to workflow-resume
      SET Pub/Sub message attribute: workflow_slug = workflow_slug
  ELSE: Write inbound_messages row (routing_status='unrouted')
  Ack

// STOP HANDLING (Decision #5 — Scoped Opt-out)
FUNCTION handle_stop(phone, callback):
  IF callback contains valid enrollment_uuid:
    Look up enrollment; extract workflow_id
    INSERT workflow_opt_outs (phone, workflow_id) ON CONFLICT DO NOTHING
    UPDATE workflow_enrollments SET status='unenrolled'
      WHERE phone=phone AND workflow_id=workflow_id AND status IN ('active','waiting')
    ← Scoped: only this workflow is blocked

  ELSE:
    INSERT workflow_opt_outs (phone, null) ON CONFLICT DO NOTHING
    UPDATE workflow_enrollments SET status='unenrolled'
      WHERE phone=phone AND status IN ('active','waiting')
    ← Global: all active workflows for this phone
```

---

## 7. Service S5 — error-handler

**`S5` — error-handler**
*Classifies failures · retries with backoff · writes DLQ · publishes RM alerts*

```
// FAILURE CLASSIFICATION CONSTANTS
  PERMANENT_CODES : { 131026 (meta_blocked), 131047 (opted_out), 131052 (invalid_number) }
  TEMPLATE_CODES  : { 132000, 132001 }
  MAX_RETRIES     : 3
  BACKOFF_DELAYS  : [ 30s, 120s, 600s ]  // indexed by current retry_count

// HANDLE FAILED MESSAGE (wa-failed topic)
FUNCTION handle_failed(message):
  payload ← deserialise WaFailedPayload from message
  code    ← payload.failure_code

  IF code IN permanent_codes OR template_codes:
    // Permanent failure — do not retry
    INSERT into dead_letter_queue: reason="Permanent failure: {code}"
    UPDATE workflow_enrollments: status='failed'
    Publish RmAlertPayload (alert_type='permanent_failure') to rm-alerts
    Write actor_timeline event: "message_retry_exhausted"

  ELSE IF payload.retry_count >= MAX_RETRIES:
    // Retry budget exhausted
    INSERT into dead_letter_queue: reason="Exhausted {MAX_RETRIES} retries"
    Publish RmAlertPayload (alert_type='retry_exhausted') to rm-alerts
    Write actor_timeline event: "message_retry_exhausted"

  ELSE:
    // Schedule retry with backoff
    delay ← BACKOFF_DELAYS[payload.retry_count]
    Increment payload.retry_count by 1
    Publish updated WaSendPayload to wa-send with delivery delay of {delay} seconds
    Write actor_timeline event: "message_retry_scheduled"
      detail: "Retry {new_count}/{MAX_RETRIES} in {delay}s"

  Ack message
```

---

## 8. Service S6 — reminder-scheduler (5 CronJobs)

**`S6` — reminder-scheduler**
*Kubernetes CronJobs · processes due reminders and Wait step timeouts*

| CronJob | Schedule (IST) | REMINDER_TYPE env | What it does |
|---------|---------------|-------------------|-------------|
| visit-reminders | `*/5 * * * *` | visit_reminder | Queries scheduled_reminders WHERE reminder_type IN ('visit_reminder_24h','visit_reminder_1h') AND status='pending' AND remind_at <= NOW(). Publishes visit.reminder_due to visit-events. |
| wait-timeouts | `*/5 * * * *` | wait_timeout | Queries workflow_enrollments WHERE status='waiting' AND wait_until <= NOW(). Publishes workflow.wait_timeout to workflow-resume topic. |
| expiry-scanner | `30 10 * * *` | expiry_scan | Publishes customer.expiry_approaching events to customer-events for T-0, T-7, T-15 actors (from Odoo customer data via Pub/Sub, not BQ). |
| goodwill-nudge | `30 10 * * *` | goodwill_nudge | After expiry-scanner: inserts scheduled_reminders rows for T-0 goodwill messages to fire at 16:00 same day. |
| followup-poller | `*/15 * * * *` | followup_poll | Queries scheduled_reminders WHERE reminder_type='followup_poll' AND status='pending' AND remind_at <= NOW(). Publishes follow-up events. |

```
// ONE BINARY, FIVE CRON JOBS — behaviour controlled by REMINDER_TYPE env var

ON STARTUP:
  Read REMINDER_TYPE from environment
  Dispatch to the matching handler function

// visit_reminder handler
FUNCTION process_visit_reminders():
  Query scheduled_reminders WHERE:
    reminder_type IN ('visit_reminder_24h', 'visit_reminder_1h')
    AND status = 'pending'
    AND remind_at <= NOW()
  FOR EACH due reminder:
    Publish scheduler.visit_reminder_due to visit-events topic
      payload: { enrollment_id, actor_id, phone, reminder_type, meta }
    UPDATE scheduled_reminders: status='published'

// wait_timeout handler
FUNCTION process_wait_timeouts():
  SELECT and row-lock workflow_enrollments WHERE:
    status = 'waiting' AND wait_until <= NOW()
    LIMIT 100 (skip locked rows to avoid double-processing across pods)
  FOR EACH timed-out enrollment:
    Publish workflow.wait_timeout to workflow-resume topic
      payload: { enrollment_id, step_id, resume_reason='timeout' }
    UPDATE enrollment: status='active'  ← workflow-engine will complete the step

// goodwill_nudge handler
FUNCTION process_goodwill_nudges():
  Query scheduled_reminders WHERE reminder_type='goodwill_nudge'
    AND status='pending' AND remind_at <= NOW()
  FOR EACH due reminder:
    Publish scheduler.goodwill_nudge to customer-events topic
    UPDATE scheduled_reminders: status='published'

// followup_poll handler
FUNCTION process_followup_polls():
  Query scheduled_reminders WHERE reminder_type='followup_poll'
    AND status='pending' AND remind_at <= NOW()
  FOR EACH due entry:
    Publish follow-up event to actor-events topic
    UPDATE scheduled_reminders: status='published'
```

---

## 9. Service S7 — odoo-bridge

**`S7` — odoo-bridge**
*Writes RM activities to Odoo · calls Interakt Chat Assignment API · only service that writes back to Odoo*

```
// HANDLE RM ALERT (rm-alerts topic)
FUNCTION handle_rm_alert(message):
  alert ← deserialise RmAlertPayload from message

  Authenticate with Odoo REST API — get session UID

  IF alert_type == 'lead_replied':
    summary ← "WhatsApp reply: {first 60 chars of message_text or button_reply_id}"
    Create Odoo activity on inquiry {alert.inquiry_id}:
      assigned to RM {alert.rm_odoo_id}, activity_type='default'
      title=summary, note=full message text
    Call Interakt Chat Assignment API:
      Assign conversation for {alert.phone} to agent {alert.rm_email}

  ELSE IF alert_type == 'ambiguous_reply':
    summary ← "Ambiguous reply — {N} active workflows: {enrollment details}"
    Create Odoo activity on inquiry {alert.inquiry_id}:
      assigned to RM, title=summary

  ELSE IF alert_type IN ('permanent_failure', 'retry_exhausted'):
    summary ← "WhatsApp delivery failed: {alert.failure_reason}"
    Create Odoo activity on inquiry {alert.inquiry_id}:
      activity_type='wa_failed', title=summary

  Ack message

// INTERAKT CHAT ASSIGNMENT
FUNCTION assign_interakt_chat(phone, rm_email):
  IF rm_email is null:
    Skip — do not fail the alert
  POST to Interakt /v1/public/assignment/ API:
    { user_phone_number: "91{phone[-10:]}", agent_email: rm_email }
  Authenticate with INTERAKT_API_KEY from Secret Manager
```

---

## 10. Shared Library — shared/

All services import from the `shared/` package. It is installed at Docker build time via `pip install -e ./shared/`. It contains: `models.py` (all Pydantic schemas), `engine.py` (WorkflowEngine class), `pubsub.py` (publish helper), `sql.py` (connection pool), `interakt.py` (API client, used only by wa-sender), `odoo.py` (REST API client, used by workflow-engine and odoo-bridge), and `config_loader.py` (YAML loading and validation).

```
// Logical responsibilities of each module:

  models        — all event and payload schemas
                   (ActorEvent, WaSendPayload, WaFailedPayload, WaResumePayload, RmAlertPayload)
                   Validates field types and phone format on deserialisation

  engine        — WorkflowEngine class used by all workflow-engine variants
                   Loaded once at startup; stateless between messages

  pubsub        — publish(topic_alias, data) helper
                   Resolves logical alias → environment-specific topic name
                   e.g. "wa-send" → "cd-prod-wa-send"
                   Serialises payload as JSON bytes before publishing

  sql           — connection pool to Cloud SQL (PostgreSQL)
                   Returns a managed connection context; handles reconnects

  interakt      — HTTP API client for Interakt
                   Used exclusively by wa-sender
                   Handles template sends and non-template (RM) sends

  odoo          — Read-only REST API client for Odoo
                   Used by workflow-engine variants and odoo-bridge
                   Results are cached per inquiry_id for 5 minutes
                   Fetches: actor name, phone, property URL, locality, config, assigned RM

  config_loader — Loads and validates workflow YAML configs at startup
                   Maps topic aliases to fully-qualified Pub/Sub topic names
```

---

## 11. CI/CD Pipeline

GitHub Actions runs three pipelines: lint (on every push), test (on every push, runs unit tests with mocked GCP clients), and deploy (on merge to main, builds and pushes changed images, applies changed manifests).

```yaml
# .github/workflows/deploy.yml — changed-only deploy
name: Deploy
on:
  push:
    branches: [main]

env:
  REGISTRY: asia-south1-docker.pkg.dev/cleardeals-prod/wa
  GKE_CLUSTER: cleardeals-wa-prod
  GKE_REGION: asia-south1

jobs:
  detect-changes:
    runs-on: ubuntu-latest
    outputs:
      services: ${{ steps.detect.outputs.services }}
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 2 }
      - id: detect
        run: |
          CHANGED=$(git diff --name-only HEAD~1 HEAD | grep '^services/' | cut -d'/' -f2 | sort -u)
          # If shared/ changed, rebuild ALL services
          if git diff --name-only HEAD~1 HEAD | grep -q '^shared/'; then
            CHANGED='webhook_gateway workflow_engine wa_sender reply_router error_handler reminder_scheduler odoo_bridge'
          fi
          echo "services=$(echo $CHANGED | jq -R -s -c 'split(" ")[:-1]')" >> $GITHUB_OUTPUT

  build-push-deploy:
    needs: detect-changes
    if: needs.detect-changes.outputs.services != '[]'
    strategy:
      matrix:
        service: ${{ fromJson(needs.detect-changes.outputs.services) }}
    steps:
      - uses: actions/checkout@v4
      - name: Build and push
        run: |
          IMAGE=${{ env.REGISTRY }}/${{ matrix.service }}:${{ github.sha }}
          docker build -t $IMAGE -f services/${{ matrix.service }}/Dockerfile .
          docker push $IMAGE
      - name: Deploy
        run: |
          kubectl set image deployment/${{ matrix.service }} \
            ${{ matrix.service }}=${{ env.REGISTRY }}/${{ matrix.service }}:${{ github.sha }} \
            -n wa-automation
          kubectl rollout status deployment/${{ matrix.service }} -n wa-automation --timeout=120s
```

---

## 12. Kubernetes Manifests — Key Patterns

### 12.1 workflow-engine ConfigMap pattern

```yaml
# manifests/workflow-engine/configmap-nurturing.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: workflow-engine-nurturing-config
  namespace: wa-automation
data:
  WORKFLOW_CONFIG_PATH: /app/configs/nurturing.yaml
  PUBSUB_SUBSCRIPTION:  cd-prod-actor-events-nurturing-sub
  WORKFLOW_SLUG:        nurturing_v2
  ENVIRONMENT:          prod
---
# manifests/workflow-engine/deployment-nurturing.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: workflow-engine-nurturing
  namespace: wa-automation
spec:
  replicas: 1
  template:
    spec:
      serviceAccountName: wa-worker-sa   # Workload Identity — no key files
      containers:
        - name: workflow-engine
          image: asia-south1-docker.pkg.dev/cleardeals-prod/wa/workflow-engine:latest
          envFrom:
            - configMapRef:
                name: workflow-engine-nurturing-config
          env:
            - name: GCP_PROJECT_ID
              valueFrom:
                configMapKeyRef:
                  name: wa-shared-config
                  key: project_id
            - name: DB_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: wa-db-secret
                  key: password
          resources:
            requests: { cpu: '100m', memory: '256Mi' }
            limits:   { cpu: '500m', memory: '512Mi' }
          livenessProbe:
            exec:
              command: ['python','-c','import os; os.kill(1,0)']
            initialDelaySeconds: 10
            periodSeconds: 30
```

### 12.2 KEDA ScaledObject — autoscaling on Pub/Sub backlog

```yaml
# manifests/workflow-engine/keda-scaledobject-nurturing.yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: workflow-engine-nurturing-scaler
  namespace: wa-automation
spec:
  scaleTargetRef:
    name: workflow-engine-nurturing
  minReplicaCount: 1
  maxReplicaCount: 5
  triggers:
    - type: gcp-pubsub
      metadata:
        subscriptionName: cd-prod-actor-events-nurturing-sub
        mode: SubscriptionSize
        value: '20'          # 1 extra pod per 20 unprocessed messages
```

---

*ClearDeals WhatsApp Automation — Services Architecture Reference | 7 Services · 10 Topics | April 2026*

*Proptech Cleardeals Pvt. Ltd.*
