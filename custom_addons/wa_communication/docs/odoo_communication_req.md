# Odoo ↔ WA Platform Communication Architecture

> Single source of truth for how the WhatsApp Automation Platform and Odoo communicate.
> Every integration decision, data contract, and walkthrough lives here.
> Read this before writing any code in `odoo.py`, `odoo-bridge`, or any Odoo WA module.

**Last updated:** 2026-05-08  
**Status:** Design — not yet implemented  
**Owner:** Cleardeals Tech

---

## UI reference — WhatsApp Activity tab wireframe

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  Ankit Mehta                                          Lead > Details Shared > Req Closed │
│  99acres · 3 BHK Sola · ₹85L · Assigned to: Priya Sharma                           │
│  Overview  [WhatsApp Activity]  Site Visits  Notes  Activity Log                    │
├──────────────────┬──────────────────────────────────────────────┬───────────────────┤
│ ENROLLMENTS      │  13 Apr · Enrolled in Lead Nurturing          │ STATS             │
│                  │                                              │ 8 Sent  100% Dlvrd│
│ Lead Nurturing   │  ┌──────────────────────────────────────┐   │ 75% Read  2 Replies│
│ ringing_followup │  │ Hi! Aapne 99acres par Sola 3 BHK...  │   │                   │
│ [Active]         │  └───────────────────── ✓✓ Read · 16:02 ┘   │ ACTIONS           │
│                  │                                              │ 📧 Send Template  │
│ Visit            │  ┌──────────────────────────────────────┐   │                   │
│ Orchestration    │  │ Great choice! Is property ke liye... │   │ 👤 Assign         │
│ confirm_visit    │  │  [Plan Site Visit]  [See Similar]    │   │    Conversation   │
│ [Active]         │  └───────────────────── ✓✓ Read · 16:05 ┘   │                   │
│                  │                                              │ + Enrol in        │
│ Post-Visit       │  Plan Site Visit        LEAD · 17:12         │   Workflow        │
│ Feedback         │  Button tapped                              │                   │
│ [Pending]        │                                              │ ↓ Export Timeline │
│                  │  · Assigned to Priya Sharma by Sales Mgr ·  │                   │
│                  │  · 14 Apr · Enrolled in Visit Orchestration · │                   │
│                  │                                              │                   │
│                  │  ┌──────────────────────────────────────┐   │                   │
│                  │  │ Your site visit is confirmed! 📍...  │   │                   │
│                  │  └──────────────── ✓ Delivered 14 Apr ┘     │                   │
│                  │                                              │                   │
│                  │  Interested, when can I visit? LEAD 14 Apr   │                   │
│                  │                                              │                   │
│                  │  ┌──────────────────────────────────────┐   │                   │
│                  │  │ Type a reply to Ankit Mehta...   Send│   │                   │
│                  └──────────────────────────────────────────┘   │                   │
└──────────────────┴──────────────────────────────────────────────┴───────────────────┘
```

### What the wireframe establishes

| UI element | Implication for architecture |
|---|---|
| Free-text input + Send button | RMs can send **any message** — not just templates. Non-template sends go through WA platform → wa-sender → `send_non_template()` |
| "Send Template" action | Separate flow for template sends — opens a template picker. Routes the same way but uses `send_template()` |
| Enrollments sidebar | `wa_communication` module reads `workflow_enrollments` from the WA platform DB (via a read API) or maintains a local mirror |
| "Assign Conversation" action | Direct Interakt chat assignment — calls WA platform API or Pub/Sub event → odoo-bridge → `interakt.assign_chat()` |
| "Enrol in Workflow" action | Odoo publishes an enrollment request event → webhook-gateway routes to workflow-engine |
| "Export Timeline" action | Purely Odoo-side — serializes `wa.message` + `wa.conversation` records to CSV/PDF |
| Stats panel | Derived from `wa.message` records in Odoo — no WA platform API call needed |
| System event bubbles | Non-message events (enrollment, assignment) rendered as pill separators in the timeline |

---

## Quick navigation

- [1. Principles](#1-principles)
- [2. Architecture overview](#2-architecture-overview)
- [3. Actor resolution — REST GET (synchronous read)](#3-actor-resolution--rest-get-synchronous-read)
- [4. WA Platform → Odoo — Pub/Sub write path](#4-wa-platform--odoo--pubsub-write-path)
- [5. Odoo → WA Platform — RM-initiated sends](#5-odoo--wa-platform--rm-initiated-sends)
- [6. Odoo → WA Platform — RM-initiated workflow enrollment](#6-odoo--wa-platform--rm-initiated-workflow-enrollment)
- [7. Odoo → WA Platform — Assign Conversation action](#7-odoo--wa-platform--assign-conversation-action)
- [8. The `wa_communication` Odoo module](#8-the-wa_communication-odoo-module)
- [9. `odoo.py` implementation scope](#9-odoopy-implementation-scope)
- [10. Pub/Sub topic and subscription additions](#10-pubsub-topic-and-subscription-additions)
- [11. Detailed scenario walkthroughs](#11-detailed-scenario-walkthroughs)
- [12. Decision log — REST vs Pub/Sub per operation](#12-decision-log--rest-vs-pubsub-per-operation)
- [13. Actor types and data model mapping](#13-actor-types-and-data-model-mapping)
- [14. Breaking-change risk register](#14-breaking-change-risk-register)

---

## 1. Principles

These constraints shape every decision in this document.

### 1.1 Pub/Sub-first for all write operations

Any operation where the WA platform is writing state into Odoo (creating activities, logging WA
events, sending RM notifications) **uses Pub/Sub**. The WA platform publishes a self-contained
event. Odoo's `wa_communication` module subscribes and handles its own internal state changes.

**Why:**
- Odoo's internal models evolve continuously. If the WA platform calls Odoo REST to write
  activities directly, every Odoo schema change could break the WA platform.
- A Pub/Sub event has a stable, versioned schema. Odoo's subscriber is the adapter — only it
  changes when Odoo internals change.
- Eliminates all write-time coupling. The WA platform has no knowledge of `mail.activity`,
  `whatsapp.response`, or any Odoo ORM model.

### 1.2 No REST calls from the WA platform to Odoo — ever

The WA platform **never calls Odoo REST**. Actor context (name, RM details, property
fields) is embedded by Odoo in every event it publishes to Pub/Sub. workflow-engine reads
from the event payload and stores a snapshot in `enrollment.meta` — no synchronous HTTP
call is needed at any point in the pipeline.

**Why this is correct:**
- Actor data needed for template variables (name, property URL, RM name) is available
  in the trigger event because Odoo publishes it at the moment it knows the full state.
- For timer-triggered steps (wait_timeout from reminder-scheduler), the stored snapshot
  in `enrollment.meta.actor` is used — it reflects the state at last-event-update time,
  which is the correct freshness for a workflow that was enrolled based on that state.
- Eliminates the need for `ODOO_BASE_URL`, `ODOO_API_KEY`, an HTTP client, caching
  infrastructure, and a timeout/retry cycle on the hot path.
- If Odoo is unavailable, no WA platform service is blocked. Events queue in Pub/Sub.

### 1.3 No breaking changes to Odoo live data

- The WA platform NEVER writes directly to `leads.new`, `lead.score`, `property.base`, or
  `res.users` via REST.
- All Odoo-side writes go through the `wa_communication` module's subscriber, which can be
  safely deployed, rolled back, and changed without any WA platform release.
- API versioning (`/api/wa/v1/`) ensures old clients continue to work during Odoo upgrades.

### 1.4 Event payload self-sufficiency — both directions

**Odoo → WA platform:** Every event published by Odoo to `actor-events`, `visit-events`, or
`customer-events` must contain a fully resolved `actor` block in `payload.actor` — name, phone,
current status, RM details, and property details (nullable). The WA platform treats this as
the sole source of actor data. No follow-up reads.

**WA platform → Odoo:** Every Pub/Sub event published to `wa-odoo-events` must contain all
fields Odoo needs to process it — no callbacks, no follow-up reads, no session tokens.

### 1.5 Seller inquiry scope

**Seller inquiries are out of scope for this version.** They live in a separate Odoo instance
for the sales team, which is not yet built. This document covers only:
- `buyer_inquiry` → `leads.new` in the operations Odoo instance
- `customer` → new `customer.base` module in the operations Odoo instance

---

## 2. Architecture overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  WA PLATFORM (GKE, asia-south1)                                              │
│                                                                              │
│  workflow-engine ◄──── actor-events / visit-events / customer-events ──────  │
│       (S2)             Each event carries full actor context in payload.actor│
│                        Snapshot stored in enrollment.meta — no REST needed   │
│                                                                              │
│  odoo-bridge ──────── Pub/Sub publish ─────────────────────────────────►    │
│       (S7)            wa-odoo-events topic                                  │
│                       (activities, RM notifications, WA event log)          │
│               ◄─────  Pub/Sub subscribe ───────────────────────────────     │
│                        odoo-wa-requests topic                               │
│                        routes: send → wa-send | enroll → workflow-engine    │
│                                assign → assign_chat()                       │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                         ODOO (operations instance)
                         ┌─────────────────────────┐
                         │  wa_communication module │
                         │  - subscribes to         │
                         │    wa-odoo-events         │
                         │  - publishes to           │
                         │    odoo-wa-requests       │
                         │  - enriches all events    │
                         │    with payload.actor     │
                         │  - owns wa.conversation   │
                         │  - owns wa.message        │
                         │  - owns wa.rm_notification│
                         │  - extends leads.new form │
                         │    (WA Communication tab) │
                         └─────────────────────────┘
```

### Data flow summary

| Direction | Mechanism | Used for |
|---|---|---|
| Odoo → WA Platform (events) | Pub/Sub → `actor-events` / `visit-events` / `customer-events` | Trigger enrollment; actor context embedded in every event |
| WA Platform → Odoo (write) | Pub/Sub → `wa-odoo-events` | Activities, notifications, WA event log |
| Odoo → WA Platform (RM actions) | Pub/Sub → `odoo-wa-requests` | RM-initiated sends, enrollments, chat assignments — consumed by odoo-bridge (S7) |

**There is no REST call in either direction.**

---

## 3. Actor context — embedded in Odoo events, stored in enrollment.meta

### 3.1 The problem `get_actor()` was trying to solve

workflow-engine needs actor fields (buyer name, property URL, RM name, etc.) to build
template `body_values` at step execution time. The original design called Odoo REST to
fetch these at the moment each step ran.

**The better solution:** Odoo embeds the full actor context in every event it publishes.
workflow-engine stores the actor block in `enrollment.meta.actor` when processing the
trigger event. All subsequent steps — including timer-triggered ones — read from this
snapshot. No REST call is ever made.

### 3.2 The `payload.actor` block

Every event on `actor-events`, `visit-events`, and `customer-events` must include a
`payload.actor` block. This is built and serialized by Odoo's publishing module
(`crm_lead_events` or `wa_communication`) at publish time.

```json
{
  "event_type":   "actor.created",
  "actor_type":   "buyer_inquiry",
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
      "phone":          "919876543210",
      "current_status": "lead",
      "inquiry_type":   "primary",
      "rm": {
        "id":    12,
        "name":  "Priya Singh",
        "email": "priya@cleardeals.co.in",
        "phone": "9876500001"
      },
      "property": {
        "id":             123,
        "prop_id":        "GBH75X0K",
        "tag":            "B-505, Green Heights",
        "bhk":            "3 BHK",
        "location":       "Bopal",
        "city":           "Ahmedabad",
        "link":           "https://www.cleardeals.in/property/green-heights-GBH75X0K",
        "owner_name":     "Mr. Patel",
        "pricing_display": "48 Lakh",
        "is_active":      true
      }
    }
  },
  "published_at": "2026-04-13T10:32:00Z"
}
```

`property` is `null` when `leads.new.property_base_id` is not set (early-stage or
unmatched leads). This is valid — `actor.property_*` vars resolve to `""` in that case.

### 3.3 Actor type → Odoo model mapping (Odoo-side reference)

| `actor_type` | Odoo model | DB table | Notes |
|---|---|---|---|
| `buyer_inquiry` | `leads.new` | `leads_new` | Joined with `property.base` (nullable) and `res.users` |
| `customer` | `customer.base` | `customer_base` | New module — TBD when designed |
| `seller_inquiry` | *(not yet in scope)* | — | Separate Odoo instance |

### 3.4 How workflow-engine uses the actor block

```
// FUNCTION process(event) — step 4 (replaces REST call)

actor_snapshot ← event.payload.get("actor")   // dict or None

// Step 5 — store in enrollment.meta
enrollment.meta["actor"] ← actor_snapshot      // persisted to DB with the enrollment row

// FUNCTION resolve_vars(var_configs, event, meta)
//   actor.* dot-paths now resolve from meta["actor"] instead of a live REST response
FOR EACH var IN var_configs:
  IF source starts with "actor.":
    value ← traverse dot-path against meta["actor"]   // e.g. "actor.property.link"
    IF value is None: value ← ""
```

**For timer-triggered resumes** (`workflow.wait_timeout` from reminder-scheduler):
- The resume event carries only `enrollment_id` and `step_id` — no Odoo data.
- `actor.*` vars resolve from `enrollment.meta["actor"]` — the snapshot stored at
  enrollment time. This is the correct data: the workflow was enrolled based on that
  actor state, and timer steps are continuations of that same enrollment.

**Snapshot staleness:**
The snapshot reflects actor state at the time the trigger event was published. If the RM
is reassigned in Odoo after enrollment, the snapshot won't update until Odoo publishes a
new event for this actor (e.g. `actor.status_changed`). At that point, workflow-engine
updates `enrollment.meta["actor"]` with the fresh snapshot from the new event.
For most workflows this is the desired behaviour: communications in a campaign reflect
the RM and property that were current when the campaign started.

---

## 4. WA Platform → Odoo — Pub/Sub write path

### 4.1 Topic

**`wa-odoo-events`** — new topic, published to by `odoo-bridge (S7)`.

Odoo's `wa_communication` module runs a Pub/Sub subscriber (long-lived process or Cloud Run)
that pulls from this topic and handles all internal Odoo state changes.

### 4.2 Event schema — `OdooWaEvent`

New Pydantic model added to `shared/shared/models.py`.

```python
class OdooWaEventType(str, Enum):
    lead_replied      = "lead_replied"
    ambiguous_reply   = "ambiguous_reply"
    permanent_failure = "permanent_failure"
    retry_exhausted   = "retry_exhausted"
    message_delivered = "message_delivered"
    message_read      = "message_read"
    message_sent      = "message_sent"

class OdooWaEvent(BaseModel):
    event_type:       OdooWaEventType
    actor_type:       str                 # "buyer_inquiry" | "customer"
    actor_id:         int                 # Odoo record ID (leads.new.id etc.)
    rm_odoo_id:       int                 # res.users.id of the assigned RM
    phone:            str                 # E.164 without + (e.g. 919876543210)
    request_id:       str | None          # WaSendPayload.request_id — for bus.bus scoping
    interakt_msg_id:  str | None          # from outbound_messages.interakt_msg_id
    message_text:     str | None          # inbound reply text (truncated to 500 chars)
    button_reply_id:  str | None          # button ID if reply was a button tap
    failure_code:     int | None          # Interakt error code
    failure_reason:   str | None          # human-readable failure summary
    occurred_at:      datetime            # UTC timestamp of the event
```

### 4.3 What Odoo's subscriber does per event_type

| `event_type` | Activity created? | bus.bus notification? | `wa.message` record? | `wa.conversation` updated? |
|---|---|---|---|---|
| `lead_replied` | Yes — on `leads.new`, assigned to RM | Yes — pop-up in RM's Odoo tab | Yes (inbound) | Yes |
| `ambiguous_reply` | Yes — "Review required: ambiguous reply" | Yes | Yes (inbound) | Yes |
| `permanent_failure` | Yes — "WA delivery failed: {reason}" | Yes | No | Yes (status=failed) |
| `retry_exhausted` | Yes — "WA retries exhausted: {reason}" | Yes | No | Yes (status=failed) |
| `message_delivered` | No | No | Update existing (status=delivered) | Yes |
| `message_read` | No | No | Update existing (status=read) | Yes |
| `message_sent` | No | No | Yes (outbound, status=sent) | Yes |

### 4.4 bus.bus notification payload (handled by Odoo internally)

When Odoo's subscriber receives a `lead_replied` or `ambiguous_reply` event, it pushes a
`bus.bus` notification on channel `wa_notification_{rm_odoo_id}`. This is entirely within
Odoo — the WA platform has no knowledge of it.

```python
# Odoo-side (NOT in odoo.py)
self.env['bus.bus']._sendone(
    f"wa_notification_{rm_odoo_id}",
    "wa_event",
    {
        "type": event.event_type,
        "actor_id": event.actor_id,
        "message": event.message_text[:60] if event.message_text else "",
        "lead_url": f"/web#model=leads.new&id={event.actor_id}",
    }
)
```

**Channel naming:** `wa_notification_{rm_odoo_id}` (integer RM user ID). The Odoo frontend
JavaScript in `wa_communication` subscribes to this channel on login.

---

## 5. Odoo → WA Platform — RM-initiated sends

### 5.1 Send paths from the Odoo UI

The WA Activity tab supports three distinct send mechanisms:

| UI element | Message type | `kind` value | Interakt API call |
|---|---|---|---|
| "Send Template" action (right sidebar) | Predefined approved template | `template` | `send_template()` |
| Free-text box + Send button | Plain-text non-template message | `freetext` | `send_non_template()` |
| Attach + Send — image (JPG/PNG/WebP) | Image message | `image` | `send_non_template()` |
| Attach + Send — PDF or Office doc | Document message (shows filename) | `document` | `send_non_template()` |
| Attach + Send — MP4/3GP video | Video message | `video` | `send_non_template()` |
| Attach + Send — audio/voice note | Audio message | `audio` | `send_non_template()` |

All paths go through the WA platform. Odoo never calls Interakt directly.

**Important constraint on non-template messages:** WhatsApp only permits non-template
messages within a 24-hour customer service window — the buyer must have messaged first
within the last 24 hours. This is enforced by Interakt and the WA platform, not by Odoo.
If the window is closed, Interakt will reject the send with an error code, which flows
back to Odoo as a `permanent_failure` event.

### 5.2 Topic

**`odoo-wa-requests`** — published by Odoo's `wa_communication` module, consumed by
`odoo-bridge (S7)`.

**Why odoo-bridge and not webhook-gateway:** `webhook-gateway (S1)` is the Interakt webhook
receiver — its sole job is to accept inbound HTTP webhooks from Interakt and publish them
to internal topics. Routing Odoo Pub/Sub events through it would mix two unrelated
concerns. `odoo-bridge (S7)` already owns all Odoo ↔ WA platform communication — it
publishes `wa-odoo-events` outbound and now also subscribes to `odoo-wa-requests` inbound.
All three request types (`send`, `enroll`, `assign`) are dispatched internally from one
place.

### 5.3 Event schema — unified `OdooWaRequest`

A **single** Pydantic model in `shared/shared/models.py` covers all three RM-initiated
action types. `request_type` is the first field and is always present — `odoo-bridge`
reads it before any other field to determine routing. All remaining fields are `None`
by default; a `ValidationError` on any malformed payload routes the message to the DLQ.

```python
class OdooWaRequestType(str, Enum):
    send   = "send"    # all message kinds: template, freetext, image, document, video, audio
    enroll = "enroll"  # manual workflow enrollment via “Enrol in Workflow”
    assign = "assign"  # Interakt conversation assignment via “Assign Conversation”

class OdooWaMessageKind(str, Enum):
    template = "template"  # predefined approved template
    freetext = "freetext"  # plain-text reply
    image    = "image"     # image attachment (JPG / PNG / WebP)
    document = "document"  # PDF or Office document (shows filename)
    video    = "video"     # video attachment (MP4 / 3GP)
    audio    = "audio"     # audio / voice note

_MEDIA_KINDS = {OdooWaMessageKind.image, OdooWaMessageKind.document,
                OdooWaMessageKind.video, OdooWaMessageKind.audio}

class OdooWaRequest(BaseModel):
    # ── mandatory on ALL request types ────────────────────────────────────────
    request_type: OdooWaRequestType  # REQUIRED — read first; never absent
    request_id:   str                # UUID; idempotency key across all types
    phone:        str                # E.164 without + (e.g. 919876543210)
    # ── send + enroll ─────────────────────────────────────────────────
    actor_type:   str | None = None  # "buyer_inquiry" | "customer"
    actor_id:     int | None = None  # Odoo record ID
    rm_odoo_id:   int | None = None  # res.users.id — for send-status callbacks
    rm_name:      str | None = None  # display name for activity records
    # ── send only: message kind ───────────────────────────────────────────
    kind:         OdooWaMessageKind | None = None  # required when request_type=send
    # ── send, kind=template ───────────────────────────────────────────
    template_name:  str | None = None
    body_values:    list[str] = []
    header_values:  list[str] = []
    button_values:  dict[str, list[str]] | None = None
    # ── send, kind=freetext ───────────────────────────────────────────
    message_text:   str | None = None  # required when kind=freetext
    # ── send, kind in {image, document, video, audio} ───────────────────────
    media_url:      str | None = None  # required when kind in _MEDIA_KINDS
    media_filename: str | None = None  # optional — shown as filename for document kind
    # ── enroll only ─────────────────────────────────────────────────
    workflow_slug:  str | None = None  # required when request_type=enroll
    meta:           dict[str, Any] = {}  # extra fields for enrollment.meta
    # ── assign only ─────────────────────────────────────────────────
    rm_email:       str | None = None  # required when request_type=assign; Interakt agent
```

**Why one model instead of three:** Pub/Sub is not a typed message bus — the deserialiser
runs before routing. With three separate classes on the same topic, the consumer must
inspect field presence (`workflow_slug`? `rm_email`? `kind`?) to decide which class to
instantiate — a heuristic that silently misroutes on a bug. With `request_type` as the
first mandatory field, the consumer reads one field, branches, then validates the
remaining fields against the expected shape. `ValidationError` is explicit and sends
the message to the DLQ.

### 5.4 Routing in odoo-bridge (S7)

`odoo-bridge` subscribes to `odoo-wa-requests`. On receipt:
1. Deserialises the raw JSON into `OdooWaRequest`. Reads `request_type` first.
2. On `ValidationError` for any field — ack and route to DLQ. Never silently drop.
3. Dispatches based on `request_type`:

**`request_type = send`:**

```
Reads kind field.

kind = template:
  constructs WaSendPayload:
    template_name  = request.template_name
    body_values    = request.body_values
    header_values  = request.header_values
    button_values  = request.button_values
    callback_data  = f"manual:{request.request_id}"
    sent_by_rm_id  = request.rm_odoo_id
    sent_by_rm_name = request.rm_name
  publishes to wa-send topic

kind = freetext:
  constructs WaSendPayload:
    message_kind   = MessageKind.text
    message_text   = request.message_text
    template_name  = ""   (sentinel)
    callback_data  = f"manual:{request.request_id}"
    sent_by_rm_id  = request.rm_odoo_id
    sent_by_rm_name = request.rm_name
  publishes to wa-send topic

kind in {image, document, video, audio}:
  constructs WaSendPayload:
    message_kind   = MessageKind(request.kind)   # enum values are identical strings
    media_url      = request.media_url
    media_filename = request.media_filename       # only meaningful for kind=document
    template_name  = ""   (sentinel)
    callback_data  = f"manual:{request.request_id}"
    sent_by_rm_id  = request.rm_odoo_id
    sent_by_rm_name = request.rm_name
  publishes to wa-send topic
```

**`request_type = enroll`:**

```
odoo-bridge publishes a synthetic enrollment trigger to workflow-engine's subscription
  (same internal path as any actor-events enrollment trigger).
workflow-engine uses request_id as idempotency key.
  duplicate (same request_id already processed) → ack and skip.
  otherwise → create workflow_enrollments row and begin execution.
```

**`request_type = assign`:**

```
odoo-bridge calls interakt.assign_chat(phone=request.phone, rm_email=request.rm_email).
Fire-and-forget — result not communicated back to Odoo at this stage.
```

4. `wa-sender (S3)` receives `WaSendPayload` from `wa-send` (for `send` requests only):
   - `message_kind == MessageKind.template` → calls `send_template()`
   - `message_kind == MessageKind.text` → calls `send_non_template(message_kind="text", message_text=...)`
   - `message_kind in {image, document, video, audio}` → calls `send_non_template(message_kind=..., media_url=..., media_filename=...)`

5. The normal `wa-sender → Interakt → status updates → odoo-bridge → wa-odoo-events` pipeline
   handles delivery. Odoo's subscriber receives `message_sent` / `message_delivered` / `message_read`
   events back, updating the RM's conversation view in real time with read-receipt ticks.

### 5.5 WaSendPayload changes required

The `WaSendPayload` model already has `message_kind`, `message_text`, `sent_by_rm_id`, and
`sent_by_rm_name` fields. Two new optional fields must be added to carry media through the
`wa-send` topic:

```python
# add to WaSendPayload in shared/shared/models.py
media_url:      str | None = None  # populated for image / document / video / audio sends
media_filename: str | None = None  # populated for document sends — shown as download filename
```

These are consumed by `wa-sender (S3)` when calling `send_non_template()`. They are `None`
for template and freetext sends — `send_non_template()` ignores them in those cases.
**TDD required**: add tests to `test_models.py` (defaults, round-trip serialisation) before
writing the implementation, then run `hatch run test`.

---

## 6. Odoo → WA Platform — RM-initiated workflow enrollment

### 6.1 Use case

The "Enrol in Workflow" action in the right sidebar. The RM picks a workflow from a list
and manually enrolls the current lead. This bypasses the automatic enrollment trigger
(which normally fires on `actor.created` or `actor.status_changed`).

### 6.2 Fields on the unified `OdooWaRequest` model

Set `request_type = "enroll"` and populate the enroll-specific fields:

```python
# Fields required for request_type=enroll (in addition to the mandatory three)
request_type:  OdooWaRequestType = OdooWaRequestType.enroll  # always "enroll"
request_id:    str    # UUID — idempotency key (duplicate taps produce same UUID)
phone:         str    # E.164 without + (e.g. 919876543210)
actor_type:    str    # "buyer_inquiry" | "customer"
actor_id:      int    # Odoo record ID
rm_odoo_id:    int    # res.users.id of the RM who triggered this
rm_name:       str    # display name
workflow_slug: str    # which workflow to enroll in  ← REQUIRED for enroll
meta:          dict[str, Any] = {}  # extra fields for enrollment.meta
# All other OdooWaRequest fields remain None
```

### 6.3 Routing

- Odoo publishes `OdooWaRequest(request_type="enroll", ...)` to `odoo-wa-requests`.
- `odoo-bridge (S7)` receives, reads `request_type="enroll"`, dispatches to
  workflow-engine's enrollment path.
- `workflow-engine` deduplicates on `request_id`.
  If duplicate → ack and skip. Otherwise → create `workflow_enrollments` row and start.

---

## 7. Odoo → WA Platform — Assign Conversation action

### 7.1 Use case

The "Assign Conversation" action button. The RM explicitly reassigns the Interakt conversation
for this buyer to themselves (or another agent).

### 7.2 Options considered

| Option | Notes |
|---|---|
| Odoo calls Interakt directly | Odoo would need `INTERAKT_API_KEY` — violates the principle that only wa-sender holds that key |
| Odoo publishes Pub/Sub event → odoo-bridge → `assign_chat()` | Clean; odoo-bridge already calls `assign_chat()` for `lead_replied` events |
| Odoo calls a WA platform REST endpoint | Adds REST coupling — avoided unless Pub/Sub is not viable |

**Decision: Pub/Sub.** Odoo publishes `OdooWaRequest(request_type="assign", ...)` to `odoo-wa-requests`.
`odoo-bridge (S7)` receives and calls `interakt.assign_chat()` directly.

### 7.3 Fields on the unified `OdooWaRequest` model

Set `request_type = "assign"` and populate the assign-specific fields:

```python
# Fields required for request_type=assign (in addition to the mandatory three)
request_type: OdooWaRequestType = OdooWaRequestType.assign  # always "assign"
request_id:   str  # UUID
phone:        str  # E.164 without + (e.g. 919876543210)
rm_email:     str  # target Interakt agent email  ← REQUIRED for assign
rm_odoo_id:   int  # res.users.id — for audit trail
# All other OdooWaRequest fields remain None
```

### 7.4 Routing

- Odoo publishes `OdooWaRequest(request_type="assign", ...)` to `odoo-wa-requests`.
- `odoo-bridge (S7)` receives, reads `request_type="assign"`, calls
  `interakt.assign_chat(phone=request.phone, rm_email=request.rm_email)` directly.
- Fire-and-forget — result not communicated back to Odoo at this stage.

---

## 8. The `wa_communication` Odoo module

> This section is the design spec for the Odoo-side module. It is implemented in Odoo, not
> in this repository. It is documented here so the WA platform and Odoo module are designed
> together from the start.

### 8.1 Module identity

| Property | Value |
|---|---|
| Technical name | `wa_communication` |
| Dependencies | `leads`, `properties`, `mail` |
| Odoo version | 19.0 |

### 8.2 Models

#### `wa.conversation`

One record per (actor, phone) pair. Tracks the live WA conversation state for this lead.

| Field | Type | Description |
|---|---|---|
| `lead_id` | `Many2one → leads.new` | Parent lead (null for customer type initially) |
| `actor_type` | `Char` | `buyer_inquiry` or `customer` |
| `actor_id` | `Integer` | Odoo record ID of the actor |
| `phone` | `Char` | E.164 without + (e.g. 919876543210) |
| `status` | `Selection` | `active` / `waiting` / `completed` / `failed` |
| `last_inbound_at` | `Datetime` | Last message received from the buyer |
| `last_outbound_at` | `Datetime` | Last message sent to the buyer |
| `message_ids` | `One2many → wa.message` | All messages in this conversation |
| `enrollment_ids` | `One2many → wa.enrollment_mirror` | Mirror of active WA platform enrollments for display |

#### `wa.message`

Individual WA message record — inbound (buyer replies), outbound-template, outbound-freetext,
and system events (enrollment, assignment). All message types appear in the timeline.

| Field | Type | Description |
|---|---|---|
| `conversation_id` | `Many2one → wa.conversation` | Parent conversation |
| `direction` | `Selection` | `inbound` / `outbound` / `system_event` |
| `message_kind` | `Selection` | `template` / `freetext` / `button_reply` / `system` |
| `message_text` | `Text` | Message content (null for system events) |
| `button_reply_id` | `Char` | Button ID if reply was a button tap |
| `template_name` | `Char` | Template name for outbound template messages |
| `interakt_msg_id` | `Char` | Interakt's message ID (for status tracking) |
| `status` | `Selection` | `queued` / `sent` / `delivered` / `read` / `failed` |
| `occurred_at` | `Datetime` | UTC time of the event |
| `request_id` | `Char` | `OdooWaRequest.request_id` or `WaSendPayload.request_id` for correlation |
| `sent_by_rm_id` | `Many2one → res.users` | Set for RM-initiated sends; null for automated sends |
| `system_event_label` | `Char` | Text for system event pill (e.g. "Enrolled in Lead Nurturing") |

**Rendering rules for the timeline:**
- `direction=outbound` → dark blue bubble, right-aligned. Show delivery ticks (sent=✓, delivered=✓✓, read=✓✓ blue).
- `direction=inbound` → white bubble, left-aligned. Show timestamp + "LEAD" label.
- `direction=system_event` → centred pill with light background (e.g. "13 Apr · Enrolled in Lead Nurturing").
- Stats panel derives values from `wa.message` records on the open `wa.conversation`.

#### `wa.enrollment_mirror`

A lightweight mirror of `workflow_enrollments` rows for display in the Enrollments sidebar.
Populated by `OdooWaEvent` events from the WA platform — not by a direct DB read.

| Field | Type | Description |
|---|---|---|
| `conversation_id` | `Many2one → wa.conversation` | Parent conversation |
| `enrollment_id` | `Char` | UUID from `workflow_enrollments.id` |
| `workflow_slug` | `Char` | e.g. `lead_nurturing_v2` |
| `workflow_display_name` | `Char` | Human label e.g. "Lead Nurturing" |
| `current_step_id` | `Char` | ID of the step the enrollment is currently on |
| `current_step_display` | `Char` | Human label e.g. "ringing_followup" |
| `status` | `Selection` | `active` / `waiting` / `paused` / `completed` / `failed` / `pending` |
| `enrolled_at` | `Datetime` | |

#### `wa.rm_notification`

Records every RM notification dispatched via bus.bus. Provides an audit trail.

| Field | Type | Description |
|---|---|---|
| `rm_id` | `Many2one → res.users` | Target RM |
| `event_type` | `Char` | `lead_replied` / `permanent_failure` / etc. |
| `actor_id` | `Integer` | Actor that triggered the event |
| `payload_json` | `Text` | Full event JSON for debugging |
| `notified_at` | `Datetime` | When the bus.bus push was made |

### 8.3 Extended leads.new form view — "WhatsApp Activity" tab

A new tab "WhatsApp Activity" added to the `leads.new` form view (via `_inherit`).

**Three-column layout (as per wireframe):**

**Left — Enrollments sidebar:**
- Lists all `wa.enrollment_mirror` records for the current conversation
- Each card shows: workflow display name, current step label, status badge (Active/Pending/Completed)
- Clicking a card could deep-link to a workflow detail view (future)

**Centre — Conversation timeline:**
- Renders all `wa.message` records in chronological order (oldest at top, newest at bottom)
- Outbound template: dark blue bubble, right. Shows template name subtly above bubble.
- Outbound freetext: dark blue bubble, right. No template label.
- Inbound reply: white bubble, left. Shows "LEAD · HH:MM" timestamp label.
- Inbound button tap: white bubble, left. Shows button label + "Button tapped" subtext.
- System event: centred pill (enrollment, assignment changes)
- Delivery ticks on outbound messages: ✓ sent, ✓✓ grey=delivered, ✓✓ blue=read
- Free-text input at bottom: any text → `OdooWaRequest(kind='freetext', ...)`

**Right — Stats and Actions:**

Stats (read from `wa.message` aggregate on this conversation):
- Messages Sent (count of outbound)
- Delivered % (delivered+read / sent)
- Read % (read / sent)
- Replies (count of inbound)

Actions:
1. **Send Template** → opens a template picker wizard. Populates `OdooWaRequest(kind='template', ...)`
2. **Assign Conversation** → confirms RM email, publishes `OdooWaRequest(request_type="assign", ...)`
3. **Enrol in Workflow** → workflow picker wizard, publishes `OdooWaRequest(request_type="enroll", ...)`
4. **Export Timeline** → generates PDF/CSV of `wa.message` + `wa.enrollment_mirror` records

### 8.4 Real-time updates (bus.bus)

- Odoo's `wa_communication` subscriber pushes `bus.bus` on channel `wa_notification_{rm_odoo_id}`
  whenever a new `OdooWaEvent` is processed.
- The page's JavaScript client subscribes to this channel on load.
- On event receipt, the conversation widget refreshes to show the new message or status update.
- The RM sees delivery ticks change from ✓ → ✓✓ → ✓✓ blue in real time without a page reload.

### 8.5 Pub/Sub subscriber in Odoo

The `wa_communication` module includes a long-running subscriber process (launched via
`wa_communication.subscribe_wa_events` RPC or a systemd unit alongside Odoo) that:

1. Pulls messages from `cd-{env}-wa-odoo-events-sub`.
2. Deserializes `OdooWaEvent` JSON.
3. In a single `with self.env.cr:` transaction:
   - Creates/updates `wa.conversation`
   - Creates/updates `wa.message`
   - Creates `mail.activity` on `leads.new` if applicable
   - Pushes `bus.bus` notification if applicable
   - Creates `wa.rm_notification` audit record
4. Acks message.

**Error handling in the subscriber:**
- `OdooWaEvent` validation errors → DLQ (ack + log) — bad events must not block the subscriber.
- Database errors → nack — Pub/Sub redelivers; transient DB issues will self-heal.

---

## 9. `odoo.py` — module is not needed

With the event-embedding design, `odoo.py` has no functions to implement:

- `get_actor()` — **eliminated** (actor data comes in the event payload)
- `write_activity()` — **never existed** (handled by Pub/Sub → `wa-odoo-events`)
- `push_bus_notification()` — **never existed** (handled by Odoo's own subscriber)

The `shared/shared/odoo.py` stub can be removed, or kept as a placeholder with just a
module docstring explaining this decision. No HTTP client, no env vars, no caching,
no TDD cycle needed.

```python
# shared/shared/odoo.py
"""
odoo.py — Odoo integration module.

There are no direct calls from the WA platform to Odoo REST.
Actor context arrives embedded in Pub/Sub events (payload.actor).
All write-backs go through the wa-odoo-events Pub/Sub topic.
See docs/ODOO_COMMUNICATION.md for full design.
"""
```

**The write path remains:**
```
odoo-bridge (S7)  →  pubsub.publish("wa-odoo-events", OdooWaEvent(...))
                                          ↓
                          Odoo's wa_communication subscriber
                          (handles all internal Odoo state changes)
```

**No `ODOO_BASE_URL` or `ODOO_API_KEY` env vars are required on any WA platform service.**

---

## 10. Pub/Sub topic and subscription additions

The following must be added to the infrastructure configuration:

| Alias | Topic name (prod) | Publisher | Subscriber(s) |
|---|---|---|---|
| `wa-odoo-events` | `cd-prod-wa-odoo-events` | odoo-bridge (S7) | Odoo `wa_communication` module |
| `odoo-wa-requests` | `cd-prod-odoo-wa-requests` | Odoo `wa_communication` module | odoo-bridge (S7) |

### KNOWN_ALIASES additions

```python
# shared/shared/pubsub.py
KNOWN_ALIASES: frozenset[str] = frozenset({
    # ... existing aliases ...
    "wa-odoo-events",
    "odoo-wa-requests",
})
```

### Subscription naming

| Subscription | Subscribing service | Purpose |
|---|---|---|
| `cd-{env}-wa-odoo-events-sub` | Odoo `wa_communication` | Odoo receives WA platform events |
| `cd-{env}-odoo-wa-requests-sub` | odoo-bridge (S7) | Receives all RM-initiated requests (send / enroll / assign) |

---

## 11. Detailed scenario walkthroughs

### Scenario A — Standard workflow: buyer taps button, RM sees reply in real time

```
1. Buyer "Ankit Mehta" (leads.new id=4521) receives a WA template message.
   Template has a "Plan Site Visit" button.
   The enrollment was created when Odoo published actor.created with payload.actor
   containing Ankit's name, RM (Priya Singh, id=12), and property (B-505, Green Heights).
   All of this was stored in enrollment.meta.actor at enrollment time.

2. Ankit taps "Plan Site Visit".
   → Interakt sends an inbound webhook to webhook-gateway (S1).

3. webhook-gateway publishes to wa-inbound topic.

4. reply-router (S4) receives the inbound event.
   → Parses callback_data: "nurturing_v2:branch_after_details:enroll-uuid-xyz"
   → Looks up enrollment by UUID → found, status=waiting
   → Publishes WaResumePayload to workflow-resume topic
   → Writes inbound_messages row

5. workflow-engine (S2) receives WaResumePayload.
   → Resolves next step (branch_after_details) → branch_condition_A matched
   → Reads actor snapshot from enrollment.meta["actor"]  ← no REST call
      actor = { "name": "Ankit Mehta", "property": { "link": "...", "tag": "B-505..." }, ... }
   → Resolves next step (assign_rm_site_visit)
   → Publishes WaSendPayload for the confirmation template

6. wa-sender (S3) sends the confirmation message via Interakt.
   → Publishes WaSendPayload to wa-send
   → Interakt delivers → callback: message_delivered

7. odoo-bridge (S7) receives RmAlertPayload (alert_type='lead_replied') from rm-alerts.
   → Constructs OdooWaEvent:
       event_type = "lead_replied"
       actor_type = "buyer_inquiry"
       actor_id   = 4521
       rm_odoo_id = 12      ← from RmAlertPayload
       phone      = "919876543210"
       request_id = "req-uuid-abc"
       message_text = "Plan Site Visit"
       button_reply_id = "plan_site_visit"
       occurred_at = <now UTC>
   → pubsub.publish("wa-odoo-events", OdooWaEvent(...))

8. Odoo's wa_communication subscriber receives the event.
   → Finds wa.conversation for (lead_id=4521, phone=919876543210) — creates if not exists
   → Creates wa.message (inbound, "Plan Site Visit", occurred_at=...)
   → Creates mail.activity on leads.new id=4521:
       type = "wa_replied"
       assigned to res.users id=12 (Priya)
       title = "WhatsApp reply: Plan Site Visit"
   → Pushes bus.bus notification on "wa_notification_12"
       → Priya's Odoo browser tab shows popup: "New WA reply from Rahul Sharma"
   → Creates wa.rm_notification audit row

9. odoo-bridge also calls interakt.assign_chat(phone, rm_email="priya@cleardeals.co.in")
   → Interakt assigns the conversation to Priya's agent account.

Result: Priya sees the reply in both her Interakt and Odoo interfaces simultaneously.
```

---

### Scenario B — RM sends a free-text reply from the Odoo chat window

```
1. Priya is on Ankit Mehta's lead (id=4521). The buyer sent "Interested, when can I visit?"
   — this already appeared in the WA Activity tab as a white inbound bubble.

2. Priya types "Hi Ankit! Let's schedule for 15 Apr at 11 AM — does that work?" in the
   text box at the bottom and clicks Send.

3. Odoo publishes OdooWaRequest to odoo-wa-requests:
     {
       request_type: "send",
       request_id:   "req-rm-manual-xyz",
       kind:         "freetext",
       actor_type:   "buyer_inquiry",
       actor_id:     4521,
       phone:        "919876543210",
       rm_odoo_id:   12,
       rm_name:      "Priya Singh",
       message_text: "Hi Ankit! Let's schedule for 15 Apr at 11 AM — does that work?"
     }
   → Creates a wa.message (status="queued") — shows in timeline immediately with a spinner.

4. odoo-bridge receives the event.
   → Reads request_type="send", kind="freetext".
   → Constructs WaSendPayload:
       message_kind  = MessageKind.text
       message_text  = "Hi Ankit! Let's schedule..."
       template_name = ""     (sentinel — unused)
       callback_data = "manual:req-rm-manual-xyz"
       sent_by_rm_id = 12
   → Publishes to wa-send topic.

5. wa-sender (S3) receives the WaSendPayload.
   → Runs pre-send checks (opt-out, meta-blocked, etc.).
   → message_kind == MessageKind.text → calls send_non_template(phone, message_text).
   → Interakt validates: buyer messaged within 24h ✓ (he sent "Interested..." 12 min ago).
   → Interakt delivers the message. Returns interakt_msg_id.
   → UPDATE outbound_messages: status='sent', interakt_msg_id=...

6. Interakt delivers → fires message_api_delivered webhook.
   → wa-sender processes → publishes RmAlertPayload (alert_type='rm_send_status',
     status='delivered', request_id='req-rm-manual-xyz') to rm-alerts.

7. odoo-bridge receives the rm_send_status alert.
   → Constructs OdooWaEvent (event_type='message_delivered', request_id='req-rm-manual-xyz').
   → pubsub.publish("wa-odoo-events", ...).

8. Odoo's subscriber:
   → Finds wa.message where request_id='req-rm-manual-xyz'
   → Updates status: queued → sent → delivered
   → Pushes bus.bus on "wa_notification_12"

9. Priya's browser receives the bus.bus event.
   → The spinner on her message disappears. Two grey ticks appear: ✓✓ delivered.
   → When Ankit reads it, a third OdooWaEvent (message_read) updates the ticks to blue: ✓✓

Result: Priya has a seamless WhatsApp chat experience from within Odoo.
```

---

### Scenario C — Property not yet linked (property_base_id is null)

```
1. A fresh portal lead "Amit Patel" (leads.new id=6789) just landed via a Housing.com
   webhook. The assignment cron has not yet run — property_base_id is null.

2. Odoo publishes actor.created. The payload.actor block reflects the current state:
     { "name": "Amit Patel", "property": null, "rm": { "name": "Rohan Mehta", ... } }

3. workflow-engine receives the event. Step 1 is send_message with vars:
     - position 1: actor.name          → "Amit Patel"
     - position 2: actor.property_url  → actor.property.link

4. enrollment.meta["actor"]["property"] is null.
   engine.py resolves vars:
   → position 1: actor.name → "Amit Patel" ✓
   → position 2: actor.property.link → property is null → resolves to "" (empty string)

5. The template is sent with body_values = ["Amit Patel", ""].
   → The step does not fail. The workflow config's failure_action controls behaviour
     if an empty property URL is unacceptable.

6. When the assignment cron links the property, Odoo publishes actor.status_changed
   (or a dedicated actor.property_linked event). workflow-engine receives it, updates
   enrollment.meta["actor"] with the fresh snapshot including the linked property.
   The next send_message step in this enrollment will see the property URL.
```

---

### Scenario D — Permanent delivery failure → RM notification

```
1. WA message to buyer "Sunita Joshi" (id=3311) fails with Interakt error 131026
   (meta_blocked — this number is blocked from receiving WA).

2. wa-sender (S3) receives the failure webhook.
   → Updates outbound_messages: status='meta_blocked'
   → Publishes WaFailedPayload to wa-failed topic.

3. error-handler (S5) classifies as permanent (131026 in PERMANENT_CODES).
   → Inserts dead_letter_queue row
   → Updates workflow_enrollments: status='failed'
   → Publishes RmAlertPayload (alert_type='permanent_failure') to rm-alerts.

4. odoo-bridge (S7) receives the RmAlertPayload.
   → Constructs OdooWaEvent:
       event_type     = "permanent_failure"
       actor_id       = 3311
       rm_odoo_id     = 9
       failure_code   = 131026
       failure_reason = "Meta has blocked this number from receiving WA messages"
       occurred_at    = <now UTC>
   → pubsub.publish("wa-odoo-events", OdooWaEvent(...))

5. Odoo's subscriber receives the event.
   → Updates wa.conversation status → "failed"
   → Creates mail.activity on leads.new id=3311:
       type = "wa_failed"
       title = "WhatsApp delivery failed: Meta blocked (131026)"
   → Pushes bus.bus notification to RM 9
   → Creates wa.rm_notification row

Result: The RM sees a prominent activity on the lead and a real-time popup.
They can switch to a phone call without the failure going unnoticed.
```

---

### Scenario E — RM sends a template message from Odoo ("Send Template" action)

```
1. Priya is on Ankit's lead. She clicks "Send Template" in the right sidebar.

2. A wizard opens with a dropdown of approved templates.
   She picks "property_followup_v1".
   The wizard pre-fills var fields from the lead's actor data.
   She overrides one field: custom note.

3. She clicks Send in the wizard.
   → Odoo publishes OdooWaRequest to odoo-wa-requests:
     {
       request_type:  "send",
       request_id:    "req-odoo-tmpl-uuid-abc",
       kind:          "template",
       actor_type:    "buyer_inquiry",
       actor_id:      4521,
       phone:         "919876543210",
       rm_odoo_id:    12,
       rm_name:       "Priya Singh",
       template_name: "property_followup_v1",
       body_values:   ["https://cleardeals.in/property/..."],
       header_values: [],
       button_values: null
     }
   → Creates a pending wa.message row (status="queued").

4. odoo-bridge receives, reads request_type="send", kind="template".
   Constructs WaSendPayload, publishes to wa-send. wa-sender calls send_template().
   Delivery ticks flow back exactly as in Scenario B (freetext path).
   The distinction is invisible to Priya — both kinds show the same tick progression.
```

---

### Scenario F — RM manually enrolls a lead in a workflow

```
1. Priya is on a lead that was created manually (not via a portal webhook).
   It was never automatically enrolled in the "lead_nurturing_v2" workflow.
   She decides to enroll it manually.

2. She clicks "Enrol in Workflow" in the right sidebar.
   → A wizard opens with a list of active workflows.
   → She picks "Lead Nurturing v2" from the list.

3. Odoo publishes OdooWaRequest to odoo-wa-requests:
     {
       request_type:  "enroll",
       request_id:    "enroll-req-uuid-xyz",
       actor_type:    "buyer_inquiry",
       actor_id:      4521,
       phone:         "919876543210",
       workflow_slug: "lead_nurturing_v2",
       rm_odoo_id:    12,
       rm_name:       "Priya Singh",
       meta:          { "portal_source": "manual", "assigned_rm_id": 12 }
     }

4. odoo-bridge receives, reads request_type="enroll".
   Routes to workflow-engine's enrollment path.
   workflow-engine checks: is there already an active enrollment for
     actor_id=4521 + workflow_slug="lead_nurturing_v2"? No.
   → Creates workflow_enrollments row: status='active', meta=...
   → Begins executing step 1 of the workflow.

5. As the workflow runs, OdooWaEvent (event_type='message_sent') flows back.
   Odoo's subscriber creates a wa.enrollment_mirror record:
     workflow_display_name = "Lead Nurturing"
     current_step_display  = "first_touch"
     status                = "active"
   → The Enrollments sidebar on Priya's tab now shows "Lead Nurturing [Active]".
```

---

### Scenario G — Ambiguous reply (multiple active enrollments)

```
1. Buyer "Vikram Desai" (phone: 919900001111) has two active enrollments
   (both visible in the Enrollments sidebar on his lead form):
   - Enrollment A: nurturing_v2 for lead id=1001
   - Enrollment B: site_visit_v1 for lead id=1002

2. Vikram sends a free-text reply "Yes interested" with no callback_data.

3. reply-router queries conversation_context → active_enrollment_count = 2 → ambiguous.
   → Publishes RmAlertPayload (alert_type='ambiguous_reply') to rm-alerts.
   → Writes inbound_messages row (routing_status='ambiguous').

4. odoo-bridge receives the RmAlertPayload.
   → Constructs OdooWaEvent:
       event_type   = "ambiguous_reply"
       phone        = "919900001111"
       message_text = "Yes interested"
       rm_odoo_id   = ... (from whichever enrollment has the RM — alert payload includes it)

5. Odoo's subscriber:
   → Creates mail.activity on leads.new id=1001 (or both — TBD in module):
       title = "Ambiguous WA reply — 2 active workflows"
       note  = "Buyer replied 'Yes interested' but is enrolled in 2 campaigns.
                Review and respond manually."
   → Pushes bus.bus notification to the RM.

Result: RM is alerted and must handle this manually. System did not crash or silently drop
the reply.
```

---

## 12. Decision log — REST vs Pub/Sub per operation

| Operation | Decision | Rationale |
|---|---|---|
| Fetch actor fields for template vars | **Read from `enrollment.meta.actor`** (stored at enrollment time from `event.payload.actor`) | No REST call; actor data travels with the Odoo event; always available even when Odoo is down |
| Write RM activity on lead replied | Pub/Sub event → `wa-odoo-events` | Async OK; decouples from Odoo schema; non-breaking |
| Write RM activity on delivery failure | Pub/Sub event → `wa-odoo-events` | Same |
| bus.bus notification to RM | Pub/Sub event (Odoo handles internally) | WA platform has no knowledge of Odoo frontend — must not couple here |
| Log WA message to wa.message | Pub/Sub event → `wa-odoo-events` | Async OK; no WA platform state depends on this write |
| RM sends template from Odoo UI | Pub/Sub → `odoo-wa-requests` (`request_type=send`, `kind=template`) consumed by odoo-bridge | Odoo must not hold Interakt API keys; odoo-bridge fans out to wa-send |
| RM sends free-text from Odoo UI | Pub/Sub → `odoo-wa-requests` (`request_type=send`, `kind=freetext`) | Same — all WA sends route through wa-sender |
| RM sends media from Odoo UI | Pub/Sub → `odoo-wa-requests` (`request_type=send`, `kind=image|document|video|audio`) | Same |
| RM enrols lead in workflow | Pub/Sub → `odoo-wa-requests` (`request_type=enroll`) | Unified model; `request_type` is mandatory — no field-presence heuristics |
| Assign Conversation action | Pub/Sub → `odoo-wa-requests` (`request_type=assign`) → odoo-bridge → `assign_chat()` | Odoo must not hold Interakt API keys; one consumer for all three request types |
| Enrollment status shown in sidebar | Mirrored via `OdooWaEvent` events | No direct DB read from Odoo into WA platform DB |
| Timeline stats panel | Derived from `wa.message` in Odoo | Purely Odoo-local — no WA platform API call |
| Export Timeline | Purely Odoo-side | Serializes `wa.message` records — no WA platform involvement |
| Interakt chat assignment (after reply) | Direct Interakt API call from odoo-bridge | Already in interakt.py — no Odoo involvement needed |
| Fetch RM email for chat assignment | Embedded in `RmAlertPayload` | No extra call — actor snapshot in `enrollment.meta` contains RM email at event time |

---

## 13. Actor types and data model mapping

### `buyer_inquiry`

**Odoo model:** `leads.new` | **DB table:** `leads_new`

Field mapping for `get_actor` response:

| Response field | Odoo field | Notes |
|---|---|---|
| `id` | `leads_new.id` | Odoo integer ID |
| `name` | `leads_new.name` | Buyer name |
| `phone` | `leads_new.phone` | Raw as stored — normalize in `odoo.py` if needed |
| `current_status` | `leads_new.current_status` | Selection value |
| `inquiry_type` | `leads_new.inquiry_type` | `primary` or `recommended` |
| `rm.id` | `leads_new.user_id` → `res_users.id` | |
| `rm.name` | `res_users.name` | |
| `rm.email` | `res_users.login` | `res.users.login` is the email |
| `rm.phone` | `res_users.phone` or `res_users.mobile` | Whichever is set |
| `property.id` | `leads_new.property_base_id` → `property_base.id` | Null if not linked |
| `property.prop_id` | `property_base.prop_id` | Short code e.g. `GBH75X0K` |
| `property.tag` | `property_base.property_tag` | Display tag |
| `property.bhk` | `property_base.bhk` | Computed: `"{bedroom_count} BHK"` |
| `property.location` | `property_base.location` | Micro-locality |
| `property.city` | `property_base.city` | City |
| `property.link` | `property_base.property_link` | Computed: full ClearDeals URL |
| `property.owner_name` | `property_base.owner_name` | |
| `property.pricing_display` | `property_base.pricing_display` | Computed: "48 Lakh" |
| `property.is_active` | `property_base.is_active` | False = expired service |

**Template variable dot-paths and their resolved values:**

| Workflow var | Dot-path | Example value |
|---|---|---|
| Buyer name | `actor.name` | `"Rahul Sharma"` |
| Property tag | `actor.property_tag` | `"B-505, Green Heights"` |
| Property BHK config | `actor.property_config` | `"3 BHK"` |
| Property locality | `actor.property_locality` | `"Bopal"` |
| Property URL | `actor.property_url` | `"https://www.cleardeals.in/property/green-heights-GBH75X0K"` |
| RM name | `actor.rm_name` | `"Priya Singh"` |

> `actor.*` var resolution is handled in `engine.py` by traversing the nested dict returned
> by `get_actor()`. The mapping from dot-path to dict key is defined in `engine.py`, not
> in `odoo.py`.

---

### `customer`

**Odoo model:** `customer.base` (new module — to be built)  
**DB table:** `customer_base`

> The `customer.base` module design is outside the scope of this document. Once designed,
> add the field mapping table here following the same structure as `buyer_inquiry` above.

The `customer` actor type will:
- Cross-reference `property.base` records where the customer is the owner (via
  `property_base.owner_phone` or a dedicated `customer_id` link)
- Support the case where one customer owns multiple properties (multiple `property.base` rows)
- `get_actor` response for `customer` will include a `properties: list[dict]` field
  (array, not single object) — to be designed when the `customer.base` module is specified

---

## 14. Breaking-change risk register

| Risk | Mitigation |
|---|---|
| Odoo renames `leads_new.user_id` → something else | Odoo's event publisher is the adapter — only the Odoo-side publishing code changes. `payload.actor` schema is stable; WA platform is unaffected. |
| `property.base` schema changes | Odoo's event publisher controls what goes into `payload.actor.property`. WA platform reads fixed keys from the snapshot. |
| `res.users.login` is not always the email | Odoo's publishing code validates and uses `login` or `email` before embedding. WA platform trusts the embedded value. |
| Odoo instance goes down | No WA platform service blocks on Odoo. All actor data is already in `enrollment.meta`. Events queue in Pub/Sub and are processed when Odoo recovers. |
| Actor data in `enrollment.meta` is stale | Snapshot is updated every time Odoo publishes a new event for this actor. For long-running workflows, this is acceptable: the campaign was designed around the actor state at enrollment. A forced refresh can be triggered by Odoo publishing a synthetic `actor.refresh` event type. |
| `payload.actor` is missing from an Odoo event | workflow-engine treats `actor_snapshot = None` → all `actor.*` vars resolve to `""`. Event is not discarded. The workflow config's `failure_action` controls what happens on empty vars. This is a bug on the Odoo publishing side, not the WA platform. |
| `wa-odoo-events` message schema changes | Use `event_schema_version: int` field in `OdooWaEvent`. Odoo subscriber handles both old and new versions for one release cycle, then drops the old handler. |
| New `event_type` added to `OdooWaEventType` | Odoo subscriber treats unknown `event_type` values as no-op (log and ack). Old Odoo deployments are unaffected. |
| Odoo subscriber falls behind (backlog) | `wa-odoo-events` subscription has a 7-day message retention. No WA platform state is blocked on Odoo writing. Activities may appear delayed but are never lost. |
| `customer.base` module not yet deployed | `payload.actor` for `customer` events will be incomplete until the module exists. workflow-engine resolves missing fields to `""`. No crash. |
| RM sends freetext or media outside 24h customer service window | Interakt rejects with error code. wa-sender classifies as permanent failure. `OdooWaEvent(event_type="permanent_failure")` flows back. Odoo shows error in the chat bubble. No silent drop. |
| `OdooWaRequest` has `kind=freetext` but `message_text` is null | `odoo-bridge` validates schema on receipt — `ValidationError` routes to DLQ. The Odoo wizard should enforce non-empty text before publishing (client-side guard). |
| `OdooWaRequest` has `kind=image\|document\|video\|audio` but `media_url` is null | Same path — `ValidationError` on receipt, event goes to DLQ. Odoo attachment widget must supply `media_url` before publishing. `media_filename` is optional (only used for `kind=document`). |
| `OdooWaRequest` has `request_type` absent or invalid | `ValidationError` on receipt — DLQ immediately. `request_type` is the first field and is always required; any message without it is structurally broken. |
| RM double-taps "Enrol in Workflow" | `request_id` on `OdooWaRequest(request_type="enroll")` is the idempotency key. odoo-bridge/workflow-engine deduplicates on it. Second event is ack'd and silently dropped. |
| `wa.enrollment_mirror` goes stale if an OdooWaEvent is missed | Mirror is updated on every status-carrying OdooWaEvent. If a message is missed, the mirror may show a stale step. A daily reconciliation cron (future) can re-sync. Not an emergency — enrollments still run correctly on the WA platform side. |
