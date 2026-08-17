# 17 — Cheat sheet, glossary and first-week exercises

[← Debugging and ops](16-debugging-and-ops.md) · [Index](00-INDEX.md)

---

The reference back-page, and three exercises to prove you have absorbed the rest.

## 17.1 Commands

### Daily

```bash
make up                    # start the stack
make down                  # stop it, keep data
make restart-odoo          # restart Odoo only — the one you'll type most
make logs-odoo             # follow Odoo's log
make status                # docker compose ps

make odoo-shell            # Python REPL with `env` bound
make psql                  # psql on cleardeals_19_dev
make shell                 # bash inside the container

make update MODULE=leads   # apply model/view/data changes
make build                 # rebuild the image
make wipe                  # DESTROY local db + filestore (confirms first)

./run_tests.sh leads       # run one module's tests
```

### `odoo-bin`

```bash
odoo -d DB -i mod1,mod2 --stop-after-init          # install
odoo -d DB -u mod1       --stop-after-init          # update
odoo -d DB -u all        --stop-after-init          # update everything
odoo shell -d DB --no-http                          # REPL
odoo scaffold my_module /mnt/extra-addons/custom    # skeleton
odoo -d DB -i mod --test-enable --test-tags /mod --stop-after-init
```

Inside our container, remember `docker exec` bypasses the entrypoint:

```bash
docker exec -it odoo-dev-app /opt/odoo-venv/bin/python3 /usr/bin/odoo shell -d cleardeals_19_dev
```

### Flags

| Flag | Effect |
|------|--------|
| `-d` | database |
| `-i` / `-u` | install / update modules |
| `--stop-after-init` | do the work, don't serve |
| `--dev=all` | `access,reload,qweb,xml` |
| `--log-level=debug_sql` | log every query |
| `--test-enable` / `--test-tags` | testing |
| `--without-demo=all` | no demo data |
| `--no-http` | with `shell` |

### Test tag grammar

```
[-][tag][/module][:class][.method]

/leads                                    all standard tests in module leads
/wa_communication:TestX.test_y            one method
-at_install                               exclude a tag
```

### URLs

| URL | What |
|-----|------|
| `/odoo` | the web client |
| `/odoo/settings?debug=1` | settings, developer mode on |
| `/web/login` | login / database selector |
| `/web/database/manager` | create, duplicate, backup, restore |
| `/odoo/action-<module>.<xmlid>` | open an action directly |
| `/odoo/action-<module>.<xmlid>/<id>` | open one record |
| `/web/tests?filter=<module>` | Hoot JS tests |
| `/web/content/<id>` | download an attachment |
| `/web/image/<id>/<w>x<h>` | resized image |

## 17.2 Shell one-liners

```python
# Records
env["leads.new"].search([("current_status", "=", "lead")], limit=5)
env["leads.new"].browse(1).read(["name", "phone"])
env.ref("leads.group_lead_score_manager")

# Introspection
sorted(env["wa.conversation"]._fields)
env["wa.message"]._fields["kind"]._description_selection(env)
env["leads.new"]._fields["phone"].required

# Grouping (returns TUPLES in 17+)
env["leads.new"]._read_group([], ["current_status"], ["__count"])

# Security
env["leads.new"].with_user(some_user).search_count([])
print(env["leads.new"].with_user(some_user)._search([]).select())   # the real SQL

# Config
env["ir.config_parameter"].sudo().get_param("wa_communication.interakt_base_url")

# Crons
env["ir.cron"].search([]).read(["cron_name", "active", "nextcall", "failure_count"])

# Cache / flush
env.flush_all(); env.invalidate_all()

# Force a recompute
env["leads.new"].search([])._compute_next_follow_up_date()

# WRITES NEED THIS
env.cr.commit()
```

## 17.3 Fields

| Field | Notes |
|-------|-------|
| `Char`, `Text`, `Html` | `Html` sanitised on write |
| `Integer`, `Float`, `Monetary` | `Float(digits=(16,2))`; `Monetary` needs `currency_field` |
| `Boolean` | |
| `Date`, `Datetime` | **UTC**; use `fields.Datetime.now()`, `fields.Date.context_today(self)` |
| `Selection` | stores the **key**; invalid key raises at write |
| `Binary` | filestore by default; `attachment=False` for a `bytea` column |
| `Json` | `jsonb` |
| `Many2one` | FK column. **Set `ondelete`** |
| `One2many` | stores nothing; needs the inverse field name |
| `Many2many` | join table; name `relation` explicitly |

### Attributes

`required` · `index` · `default` · `readonly` (UI only) · `copy` · `tracking` ·
`groups` (real enforcement) · `help` · `related` · `compute` · `store` ·
`inverse` · `search` · `ondelete` · `domain` · `company_dependent`

### x2many commands

| Tuple | `Command` | Meaning |
|-------|-----------|---------|
| `(0, 0, vals)` | `Command.create(vals)` | create and link |
| `(1, id, vals)` | `Command.update(id, vals)` | update linked |
| `(2, id)` | `Command.delete(id)` | delete |
| `(3, id)` | `Command.unlink(id)` | unlink, keep |
| `(4, id)` | `Command.link(id)` | link existing |
| `(5,)` | `Command.clear()` | unlink all |
| `(6, 0, ids)` | `Command.set(ids)` | replace set |

`from odoo import Command`

## 17.4 Decorators

| Decorator | Use |
|-----------|-----|
| `@api.depends("f", "rel.f")` | compute triggers |
| `@api.depends_context("uid")` | context-sensitive compute |
| `@api.constrains("f")` | validation on create/write of `f` |
| `@api.onchange("f")` | **form-only** convenience defaults |
| `@api.model` | no recordset needed |
| `@api.model_create_multi` | `create` overrides — **always** |
| `@api.returns` | control the return type |
| `@api.autovacuum` | run with the vacuum cron |
| `@tagged(...)` | test selection |

## 17.5 Domains

```python
[("state", "=", "new")]
[("a", "=", 1), ("b", "=", 2)]                       # implicit AND
["|", ("a", "=", 1), ("b", "=", 2)]                  # OR
["&", ("x", "=", 1), "|", ("y", "=", 2), ("z", "=", 3)]
[("user_id.name", "ilike", "asha")]                  # dotted
[(1, "=", 1)]                                        # all records
```

| Operator | Meaning |
|----------|---------|
| `=` `!=` `>` `>=` `<` `<=` | comparison |
| `in` `not in` | membership (give a list) |
| `like` `ilike` | substring; `i` = case-insensitive |
| `=like` `=ilike` | you supply `%` |
| `child_of` `parent_of` | hierarchy |
| `any` `not any` | sub-domain over a relation (19) |

`&` and, `|` or, `!` not — prefix, applying to the following terms.

## 17.6 Views

| Type | Tag |
|------|-----|
| list | `<list>` (was `<tree>`) |
| form | `<form>` |
| search | `<search>` |
| kanban / pivot / graph / calendar / activity | `<kanban>` etc. |

### Odoo 19 expressions — not `attrs`

```xml
<field name="x" invisible="state != 'draft'"/>
<field name="y" required="state == 'done'" readonly="locked"/>
<field name="z" column_invisible="1"/>
```

### Inheritance

```xml
<record id="..." model="ir.ui.view">
    <field name="inherit_id" ref="module.view_id"/>
    <field name="arch" type="xml">
        <xpath expr="//field[@name='phone']" position="after">
            <field name="alt_phone"/>
        </xpath>
        <xpath expr="//field[@name='phone']" position="attributes">
            <attribute name="required">1</attribute>
        </xpath>
    </field>
</record>
```

`position`: `inside` · `after` · `before` · `replace` · `attributes`

## 17.7 Manifest

```python
{
    "name": ..., "version": "19.0.1.0.0", "summary": ..., "description": ...,
    "author": "Cleardeals Technology", "category": ..., "license": "LGPL-3",
    "depends": [...],
    "data": [
        # 1 security, 2 data, 3 wizard views,
        # 4 model views (define actions), 5 menus, 6 inherited views
    ],
    "assets": {"web.assets_backend": [...], "web.assets_unit_tests": [...]},
    "external_dependencies": {"python": [...]},
    "installable": True, "application": False, "auto_install": False,
}
```

## 17.8 Framework tables

| Table | Contents |
|-------|----------|
| `ir_model`, `ir_model_fields` | models and fields |
| `ir_model_data` | external ID → (model, id) |
| `ir_model_access` | ACLs |
| `ir_rule` | record rules |
| `ir_ui_view`, `ir_ui_menu` | views and menus |
| `ir_cron` | scheduled actions |
| `ir_config_parameter` | system parameters |
| `ir_attachment` | files |
| `ir_module_module` | installed modules and versions |

## 17.9 Odoo 19 changes that break older examples

| Was | Now |
|-----|-----|
| `_sql_constraints = [...]` | `models.Constraint("UNIQUE(x)", message=...)` — old form **silently no-ops** |
| `attrs="{'invisible': [...]}"` | `invisible="expr"` |
| `<tree>` | `<list>` |
| `res.groups.category_id` | `privilege_id` → `res.groups.privilege` |
| `read_group()` | `_read_group()` — returns **tuples** |
| `@route(type='json')` | `type='jsonrpc'` (old form deprecated) |
| routes read/write by default | **`auth='none'` ⇒ `readonly=True`** |

## 17.10 Where do I look for X

| Question / symptom | Chapter |
|--------------------|---------|
| What is Odoo, where is our code | [01](01-what-is-odoo.md) |
| Get it running, developer mode, `make` targets | [02](02-getting-started.md) |
| Workers, gevent, crons, limits, request lifecycle | [03](03-server-and-execution-modes.md) |
| Fields, computes, recordsets, transactions, constraints | [04](04-orm-and-database.md) |
| New module, manifest, wizard, install errors | [05](05-writing-a-module.md) |
| Views, xpath, widgets, OWL, assets | [06](06-views-and-web-client.md) |
| ACLs, record rules, `sudo()` | [07](07-security.md) |
| Routes, webhooks, REST, `call_kw` | [08](08-controllers-and-http.md) |
| Random logouts, session storage | [09](09-sessions.md) |
| Attachments, backups, stale JavaScript | [10](10-filestore-and-attachments.md) |
| Data files, `noupdate`, config params, crons | [11](11-data-files-and-crons.md) |
| Schema change on live data | [12](12-migrations.md) |
| Tests, fixtures, mocking, runners | [13](13-testing.md) |
| Pub/Sub, WhatsApp, trace ids | [14](14-integrations.md) |
| Style, commits, skills | [15](15-conventions.md) |
| Logs, profiling, symptom table, deploys | [16](16-debugging-and-ops.md) |

## 17.11 Glossary

**Action** — what to open. `act_window` opens a model in views; `client` runs a JS
component; `server` runs Python.

**Addon / Module** — a directory with `__manifest__.py`. Not a Python module.

**Assets bundle** — a named JS/CSS collection, concatenated and cached as an
`ir.attachment`.

**Chatter** — the message/activity log from `mail.thread`.

**Context** — a dict on the environment carrying `lang`, `tz`, company, and
caller flags like `automated_lead_creation`.

**Cursor (`cr`)** — the PostgreSQL transaction.

**Domain** — a search filter in prefix notation.

**Environment (`env`)** — cursor + user + context. The entry point to everything.

**External ID / XML ID** — `module.identifier`, stored in `ir_model_data`.

**Filestore** — the on-disk directory holding attachment bytes.

**Hoot** — Odoo's browser test runner, at `/web/tests`.

**Mixin** — an `AbstractModel` pulled in via `_inherit`.

**`noupdate`** — data-file flag meaning "create once, never overwrite".

**OWL** — Odoo Web Library, the front-end component framework.

**Prefork** — multi-process server mode (`workers > 0`).

**QWeb** — the XML templating language.

**Recordset** — an ordered collection of records of one model. The core
abstraction; a single record is a recordset of length 1.

**Record rule (`ir.rule`)** — a domain injected into queries, limiting *which
rows*. Group rules are **OR**ed.

**Registry** — the per-database assembly of all model classes after module
loading.

**`sudo()`** — same records, superuser environment, all checks bypassed.

**TransientModel** — a model whose rows are garbage-collected. Wizards.

**Trace id** — correlation id from the WhatsApp platform, prefixed onto Odoo log
lines.

**Wizard** — a short-lived form on a `TransientModel`.

---

## 17.12 First-week exercises

Three graded exercises. Do them in order, on your local stack, on a branch. Each
lists acceptance criteria so you can check yourself.

### Exercise 1 — a field, a constraint and a test

**Goal:** touch the ORM, security and testing without any UI complexity.

Add to `leads.new` a field recording how the buyer prefers to be contacted.

1. Add `preferred_contact_time` — a `Selection` of `morning` / `afternoon` /
   `evening` / `anytime`, defaulting to `anytime`, indexed, with a `help`.
2. Add an `@api.constrains` rejecting `morning` when `current_status` is
   `site_visit_scheduled` **and** `site_visit_scheduled_date` falls in an
   afternoon — with a message that names the conflict and quotes the date.
3. Exempt automated creators via the `automated_lead_creation` context key, the
   way `_check_phone_number` does.
4. Bump the module version and add the field to the lead list and form views.
5. Write tests: the default, the constraint firing, the automated exemption.

**Acceptance criteria**

- [ ] `make update MODULE=leads` is clean, no new WARNING or ERROR
- [ ] the column exists (check via `psql`)
- [ ] the field appears in both views and is editable
- [ ] `./run_tests.sh leads` green
- [ ] the constraint does **not** fire when editing an unrelated field on an
      existing bad row — and you can explain why
      ([Chapter 04](04-orm-and-database.md))
- [ ] no f-strings in logging, trailing commas present, `ruff check` clean

**What it teaches:** [04](04-orm-and-database.md), [05](05-writing-a-module.md),
[13](13-testing.md).

---

### Exercise 2 — a view, a record rule and a menu

**Goal:** the security model, where the OR-across-groups rule actually bites.

Give managers a screen listing leads with no phone number.

1. Add a list view showing name, source, assigned RM, created date; colour rows
   red where `phone` is empty (`decoration-danger`).
2. Add an action with a `domain` restricting it to leads with no phone, and a
   `help` empty state.
3. Add it under a manager-only menu.
4. Add a record rule so **Lead RMs see only their own** rows in this model while
   **managers see all** — then verify you have not accidentally widened anything.
5. Write security tests: an RM sees only theirs; a manager sees all.

**Acceptance criteria**

- [ ] the menu is invisible to a non-manager, and you can state why that is *not*
      security ([Chapter 07](07-security.md))
- [ ] an RM's `search_count` on the model differs from a manager's
- [ ] you can print the SQL a domain compiles to for each user
      (`_search(...).select()`) and point at the rule clause
- [ ] tests assert both directions, using `with_user()` and not `sudo()`
- [ ] you have checked whether any existing group rule already grants
      `[(1,'=',1)]` on this model, and said so in your PR description

**What it teaches:** [06](06-views-and-web-client.md), [07](07-security.md),
[13](13-testing.md).

---

### Exercise 3 — an endpoint and a migration

**Goal:** the outside boundary, plus changing a schema that has data in it.

Expose a read-only endpoint returning a count of leads by status, and backfill a
new column.

1. Add `GET /api/v1/leads/status_summary`, authenticated with a **new**
   `ir.config_parameter` API key compared using `hmac.compare_digest`. Seed the
   parameter empty in a `noupdate="1"` data file; return 503 if unset.
2. Accept an optional `days` query parameter, parsed defensively and **clamped**
   to 1–365.
3. Return `{"success": true, "data": {...}}` via the existing response helpers
   pattern, built with `_read_group`.
4. Add a stored `Boolean` `has_valid_phone` to `leads.new`, computed on write.
5. Write a **migration** to backfill it for existing rows: numbered filename,
   PURPOSE / MIGRATION PLAN / IDEMPOTENCY header, pre-flight check, conditional
   `WHERE`, `cr.rowcount` logged.
6. Tests: the endpoint with a good key, a bad key, no key configured, and a
   `days` value out of range.

**Acceptance criteria**

- [ ] you **restarted** rather than only `-u`, and can say why
      ([Chapter 08](08-controllers-and-http.md))
- [ ] `save_session=False` and `methods=["GET"]` set; you can explain both
- [ ] `readonly` is stated explicitly, and you can say what it defaults to here
- [ ] no key configured ⇒ 503 plus a warning log; wrong key ⇒ 401
- [ ] `days=99999` returns clamped results, not a timeout
- [ ] the migration runs on `-u`, and **running it twice reports zero changes**
- [ ] the version was bumped, and you can explain what happens if it is not
- [ ] no secret committed
- [ ] `./run_tests.sh leads` green

**What it teaches:** [08](08-controllers-and-http.md),
[11](11-data-files-and-crons.md), [12](12-migrations.md),
[13](13-testing.md).

---

### When you finish

Open a pull request for each, written in the house style
([Chapter 15](15-conventions.md)): old behaviour, new behaviour, and the
reasoning behind any scoping decision. Walk the pre-flight checklist in
[Chapter 05](05-writing-a-module.md) §5.13 properly rather than assuming it.

Then pick up a real ticket.

---

[← Debugging and ops](16-debugging-and-ops.md) · [Index](00-INDEX.md)
