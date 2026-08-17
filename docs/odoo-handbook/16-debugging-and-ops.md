# 16 — Debugging, observability and operations

[← Conventions](15-conventions.md) · [Index](00-INDEX.md) · [Next: Cheat sheet and exercises →](17-cheatsheet-and-exercises.md)

---

Everything in this chapter is a tool for answering "why is it doing that?". The
symptom table in §16.8 is the most useful part; read it once now so you recognise
the shapes later.

## 16.1 Logs

### Configuring them

```ini
logfile =                                   ; empty → stdout
log_level = info
log_handler = :INFO,werkzeug:WARNING
```

`log_handler` sets levels per logger, comma-separated as `logger:LEVEL`. An empty
logger name is the root. So the line above means "everything at INFO, except
werkzeug at WARNING", which suppresses the per-request access log that otherwise
floods the terminal.

Useful combinations:

```ini
; Debug one module only — the most valuable form.
log_handler = :INFO,odoo.addons.wa_communication:DEBUG

; Every SQL statement the ORM emits. Very loud, occasionally essential.
log_level = debug_sql

; See HTTP routing again.
log_handler = :INFO
```

| `log_level` | What you get |
|-------------|--------------|
| `critical`, `error`, `warn` | progressively less |
| `info` | the default; module loading, crons, requests |
| `debug` | ORM internals, cache behaviour |
| `debug_sql` | **every query** |
| `debug_rpc` / `debug_rpc_answer` | RPC calls and their responses |
| `test` | what the test runner uses |

Reading them:

```bash
make logs-odoo                                  # follow
make logs-odoo | grep -E "ERROR|CRITICAL"       # just the bad news
docker compose -f docker-compose.dev.yml logs --since 10m odoo
```

### `--dev` flags

From `ODOO_DEV=all` ([Chapter 02](02-getting-started.md)):

| Flag | Effect |
|------|--------|
| `reload` | restart on Python change (needs VirtioFS on macOS) |
| `xml` | reload XML views without restart |
| `qweb` | log the compiled template when a QWeb render fails |
| `access` | **full traceback for permission errors** instead of a bare message |

> **`--dev=access` is underused.** An `AccessError` normally tells you the model
> and the groups; with this flag you get the stack that triggered it, which is how
> you find out *which* line tripped a record rule.

## 16.2 The debug menu

Covered in [Chapter 02](02-getting-started.md) §2.5, and it is the first thing to
reach for. The four items that solve most problems:

| Item | Solves |
|------|--------|
| **Computed Arch** | "my xpath doesn't match" / "the view isn't what I wrote" |
| **Regenerate Assets** | "my JavaScript change won't appear" |
| **Access Rights / Record Rules** | "why can't this user see it" |
| **Become Superuser** | "is this actually a permissions problem?" |

![The debug menu](images/24-debug-menu.png)

> **Our convention.** *Become Superuser* is for **diagnosis**, not for getting
> work done. If a flow only works as superuser, that is the bug — go fix the ACL
> or rule ([Chapter 07](07-security.md)).

## 16.3 The shell

`make odoo-shell` is the most efficient debugging tool available, because you can
interrogate live state instead of guessing.

```python
# Is this record what I think it is?
>>> lead = env["leads.new"].browse(1)
>>> lead.read(["name", "phone", "current_status", "user_id"])

# What does a specific user actually see? (record rules applied)
>>> rm = env["res.users"].search([("login", "=", "asha.rm")])
>>> env["leads.new"].with_user(rm).search_count([])

# Why can't they see it — ACL or rule?
>>> env["ir.model.access"].search([("model_id.model", "=", "leads.new")]).read(
...     ["name", "group_id", "perm_read", "perm_write"])
>>> env["ir.rule"].search([("model_id.model", "=", "leads.new")]).read(
...     ["name", "groups", "domain_force"])

# What SQL does a domain actually produce?
>>> query = env["leads.new"].with_user(rm)._search([("current_status", "=", "lead")])
>>> print(query.select())

# Force a recompute to test a compute change.
>>> env["leads.new"].search([])._compute_next_follow_up_date()

# Inspect a config parameter.
>>> env["ir.config_parameter"].sudo().get_param("wa_communication.topic_actor_events")

# Which cron ran when?
>>> env["ir.cron"].search([]).read(["cron_name", "active", "nextcall", "lastcall", "failure_count"])

# Trigger a cron by hand.
>>> env["wa.reassignment.request"]._cron_release_stuck_confirming()
>>> env.cr.commit()
```

> **Trap.** The shell never commits for you. Reads are free; **any write needs
> `env.cr.commit()`** or it is silently rolled back on exit.

`query.select()` is worth remembering — it shows you the SQL a domain compiles
to, **including the record-rule clauses**, which is the definitive answer to "why
is this row missing".

## 16.4 Breakpoints

```python
def my_method(self):
    breakpoint()          # plain pdb, in the log stream
```

For that to be usable you need to be attached to the process:

```bash
docker compose -f docker-compose.dev.yml exec odoo bash
```

> **Our convention.** Set `workers = 0` in `odoo.dev.conf` before an interactive
> debugging session. In prefork mode you cannot predict which worker handles your
> request, and the master's `limit_time_real` watchdog will `SIGKILL` the worker
> you are paused in ([Chapter 03](03-server-and-execution-modes.md)). Threaded
> mode has neither problem. Remember that websockets stop working while you are
> there.

For remote debugging, `debugpy` and a published port works, but for most Odoo
problems the shell plus a `_logger.info` is faster than a debugger.

## 16.5 SQL-level debugging

```bash
make psql
```

```sql
-- What is actually running right now, and for how long?
SELECT pid, now() - query_start AS duration, state, left(query, 120)
FROM pg_stat_activity
WHERE datname = current_database() AND state <> 'idle'
ORDER BY duration DESC;

-- Lock contention: who is blocking whom?
SELECT blocked.pid AS blocked_pid,
       blocking.pid AS blocking_pid,
       left(blocked.query, 80)  AS blocked_query,
       left(blocking.query, 80) AS blocking_query
FROM pg_stat_activity blocked
JOIN pg_stat_activity blocking
  ON blocking.pid = ANY(pg_blocking_pids(blocked.pid))
WHERE blocked.datname = current_database();

-- Is a query slow for want of an index?
EXPLAIN ANALYZE SELECT * FROM leads_new WHERE phone = '9812340001';

-- Table sizes.
SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) AS size
FROM pg_catalog.pg_statio_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 15;
```

Introspection tables (`ir_model`, `ir_model_fields`, `ir_model_data`, `ir_rule`,
`ir_cron`) are listed in [Chapter 04](04-orm-and-database.md) §4.13.

## 16.6 Profiling

Odoo ships a profiler (`odoo/tools/profiler.py`, with speedscope output at
`odoo/tools/speedscope.py`). Turn it on from the debug menu → **Enable
profiling**, exercise the slow screen, then open the recorded profile.

For code you can reach directly:

```python
from odoo.tools.profiler import Profiler

with Profiler():
    env["leads.new"].search([])._compute_next_follow_up_date()
```

What it usually tells you, in order of frequency:

1. **N+1** — a `search()` or `browse()` inside a loop
   ([Chapter 04](04-orm-and-database.md)).
2. **A missing index** on a field used in a domain or a record rule.
3. **A record rule with a join** in `domain_force`, applied to every query
   ([Chapter 07](07-security.md)).
4. **A non-stored compute** being evaluated per row in a list view.

## 16.7 Trace correlation across the platform

For anything involving WhatsApp, the `trace_id` is the fastest path from a
customer report to a log line.

The platform mints it at ingress; Odoo binds it for the duration of each
`/wa/pubsub/push` request so **every** log line in that request is prefixed
([Chapter 14](14-integrations.md)):

```
2026-08-08 09:41:20 INFO handbook odoo.addons.wa_communication...: [trace=abc123] inbound message ...
```

So:

```bash
# Everything Odoo did for one platform event.
make logs-odoo | grep 'trace=abc123'
```

And the same id is stored on the `wa.event.log` row, so you can go the other way:

```python
>>> env["wa.event.log"].search([("trace_id", "=", "abc123")]).read()
```

> **Our convention.** When investigating a WhatsApp issue, get the `trace_id`
> first. It turns a search across two systems into two greps.

## 16.8 Symptom → cause → fix

The table to skim now and return to later.

| Symptom | Cause | Fix |
|---------|-------|-----|
| `KeyError: 'my.model'` | model file not imported in `models/__init__.py` | add the import ([05](05-writing-a-module.md)) |
| Test file never runs | not imported in `tests/__init__.py`, or module absent from CI lists | add it in all the required places ([13](13-testing.md)) |
| `AccessError` naming groups | user not in a group the ACL grants | add the group, or add the ACL line ([07](07-security.md)) |
| User sees no rows but no error | a record rule filters them | `search()` filters where `read()` raises; inspect `ir_rule` ([07](07-security.md)) |
| `admin` gets an access error | `admin` is not a superuser | it needs the group like anyone else ([07](07-security.md)) |
| Permission fix from `odoo shell` has no effect | per-registry cache in the running process | `make restart-odoo` ([03](03-server-and-execution-modes.md)) |
| View edit has no effect | views are database records | `make update MODULE=…` ([06](06-views-and-web-client.md)) |
| `xpath … cannot be located` | element absent, or another module got there first | debug menu → **Computed Arch** ([06](06-views-and-web-client.md)) |
| JS/SCSS change never appears | cached asset-bundle attachment | debug menu → **Regenerate Assets** ([10](10-filestore-and-attachments.md)) |
| Python change has no effect | auto-reload did not fire | `make restart-odoo`; check VirtioFS ([02](02-getting-started.md)) |
| New route 404s | routing map built at registry load | restart, do not just `-u` ([08](08-controllers-and-http.md)) |
| Endpoint writes fail / double-executes | `auth='none'` defaults to `readonly=True` | declare `readonly=False` ([08](08-controllers-and-http.md)) |
| `psycopg2.errors.UndefinedColumn` | schema behind the code | `make update MODULE=…` ([05](05-writing-a-module.md)) |
| Uniqueness silently not enforced | model still uses removed `_sql_constraints` | migrate to `models.Constraint` ([04](04-orm-and-database.md)) |
| Migration did not run | manifest version not bumped, or fresh install | bump it; migrations never run on install ([12](12-migrations.md)) |
| Stored compute is stale | its real dependency is not in `@api.depends` (often time) | add a cron, or recompute in a migration ([04](04-orm-and-database.md)) |
| DB and Python disagree | ORM cache / deferred writes vs raw SQL | `flush_all()` before reading, `invalidate_all()` after writing ([04](04-orm-and-database.md)) |
| Data-file edit ignored | the record is `noupdate="1"` | write a migration ([11](11-data-files-and-crons.md)) |
| Config value ignored | option is `file_exportable=False` | set it via environment, e.g. `ODOO_DEV` ([03](03-server-and-execution-modes.md)) |
| Worker vanishes, no traceback | `limit_time_real` → master `SIGKILL` | raise the limit, or make the request faster ([03](03-server-and-execution-modes.md)) |
| Serialization failure in the log | concurrent writes; framework retries up to 5× | fine — unless you swallow it ([03](03-server-and-execution-modes.md)) |
| A write silently disappeared | `except Exception` swallowed a concurrency error | re-raise the retryable classes ([08](08-controllers-and-http.md)) |
| Random logouts | multiple servers, unshared `data_dir` | shared volume or sticky sessions ([09](09-sessions.md)) |
| Attachments all broken after restore | database restored without the filestore | restore both together ([10](10-filestore-and-attachments.md)) |
| Disk/inodes filling with tiny files | machine endpoints without `save_session=False`, or GC/vacuum crons off | set the flag; check Scheduled Actions ([09](09-sessions.md)) |
| WhatsApp event never arrived | in-flight publish lost on worker exit | known gap; check the sweeper ([14](14-integrations.md)) |
| Workflow toggle vanishes | `GCP_ENV` unset → publishes to `cd-local-*` | set it ([14](14-integrations.md)) |
| Websockets/bell dead locally | `workers = 0`, so no gevent process | set `workers = 2` ([03](03-server-and-execution-modes.md)) |
| Developer mode keeps turning off | `debug` lives in the session | re-append `?debug=1` ([09](09-sessions.md)) |
| `Invalid field 'category_id' in 'res.groups'` | Odoo 19 rename | use `privilege_id`, or drop it ([07](07-security.md)) |
| Boot: `Model x has no table` | `_auto = False`, or `AbstractModel` vs `Model` | intentional for our two analytics models ([04](04-orm-and-database.md)) |
| Boot: `Missing 'license' key` | manifest incomplete | add `"license": "LGPL-3"` ([05](05-writing-a-module.md)) |
| Git Bash: "Invalid tag", 0 tests | MSYS path rewriting mangles `/leads` | `run_tests.sh` already handles it ([13](13-testing.md)) |

## 16.9 Environments

| Environment | Where | Notes |
|-------------|-------|-------|
| **Local** | Docker on your machine | `docker-compose.dev.yml`, port 8069. ⚠️ ships pointed at **production** Pub/Sub |
| **Staging** | GCP VM `odoo-stage` (zone `us-central1-c`, project `odoo-472708`) | wired to production Pub/Sub and the platform database |
| **Production** | GCP VM, deployed by CI | `19.0` branch |

> **Our convention.** **All staging changes go to the `odoo-stage` VM** — reach it
> over SSH with `gcloud`. Do not create a parallel staging environment.

### Deployment

`.github/workflows/deploy.yml` is triggered by the **successful completion** of
the test workflow on `19.0`:

```yaml
on:
  workflow_run:
    workflows: ["Run Odoo Tests"]
    branches: ["19.0"]
    types: [completed]
...
if: ${{ github.event.workflow_run.conclusion == 'success' }}
```

It then SSHes to the VM, fetches `19.0`, `git reset --hard origin/19.0`, writes
`odoo.conf` from a secret, rebuilds the image and recreates the container.

Two consequences worth internalising:

- **Tests gate the deploy.** A red test run means no deployment. That is also why
  the CI gaps in [Chapter 13](13-testing.md) matter: anything CI does not run
  cannot block a bad deploy.
- **`git reset --hard`** means the VM's working tree is disposable. Never edit
  files on the production VM; the next deploy discards them.

### Deploying a migration

Ordering, from [Chapter 12](12-migrations.md):

1. Rehearse against a read-only production snapshot
   (`odoo-prod-migration-check`).
2. Merge to `19.0`; tests must pass.
3. Deploy runs, the container is recreated, and `-u` executes the migration.
4. **Read the deploy log** and check your per-step counts are what you predicted.

## 16.10 Health checks

```bash
# Is it up?
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8069/web/login   # expect 303

# Anything bad since the last restart?
make logs-odoo | grep -E "ERROR|CRITICAL" | tail -30

# Crons healthy? (failure_count should be 0)
```

```sql
SELECT cron_name, active, nextcall, lastcall, failure_count
FROM ir_cron ORDER BY failure_count DESC, nextcall;
```

```bash
# Session and filestore growth.
docker exec odoo-dev-app find /var/lib/odoo/sessions -type f | wc -l
docker exec odoo-dev-app du -sh /var/lib/odoo/filestore/*
```

```sql
-- Queued WhatsApp messages that never advanced — the §14.4 symptom.
SELECT count(*) FROM wa_message
WHERE status = 'queued' AND create_date < now() - interval '10 minutes';
```

> **Our convention.** That last query is the canary for the deferred Pub/Sub gap
> ([Chapter 14](14-integrations.md)). A non-zero, growing count means publishes
> are being lost, not that WhatsApp is slow.

## 16.11 What to take away

1. `log_handler = :INFO,odoo.addons.<module>:DEBUG` to debug one module without
   drowning.
2. `--dev=access` gives you the traceback behind an `AccessError`.
3. **Computed Arch** and **Regenerate Assets** solve a large share of confusing
   UI problems.
4. `make odoo-shell` plus `query.select()` answers "why is this row missing"
   definitively — and remember to commit.
5. `workers = 0` before you attach a debugger.
6. Get the `trace_id` first for anything WhatsApp.
7. Tests gate the deploy, and the VM working tree is disposable.
8. Read the §16.8 table once now; it will save you hours later.

---

[← Conventions](15-conventions.md) · [Index](00-INDEX.md) · [Next: Cheat sheet and exercises →](17-cheatsheet-and-exercises.md)
