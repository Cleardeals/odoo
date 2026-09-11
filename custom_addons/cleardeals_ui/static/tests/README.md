# Frontend (Hoot) unit tests

OWL component tests using Odoo 19's **Hoot** framework. They live in
`static/tests/*.test.js` and are registered in the `web.assets_unit_tests`
bundle (see each module's `__manifest__.py`).

## How to run

Hoot tests execute **in a browser**, not via `./run_tests.sh` (which is
Python-only and has no Chromium):

1. Start Odoo with the modules installed.
2. Open **`/odoo/web/tests`** (Hootest runner).
3. Filter by suite name, e.g. `CdWindowBadge`, `CdConversationListItem`, `WaInbox`.

The runner reloads on file change, so it doubles as a watch mode during dev.

## Coverage

| Suite | File | What it checks |
|---|---|---|
| `CdWindowBadge` | `cleardeals_ui/.../window_badge.test.js` | open / closed / **closing_soon** rendering (regression guard for the inbox redesign). Pure — no mock server. |
| `CdConversationListItem` | `cleardeals_ui/.../conversation_list_item.test.js` | name/phone fallback, unread badge, SLA waiting chip, claim-vs-reassign, select. Prop-driven. |
| `WaInbox` | `wa_communication/.../wa_inbox.test.js` | role-aware structure (RM hides ownership tabs), quick chips + counts, `Closing soon` → `window=closing_soon`. Mocks RPC (`onRpc`) and stubs `cd_notification`/`bus_service`. |

## CI automation (not yet wired)

To run these in the pipeline, the test image needs **Chromium** and a headless
runner step. That is a separate infra change (Dockerfile + `run_tests.sh`); until
then, run the suites manually in a browser before shipping frontend changes.
