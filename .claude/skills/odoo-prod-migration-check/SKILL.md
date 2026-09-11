---
name: odoo-prod-migration-check
description: >-
  Rehearse an Odoo deployment against a fresh, READ-ONLY snapshot of the
  production database, entirely on the local machine, to prove that the modules
  about to be deployed upgrade cleanly (migrations run, no errors, no data loss)
  BEFORE pushing to production. Use whenever the user wants to "test the
  migration against prod", "check this before deploying", "run a pre-deploy /
  pre-push migration check", "rehearse the upgrade on real data", or "take a
  prod DB snapshot and verify migrations". Production is only ever READ — the
  snapshot is streamed over SSH and nothing is written to the prod VM or DB.
---

# Odoo prod migration check (pre-deploy rehearsal)

## What this does
Takes a **read-only** snapshot of the production Odoo Postgres database, restores
it into a throwaway local Postgres container, runs `odoo -u <modules>` with the
**current working-tree code** against that copy, and reports whether the upgrade
(including any `pre-migrate`/`post-migrate` scripts) runs cleanly and losslessly.

This is the automated version of the "staging rehearsal" every risky migration
should get — but against a real prod snapshot, on the local machine, in minutes.

## Safety guarantees (state these to the user)
- **Production is READ-ONLY.** The snapshot is taken by streaming `pg_dump` over
  SSH straight to local stdout — **nothing is written to the prod VM's disk and
  nothing is written to the prod database.**
- All restore + upgrade work happens in **disposable local containers** that are
  removed on exit (unless `KEEP=1`).
- The restored DB contains real customer data (leads, phones). It stays local;
  offer to remove it when done (`docker rm -f prodcheck_db`).

## How to run it
From the repo root:

```bash
# auto-detect which installed modules have a higher code version than prod,
# and rehearse upgrading exactly those:
.claude/skills/odoo-prod-migration-check/prod_migration_check.sh

# or rehearse a specific set (matches the intended deploy command):
.claude/skills/odoo-prod-migration-check/prod_migration_check.sh properties leads

# keep the restored DB up afterwards to poke around, and save the log:
KEEP=1 .claude/skills/odoo-prod-migration-check/prod_migration_check.sh
```

Prerequisites: Docker running, `gcloud` authenticated with access to the prod
project, and the local Odoo image built (`./run_tests.sh` once builds
`my-odoo-image`). Works on macOS, Linux, WSL2, and Git Bash.

## Configuration (env overrides)
The defaults target the Cleardeals prod VM; override for a different environment:

| Var | Default | Meaning |
|---|---|---|
| `GCP_ZONE` | `us-central1-f` | prod VM zone |
| `GCP_INSTANCE` | `odoo-19-prod` | prod VM name |
| `GCP_PROJECT` | `odoo-472708` | GCP project |
| `PROD_DB_CONTAINER` | `odoo-project-db-1` | Postgres container on the VM |
| `PROD_DB_NAME` | `odoo_db` | prod database name |
| `PROD_DB_USER` | `odoo` | prod DB role |
| `IMAGE_NAME` | `my-odoo-image` | local Odoo image |
| `REUSE_DUMP` | *(unset)* | path to an existing dump to skip the SSH snapshot |
| `KEEP` | `0` | `1` = leave the local DB/containers up and copy the log |

## How to read the result
- **PASS**: Odoo exits 0, no real Odoo `ERROR`/`CRITICAL`/`Traceback`, and version
  numbers advanced. The `── Migration log ──` block shows each upgrade step and
  any backfill/drop counts.
- **Backfill counts** (for data-moving migrations): a non-zero "safety-net
  backfilled N row(s)" is fine — it means the migration rescued rows the earlier
  migrations missed, and the drop is still lossless. A **large or surprising** N
  is a signal to investigate data lineage before trusting prod (it is not a
  failure by itself). Cross-check that the destination table grew by the total N.
- **FAIL**: any real Odoo error or non-zero exit → **do not deploy**; the full
  log is copied to `./prod_migration_check.log`.
- **Ignore** `(ERROR/3)` / `(WARNING/2)` lines prefixed with `<string>:NN:` —
  those are docutils RST-rendering warnings of module description text, not code
  errors, and the script already excludes them from the verdict.

## Notes / gotchas the script already handles
- `pg_restore` over TCP needs `PGPASSWORD` (set automatically).
- Restore uses `--no-owner --no-privileges` so it is independent of prod DB roles.
- `pg_dump`/`pg_restore` run from a matching Postgres image (major version must
  match prod — currently 17; override `PG_IMAGE`).
- Docker on the prod VM needs `sudo` (the SSH user isn't in the docker group).
- The filestore (attachments) is **not** copied — it isn't needed to exercise
  migrations. This check validates the DB upgrade, not attachment integrity.

## When NOT to rely on this alone
This proves the schema/data migration path. It does not exercise the running
app's HTTP surface or the filestore. Pair it with `./run_tests.sh` (the test
suite) for behavioural coverage.
