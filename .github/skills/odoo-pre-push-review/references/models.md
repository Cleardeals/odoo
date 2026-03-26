# Model Files Reference (`models/*.py`)

## Access rules — the most commonly missed step

Every model that subclasses `models.Model` needs at least one row in
`security/ir.model.access.csv`. Without it, every user (including
administrators in some Odoo versions) gets `AccessError` on any ORM
operation touching that model.

The `model_id:id` value is deterministic:
```
model._name         → model_id:id
property.base       → model_property_base
property.portal.listing → model_property_portal_listing
leads.new           → model_leads_new
lead.property.interest → model_lead_property_interest
```

Rule: dots become underscores, prefix with `model_`.

## One2many field declarations

A filtered `One2many` (e.g. per-portal) must be explicitly declared with
a `domain` argument. It does not inherit a filter from the view:

```python
# WRONG — returns ALL listings, domain in view is ignored at ORM level
portal_listing_ids = fields.One2many("property.portal.listing", "property_base_id")

# CORRECT — filtered at ORM level
portal_listing_99acres_ids = fields.One2many(
    "property.portal.listing", "property_base_id",
    domain=[("portal_name", "=", "99acres")],
    string="99acres Listings",
)
```

If the view references `portal_listing_99acres_ids` but the model only
declares `portal_listing_ids`, the view fails with `FieldDoesNotExist`.

## @api.depends completeness

Every field read inside a compute method must appear in `@api.depends`.
Missing a dependency means the field is not recomputed when that dependency
changes — the stored value goes stale silently.

```python
@api.depends("property_base_id", "interest_ids.property_base_id")
def _compute_all_associated_properties(self):
    for lead in self:
        properties = lead.property_base_id          # ← must be in depends
        if lead.interest_ids:
            properties |= lead.interest_ids.mapped("property_base_id")  # ← must be in depends
        lead.all_associated_properties = properties
```

For `related=` fields, Odoo computes the dependency chain automatically —
no `@api.depends` needed.

## related= fields with store=True

```python
# CORRECT pattern
base_property_tag = fields.Char(
    related="property_base_id.property_tag",
    store=True,
    readonly=True,   # ← required when store=True on a related field
)
```

`store=True` on a `related=` field without `readonly=True` creates an
ambiguous field — it is both computed (from the related path) and writable
(no readonly). Odoo resolves this inconsistently across versions. Always
pair `store=True` with `readonly=True` on related fields.

## search() calls inside create()/write()

```python
def create(self, vals_list):
    for vals in vals_list:
        # This search runs as the current user
        existing = self.env["property.portal.listing"].search([...])
```

If the current user lacks read access to `property.portal.listing`, this
raises `AccessError` inside `create()`, which the user sees as a cryptic
error when saving a form that has nothing to do with portal listings.

Fix with `sudo()` for lookups that are administrative in nature:
```python
existing = self.env["property.portal.listing"].sudo().search([...])
```

Use `sudo()` judiciously — only for reads where access control is not
the point of the check.

## Context keys and ir.rule coupling

A field definition with a context key:
```python
property_base_id = fields.Many2one(
    "property.base",
    context={'search_all_properties_for_lead': True},
)
```

This context key only does something if an `ir.rule` exists that reads it:
```xml
<field name="domain_force">
    ['|',
        ('rm_user_id', '=', user.id),
        '&', ('active', '=', True),
             (context.get('search_all_properties_for_lead'), '=', True)
    ]
</field>
```

If the field has the context key but no `ir.rule` honours it, the key
does nothing — the security restriction is not bypassed and the feature
does not work. Always verify the matching rule exists.

## _sql_constraints format

```python
_sql_constraints = [
    (
        "unique_portal_listing",                          # constraint name (Python id)
        "UNIQUE(portal_name, portal_listing_id)",        # PostgreSQL constraint SQL
        "This listing ID is already registered.",        # User-facing error message
    )
]
```

The constraint SQL is raw PostgreSQL. Common mistakes:
- Using Odoo field names instead of column names (usually the same, but
  `One2many` fields have no column — they cannot be in SQL constraints)
- Column names that do not exist yet (if the model is new and migration
  hasn't run, the column may not exist when the constraint is applied)

## write() recursion guard

```python
def write(self, vals):
    if "current_status" in vals:
        leads_to_stamp = self.filtered(lambda r: not r.first_contact_datetime)
        if leads_to_stamp:
            timestamp = fields.Datetime.now()

    res = super().write(vals)  # super() FIRST

    if leads_to_stamp:
        leads_to_stamp.write({"first_contact_datetime": timestamp})
        # This recursive write() call is safe ONLY because:
        # 1. "first_contact_datetime" is not in the original vals
        # 2. The recursive call does not trigger the if-branch again
        # Any change to this logic must preserve these two properties

    return res
```

Flag any `write()` override that calls `self.write()` recursively without
a clear guard that prevents infinite recursion.
