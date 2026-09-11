# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

> **This repository is PUBLIC** (a fork of `odoo/odoo`). Never commit an API key,
> password, connection string or customer data — not in code, not in a test
> fixture, not in a doc, not in a comment. Secrets live in Secret Manager and in
> `ir.config_parameter` at runtime. `odoo.prod.conf` holds `__PLACEHOLDER__`
> tokens and a CI gate fails the build if a real value ever replaces one.

## What this repo is

A fork of Odoo 19.0 carrying Cleardeals' own modules. **Only `custom_addons/` is
ours.** `odoo/`, `addons/`, `doc/`, `setup/` and `debian/` are vendored upstream
core — read them to answer "how does Odoo actually do X", but do not edit them.
The `upstream` remote points at `odoo/odoo`.

Modules, and what depends on what:

| Module | Version | Depends on |
|---|---|---|
| `properties` | 19.0.1.8.0 | base, web, mail |
| `lead_suggestor` | 19.0.1.1.0 | base, web, properties |
| `leads` | 1.11.0 | base, web, mail, lead_suggestor, properties |
| `cleardeals_dashboards` | 19.0.1.0 | base, leads, lead_suggestor, mail |
| `cleardeals_notification` | 1.0.0 | bus |
| `cleardeals_ui` | 1.2.0 | web, cleardeals_notification |
| `cleardeals_pubsub` | 1.0.0 | base, web |
| `wa_communication` | 1.6.0 | cleardeals_pubsub, leads, cleardeals_ui, cleardeals_notification |
| `property_dashboard`, `property_listings`, `property_renewal` | 1.0 | **DEPRECATED — `installable: False`. Never install. Never revive.** |
| `deals` | — | **Not on this branch.** The module lives, unmerged, on `deal/odoo`. |

`wa_communication` is one half of a two-repo system; the other half is the
`cleardeals-whatsapp-platform` repo (7 Python services on GKE). They communicate
**only** over Google Cloud Pub/Sub — there is no HTTP call between them in
either direction.

## Commands

### Dev stack (`docker-compose.dev.yml`)

```bash
make up                      # start the stack (Odoo on http://localhost:8069 via nginx)
make logs-odoo               # tail Odoo
make restart-odoo
make update MODULE=leads     # -u a module (comma-separate for several)
make odoo-shell              # Odoo shell against cleardeals_19_dev
make psql                    # psql into the dev DB (also reachable on host port 5434)
make wipe                    # destroy dev DB + filestore (prompts)
```

Windows: `.\make.ps1 <target>`.

### Tests

```bash
./run_tests.sh                    # every installable module, exactly as CI does
./run_tests.sh leads              # one module
./run_tests.sh leads properties   # several
REBUILD=1 ./run_tests.sh          # force a fresh image build
KEEP_DB=1 ./run_tests.sh          # leave Postgres up to inspect afterwards
```

It builds `my-odoo-image`, runs Postgres 17 on a private bridge network (no host
ports, so it never clashes with the dev stack) and installs + tests the module
list. **Always run the suite before proposing a change is done.**

The module list is **derived from the tree** — any directory with a manifest that
is not `installable: False`. The same rule is duplicated in `cloudbuild.yaml` and
`cloudbuild.ci.yaml`. If you change the discovery rule, change all three; a new
module must never be able to reach production through a gate that never installed
it.

### WhatsApp local testing

```bash
make wa-config       # print the WA system parameters (key masked) + the container's Pub/Sub env
make wa-interakt     # set the Interakt key from a hidden prompt (never as a make variable)
make wa-tunnel       # cloudflared quick tunnel so Interakt can fetch local media
```

**Run `make wa-config` before any send test.** The dev stack defaults to the
Pub/Sub emulator and `cd-local-*` topics, but the **outbound leg to Interakt
leaves your machine regardless** — the emulator gives no protection there.
Isolation on that leg comes from the account key and nothing else, so it must be
the *test* account's. The key exists in two places that must agree: this repo's
`ir.config_parameter` (`wa_communication.interakt_api_key`, drives the template
picker) and the platform repo's local Kubernetes secret (what actually sends).
Mismatched accounts mean the picker lists templates the sender cannot send.

## Branching and deploy — read before committing

```
feature/*  →  development_19  →  19.0
```

- **`19.0` is production.** A merge there queues an approval-gated Cloud Build
  (`odoo-cd-19`) that builds, gates, pushes and deploys to the production VM.
- **Nothing merges directly to `19.0`.** Everything is promoted through
  `development_19`, which means two PRs, not one.
- Branch protection enforces "up to date with base", so expect to merge
  `19.0` back into `development_19` before a promotion PR can land — that is what
  the recurring "Merge 19.0 into development_19 for the strict up-to-date policy"
  commits are.
- Never push to `19.0` directly. Never force-push a shared branch.

`cloudbuild.ci.yaml` (PRs) and `cloudbuild.yaml` (deploy) deliberately share the
same gates: build → image-contents → config-check → test → push → deploy. Keep
them in step; when CI and deploy each keep their own idea of "the checks", the
first thing anyone notices is a green PR that broke production.

**Editing either cloudbuild file? Use lowercase shell variables only.** Cloud
Build substitutes `$UPPERCASE` *before bash ever runs* and rejects unknown names.
This applies inside `args` strings **including comments in them** — one build
failed because a comment spelled the pattern out literally. Escaping as `$$`
fixes the reference but breaks the assignment (`unbound variable`). Five deploys
died on this; the `deploy-config-check` CI gate now catches it statically.

**The pipeline does not install or upgrade modules by default.** `scripts/deploy.sh`
is an image swap with a health gate and image rollback. A module upgrade is
opt-in via `ODOO_UPGRADE_MODULES` or a one-shot untracked `.deploy-upgrade` file
in the app dir; a first install (`-i`) is deliberately manual and never wired in.
So **shipping new module code does not migrate the schema** — if a change needs
an upgrade, say so explicitly in the PR.

Rollback restores the **image, never the database**. A migration that ran stays
run. Any release with a migration wants a verified `pg_dump -Fc` first.

## Module conventions

```
custom_addons/<module>/
  __manifest__.py
  models/  views/  controllers/  security/  data/  static/  tests/
  migrations/<version>/pre-|post-migrate.py
  README.md
```

- **Bump `__manifest__.py` version in the same commit as any model, view or data
  change.** Odoo only runs a migration and reloads data files when the version
  string increases. An unbumped version means the change silently does not land.
- Access rights in `security/ir.model.access.csv`; record rules in
  `security/*.xml`; both listed in the manifest's `data`.
- Migrations go in `migrations/<manifest version>/pre-migrate.py` or
  `post-migrate.py`. They run against real production rows, so they must be
  idempotent and must tolerate NULLs and pre-existing data.
- Tests are tagged `@tagged('post_install', '-at_install')`, plus a module tag
  where one exists (`'wa_communication'`, `'leads'`). `run_tests.sh` selects by
  `/module` tag, so an untagged test file is a test file that never runs.

## Odoo 19 traps — all verified in the vendored core

These are the ones that have actually bitten this codebase. Each cites the core
source so you can re-check rather than trust this file.

**`_sql_constraints` is gone and fails SILENTLY.** `odoo/orm/model_classes.py:162`
only logs `"Model attribute '_sql_constraints' is no longer supported"` — the
constraint is simply never created, so a uniqueness guarantee you think you have
does not exist. Declare constraints as class attributes instead:

```python
_phone_unique = models.Constraint('UNIQUE(phone)', "Phone must be unique.")
```

(`Constraint` is `odoo/orm/table_objects.py:79`.) The only remaining
`_sql_constraints` in this repo are in the deprecated `property_listings` models,
which is harmless only because they can never be installed.

**A route with `auth='none'` defaults to `readonly=True`.**
`odoo/http.py:924` — `default_mode = ...get('readonly', default_auth == 'none')`.
Any handler that writes must set `readonly=False` explicitly, or it runs in a
read-only transaction and depends on the implicit readonly→read/write retry:
a wasted request in production, and an outright failure under `HttpCase`. See
`custom_addons/wa_communication/controllers/push_controller.py:68`.

**On `auth='none'` routes there is no acting user.** `env.user` is empty and
`env.uid` is `None`, so anything that needs an author (mail tracking, a
`create_uid`-style default, an ownership check) must supply one deliberately.
`wa_communication` handles this in several places — grep for `auth='none'` in its
models before writing a new one.

**`res.users.groups_id` is now `group_ids`**, and implied groups are
`all_group_ids` (a compute over `group_ids.all_implied_ids`) —
`odoo/addons/base/models/res_users.py:257-259`. Code and test fixtures written
against Odoo 18 field names fail with a confusing field error.

## Docker and image traps

**Never `COPY` addons to `/mnt/extra-addons`.** The `odoo:19.0` base image
declares `VOLUME ["/mnt/extra-addons", "/var/lib/odoo"]`, so at runtime Docker
mounts an anonymous empty volume over that path and silently hides whatever was
baked beneath it. **This took production down**: the addons vanished, `leads`
never loaded, view controllers raised `KeyNotFoundError` and crons died on
`KeyError 'leads.new'`. Addons are baked to `/opt/cleardeals-addons`, which is not
a declared volume.

**Addons are baked into the image, not bind-mounted, in staging and production.**
That is what makes an image SHA an honest answer to "what is in production" and
what makes rollback real. Do not add a bind mount "to make it easier" — it
shadows the baked copy and quietly breaks rollback. (The dev stack does mount, on
purpose.)

**The `image-contents` gate requires `ls /opt/cleardeals-addons` to equal
`ls custom_addons` exactly.** Docker does not read `.gitignore`, so a local build
once baked twelve modules from a tree where seven were tracked — including an
entire unreleased suite. Cloud Build takes both sides from git and so is immune;
a build from a dirty working tree is not. Untracked leftovers under
`custom_addons/` (a stale `__pycache__` from a branch you switched away from is
the usual one) will fail that gate locally — clean them rather than working
around it.

**A missing browser makes OWL/Hoot suites skip, not fail.**
`HttpCase.browser_js` looks for chrome/chromium on `PATH` and skips when there is
none, so a suite that never ran looks exactly like one that passed. The Dockerfile
installs Chromium via Playwright (Ubuntu 24.04's `chromium` is a snap stub that
cannot run in a container), and `cleardeals_ui` and `wa_communication` each ship a
`test_browser_harness_is_available` that converts that skip into a failure. If you
see it fail, the browser is missing — do not "fix" it by deleting the test.

## API specs

Every controller route must have an OpenAPI spec in `docs/api/openapi/` (4 specs
split by audience). **CI fails when a route has no spec** — update the spec in the
same commit as any route change. These specs and their gate exist **only on this
branch** (`feature/ml-matching-integration`); nothing enforces them on `19.0` yet.

## Project skills

`.claude/skills/` carries `odoo-clean-code` (the standard for new code),
`odoo-refactor` (behaviour-preserving cleanup) and `odoo-prod-migration-check`
(rehearse a deploy against a read-only production snapshot, locally). Use the
migration-check skill before any release that carries a migration.

## Further reading in-repo

- `docs/wa_production_cutover_plan.md` — the measured state of the WhatsApp
  rollout and its runbook.
- `custom_addons/wa_communication/README_WHATSAPP_SUITE.md` — the suite's own
  architecture notes.
- `custom_addons/leads/controllers/API_DOCUMENTATION.md`, `CHANGELOG.md`,
  `MIGRATION_LOGS.md`.
- `postman/` — request collections for the public endpoints.

Note that `CHECKPOINT.md`, if present in the working tree, is an untracked
personal handoff note and is **stale**. Do not treat it as current.
