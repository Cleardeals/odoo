# 05 — Writing a custom module, end to end

[← The ORM and database](04-orm-and-database.md) · [Index](00-INDEX.md) · [Next: Views and the web client →](06-views-and-web-client.md)

---

This chapter builds a module from an empty directory, explains every file and
every manifest key, and then covers installing, iterating, and the failures you
will hit. It ends with a copy-pasteable skeleton and a pre-flight checklist.

The worked example is a small but genuinely complete module: a **lead callback
request** — an RM records that a buyer asked to be called back at a particular
time, and a manager can see the queue. It is small enough to read in one sitting
and large enough to need a model, a constraint, security, three views, a menu, a
wizard, a data file and tests.

## 5.1 The minimum viable module

The entire contract between Odoo and your directory is two files.

```
lead_callback/
├── __init__.py          ← tells Python what to import
└── __manifest__.py      ← tells Odoo what this module is
```

`__manifest__.py` is a single Python dict — not JSON, not YAML. It is
`eval`'d, so it may contain comments, which we use heavily.

That is enough to appear in the Apps list. It does nothing yet.

## 5.2 The full layout

Here is the shape every non-trivial module in `custom_addons/` follows. Not all
of it is always needed; the *ordering and naming* are the convention.

```
lead_callback/
├── __init__.py                     from . import models, wizard, controllers
├── __manifest__.py
├── README.md                       what this module is for (see Ch15)
├── CHANGELOG.md                    optional; leads/ has one
├── MIGRATION_LOGS.md               optional; a human log of migrations
│
├── models/
│   ├── __init__.py                 from . import lead_callback
│   └── lead_callback.py            one model per file, named after the model
│
├── wizard/
│   ├── __init__.py
│   └── lead_callback_bulk_wizard.py
│
├── controllers/
│   ├── __init__.py
│   └── main.py                     only if you expose HTTP routes
│
├── security/
│   ├── security.xml                groups and record rules
│   └── ir.model.access.csv         ACLs — one line per model per group
│
├── data/
│   └── lead_callback_cron.xml      records shipped with the module
│
├── views/
│   ├── lead_callback_views.xml     views + actions
│   └── lead_callback_menu.xml      menus (separate file — see §5.4)
│
├── static/
│   ├── src/
│   │   ├── js/    xml/    scss/
│   └── tests/                      *.test.js — Hoot unit tests
│
├── migrations/
│   └── 19.0.1.1.0/
│       └── post-01-backfill_x.py
│
└── tests/
    ├── __init__.py
    └── test_lead_callback.py
```

> **Our convention.** One model per Python file, and the file is named after the
> model with dots replaced by underscores: `lead.callback` lives in
> `models/lead_callback.py`. Grep-ability beats cleverness. `leads/models/`
> follows this for all ~15 of its models.

### The `__init__.py` chain

Python has to be told to import each subpackage, and each subpackage has to
import its own modules. There are two levels:

```python
# lead_callback/__init__.py
from . import models
from . import wizard
from . import controllers
```

```python
# lead_callback/models/__init__.py
from . import lead_callback
```

> **Trap.** A model whose file is not imported in `models/__init__.py` **does
> not exist**. No error, no warning — the class is simply never defined, so the
> table is never created and `env["lead.callback"]` raises `KeyError`. This is
> the single most common "why isn't my model there" cause. When you add a model
> file, add the import in the same edit.
>
> Note that our `ruff.toml` deliberately ignores `F401` (unused import) for
> `**/__init__.py` for exactly this reason — these imports look unused to a
> linter but are load-bearing.

## 5.3 The manifest, key by key

Here is our example manifest, followed by a table covering every key you will
ever need.

```python
{
    "name": "Lead Callback Requests",
    "version": "19.0.1.0.0",
    "summary": "Record and queue buyer callback requests against a lead.",
    "description": """
Lets an RM record that a buyer asked to be called back at a specific time,
and gives managers a queue view of everything due.

Adds ``lead.callback`` (one row per request) and a bulk-close wizard.
Overdue requests are flagged by the ``lead_callback.cron_flag_overdue``
scheduled action.
    """,
    "author": "Cleardeals Technology",
    "category": "Sales",
    "license": "LGPL-3",
    "depends": ["base", "mail", "leads"],
    "data": [
        # 1. Security — ALWAYS FIRST.
        "security/security.xml",
        "security/ir.model.access.csv",
        # 2. Data.
        "data/lead_callback_cron.xml",
        # 3. Wizard views.
        "views/lead_callback_bulk_wizard_views.xml",
        # 4. Model views — these define the actions.
        "views/lead_callback_views.xml",
        # 5. Menus — these consume the actions defined above.
        "views/lead_callback_menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "lead_callback/static/src/**/*.js",
            "lead_callback/static/src/**/*.xml",
            "lead_callback/static/src/**/*.scss",
        ],
        "web.assets_unit_tests": [
            "lead_callback/static/tests/**/*.test.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
```

### Every key

| Key | Type | Meaning and gotchas |
|-----|------|---------------------|
| `name` | str | Human-readable, shown in Apps. |
| `version` | str | See §5.3.1 — this drives migrations. |
| `summary` | str | One line, shown on the Apps card. |
| `description` | str | Long form. Ours are substantial; `wa_communication`'s documents the whole inbound/outbound architecture and every config key, which is genuinely the right place for it. |
| `author` | str | `"Cleardeals Technology"`. |
| `category` | str | Groups the module in Apps. |
| `license` | str | **`"LGPL-3"`. Do not omit it.** Odoo warns at every boot otherwise: `Missing 'license' key in manifest for 'my_module', defaulting to LGPL-3`. We run Community, so LGPL-3 is the correct value for every module here. |
| `depends` | list | Modules that must load first. See §5.3.2. |
| `data` | list | XML/CSV files loaded on install and update, **in listed order**. See §5.4. |
| `demo` | list | Files loaded only when demo data is enabled. |
| `assets` | dict | JS/CSS/XML added to named bundles. See [Chapter 06](06-views-and-web-client.md). |
| `external_dependencies` | dict | Non-Odoo requirements, e.g. `{"python": ["google-cloud-pubsub", "google-auth"]}` as in `wa_communication`. Odoo refuses to install if they are missing — which is a feature: it fails loudly at install rather than mysteriously at runtime. |
| `installable` | bool | `False` hides it from Apps entirely. |
| `application` | bool | `True` makes it a top-level "app" rather than a technical module. Ours are mostly `False`; `properties` is `True`. |
| `auto_install` | bool | `True` installs it automatically once all its `depends` are installed. Use for glue modules only. |
| `post_init_hook` / `pre_init_hook` / `uninstall_hook` | str | Names of functions in `__init__.py` to run around install. Prefer a migration script; see [Chapter 12](12-migrations.md). |
| `sequence` | int | Ordering in the Apps list. |

### 5.3.1 Versioning — and an inconsistency to be aware of

The version string is not decoration. **Odoo compares the manifest version
against the installed version in `ir_module_module` to decide whether migration
scripts must run.** Bump it, and `-u` runs your migrations; forget to bump it,
and they are silently skipped.

Two formats are legal, and **our repo currently uses both**:

| Module | Version | Style |
|--------|---------|-------|
| `properties` | `19.0.1.7.0` | Odoo major + module version |
| `cleardeals_dashboards` | `19.0.1.0` | Odoo major + module version (short) |
| `leads` | `1.7.2` | module version only |
| `wa_communication` | `1.3.8` | module version only |
| `cleardeals_ui` | `1.1.3` | module version only |

> **Our convention.** New modules use the full **`19.0.x.y.z`** form, matching
> `properties` and the `odoo-migration-writer` skill. It makes the Odoo major
> explicit, which matters when a module survives a version upgrade, and it means
> the migration directory name matches the manifest exactly.
>
> Do not retro-rename the existing short-form modules — the version is compared
> against what is already in the database, and rewriting it would confuse the
> migration machinery on live installs. Leave `leads` at `1.7.2` and keep
> incrementing it in place.

Bump the **last** segment for a normal change, the middle for a feature, and
only touch the leading Odoo version on an actual Odoo upgrade.

### 5.3.2 `depends` — get this right first

`depends` does three things at once: it forces load order, it makes the other
module's models and fields available to extend, and it makes its external IDs
resolvable in your XML.

```python
"depends": ["base", "mail", "leads"],
```

Rules:

- **`base` is implicit** but conventionally listed anyway.
- Add `mail` if you want `mail.thread` (the chatter) or `mail.activity.mixin`.
- Add `web` if you ship backend assets.
- **Depend on the module that owns anything you reference.** If your XML says
  `ref="leads.group_lead_score_rm"`, you must depend on `leads`, or the install
  fails with a "external ID not found" error.
- **Respect the direction of the graph** from
  [Chapter 01](01-what-is-odoo.md). Do not add a dependency that points
  downward — extend from above instead.

> **Trap.** Adding a dependency is easy; removing one later is not, because
> uninstalling a dependency cascades. Think about direction before you type it.

## 5.4 The `data` list ordering convention

The `data` list is loaded **top to bottom**, and later files can reference
earlier records but not vice versa. Getting the order wrong produces install
failures that look like missing records.

Our ordering is codified — and `leads/__manifest__.py` literally carries the
numbered comments, including a note recording that two entries had to be moved:

```python
"data": [
    # 1. Security (Always First)
    "security/security.xml",
    "security/ir.model.access.csv",
    # 2. Data
    "data/ir_config_parameter_data.xml",
    "data/lead_source_data.xml",
    ...
    # 3. Wizard Views
    "views/lead_score_bq_wizard_views.xml",
    ...
    # 4. Model Views (Defines Actions) -- [MOVED UP]
    "views/lead_score_views.xml",
    "views/leads_bde_views.xml",
    # 5. Menus (Uses Actions defined above) -- [MOVED DOWN]
    "views/lead_score_menu.xml",
    # 6. Other Views (May depend on Menus)
    "views/whatsapp_response_views.xml",
    ...
],
```

The rule and the reason:

| Order | What | Why here |
|-------|------|----------|
| 1 | `security/security.xml` | Groups must exist before anything references them with `groups=`. |
| 2 | `security/ir.model.access.csv` | ACLs reference the groups defined above. |
| 3 | `data/*.xml` | Seed data; may reference groups. |
| 4 | Wizard views | Wizards are referenced by buttons in model views. |
| 5 | Model views **and actions** | An action must exist before a menu points at it. |
| 6 | Menus | Menus consume actions and are gated by groups. |
| 7 | Inherited views of other modules | Safest last. |

> **Our convention.** Keep menus in their **own file**, loaded after all view
> files. This is why `leads` has `lead_score_menu.xml` separate from
> `lead_score_views.xml`. It removes an entire class of ordering bug, because a
> menu can then never be loaded before the action it references.
>
> Where a menu genuinely belongs next to its views (a small module,
> `lead_source_views.xml` defines its own `menuitem`s at the bottom), that is
> acceptable — but the *file* must still come after anything it depends on.

> **Trap.** A file missing from the `data` list is simply never loaded. No
> error. Your view does not appear, your ACL does not apply, your cron does not
> exist. When something you wrote in XML has no effect, check the manifest
> before you debug the XML.

## 5.5 The model

```python
# lead_callback/models/lead_callback.py
"""Buyer callback requests raised against a lead.

One row per request.  A request is created by an RM from the lead form, is due
at ``due_at``, and is closed by an RM or by the bulk wizard.  Overdue requests
are flagged by ``lead_callback.cron_flag_overdue`` rather than by a stored
compute, because "overdue" depends on the clock and the clock is not a field.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class LeadCallback(models.Model):
    _name = "lead.callback"
    _description = "Lead Callback Request"
    _inherit = ["mail.thread"]
    _order = "due_at asc, id desc"
    _rec_name = "display_name"

    # ── Constraints (Odoo 19 declarative style) ──────────────────────────────
    _one_open_per_lead = models.Constraint(
        "UNIQUE(lead_id, state) DEFERRABLE INITIALLY DEFERRED",
        message="This lead already has an open callback request.",
    )

    # ── Fields ───────────────────────────────────────────────────────────────
    lead_id = fields.Many2one(
        "leads.new",
        string="Lead",
        required=True,
        index=True,
        ondelete="cascade",
        help="The enquiry this callback belongs to.",
    )
    requested_by_id = fields.Many2one(
        "res.users",
        string="Requested By",
        required=True,
        index=True,
        default=lambda self: self.env.user,
        ondelete="restrict",
    )
    due_at = fields.Datetime(
        string="Call Back At",
        required=True,
        index=True,
        tracking=True,
        help="When the buyer asked to be called. Stored in UTC.",
    )
    note = fields.Text(string="Note")
    state = fields.Selection(
        [
            ("open", "Open"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="open",
        index=True,
        tracking=True,
    )
    is_overdue = fields.Boolean(
        string="Overdue",
        default=False,
        index=True,
        help="Set by the overdue cron. Not a compute — see the module docstring.",
    )
    phone = fields.Char(related="lead_id.phone", store=True, readonly=True)

    display_name = fields.Char(compute="_compute_display_name", store=True)

    # ── Computes ─────────────────────────────────────────────────────────────
    @api.depends("lead_id.name", "due_at")
    def _compute_display_name(self):
        for rec in self:
            when = fields.Datetime.to_string(rec.due_at) or _("unscheduled")
            rec.display_name = "%s — %s" % (rec.lead_id.name or _("Lead"), when)

    # ── Validation ───────────────────────────────────────────────────────────
    @api.constrains("due_at")
    def _check_due_at_not_in_past(self):
        """Reject a callback scheduled in the past on manual entry only.

        Automated creators (the WhatsApp triage flow) pass
        ``automated_callback_creation`` and are exempt: an event that arrives
        late must still be recorded, and losing it is worse than storing a
        stale due date somebody will correct.
        """
        if self.env.context.get("automated_callback_creation"):
            return
        now = fields.Datetime.now()
        for rec in self:
            if rec.due_at and rec.due_at < now:
                raise ValidationError(
                    _("The callback time %s is in the past.", rec.due_at),
                )

    # ── Actions ──────────────────────────────────────────────────────────────
    def action_mark_done(self):
        """Close these requests. Safe to call on a multi-record set."""
        return self.write({"state": "done", "is_overdue": False})

    # ── Cron ─────────────────────────────────────────────────────────────────
    @api.model
    def _cron_flag_overdue(self):
        """Flag open requests whose time has passed. Idempotent by construction."""
        overdue = self.search([
            ("state", "=", "open"),
            ("due_at", "<", fields.Datetime.now()),
            ("is_overdue", "=", False),
        ])
        if overdue:
            overdue.write({"is_overdue": True})
            _logger.info("Flagged %s callback request(s) overdue", len(overdue))
```

Everything in there was covered in [Chapter 04](04-orm-and-database.md). Note
specifically: `models.Constraint` not `_sql_constraints`; the constraint is
scoped by context exactly as `_check_phone_number` is; `is_overdue` is a plain
stored Boolean driven by a cron rather than a stored compute, because it depends
on the clock.

## 5.6 Security — never skip this

Two files, and the module is broken without them.

**`security/security.xml`** — groups and record rules:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <data>
        <record id="group_callback_user" model="res.groups">
            <field name="name">Callback User</field>
        </record>

        <record id="group_callback_manager" model="res.groups">
            <field name="name">Callback Manager</field>
            <field name="implied_ids" eval="[(4, ref('group_callback_user'))]"/>
        </record>

        <record id="rule_callback_own" model="ir.rule">
            <field name="name">Callbacks: user sees own</field>
            <field name="model_id" ref="model_lead_callback"/>
            <field name="groups" eval="[(4, ref('group_callback_user'))]"/>
            <field name="domain_force">[('requested_by_id', '=', user.id)]</field>
        </record>

        <record id="rule_callback_manager_all" model="ir.rule">
            <field name="name">Callbacks: manager sees all</field>
            <field name="model_id" ref="model_lead_callback"/>
            <field name="groups" eval="[(4, ref('group_callback_manager'))]"/>
            <field name="domain_force">[(1, '=', 1)]</field>
        </record>
    </data>
</odoo>
```

Note `model_id` uses the auto-generated external ID `model_lead_callback` —
Odoo creates `model_<table_name>` for every model, in the module that defines
it. To reference another module's model you qualify it:
`ref="properties.model_property_base"`.

**`security/ir.model.access.csv`** — the ACLs:

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_lead_callback_user,lead.callback.user,model_lead_callback,lead_callback.group_callback_user,1,1,1,0
access_lead_callback_manager,lead.callback.manager,model_lead_callback,lead_callback.group_callback_manager,1,1,1,1
access_lead_callback_bulk_wizard,lead.callback.bulk.wizard,model_lead_callback_bulk_wizard,lead_callback.group_callback_user,1,1,1,1
```

> **Trap.** **Every model needs at least one ACL line, including
> `TransientModel` wizards.** With no line, nobody except uid 1 can touch it,
> and the user gets the access error you saw in
> [Chapter 02](02-getting-started.md). Forgetting the wizard's line is the
> classic version of this bug — the feature works for you (you tested as an
> admin who happened to be in a group that had it) and fails for everyone else.

[Chapter 07](07-security.md) covers the semantics properly, including the
crucial detail that rules across different groups are **OR**ed.

## 5.7 Views, actions and menus

Covered in depth in [Chapter 06](06-views-and-web-client.md). The minimum for a
working module is a list view, a form view, an action and a menu:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_lead_callback_list" model="ir.ui.view">
        <field name="name">lead.callback.list</field>
        <field name="model">lead.callback</field>
        <field name="arch" type="xml">
            <list string="Callback Requests" decoration-danger="is_overdue">
                <field name="due_at"/>
                <field name="lead_id"/>
                <field name="phone"/>
                <field name="requested_by_id"/>
                <field name="state"/>
                <field name="is_overdue" column_invisible="1"/>
            </list>
        </field>
    </record>

    <record id="view_lead_callback_form" model="ir.ui.view">
        <field name="name">lead.callback.form</field>
        <field name="model">lead.callback</field>
        <field name="arch" type="xml">
            <form string="Callback Request">
                <header>
                    <button name="action_mark_done" type="object"
                            string="Mark Done" class="btn-primary"
                            invisible="state != 'open'"/>
                    <field name="state" widget="statusbar"/>
                </header>
                <sheet>
                    <group>
                        <group>
                            <field name="lead_id"/>
                            <field name="phone" readonly="1"/>
                            <field name="due_at"/>
                        </group>
                        <group>
                            <field name="requested_by_id"/>
                            <field name="is_overdue" readonly="1"/>
                        </group>
                    </group>
                    <field name="note" placeholder="What did the buyer ask for?"/>
                </sheet>
                <chatter/>
            </form>
        </field>
    </record>

    <record id="action_lead_callback" model="ir.actions.act_window">
        <field name="name">Callback Requests</field>
        <field name="res_model">lead.callback</field>
        <field name="view_mode">list,form</field>
        <field name="context">{'search_default_open': 1}</field>
        <field name="help" type="html">
            <p class="o_view_nocontent_smiling_face">No callback requests yet.</p>
        </field>
    </record>
</odoo>
```

…and in a separate menu file, loaded afterwards:

```xml
<odoo>
    <menuitem id="menu_lead_callback_root" name="Callbacks" sequence="20"/>
    <menuitem id="menu_lead_callback"
              name="Requests"
              parent="menu_lead_callback_root"
              action="action_lead_callback"
              groups="lead_callback.group_callback_user"
              sequence="10"/>
</odoo>
```

## 5.8 A wizard

A wizard is a `TransientModel` with a form view and an action that opens it as a
dialog. All of ours live in `wizard/`.

```python
# lead_callback/wizard/lead_callback_bulk_wizard.py
"""Bulk-close callback requests selected in the list view."""

from odoo import _, fields, models
from odoo.exceptions import UserError


class LeadCallbackBulkWizard(models.TransientModel):
    _name = "lead.callback.bulk.wizard"
    _description = "Bulk Close Callback Requests"

    callback_ids = fields.Many2many(
        "lead.callback",
        string="Requests",
        default=lambda self: self.env.context.get("active_ids", []),
    )
    resolution = fields.Selection(
        [("done", "Done"), ("cancelled", "Cancelled")],
        required=True,
        default="done",
    )

    def action_apply(self):
        self.ensure_one()
        if not self.callback_ids:
            raise UserError(_("Select at least one request."))
        open_requests = self.callback_ids.filtered(lambda cb: cb.state == "open")
        open_requests.write({"state": self.resolution, "is_overdue": False})
        return {"type": "ir.actions.act_window_close"}
```

Two idioms to note:

- **`default=lambda self: self.env.context.get("active_ids", [])`** is how a
  wizard receives the records the user selected. Odoo puts `active_id`,
  `active_ids` and `active_model` in the context when opening a wizard from a
  list or form.
- **`self.ensure_one()`** raises if the recordset is not exactly one record. Use
  it at the top of any method that assumes a single record — it turns a
  confusing downstream error into a clear one.

The view and the action that opens it:

```xml
<record id="view_lead_callback_bulk_wizard" model="ir.ui.view">
    <field name="name">lead.callback.bulk.wizard.form</field>
    <field name="model">lead.callback.bulk.wizard</field>
    <field name="arch" type="xml">
        <form string="Close Requests">
            <group>
                <field name="resolution"/>
                <field name="callback_ids" widget="many2many_tags" readonly="1"/>
            </group>
            <footer>
                <button name="action_apply" type="object" string="Apply" class="btn-primary"/>
                <button string="Cancel" class="btn-secondary" special="cancel"/>
            </footer>
        </form>
    </field>
</record>

<record id="action_lead_callback_bulk" model="ir.actions.act_window">
    <field name="name">Close Requests</field>
    <field name="res_model">lead.callback.bulk.wizard</field>
    <field name="view_mode">form</field>
    <field name="target">new</field>            <!-- 'new' = modal dialog -->
    <field name="binding_model_id" ref="model_lead_callback"/>
    <field name="binding_view_types">list</field>
</record>
```

`target="new"` makes it a dialog rather than a full page. `binding_model_id`
plus `binding_view_types` puts it in the list view's **Actions** cog menu
automatically — no menu item needed.

## 5.9 A data file

```xml
<!-- lead_callback/data/lead_callback_cron.xml -->
<odoo>
    <data noupdate="1">
        <record id="cron_flag_overdue" model="ir.cron">
            <field name="name">Callbacks: flag overdue</field>
            <field name="model_id" ref="model_lead_callback"/>
            <field name="state">code</field>
            <field name="code">model._cron_flag_overdue()</field>
            <field name="interval_number">15</field>
            <field name="interval_type">minutes</field>
            <field name="active" eval="True"/>
        </record>
    </data>
</odoo>
```

`noupdate="1"` means "create this on install, then never overwrite it on
subsequent updates" — which is right for a cron whose schedule an administrator
may tune in the UI. It is also a trap in the other direction; see
[Chapter 11](11-data-files-and-crons.md).

## 5.10 Installing and iterating

```bash
# Install for the first time.
docker compose -f docker-compose.dev.yml exec odoo python3 /usr/bin/odoo \
  -d cleardeals_19_dev -i lead_callback --stop-after-init
make restart-odoo

# Iterate after a change.
make update MODULE=lead_callback
```

You can also install from the UI — Apps → search → Activate — after clicking
*Update Apps List* so Odoo rescans the addons path for new directories. The CLI
is faster and shows you the traceback.

### Reading install failures

The traceback is long but it is structured, and the useful part is at the
bottom. Real example from this repository:

```
ValueError: Invalid field 'category_id' in 'res.groups'

The above exception was the direct cause of the following exception:
...
odoo.tools.convert.ParseError: while parsing
/mnt/extra-addons/custom/property_listings/security/security.xml:10,
somewhere inside
<record id="group_property_listings_rm" model="res.groups">
```

Read it bottom-up: **which file and line**, **which record**, then **what was
wrong**. Here: a field that no longer exists in Odoo 19.

Common failures and what they actually mean:

| Message | Cause |
|---------|-------|
| `KeyError: 'lead.callback'` at runtime | Model file not imported in `models/__init__.py` (§5.2) |
| `External ID not found in the system: leads.xyz` | Missing `depends`, or a typo, or the referenced file is later in `data` |
| `ValueError: Invalid field 'x' in 'model'` | The field does not exist — often an Odoo version change |
| `ParseError: while parsing …:NN` | Broken XML or a bad `ref`; the line number is exact |
| `Element '<xpath expr="...">' cannot be located` | An inherited view's xpath no longer matches ([Chapter 06](06-views-and-web-client.md)) |
| `psycopg2.errors.UndefinedColumn` | Schema out of date — you edited a field but did not `-u` |
| `Model attribute '_sql_constraints' is no longer supported` (WARNING) | Odoo 19 — migrate to `models.Constraint` ([Chapter 04](04-orm-and-database.md)) |
| `Missing 'license' key in manifest` (WARNING) | Add `"license": "LGPL-3"` |
| `Model x.y has no table` (ERROR) | `_auto = False`, or an `AbstractModel` where you wanted a `Model` |

### `odoo scaffold`

Odoo can generate a skeleton:

```bash
docker compose -f docker-compose.dev.yml exec odoo python3 /usr/bin/odoo \
  scaffold lead_callback /mnt/extra-addons/custom
```

It produces upstream's default layout, which is close to but not identical to
ours — no `wizard/`, no `security/security.xml`, no numbered `data` comments.
Useful as a starting point; adjust to §5.2 afterwards.

## 5.11 Tests

Never optional. `tests/__init__.py` must import your test modules, exactly like
`models/__init__.py`:

```python
# lead_callback/tests/__init__.py
from . import test_lead_callback
```

```python
# lead_callback/tests/test_lead_callback.py
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLeadCallback(TransactionCase):

    def setUp(self):
        super().setUp()
        source = self.env["leads.new"]._get_or_create_source("TestSource")
        self.lead = self.env["leads.new"].with_context(
            automated_lead_creation=True,
        ).create({"name": "Test Buyer", "source_id": source.id})

    def test_past_due_at_is_rejected_for_manual_entry(self):
        with self.assertRaises(ValidationError):
            self.env["lead.callback"].create({
                "lead_id": self.lead.id,
                "due_at": "2020-01-01 09:00:00",
            })

    def test_automated_creation_may_be_in_the_past(self):
        callback = self.env["lead.callback"].with_context(
            automated_callback_creation=True,
        ).create({"lead_id": self.lead.id, "due_at": "2020-01-01 09:00:00"})
        self.assertEqual(callback.state, "open")
```

Then register the module with the runners so it is actually gated in CI — add it
to `DEFAULT_MODULES` and `DEFAULT_TAGS` in `run_tests.sh` **and** to the
`-i`/`--test-tags` lists in `.github/workflows/test.yml`. See
[Chapter 13](13-testing.md), which also explains why forgetting the CI half is a
real and current problem in this repo.

## 5.12 The skeleton

Copy this to start.

```
my_module/
├── __init__.py                 from . import models
├── __manifest__.py             (below)
├── README.md
├── models/
│   ├── __init__.py             from . import my_model
│   └── my_model.py
├── security/
│   ├── security.xml
│   └── ir.model.access.csv
├── views/
│   ├── my_model_views.xml
│   └── my_model_menu.xml
└── tests/
    ├── __init__.py             from . import test_my_model
    └── test_my_model.py
```

```python
{
    "name": "My Module",
    "version": "19.0.1.0.0",
    "summary": "One line.",
    "author": "Cleardeals Technology",
    "category": "Sales",
    "license": "LGPL-3",
    "depends": ["base", "mail"],
    "data": [
        # 1. Security (always first)
        "security/security.xml",
        "security/ir.model.access.csv",
        # 2. Data
        # 3. Wizard views
        # 4. Model views (define actions)
        "views/my_model_views.xml",
        # 5. Menus (use the actions above)
        "views/my_model_menu.xml",
        # 6. Inherited views of other modules
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
```

## 5.13 Pre-flight checklist

Before you open a pull request on a new or changed module:

**Manifest**
- [ ] `version` bumped (and a migration written if the schema changed)
- [ ] `license` present
- [ ] every new file added to `data`, in the right ordering band
- [ ] `depends` covers every module you `ref` or extend
- [ ] `external_dependencies` declared for any new Python package

**Code**
- [ ] every new model file imported in `models/__init__.py`
- [ ] `_description` on every model
- [ ] `ondelete` set deliberately on every `Many2one`
- [ ] `index=True` on fields you filter or sort by
- [ ] constraints use `models.Constraint`, not `_sql_constraints`
- [ ] `@api.model_create_multi` on any `create` override
- [ ] no `sudo()` without a comment saying why

**Security**
- [ ] an ACL line for **every** model, including wizards
- [ ] record rules for both the user and manager cases
- [ ] checked that OR-across-groups does not accidentally widen access
      ([Chapter 07](07-security.md))

**Verification**
- [ ] installs clean on a fresh database
- [ ] `make update MODULE=…` is clean on an existing one
- [ ] no new WARNING or ERROR lines at boot
- [ ] tests written, and the module registered in `run_tests.sh` **and**
      `.github/workflows/test.yml`
- [ ] `./run_tests.sh my_module` green

---

[← The ORM and database](04-orm-and-database.md) · [Index](00-INDEX.md) · [Next: Views and the web client →](06-views-and-web-client.md)
