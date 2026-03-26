# View Files Reference (`views/*.xml`)

## Field existence validation

Every `<field name="X"/>` in a view must correspond to a field declared
on the model. When the user shares both the view and the model, cross-check
every field name. Fields that were removed from the model but left in the view
cause a `FieldDoesNotExist` error when the view is loaded.

**High-risk situations:**
- Removing a flat field and replacing with a relational field (e.g. removing
  `ninety_nine_acres_id` and adding `portal_listing_ids`) — all view references
  to the old field name must be updated
- Renaming a field — old name in any view causes immediate load failure
- Moving a field between models — references via `related=` path change

## Search view field paths

When a model field is replaced by a relational field, the search view must
update its filter to use the correct relational path:

```xml
<!-- OLD — flat field, now removed from model -->
<field name="ninety_nine_acres_id" string="99acres ID"/>

<!-- NEW — search through the One2many relation -->
<field name="portal_listing_ids"
       string="Portal Listing ID"
       filter_domain="[('portal_listing_ids.portal_listing_id', 'ilike', self)]"/>
```

The `filter_domain` attribute overrides the default search behaviour.
Without it, searching a `One2many` field uses the field's `_rec_name`,
which is usually `id` — not what you want.

## Duplicate fields

A field appearing in two places in the same form view causes confusing
UX — changes in one place do not visibly update the other until the form
is saved or re-opened. Common causes:

- A field kept in both a group and a tab during a UI refactor
- A field appearing in both Overview and Portal IDs tab
- `property_tag` appearing in both a group and inside a notebook page

When found: remove from the less prominent location, keep in the canonical one.

## Old tab vs new tab coexistence

When a notebook page is replaced (e.g. "Portal IDs" → "Portal Listings"),
both the old and new pages being present simultaneously creates:
1. Manager confusion — which tab is authoritative?
2. Stale writes — edits to old tab bypass new model
3. Future breakage — when old fields are dropped, old tab throws errors

Remove the old tab entirely when the new tab replaces it.

## column_invisible vs invisible

```xml
<!-- Hides the column header AND all cells in a list view -->
<field name="portal_name" column_invisible="1"/>

<!-- Hides the entire row when condition is true -->
<field name="portal_name" invisible="some_condition"/>
```

`column_invisible` is for list view columns you want to include in the
ORM read (e.g. for force_save or domain evaluation) but not show.
`invisible` is for conditionally hiding individual fields or rows.

Using `invisible="1"` on a list column does not remove the column header —
it creates empty cells under a visible header, which looks broken.

## force_save with context defaults

This pattern is correct and intentional:

```xml
<field name="portal_name"
       column_invisible="1"
       force_save="1"/>
```

Used when:
1. The field is set by `context={'default_portal_name': '99acres'}` on
   the parent `One2many` field
2. The field must be `readonly` (user should not change it)
3. The value must still be saved when the user saves the row

`force_save="1"` tells Odoo to include this field's value in the write
even though it is `readonly`. Without it, the context-defaulted value
is shown but not persisted — the column saves as NULL.

**Verify:** the parent `One2many` field in the form view has the matching
`context` key set:
```xml
<field name="portal_listing_99acres_ids"
       context="{'default_portal_name': '99acres'}">
```

## Odoo 17+ attrs syntax

Odoo 16 used `attrs` dict:
```xml
<!-- Odoo 16 style — deprecated in 17+ -->
<field name="source" attrs="{'readonly': [('portal_property_id', '!=', False)]}"/>
```

Odoo 17+ uses inline expression:
```xml
<!-- Odoo 17+ style -->
<field name="source" readonly="portal_property_id != False"/>
```

Mixing styles in the same file does not immediately crash but causes
unpredictable behaviour in Odoo 17+ as the attrs parser is less reliable.
Flag mixed-style files and recommend consistent migration to the new syntax.

## Groups attribute validation

```xml
<page string="Portal Listings" groups="properties.group_property_manager">
```

The xmlid `properties.group_property_manager` must:
1. Be defined in `security/property_security.xml` (or another security XML)
2. That security XML must be loaded in the manifest `data` list BEFORE this view

If the group does not exist at view load time, Odoo silently makes the element
visible to no one — the page disappears without an error message.

## Action and view record cross-references

`ir.actions.act_window.view` records reference both an action and a view by xmlid:
```xml
<field name="act_window_id" ref="action_property_base"/>
<field name="view_id"       ref="view_property_base_list"/>
```

Both xmlids must exist in the same module or a dependency. A dangling `ref`
causes an `External ID not found` error at module load time.
