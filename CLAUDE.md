# CLAUDE.md

Guidance for Claude Code when working in this repository.

> This repo is **public**. Never commit credentials, internal IPs, GCP project
> details, firewall configuration, customer data, or infrastructure audits.
> Sensitive operational context lives outside the repo — see "Local context".

## What this is

A fork of **Odoo 19.0** (`odoo/release.py` → `19, 0, 0, FINAL`). Upstream Odoo
source is vendored at the repo root; **all Cleardeals code lives in
`custom_addons/`.** Treat everything outside `custom_addons/` as third-party —
read it to understand framework behaviour, don't modify it.

## Modules

| Module | Purpose |
|---|---|
| `leads` | Core lead model; `leads.bde` is reused across modules |
| `lead_suggestor` | Lead/property matching |
| `properties`, `property_listings`, `property_dashboard`, `property_renewal` | Property domain |
| `deals` | Deal / transaction / package / offer hub |
| `wa_communication` | WhatsApp inbox, templates, scorecards |
| `cleardeals_pubsub` | Google Pub/Sub transport shared by other modules |
| `cleardeals_notification` | Central `cleardeals.notification` model + `notify()` API |
| `cleardeals_ui` | Global UI: popups, systray bell |
| `cleardeals_dashboards` | Reporting dashboards |

## Testing

```bash
./run_tests.sh                    # default: leads, lead_suggestor, cleardeals_dashboards, properties
./run_tests.sh wa_communication   # specific module(s), space-separated
```

Docker-based, mirrors the GitHub Actions workflow exactly. Useful env vars:
`KEEP_DB=1` (leave Postgres up), `REBUILD=1` (force image rebuild),
`LOG_LEVEL=debug`.

Use the **`writing-odoo-tests`** skill before adding tests — it covers the shared
fixtures in `wa_communication/tests/common.py`, Pub/Sub mocking, append-only
models, and HttpCase patch targets.

## Branches and CI

- `19.0` — production. PRs target this.
- `development_19` — integration branch.
- Feature work: `feature/<name>`.

`.github/workflows/test.yml` runs on PRs; `deploy.yml` fires **automatically on a
successful test run against `19.0`** and deploys to the production VM. A merge to
`19.0` is a production deploy — treat it that way.

## Odoo 19 gotchas that have bitten this codebase

- `_sql_constraints` was removed in Odoo 19. Constraints declared that way are
  **silent no-ops**. Use `_table_constraint` / explicit SQL or Python constraints.
- `res.groups` fields were renamed in 19 — check the vendored source, don't assume.
- `auth='none'` controller routes are readonly by default; declare otherwise when
  the route writes.
- Verify framework behaviour against the vendored `odoo/` source rather than from
  general knowledge — the **`odoo-code-review`** skill encodes this discipline and
  has caught real production bugs in compute/related fields, sequences, and
  onchange logic.

## API specs

Every controller route must have an OpenAPI spec in `docs/api/openapi/` (4 specs
split by audience). **CI fails when a route has no spec** — update the spec in the
same commit as any route change.

## Before deploying

Use the **`odoo-prod-migration-check`** skill to rehearse migrations against a
read-only snapshot of the production database, and **`odoo-pre-push-review`** for
manifest/migration/security review.

## Local context (not in this repo)

Claude Code's memory for this project lives at
`~/.claude/projects/-Users-cleardealstech-Documents-GitHub-odoo/memory/` — start
with `MEMORY.md`. It carries the WhatsApp architecture, staging VM details,
project history, and infrastructure notes that cannot live in a public repo.

`CHECKPOINT.md` (gitignored, repo root) holds current session-handoff state.
