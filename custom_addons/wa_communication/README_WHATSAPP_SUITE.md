# Cleardeals WhatsApp Suite — Developer Guide

> A guided tour of the three Odoo 19 modules that power Cleardeals' WhatsApp
> communication, the reusable notification backend, and the shared OWL component
> library. Read this first; then dive into the per-module READMEs linked below.

| Module | Purpose | README |
|---|---|---|
| **`wa_communication`** | WhatsApp ↔ Odoo messaging: inbound push receiver, conversation threads, outbound send pipeline, assignment, quick replies, templates, dashboard. | [`wa_communication/README.md`](./wa_communication/README.md) |
| **`cleardeals_notification`** | Reusable, persistent, WhatsApp-agnostic user-notification **backend** (`cleardeals.notification` model + `notify()` API + bus fan-out). | [`cleardeals_notification/README.md`](./cleardeals_notification/README.md) |
| **`cleardeals_ui`** | Central OWL **component library**: chat widgets, charts, field widgets, and the notification **UI** (systray bell + popups). | [`cleardeals_ui/README.md`](./cleardeals_ui/README.md) |

---

## 1. The big picture

Odoo is **not** connected to the WhatsApp Cloud API directly. All WhatsApp
traffic flows through a separate Kubernetes-based platform (the
`cleardeals-whatsapp-platform` repo). Odoo and the platform communicate **only**
through **Google Cloud Pub/Sub** — fire-and-forget, decoupled, and replay-safe —
with a single exception: Odoo fetches the Interakt template catalogue over HTTPS
directly (see `wa_communication`, Feature "Send Template").

```
                         ┌──────────────────────────────────────────────┐
                         │            cleardeals-whatsapp-platform        │
   WhatsApp Cloud API    │  (k8s services, separate repo)                 │
        ▲   │            │  webhook-gateway · workflow-engine · wa-sender │
        │   │            │  reply-router · error-handler · odoo-bridge    │
        │   ▼            │  reminder-scheduler                            │
   ┌──────────┐  webhook │                                                │
   │ Interakt │─────────▶│  ── publishes OdooWaEvent ──┐                  │
   │  (BSP)   │◀─────────│  ◀─ consumes OdooWaRequest ─┼──┐               │
   └──────────┘   send   └─────────────────────────────┼──┼──────────────┘
        ▲                                               │  │
        │ HTTPS GET templates                      Pub/Sub topics & subs
        │ (Odoo holds the key)                          │  │
        │                            ┌──────────────────▼──┴──────────────┐
        └────────────────────────────│            Odoo 19                 │
                                      │  wa_communication                 │
                                      │   • POST /wa/pubsub/push (inbound) │
                                      │   • send_message() → Pub/Sub (out) │
                                      │  cleardeals_notification (bell)    │
                                      │  cleardeals_ui (OWL components)    │
                                      └────────────────────────────────────┘
```

### Two directions of traffic

**Inbound (Platform → Odoo)** — the platform's `odoo-bridge` publishes
`OdooWaEvent` messages to the `cd-{env}-wa-odoo-events` topic. A GCP **push
subscription** POSTs each one to Odoo at **`/wa/pubsub/push`**. Odoo verifies the
OIDC token, parses the event, and updates conversations / messages / status, then
raises user notifications.

**Outbound (Odoo → Platform)** — `wa.conversation.send_message()` creates a
`queued` `wa.message` and publishes an `OdooWaRequest` (`request_type='send'`) to
`cd-{env}-odoo-wa-requests`. The platform's `wa-sender` performs the actual WA
send and reports back **via the inbound path** (`message_sent` →
`message_delivered` → `message_read`, or `message_failed`).

Chat **assignment** uses the same decoupled pattern: Odoo publishes
`request_type='assign'` to the `wa-assign` topic; the platform calls Interakt and
echoes an `assignment_confirmed` event back through the inbound path. Odoo flips
ownership **only after** that confirmation.

---

## 2. Module dependency graph

```
                 web (Odoo core)        bus (Odoo core)
                   │                       │
                   │                       ▼
                   │            cleardeals_notification   ◀── notify() backend
                   │                       │
                   ▼                       ▼
            cleardeals_ui  ───────────────┘   ◀── OWL components + notification UI
                   │
   cleardeals_pubsub, leads ──┐
                              ▼
                       wa_communication      ◀── the WhatsApp app
```

- `cleardeals_ui` **depends on** `cleardeals_notification` (it provides the bell/popup
  UI for that backend).
- `wa_communication` **depends on** `cleardeals_pubsub`, `leads`, `cleardeals_ui`,
  and `cleardeals_notification`.

Install order is resolved automatically by Odoo from these `depends`.

---

## 3. Local development environment

The dev stack runs in Docker (`odoo-dev-app`, `odoo-dev-db` Postgres, `odoo-dev-nginx`),
with the WhatsApp platform infra (`wa-postgres`, `wa-pubsub-emulator`) alongside.

| Concern | Value |
|---|---|
| App container | `odoo-dev-app` (image `odoo-cleardeals:dev`) |
| DB | `odoo-dev-db` (Postgres 17), database **`cleardeals_19_dev`** |
| URL | `http://localhost:8069` (via `odoo-dev-nginx`) |
| Dev mode | `ODOO_DEV=all` — Python auto-reload + asset rebuild on file change |
| Source mount | `custom_addons/` → `/mnt/extra-addons/custom` (live edits) |
| Pub/Sub | emulator at `host.docker.internal:8085` (`PUBSUB_EMULATOR_HOST`) |
| Workers | `workers = 2` → bus runs over a websocket on the gevent port (8072), proxied by nginx at `/websocket` |

### Common dev tasks

```bash
# Open the Odoo shell (note: use the venv python, not the system one)
docker exec -i odoo-dev-app sh -c \
  'export PATH=/opt/odoo-venv/bin:$PATH; python3 /usr/bin/odoo shell -d cleardeals_19_dev --no-http'

# Psql into the dev DB (Docker Postgres, NOT your host's 5432!)
docker exec odoo-dev-db psql -U odoo -d cleardeals_19_dev

# Force a clean front-end asset rebuild (after JS/XML/SCSS edits that don't hot-reload)
docker exec odoo-dev-db psql -U odoo -d cleardeals_19_dev \
  -c "DELETE FROM ir_attachment WHERE name LIKE 'web.assets_%';"
# …then hard-reload the browser (Cmd+Shift+R).

# Apply Python model/migration changes that require a module update
docker exec odoo-dev-app sh -c \
  'export PATH=/opt/odoo-venv/bin:$PATH; python3 /usr/bin/odoo -d cleardeals_19_dev \
   -u wa_communication --stop-after-init --no-http'
```

> ⚠️ **The dev DB is inside Docker (Postgres 17), reachable on host port 5434 —
> not your local Postgres on 5432.** A `psql` to `localhost:5432` hits a different
> database. Always go through `docker exec odoo-dev-db`.

---

## 4. Running the test suite

Tests are tagged per module and run in a throwaway Postgres via `run_tests.sh`,
mirroring CI.

```bash
# All tagged modules
./run_tests.sh

# Just the WhatsApp module (use a free DB port if 5432 is taken locally)
DB_PORT=5455 ./run_tests.sh wa_communication
```

If the runner can't bind port 8069 (your dev nginx holds it), run the equivalent
docker command on a free HTTP port:

```bash
docker run --rm --network host \
  -v "$(pwd)/custom_addons:/mnt/extra-addons" my-odoo-image \
  odoo -d odoo_test_db --db_host=localhost --db_port=5455 \
       --db_user=odoo --db_password=odoo \
       --addons-path=/mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons \
       -i wa_communication --test-enable --test-tags /wa_communication \
       --stop-after-init --http-port=8899 --workers=0 --log-level=test
```

See the **`writing-odoo-tests`** local skill and `wa_communication/tests/common.py`
for fixtures (`WaTransactionCase`, `make_conversation`, `make_user`, `mock_pubsub`).

---

## 5. Conventions & hard-won gotchas

These bit us in production. Keep them in mind.

| Area | Rule |
|---|---|
| **Odoo 19 session** | `session.uid` was **removed**. Get the current user id from `import { user } from "@web/core/user"` → **`user.userId`**. Reading `session.uid` silently returns `undefined`. |
| **Bus channels** | Server `_sendone(channel, type, msg)` with a string channel is matched against client `addChannel(channel)`. The bus NOTIFY/LISTEN runs on the **`postgres`** maintenance DB (cross-database) — that log line is normal. |
| **OWL `t-foreach`** | Always give the list a **unique** `t-key`, never reuse `t` as the loop alias (`t` is OWL's namespace tag), and keep the VList under a **real DOM element**, not a `<t>` fragment chain. Violations crash with `moveBeforeVNode … null parentEl`. |
| **`auth='none'` routes** | In Odoo 19 these default to **readonly**. A writing webhook must declare `readonly=False`. |
| **Append-only data** | `wa.message` / `wa.event.log` are effectively immutable audit rows — never mutate historical content; write status transitions only. |
| **Pub/Sub publishing** | Sends are deferred to `cr.postcommit` so a rolled-back transaction never triggers a real WA message. |
| **Odoo shell** | Use the venv python (`/opt/odoo-venv/bin/python3 /usr/bin/odoo`), the system `python3` lacks `google.cloud`. |

---

## 6. Where to go next

- **Building a WhatsApp feature?** → [`wa_communication/README.md`](./wa_communication/README.md)
- **Raising a notification from any module?** → [`cleardeals_notification/README.md`](./cleardeals_notification/README.md)
- **Adding a UI component or a notification type?** → [`cleardeals_ui/README.md`](./cleardeals_ui/README.md)
