# Migration Log - Odoo 18 to 19

## Module: lead_suggestor
**Date:** 2025-12-15
**Status:** In Progress

### Security (`security.xml`)
- **[REMOVED]** `category_id` field from `res.groups` definitions (`group_property_prospector_rm`, `group_property_prospector_manager`).
    - *Reason:* The `category_id` field was removed from the `res.groups` model in Odoo 19 core.
- **[KEPT]** `ir.module.category` record (`module_category_property_prospector`).
    - *Reason:* Retained for App Store grouping and potential future linkage, though currently disconnected from groups.


### Views (`property_inventory_views.xml`)
- **[FIX]** Removed `expand="0"` from `<group>` in Search View (attribute removed in v19).
- **[FIX]** Replaced `attrs="{'invisible': ...}"` with `invisible="suggested_lead_phone_whatsapp_url == False"`.
- **[INFO]** Validated usage of `<list>` tag (replacing `<tree>`) for One2many field.


### Installation Status
- **[SUCCESS]** Module `lead_suggestor` installed successfully on Odoo 19 database.
- **[PENDING]** Fix Deprecation Warning: `_sql_constraints` needs to be converted to `models.Constraint`.
- **[PENDING]** Fix Polish Warning: Duplicate field labels on `property.lead.suggestion`.


### Models (`property_lead_suggestion.py`)
- **[FIX]** Converted `_sql_constraints` to `models.Constraint` class attribute `prop_lead_uniq`.
- **[FIX]** Renamed `suggested_lead_phone_html` field label to "Lead Phone Link" to resolve duplicate label warning.
- **[FIX]** Corrected `models.Constraint` argument from `string` to `message` (Fixes TypeError).
**[FIX]** Renamed `prop_lead_uniq` to `_prop_lead_uniq`.
    - *Reason:* Odoo 19 requires `models.Constraint` attributes to start with an underscore (`AssertionError`).
- **[CLEANUP]** Added Python type hints and removed unused imports.


### Models (`property_inventory.py`)
- **[FIX]** Converted `_sql_constraints` to `models.Constraint` class attribute `_property_tag_uniq`.


### Views (`property_inventory_views.xml`)
- **[CRITICAL FIX]** Renamed Kanban template from `kanban-box` to `card` (Odoo 19 Standard).
- **[FIX]** Removed outer `oe_kanban_global_click` div wrapper as the `card` system handles the container automatically.


