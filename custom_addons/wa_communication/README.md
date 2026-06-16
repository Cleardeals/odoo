# `wa_communication` — WhatsApp ↔ Odoo Communication Layer

**Version:** 1.1.8 · **Depends:** `cleardeals_pubsub`, `leads`, `cleardeals_ui`,
`cleardeals_notification` · **External Python:** `google-cloud-pubsub`, `google-auth`

The WhatsApp application module: it receives inbound WhatsApp traffic over GCP
Pub/Sub push, models conversations and messages, publishes outbound sends and
assignment requests, gates sending by chat ownership, and ships a full RM-facing
UI (lead-form tab, standalone inbox, dashboard, quick replies, template picker).

> New here? Read [`../README_WHATSAPP_SUITE.md`](../README_WHATSAPP_SUITE.md) first
> for the platform/Pub/Sub big picture.

---

## Table of contents

1. [Architecture & data flow](#1-architecture--data-flow)
2. [Data model](#2-data-model)
3. [Inbound: the push pipeline](#3-inbound-the-push-pipeline)
4. [Outbound: the send pipeline](#4-outbound-the-send-pipeline)
5. [The 24-hour window gate](#5-the-24-hour-window-gate)
6. [Assignment & reassignment](#6-assignment--reassignment)
7. [Quick replies](#7-quick-replies)
8. [Templates (Interakt direct fetch)](#8-templates-interakt-direct-fetch)
9. [Lead event publishing](#9-lead-event-publishing)
10. [HTTP endpoints](#10-http-endpoints)
11. [Public RPC API](#11-public-rpc-api-called-from-owl)
12. [Security model](#12-security-model)
13. [Configuration](#13-configuration-system-parameters)
14. [Frontend surfaces](#14-frontend-surfaces)
15. [Migrations](#15-migrations)
16. [Testing](#16-testing)

---

## 1. Architecture & data flow

```
INBOUND  (Platform → Odoo)                    OUTBOUND  (Odoo → Platform)
─────────────────────────                     ──────────────────────────
GCP push subscription                         conversation.send_message()
        │ POST /wa/pubsub/push                         │ creates wa.message (queued)
        ▼                                              │ publishes OdooWaRequest
WaPubSubPushController.wa_push()                       ▼   (deferred to postcommit)
        │ verify OIDC                          topic: cd-{env}-odoo-wa-requests
        ▼                                              │
wa.conversation._process_inbound_push()                ▼
        │ envelope type?                       platform wa-sender → Interakt → WA
        ├── event_type present → OdooWaEvent            │
        │     dispatch table (§3)                       │ status receipts come back
        └── WA webhook envelope → inbound msg           ▼ through the INBOUND path
                                              message_sent/delivered/read/failed
```

Everything Odoo emits is **fire-and-forget**. Everything Odoo learns about a
message's fate arrives later as an inbound `OdooWaEvent`. There is no synchronous
WhatsApp call anywhere in this module (the one direct HTTPS call is the Interakt
**template catalogue** fetch — see §8).

---

## 2. Data model

| Model | Purpose |
|---|---|
| **`wa.conversation`** | One thread per phone number. The aggregate root the UI talks to. |
| **`wa.message`** | Append-only message row (inbound & outbound). Immutable content; only status transitions are written after creation. |
| **`wa.event.log`** | Audit trail — **every** inbound event is logged here before dispatch. |
| **`wa.quick.reply`** | Canned replies (personal + team-shared). |
| **`wa.reassignment.request`** | The chat-handover handshake record. |
| **`wa.workflow`** | Registry of automation workflows + manager pause/resume health. |
| **`wa.enrollment`** | Read-mostly mirror of a lead's workflow enrollment. |
| **`wa.dashboard`** | Analytics aggregation for the dashboard client action. |
| **`wa.message.log`** | Analytics projection over `wa.message` for the Message Log surface. |
| `leads.new` *(inherited)* | Publishes lead lifecycle events to Pub/Sub (see §9). |

### `wa.conversation` key fields

| Field | Type | Notes |
|---|---|---|
| `phone_number` | Char | E.164-without-plus; the natural key. |
| `lead_id` | M2o `leads.new` | The lead this chat belongs to (may be unresolved). |
| `message_ids` / `message_count` | O2m / Int | Timeline. |
| `last_message_at` / `last_message_preview` / `unread_count` | — | Inbox row data. |
| `state` | Selection | `active` / `archived`. |
| `assigned_user_id` | M2o `res.users` | **The RM who owns the chat.** Drives the send gate. |
| `assignment_pending` | Bool | True while an assignment round-trip is in flight (UI shows a spinner). |
| `window_expires_at` | Datetime | When the 24h free-text window closes. |
| `window_state` | Selection (computed) | `open` / `closed`. |
| `interakt_inbox_url` | Char | Deep link into Interakt's inbox. |

### `wa.message` key fields

`direction` (`inbound`/`outbound`), `initiator` (`rm`/`workflow`/`buyer`/…),
`kind` (see below), `body`, template fields (`template_name`, `template_body`,
`template_header`, `template_footer`, `template_buttons`), workflow context
(`workflow_slug`, `step_id`, `enrollment_id`), `status` + `status_updated_at`,
media (`media_url`, `media_filename`), receipts (`delivered_at`, `seen_at`),
quoting (`quoted_message_id`, `quoted_body`, `quoted_sender`), `cost_inr`,
`occurred_at`, `wa_message_id` (WA's id, the dedup key), `request_id`
(our `OdooWaRequest` UUID), and `raw_payload`.

**`kind` values:** `template`, `freetext`, `image`, `document`, `video`, `audio`,
`button_reply`, `text_reply`, `system`, `unknown`.

### `wa.conversation` source layout

`wa.conversation` is one model, but it is large, so its methods are split across
partial-class files by responsibility. Each declares `_inherit = 'wa.conversation'`
and is merged into the single model at registry build time — there is no behaviour
or API difference from a one-file model; it is purely for readability.

| File | Responsibility |
|---|---|
| `models/wa_conversation.py` | Base: record definition (fields, constraints, computes), the inbound push **dispatcher** `_process_push_event`, core lookups, and the shared `_owa_*` helpers. Module-level constants and free functions live here and are imported by the others. |
| `models/wa_conversation_segments.py` | Inquiry-segment attribution (the "Discussing: <property>" context). |
| `models/wa_conversation_inbound.py` | WA Cloud API webhook handlers (legacy/direct-push format). |
| `models/wa_conversation_events.py` | `OdooWaEvent` handlers (status receipts, replies, enrollments, workflow sync). |
| `models/wa_conversation_assignment.py` | Ownership: claim, the reassignment handshake, the send gate. |
| `models/wa_conversation_outbound.py` | Outbound send paths (`send_message`, `send_first_message`, templates). |
| `models/wa_conversation_serializers.py` | Read-side serializers for the OWL UI (`get_inbox`, `get_thread`). |

> `_process_push_event` must stay on the base class — `test_push_controller.py`
> patches it by its fully-qualified path. `models/__init__.py` imports the base
> first so the partial-class files can import its module-level helpers.

---

## 3. Inbound: the push pipeline

**Entry point:** `WaPubSubPushController.wa_push()` → `/wa/pubsub/push`.

1. **Verify OIDC** — the GCP push bearer token is checked against
   `wa_communication.inbound_push_audience` (and optionally
   `…_sa_email`). On failure → **HTTP 401**. When `PUBSUB_EMULATOR_HOST` is set
   (local dev) the check is bypassed.
2. **Decode** the Pub/Sub envelope → the inner message JSON.
3. **Branch on envelope type** in `_process_inbound_push()`:
   - Has an **`event_type`** key → it's an **`OdooWaEvent`** from the platform's
     `odoo-bridge`; go to the dispatch table.
   - Otherwise → a raw **WA webhook envelope** (inbound message / status update).
4. **Audit-log** every event to `wa.event.log` *before* dispatch.
5. On any non-auth error → **HTTP 200** with the error logged, so GCP does **not**
   redeliver poison messages forever.

### `OdooWaEvent` dispatch table

`_process_odoo_wa_event()` maps `event_type` → handler:

| `event_type` | Handler | Effect |
|---|---|---|
| `message_sent` | `_handle_odoo_message_sent` | Outbound accepted by Interakt; store WA id. |
| `message_delivered` | `_handle_odoo_message_delivered` | Delivery receipt + cost. |
| `message_read` | `_handle_odoo_message_read` | Read receipt. |
| `message_failed` | `_handle_odoo_message_failed` | Map failure code → status. |
| `lead_replied` | `_handle_odoo_lead_replied` | Create inbound `wa.message`; **notify the assigned RM**. |
| `ambiguous_reply` | `_handle_odoo_ambiguous_reply` | Unroutable reply; create message + notify. |
| `permanent_failure` / `retry_exhausted` | `_handle_odoo_permanent_failure` | Mark failed; notify. |
| `enrollment_created` | `_handle_odoo_enrollment_created` | Mirror enrollment start. |
| `enrollment_completed` | `_handle_odoo_enrollment_completed` | Mirror enrollment finish. |
| `enrollment_step_changed` | `_handle_odoo_enrollment_step_changed` | Step pill in timeline. |
| `assignment_confirmed` | `_handle_odoo_assignment_confirmed` | **Flip `assigned_user_id`** after platform confirms (see §6). |

**Idempotency:** inbound messages dedup on `wa_message_id`; redelivery is a no-op.
Handlers `SELECT … FOR UPDATE` the conversation before creating rows to avoid
deadlocks under concurrent pushes.

---

## 4. Outbound: the send pipeline

**`wa.conversation.send_message(body, kind='freetext', …)`** →
returns the created `wa.message`.

```python
conv.send_message(body="Hi, following up on your visit", kind="freetext")

conv.send_message(kind="template", template_name="visit_reminder",
                  template_language="en",
                  body_values=["Rahul", "Sat 3pm"], header_values=[])

conv.send_message(kind="image", media_url="https://…/floorplan.png")
```

Pipeline:
1. **Validate** — phone present; the **send gate** (`_assert_can_send`, §6) passes;
   the **24h window** (§5) allows this `kind`.
2. **Create** a `wa.message` with `status='queued'`.
3. **Publish** an `OdooWaRequest` (`request_type='send'`) to
   `wa_communication.topic_odoo_wa_requests` — **deferred to `cr.postcommit`** so a
   rolled-back transaction never sends a real message.
4. The platform `wa-sender` does the actual send and reports back via inbound
   events (`message_sent` → `message_delivered` → `message_read`, or
   `message_failed`).

`initiator='rm'` sends route with `step_id="rm_manual"` and bypass workflow
enrollment checks; `initiator='workflow'` sends carry real workflow context.

---

## 5. The 24-hour window gate

WhatsApp only allows **free-form** messages within 24h of the customer's last
inbound message; outside it you may send **only approved templates**.

- `window_expires_at` is set from the last inbound message (or supplied by the
  platform), and `window_state` computes `open`/`closed`.
- `send_message()` **raises `UserError`** for `freetext`/media kinds when the
  window is closed, but always permits `kind='template'`.
- The composer reflects this with a window badge (`CdWindowBadge`).

---

## 6. Assignment & reassignment

### Ownership & the send gate

`assigned_user_id` is the source of truth for who may send. `send_message()` calls
`_assert_can_send()`, which allows the send when **any** of:
- the initiator is **not** an RM (system/workflow sends), **or**
- the current user is a **WhatsApp Manager** (`group_wa_manager`), **or**
- the current user **is** `assigned_user_id`.

Otherwise it raises `UserError("This chat is assigned to <name>…")`. This is the
authoritative backstop, independent of whatever the UI shows.

### Platform-routed assignment (never call Interakt directly)

Assignment must keep the platform's `rm_assignments` table consistent, so Odoo
**never** calls Interakt's assignment API itself. Instead:

```
Odoo  _request_assign(target_user)             Platform                      Odoo
  │ publish request_type='assign'  ───────────▶ wa-sender                     │
  │ set assignment_pending=True                 calls Interakt assignment     │
  │ (ownership NOT yet flipped)                 upserts rm_assignments         │
  │                                             publishes assignment_confirmed │
  │                                  ◀──────────  {success, rm_odoo_id, …} ───▶│
  │                                              _handle_odoo_assignment_confirmed
  │                                              • success → set assigned_user_id,
  │                                                clear pending, notify new RM
  │                                              • failure → notify, keep owner
```

### Three user flows

| Situation | Method | Behaviour |
|---|---|---|
| Chat **unassigned** | `action_claim()` | Any WA user self-claims; ownership flips on confirmation. |
| Chat owned by **someone else** | `request_assignment(note)` | Creates a `wa.reassignment.request`; the **current assignee** is notified to Approve/Decline. |
| **Manager** override | `action_reassign(user_id=…)` | Force-reassign with no handshake; still waits for platform confirmation. |

### `wa.reassignment.request`

Fields: `conversation_id`, `requester_id`, `current_assignee_id`,
`state` (`pending` / `confirming` / `approved` / `declined` / `failed` /
`cancelled`), `note`, `request_id`, `resolved_at`.
Methods: `approve()` (assignee or manager → `_request_assign`, state→`confirming`),
`decline()`, `cancel()` (requester), and internal `_mark_approved` / `_mark_failed`
called by the confirmation handler. Each transition notifies the requester.

---

## 7. Quick replies

**Model `wa.quick.reply`** — `title`, `shortcut` (e.g. `/visit`), `body`,
`user_id` (empty ⇒ **shared**), `is_shared` (computed/stored), `active`,
`sequence`.

- `@api.model get_for_composer()` → the current user's own replies + all shared,
  ordered, shaped for the composer picker.
- **Record rules** (`wa_quick_reply_rules.xml`): a plain user reads own + shared
  but may write/unlink only their **own personal** rows; managers manage
  everything including shared.

UI: the composer's **bolt** button opens `CdQuickReplyPicker`; the **WhatsApp →
Quick Replies** menu opens the `wa_quick_replies` client action (a card-grid
manager).

---

## 8. Templates (Interakt direct fetch)

The only place Odoo talks to a WhatsApp BSP directly. There is **no `wa.template`
model and no caching** — the catalogue is fetched live when the picker opens.

- **Helper:** `models/interakt_client.py` (`fetch_templates`) — Basic-auth GET to
  `{base}/v1/public/track/organization/templates`, paginated, normalised.
- **RPC:** `wa.conversation.fetch_templates(template_name=None)` returns
  `[{name, display_name, language, category, header, body, footer, buttons,
  variables:[{scope, position, label}]}]`. Variables are the ordered `{{N}}`
  slots scanned from header + body. Missing key / HTTP error → `UserError`.
- **Config:** `wa_communication.interakt_api_key` (per-env, never sent to the
  browser) and `wa_communication.interakt_base_url` (default `https://api.interakt.ai`).
- **UI:** `CdTemplatePickerModal` — search/list → fill `{{N}}` variables with a
  live preview → **Send** routes through `send_message(kind='template', …)`.

> ⚠️ Interakt returns the **same template name once per language** (`language=all`).
> The picker must key its list by index (not by `name`) to avoid duplicate OWL keys.

---

## 9. Lead event publishing

`leads.new` is inherited (`models/wa_lead_event_publisher.py`) to publish Pub/Sub
events on lead lifecycle changes (created, site visit scheduled/done, etc.). Each
category has its own topic param so the platform can fan them into the right
workflow triggers:

`topic_actor_events`, `topic_visit_events`, `topic_property_events`,
`topic_customer_events`. Managers can also pause/resume a workflow, which publishes
to `topic_workflow_control`.

---

## 10. HTTP endpoints

| Route | Type | Auth | Purpose |
|---|---|---|---|
| `POST /wa/pubsub/push` | http | `none` (OIDC-verified, `readonly=False`) | GCP Pub/Sub push receiver for all inbound events. |
| `POST /wa/media/upload` | http | `user` | RM uploads an image/PDF/etc.; stored as a **public** `ir.attachment`, returns a public URL for `send_message(media_url=…)`. |

> `auth='none'` routes default to **readonly** in Odoo 19 — the push route
> declares `readonly=False` because it writes.

---

## 11. Public RPC API (called from OWL)

All on `wa.conversation`:

| Method | Returns | Used by |
|---|---|---|
| `get_inbox(filters=None)` | list of inbox rows (incl. `can_send`, `is_manager`, `assignment_pending`, window, assignee) | Inbox |
| `get_inbox_counts()` | dict of filter counts | Inbox tabs |
| `get_thread(conversation_id)` | full thread dict (messages + gating flags) | Inbox / lead tab |
| `send_message(…)` | created `wa.message` | Composer |
| `fetch_templates(template_name=None)` | normalised template list | Template picker |
| `action_claim()` | — | Claim button |
| `request_assignment(note=None)` | request id | Request button |
| `action_reassign(lead_id=None, user_id=None)` | — | Manager reassign |
| `get_quick_replies` via `wa.quick.reply.get_for_composer()` | quick replies | Composer picker |

Thread/inbox serializers include **`can_send`** (manager or assignee),
`assigned_user_id` + name, `is_manager`, `assignment_pending`, and `window_state`,
so the composer can lock/unlock itself correctly.

---

## 12. Security model

- **`base.group_user` is the WA-user baseline** — every internal user gets
  read/write/create on the `wa.*` models (see `ir.model.access.csv`).
- **`group_wa_manager` ("WhatsApp Manager")** adds the privileges the gate checks:
  send on **any** chat, **force-reassign** without the handshake, and manage
  **shared** quick replies. It implies `base.group_user`.
- **Record rules:** quick replies (own + shared visibility, own-only write);
  reassignment requests scoped appropriately.
- Append-only models (`wa.message`, `wa.event.log`) grant no unlink to users.

---

## 13. Configuration (System Parameters)

Set per environment under **Settings → Technical → System Parameters**. Defaults
ship in `data/wa_communication_config_data.xml` with `noupdate="1"` (created on
first install; **not** overwritten on `-u`).

| Key | Purpose |
|---|---|
| `wa_communication.inbound_push_audience` | OIDC `aud` claim = the push endpoint URL. |
| `wa_communication.inbound_push_sa_email` | Optional SA-email assertion. |
| `wa_communication.topic_odoo_wa_requests` | Outbound WA send requests. |
| `wa_communication.topic_actor_events` | Lead / RM events. |
| `wa_communication.topic_visit_events` | Site-visit events. |
| `wa_communication.topic_property_events` | Property events. |
| `wa_communication.topic_customer_events` | Customer events. |
| `wa_communication.topic_workflow_control` | Workflow pause/resume (alias; `cd-{env}-` added at runtime). |
| `wa_communication.interakt_api_key` | Interakt Basic-auth key (template fetch). **Server-only.** |
| `wa_communication.interakt_base_url` | Interakt API base (default `https://api.interakt.ai`). |

Topic naming convention: `cd-{env}-{alias}` (e.g. `cd-prod-odoo-wa-requests`).

---

## 14. Frontend surfaces

All OWL, built from `cleardeals_ui` primitives. Menus live under the **WhatsApp**
root menu.

| Surface | Files | Client action / mount |
|---|---|---|
| **Lead form tab** | `static/src/lead_tab/` | Embedded `<widget>` on the lead form (`wa_lead_form_inherit.xml`). |
| **Inbox** (full screen) | `static/src/inbox/` | `action_wa_inbox` (tag `wa_inbox`). |
| **Dashboard** | `static/src/dashboard/` | `action_wa_dashboard` (tag `wa_dashboard`). |
| **Message Log** | `static/src/message_log/` | `action_wa_message_log` (tag `wa_message_log`). |
| **Quick Replies manager** | `static/src/quick_replies/` | `action_wa_quick_replies` (tag `wa_quick_replies`). |
| **Webhook Log** | `static/src/webhook_log/` | Audit viewer. |
| **Notification types** | `static/src/notifications/wa_notification_types.js` | Registers WA types into the `cd_notification_types` registry (see `cleardeals_ui`). |

The lead tab and inbox both subscribe to `cleardeals_notification_{uid}` to live-
refresh the open thread when a relevant notification arrives. They read the user
id from `@web/core/user` (`user.userId`) — **not** `session.uid`.

---

## 15. Migrations

`migrations/1.1.1/pre-migrate.py` — drops the legacy `action_wa_message_log`
**`ir.actions.act_window`** so the post-load XML can recreate it as an
**`ir.actions.client`** (Odoo refuses to change a record's model in place). It is
**idempotent** and **skips fresh installs** (guarded by an `ir_model_data`
existence check), so CI's fresh install is never broken.

---

## 16. Testing

Tagged `wa_communication`; base class `WaTransactionCase` (see `tests/common.py`).
**122 tests** at the time of writing.

The model is split across several files (§2) but the suite is unaffected — tests
exercise the merged `wa.conversation` model and its public RPC API, not individual
files, so the split required **zero test changes**.

| Test file | Covers |
|---|---|
| `test_inbound_events.py` | The `OdooWaEvent` dispatch table, dedup, audit logging, error isolation, **notification routing to the assigned RM**. |
| `test_segments.py` | Inquiry-segment attribution: flag-gating (off = no-op), workflow-send tagging, two-inquiry split, relink/move recompute, swipe-reply-to-other-property filing, `set_active_segment`, immutability. |
| `test_send_message.py` | Outbound queueing, the 24h window gate, media/template paths. |
| `test_send_template.py` | `fetch_templates` parsing + `send_message(kind='template')`. |
| `test_assignment.py` | Send gate, `_request_assign`, confirmation handler, request lifecycle, claim/force. |
| `test_quick_reply.py` | Personal-vs-shared isolation, `get_for_composer`, record-rule access. |
| `test_thread_serializers.py` | `get_thread` / `get_inbox` shapes incl. `can_send`. |
| `test_push_controller.py` | OIDC verification + the HTTP push path (`WaHttpCase`). Patches `WaConversation._process_push_event` by its fully-qualified path — which is why that method stays on the base class (§2). |
| `test_inbound_migration.py` | The conversation dedup/canonicalization pre-migration. |
| `test_interakt_client.py`, `test_wa_message_model.py`, `test_conversation_model.py` | Client helper, message model, conversation model. |

Fixtures: `make_conversation`, `make_user(manager=…)`, `make_message`,
`make_lead`, and `mock_pubsub()` (captures `publish_async`, flushes postcommit).

```bash
DB_PORT=5455 ./run_tests.sh wa_communication
```
