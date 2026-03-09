# Copilot Instructions for Odoo HRMS Project

## Python Code Standards

### Imports
- Always place imports at the top of the file
- Use this order: standard library, third-party, Odoo, local
- Example:
```pythonimport base64
from datetime import datetimefrom odoo import models, fields, api
from odoo.exceptions import ValidationErrorfrom . import other_module

### Logging
- NEVER use f-strings in logging statements
- Always use lazy formatting with %s placeholders
- ❌ BAD: `_logger.info(f"Processing {record.id}")`
- ✅ GOOD: `_logger.info("Processing %s", record.id)`

### Variable Naming
- Never use ambiguous single-letter variables like `l` (lowercase L)
- Use descriptive names: `line` not `l`, `record` not `r`
- ❌ BAD: `lambda l: l.is_required`
- ✅ GOOD: `lambda line: line.is_required`

### Trailing Commas (COM812)
- **MANDATORY**: Always include a trailing comma for the last item in multi-line data structures (dicts, lists, tuples) and function calls
- This ensures cleaner git diffs (1 line change vs 2) and correct behavior for auto-formatters
- ❌ BAD:
```python
child = self.Category.create({
    "name": "Child",
    "parent_id": parent.id
})
```
- ✅ GOOD:
```python
child = self.Category.create({
    "name": "Child",
    "parent_id": parent.id,
})
```

### Exception Handling
- Never catch blind `Exception` unless absolutely necessary
- Always catch specific exceptions: `ValidationError`, `AccessError`, etc.
- ❌ BAD: `except Exception:`
- ✅ GOOD: `except (ValidationError, AccessError):`

### Return Statements
- Avoid unnecessary variable assignment before return (RET504)
- Return directly when possible
- ❌ BAD:
```python
def get_pdf():
    pdf_content = b"%PDF-1.4..."
    return pdf_content
```
- ✅ GOOD:
```python
def get_pdf():
    return b"%PDF-1.4..."
```
- Exception: Use assignment when it improves readability for complex expressions

### Odoo-Specific Patterns
- Function calls in default arguments are okay: `fields.Date.today`
- Use camelCase for Odoo method names: `_compute_field_name`
- Use snake_case for regular Python functions

### Type Hints (Python 3.10+)
- Use modern type hints: `dict`, `list`, `tuple` (not `Dict`, `List`, `Tuple`)
- ❌ BAD: `def func() -> Dict[str, List[int]]:`
- ✅ GOOD: `def func() -> dict[str, list[int]]:`

### Encoding Declarations
- Do NOT add `# -*- coding: utf-8 -*-` (unnecessary in Python 3)

### Line Length
- Maximum 100 characters per line
- Break long lines appropriately

## Testing Standards

### Test Variables
- Always use test variables meaningfully or don't assign them
- ❌ BAD: `docs = Model.search([])  # never used`
- ✅ GOOD: `docs = Model.search([]); self.assertTrue(docs)`

### Testing Model Field Properties
- When testing model-level field properties (like `translate`, field type, etc.), access the field directly from the model class
- Do NOT create an instance if you're only inspecting field metadata
- ❌ BAD:
```python
def test_field_translatable(self):
    record = self.Model.create({"name": "Test"})  # Unnecessary
    field = self.Model._fields["name"]
    self.assertTrue(field.translate)
```
- ✅ GOOD:
```python
def test_field_translatable(self):
    field = self.Model._fields["name"]
    self.assertTrue(field.translate)
```

### Security Tests
- For access tests, always assert something or use `with self.assertRaises(AccessError):`
- Don't just call methods without verification

## File Organization

### Odoo Module Structuremodule_name/
├── init.py
├── manifest.py
├── models/
│   ├── init.py
│   └── model_name.py
├── views/
│   └── views.xml
├── security/
│   └── ir.model.access.csv
└── tests/
├── init.py
└── test_model.py

## XML Standards (Odoo Views)

### Menu Items
- Keep attributes on same line when concise
- Use 4-space indentation
- Example:
```xml  <menuitem id="menu_id" name="Menu Name" parent="parent_menu" sequence="10"/>
```
Views

Use explicit view inheritance
Always include arch attribute
Use proper xpath expressions

Common Ruff Errors to Avoid

F841: Unused variables - remove or use them
E741: Ambiguous variable names - use descriptive names
UP009: Remove UTF-8 coding declarations
I001: Keep imports sorted and organized
- G004: Use lazy logging formatting (never f-strings in logging)
- BLE001: Don't catch blind exceptions
- SIM105: Use contextlib.suppress() sparingly (our preference: stick with try-except)
- PLC0415: **Imports at top-level only - NEVER inside functions/methods**
- RET504: Avoid unnecessary assignment before return statement
- TRY401: Don't pass redundant exception object to logging.exception()- **COM812: Missing trailing comma - ALWAYS add trailing commas in multi-line structures**
When Writing New Code

Check if similar patterns exist in the codebase
Follow Odoo conventions over generic Python when they conflict
Write tests for new functionality
Use Ruff-compliant patterns from the start


---

## Odoo 19 — XML Breaking Changes & Install-Time Errors

These fields/attributes were **removed** in Odoo 17–19 and will cause
`ValueError` / `ParseError` / `ValidationError` at module install time.

---

### A. `ir.cron` — Removed fields: `numbercall`, `active`, `priority`

**Error:** `ValueError: Invalid field 'numbercall' in 'ir.cron'`

❌ Invalid (Odoo ≤ 16):
```xml
<record id="my_cron" model="ir.cron">
    ...
    <field name="numbercall">-1</field>   <!-- REMOVED in Odoo 19 -->
    <field name="active">True</field>     <!-- REMOVED in Odoo 19 -->
    <field name="priority">5</field>      <!-- REMOVED in Odoo 19 -->
</record>
```

✅ Valid (Odoo 19) — valid fields only: `name`, `model_id`, `state`, `code`, `interval_number`, `interval_type`, `nextcall` (optional):
```xml
<record id="my_cron" model="ir.cron">
    <field name="name">My Module: Sync Data</field>
    <field name="model_id" ref="model_my_model"/>
    <field name="state">code</field>
    <field name="code">model._cron_do_something()</field>
    <field name="interval_number">3</field>
    <field name="interval_type">hours</field>
    <field name="nextcall" eval="(DateTime.now() + relativedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')"/>
</record>
```

---

### B. `ir.actions.server` — Removed field: `groups_id`

**Error:** `ValueError: Invalid field 'groups_id' in 'ir.actions.server'`

❌ Invalid:
```xml
<field name="groups_id" eval="[(4, ref('my_module.group_manager'))]"/>
```

✅ Valid: Remove `groups_id`. Control visibility via the view button's `groups=`
attribute and/or a `has_group()` check inside the Python method.

---

### C. `res.groups` — Removed field: `category_id` (and `ir.module.category`)

**Error:** `ValueError: Invalid field 'category_id' in 'res.groups'`

❌ Invalid:
```xml
<record id="module_category_my_module" model="ir.module.category">...</record>
<record id="group_rm" model="res.groups">
    <field name="category_id" ref="module_category_my_module"/>  <!-- REMOVED -->
</record>
```

✅ Valid — use `comment`, no `ir.module.category` record needed:
```xml
<record id="group_rm" model="res.groups">
    <field name="name">RM</field>
    <field name="comment">Relationship Manager — read-only access</field>
    <field name="implied_ids" eval="[(4, ref('base.group_user'))]"/>
</record>
<record id="group_manager" model="res.groups">
    <field name="name">Manager</field>
    <field name="comment">Full access including configuration</field>
    <field name="implied_ids" eval="[(4, ref('my_module.group_rm'))]"/>
</record>
```

---

### D. Search Views — `<group>` no longer accepts `expand` or `string`

**Error:** `ParseError: Invalid view <name>.search definition in <file>`

The RelaxNG schema (`common.rng`) does not define `expand` or `string` on
`<group>` in Odoo 19 search views. The view fails RNG validation silently and
then raises a ParseError pointing to the `<record>` line, not the `<group>`.

❌ Invalid:
```xml
<group expand="0" string="Group By">
    <filter name="group_city" string="City" context="{'group_by': 'city'}"/>
</group>
```

✅ Valid — bare `<group>`, no attributes:
```xml
<group>
    <filter name="group_city" string="City" context="{'group_by': 'city'}"/>
</group>
```

> Note: `groups=` (access control) on `<filter>` is still valid in Odoo 19.

---

### E. Search Views — Avoid `relativedelta` in filter `domain=`

`relativedelta` is not guaranteed to be in `safe_eval` scope for filter domains.

❌ Risky (may raise `NameError` at runtime):
```xml
<filter name="this_month"
        domain="[('date', '>=', (context_today() + relativedelta(day=1)).strftime('%Y-%m-%d'))]"/>
```

✅ Use the built-in `date=` attribute (renders a period picker in the UI):
```xml
<filter name="date_filter" string="Registration Date" date="reg_date"/>
```

✅ Or use `timedelta` which IS in the eval context:
```xml
<filter name="last_30_days" string="Last 30 Days"
        domain="[('date', '&gt;=', (context_today() - timedelta(days=30)).strftime('%Y-%m-%d'))]"/>
```

---

### F. `attrs=` and `states=` — Removed since Odoo 17.0

**Error:** `ValidationError: Since 17.0, the "attrs" and "states" attributes are no longer used.`

❌ Invalid:
```xml
<field name="my_field" attrs="{'invisible': [('state', '=', 'done')]}"/>
<field name="my_field" states="cancel"/>
```

✅ Valid:
```xml
<field name="my_field" invisible="state == 'done'"/>
```

---

### G. Quick Reference Table

| Removed item | Location | Odoo 19 replacement |
|---|---|---|
| `numbercall` | `ir.cron` | Not needed (crons run forever by default) |
| `active` | `ir.cron` | Not needed |
| `priority` | `ir.cron` | Not needed |
| `groups_id` | `ir.actions.server` | `groups=` on view button + Python check |
| `category_id` | `res.groups` | Use `comment` for description text |
| `ir.module.category` records | security XML | Remove entirely |
| `expand="…"` on `<group>` | search views | Remove the attribute |
| `string="…"` on `<group>` | search views | Remove the attribute |
| `attrs=` | any view | Inline `invisible=` / `readonly=` / `required=` |
| `states=` | any view | Inline `invisible=` |


---

## Odoo 19 - XML Breaking Changes and Install-Time Errors

These fields/attributes were removed in Odoo 17-19 and will cause
ValueError / ParseError / ValidationError at module install time.

---

### A. ir.cron - Removed fields: numbercall, active, priority

Error: ValueError: Invalid field numbercall in ir.cron

Invalid (Odoo 16 and below):
    <record id="my_cron" model="ir.cron">
    </record>

Valid (Odoo 19) - only these fields: name, model_id, state, code,
interval_number, interval_type, nextcall (optional):
    <record id="my_cron" model="ir.cron">
        <field name="name">My Module: Sync Data</field>
        <field name="model_id" ref="model_my_model"/>
        <field name="state">code</field>
        <field name="code">model._cron_do_something()</field>
        <field name="interval_number">3</field>
        <field name="interval_type">hours</field>
        <field name="nextcall" eval="(DateTime.now() + relativedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')"/>
    </record>

---

### B. ir.actions.server - Removed field: groups_id

Error: ValueError: Invalid field groups_id in ir.actions.server

Invalid:
    <field name="groups_id" eval="[(4, ref('my_module.group_manager'))]"/>

Valid: Remove groups_id entirely. Control visibility via the view button groups=
attribute and/or a has_group() check inside the Python method.

---

### C. res.groups - Removed field: category_id (and ir.module.category)

Error: ValueError: Invalid field category_id in res.groups

Invalid:
    <record id="module_category_my_module" model="ir.module.category">...</record>
    <record id="group_rm" model="res.groups">
    </record>

Valid - use comment field, no ir.module.category record needed:
    <record id="group_rm" model="res.groups">
        <field name="name">RM</field>
        <field name="comment">Relationship Manager - read-only access</field>
        <field name="implied_ids" eval="[(4, ref('base.group_user'))]"/>
    </record>
    <record id="group_manager" model="res.groups">
        <field name="name">Manager</field>
        <field name="comment">Full access including configuration</field>
        <field name="implied_ids" eval="[(4, ref('my_module.group_rm'))]"/>
    </record>

---

### D. Search Views - group element no longer accepts expand or string attributes

Error: ParseError: Invalid view <name>.search definition in <file>

The RelaxNG schema (common.rng) does not define expand or string on the group
element in Odoo 19 search views. The view fails RNG validation and then raises
a ParseError pointing to the record line, not the group element.

Invalid:
    <group expand="0" string="Group By">
        <filter name="group_city" string="City" context="{'group_by': 'city'}"/>
    </group>

Valid - bare group element with no attributes:
    <group>
        <filter name="group_city" string="City" context="{'group_by': 'city'}"/>
    </group>

Note: groups= (access control) on filter elements is still valid in Odoo 19.

---

### E. Search Views - Avoid relativedelta in filter domain attribute

relativedelta is not guaranteed to be in safe_eval scope for filter domains.

Risky - may raise NameError at runtime:
    <filter name="this_month"
            domain="[('date', '>=', (context_today() + relativedelta(day=1)).strftime('%Y-%m-%d'))]"/>

Safe - use the built-in date= attribute (renders a period picker in the UI):
    <filter name="date_filter" string="Registration Date" date="reg_date"/>

Also safe - timedelta IS available in the eval context:
    <filter name="last_30_days" string="Last 30 Days"
            domain="[('date', '>=', (context_today() - timedelta(days=30)).strftime('%Y-%m-%d'))]"/>

---

### F. attrs= and states= - Removed since Odoo 17.0

Error: ValidationError: Since 17.0, the attrs and states attributes are no longer used.

Invalid:
    <field name="my_field" attrs="{'invisible': [('state', '=', 'done')]}"/>
    <field name="my_field" states="cancel"/>

Valid:
    <field name="my_field" invisible="state == 'done'"/>

---

### G. Quick Reference Table

| Removed item          | Location            | Odoo 19 replacement                          |
|-----------------------|---------------------|----------------------------------------------|
| numbercall            | ir.cron             | Not needed (crons run forever by default)    |
| active                | ir.cron             | Not needed                                   |
| priority              | ir.cron             | Not needed                                   |
| groups_id             | ir.actions.server   | groups= on view button + Python check        |
| category_id           | res.groups          | Use comment for description text             |
| ir.module.category    | security XML        | Remove entirely                              |
| expand=               | search view group   | Remove the attribute                         |
| string= on group      | search view group   | Remove the attribute                         |
| attrs=                | any view            | Inline invisible= / readonly= / required=    |
| states=               | any view            | Inline invisible=                            |

---

### H. Menu Items - action= must reference an XML ID from an installed module

Error: ValueError: External ID not found in the system: <module>.<xml_id>

Menuitem action= attributes must reference XML IDs from modules that are
listed in your manifest depends. The module that defines the action must be
installed before your module loads.

Common mistake - referencing base_automation when it is not a dependency:

Invalid:
    <menuitem id="menu_cron" name="Scheduled Syncs"
              action="base_automation.base_automation_act"/>

This fails if base_automation is not in your manifest depends list.

Fixes:

Option 1 - Use the equivalent action from the base module (always available):
    <menuitem id="menu_cron" name="Scheduled Syncs"
              action="base.ir_cron_act"/>

    <menuitem id="menu_auto" name="Automation"
              action="base.base_automation_act"/>

Option 2 - Add the module to depends in __manifest__.py:
    "depends": ["base", "web", "mail", "base_automation"],

Common action XML IDs available from core base (no extra depends needed):

| Purpose              | XML ID                          |
|----------------------|---------------------------------|
| Scheduled Actions    | base.ir_cron_act                |
| Automated Actions    | base.base_automation_act        |
| Server Actions       | base.ir_action_server_act       |
| Users                | base.action_res_users           |
| Groups               | base.action_res_groups          |
| Technical Settings   | base.action_ir_config_menu_view |


---

### I. Migration Crons - FK Violations When Relinking Many2one Fields

Error:
    psycopg2.errors.ForeignKeyViolation: insert or update on table "<table>"
    violates foreign key constraint "<table>_<field>_fkey"
    DETAIL: Key (<field>)=(<id>) is not present in table "<target_table>".

Cause: A migration cron wrote a record ID from model A into a Many2one field
that is still declared as pointing to model B. The ORM buffers writes and flushes
them lazily (on the next search/read), at which point the DB FK check fires.

Example - wrong pattern:
    # property_lead_suggestion.property_inventory_id is Many2one(property.inventory)
    suggestions.write({"property_inventory_id": prop.id})  # FK violation!

The flush happens inside the next .search() call in the same loop:
    self.env["property.lead.suggestion"].search([...])
    # -> flush_query() -> _write_multi() -> DB FK check -> VIOLATION

Fix: Never write a record ID from one model into a Many2one field declared for
a different model. If the goal is to relink the FK to a new model, the field
declaration on the source model must be changed first (add a new Many2one field
pointing to the new model), and only then can the migration write that field.

Correct phased approach:
  Phase 1 (this cron): Populate manager-editable fields on property.base only.
                        Do NOT touch any FK fields on related models.
  Phase 2 (after PROP-9): Add property_base_id = Many2one(property.base) to
                           property.lead.suggestion via _inherit in lead_suggestor.
                           Run a separate migration pass to populate property_base_id.
                           Only then drop or nullify the old property_inventory_id FK.

Correct migration code pattern:
    for prop in unmigrated:
        inv = inventory_map.get(prop.property_link)
        if not inv:
            continue

        # Write ONLY fields on the model being migrated (property.base)
        prop.write(migration_vals)

        # Do NOT attempt to relink FKs on other models here.
        # That requires the other model to have the new field declared first.
