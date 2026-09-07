# `cleardeals_notification` — Central Notification Backend

**Version:** 1.0.0 · **Depends:** `bus`

A small, reusable, **WhatsApp-agnostic** backend for user-facing notifications.
Any Cleardeals module raises a notification with one call; the notification is
**persisted** (so it survives an offline user and is recovered on next load) and
**fanned out live** over the bus for an instant popup. The **UI** that renders it
(systray bell + popups) lives in [`cleardeals_ui`](../cleardeals_ui/README.md).

> Separation of concerns: this module owns *what a notification is and how it's
> delivered*; `cleardeals_ui` owns *how it looks and what its buttons do*.

---

## 1. Why it exists

Before this, modules raised ad-hoc `bus.bus._sendone(...)` messages with bespoke
channels and bespoke frontend listeners — no persistence, lost if the user was on
another screen, and duplicated per module. This module centralises all of that:

- **Compulsory delivery** — every notification is a DB row; the frontend pulls
  unread rows on mount, so nothing is lost to a missed websocket frame.
- **One channel, one event type** — `cleardeals_notification_{uid}` / `cd_notification`.
- **Type-tagged & declarative** — callers pass a `notif_type` string; the frontend
  registry maps it to an icon/colour/actions. New kinds need **no backend change**.

---

## 2. The model — `cleardeals.notification`

| Field | Type | Notes |
|---|---|---|
| `user_id` | M2o `res.users` (required, indexed, `ondelete=cascade`) | Recipient. One row per recipient. |
| `notif_type` | Char (required, indexed) | Frontend registry key, e.g. `reassignment_request`, `lead_replied`. |
| `title` | Char | Headline. |
| `body` | Text | Message body. |
| `payload` | Json | Arbitrary event data (`request_id`, `conversation_id`, `suppress_key`, …). **Spread into the client message** so handlers read keys at the top level. |
| `is_actionable` | Bool | Has inline actions (Approve/Decline); stays until resolved. |
| `is_read` | Bool (indexed) | — |
| `sticky` | Bool | Popup doesn't auto-dismiss. |

`_order = 'create_date desc, id desc'` (newest first).

### Serialisation (`_to_dict`)

The bus message and RPC responses are `_to_dict()`:

```jsonc
{
  "notification_id": 42,
  "type": "lead_replied",          // == notif_type
  "title": "Rahul replied on WhatsApp",
  "message": "Is the flat still available?",
  "actionable": false,
  "sticky": false,
  "is_read": false,
  "created_at": "2026-06-05T07:14:50",
  // …all payload keys spread in here (phone, lead_id, request_id, suppress_key…)
}
```

`notification_id` and `type` are re-asserted **after** the payload spread, so a
payload can never accidentally override them.

---

## 3. The emission API — `notify()`

```python
self.env['cleardeals.notification'].notify(
    users,                       # recordset, single id, or list of ids
    'reassignment_request',      # notif_type (frontend registry key)
    title="Chat handover requested",
    body="Nirat wants to take over this chat.",
    payload={'request_id': req.id, 'suppress_key': phone},
    actionable=True,             # persists in the bell until acted upon
    sticky=False,                # popup auto-dismisses unless sticky/actionable
)
```

What it does, per recipient:
1. **Creates** a `cleardeals.notification` row (via `sudo()` — callers need no
   create rights).
2. **Pushes** `_to_dict()` over `bus.bus._sendone('cleardeals_notification_{uid}',
   'cd_notification', …)`.
3. A bus failure is caught and logged — it never breaks the calling business flow.

`users` is coerced by `_coerce_user_ids` (recordset / int / list). Returns the
created recordset.

### The `suppress_key` convention

A caller may set `payload['suppress_key']` (e.g. the chat phone number). If the
user is **already viewing that exact context**, the frontend suppresses the
**popup** only — the history entry is still recorded. The viewing component sets
the active key via the `cd_notification` service's `setActiveSuppressKey`.

---

## 4. Client-facing RPC helpers

All `@api.model`, scoped to the current user:

| Method | Purpose |
|---|---|
| `get_unread(limit=40)` | Current user's unread rows (newest first). Frontend calls this on mount to recover anything missed offline. |
| `get_unread_count()` | Count of unread. |
| `mark_read(ids)` | Flag the caller's own rows read. |
| `mark_all_read()` | Flag all the caller's unread read. |

---

## 5. Transport (bus) details

- **Channel:** `cleardeals_notification_{uid}` (string channel; the client must
  `addChannel` the same string).
- **Event type:** `cd_notification`.
- The bus NOTIFY/LISTEN runs on the **`postgres`** maintenance database
  (cross-database by design) — a `Bus.loop listen imbus on db postgres` log line
  is normal and correct.
- With `workers ≥ 1`, delivery is over a websocket on the gevent port; nginx must
  proxy `/websocket` to it.

---

## 6. Security

`security/ir.model.access.csv`:

| Group | r | w | c | u |
|---|---|---|---|---|
| `base.group_user` | ✅ | ✅ | — | — |
| `base.group_system` | ✅ | ✅ | ✅ | ✅ |

Emission is done with `sudo()`, so ordinary users need no create/unlink rights.

`security/cleardeals_notification_rules.xml` — a record rule restricts
`base.group_user` to **their own** notifications:
`domain_force = [('user_id', '=', user.id)]` (read + write; no create/unlink). A
user can therefore read and mark-read only their own rows.

---

## 7. End-to-end sequence

```
Module code                    cleardeals.notification            Browser (cleardeals_ui)
───────────                    ───────────────────────            ───────────────────────
notify(uid, 'lead_replied', …) ─▶ create row (sudo)
                                  _sendone(cleardeals_notification_{uid},
                                           'cd_notification', _to_dict())  ──▶ cd_notification service
                                                                              onEvent(payload)
                                                                              • upsert into store
                                                                              • showPopup (unless suppressed)
                                                                              • bell badge ++
       (user was offline)                                          on next page load:
                                  get_unread()  ◀───────────────── loadPersisted()
                                  rows  ─────────────────────────▶ restore bell history
```

---

## 8. Adding a new notification kind

1. **Backend:** just call `notify(users, 'my_new_type', …)` — no model change.
2. **Frontend:** register a display/behaviour config for `'my_new_type'` in the
   `cd_notification_types` registry (see
   [`cleardeals_ui`](../cleardeals_ui/README.md#notification-ui)). Unregistered
   types still render with a safe default (bell icon, no actions).

---

## 9. Testing

`tests/test_notification.py` (base `TransactionCase`) covers persistence,
`_to_dict` payload spreading + canonical-key re-assertion, the own-only record
rule, and `get_unread` / `mark_read` / `mark_all_read`.
