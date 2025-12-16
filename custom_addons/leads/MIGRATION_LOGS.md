# Migration Log: Lead Scoring Module (Odoo 19.0)

**Module:** `leads`  
**Date:** 2025-12-16  
**Maintainer:** Engineering Team  
**Status:** ✅ Completed

## 1. Manifest & Dependencies (`__manifest__.py`)
* **[FIX] Dependency Injection:** Added `lead_suggestor` to `depends`. The module relies on JS assets (`whatsapp_action.js`) defined in `lead_suggestor`.
* **[FIX] Load Order:** Reordered `data` list. Moved `lead_score_views.xml` **before** `lead_score_menu.xml`.
    * *Reason:* Odoo 19 Strictness. Menus cannot reference Actions that haven't been loaded into the registry yet.

## 2. Security & ACLs (`security.xml`)
* **[DEPRECATION] Group Categories:** Removed `category_id` field assignment from `res.groups` records.
    * *Reason:* The `category_id` field on `res.groups` was removed or restricted in Odoo 19.0.
* **[FIX] Access Rights:** Added access rules for `lead.import.wizard` in `ir.model.access.csv` to prevent Access Errors for managers.

## 3. Python Models (`models/*.py`)
* **[FIX] `new_portal_leads.py`:** Removed deprecated Python libraries (`urllib`, `xml.etree`).
* **[UPDATE] Bus Notifications:** Verified `self.env['bus.bus']._sendone()` usage for Odoo 19 compatibility.
* **[DEPRECATION] `whatsapp_response.py`:** * Replaced legacy `name_get` method with Odoo 19 standard `_compute_display_name`.
    * Fixed `_compute_response_type` logic to match the actual Selection keys (e.g., checked for `yes_going_for_visit` instead of `yes_interested`).
* **[DEPRECATION] SQL Constraints:** Converted legacy `_sql_constraints` to `models.Constraint` syntax in `lead_property_interest.py`.
* **[CLEANUP] `lead_score_bq_wizard.py`:** Removed non-breaking space characters (`\xa0`) that were causing SyntaxErrors.
* **[LOGIC] `lead_import_wizard.py`:** Updated `_find_property_by_name` to search in `property.inventory` (active model) instead of the deprecated `property.listing`.

## 4. XML Views (`views/*.xml`)
* **[DEPRECATION] Kanban Layout:** Replaced `<t t-name="kanban-box">` with `<t t-name="card">`.
    * *Reason:* Odoo 19 replaced the legacy Kanban structure with a streamlined Card API.
* **[DEPRECATION] Tree Views:** Renamed `<tree>` tag to `<list>`.
    * *Reason:* `tree` view definition is deprecated in favor of `list`.
* **[DEPRECATION] Search View Groups:** Removed `<group expand="0">` wrappers inside `<search>` views.
    * *Reason:* Grouping filters inside a `<group>` tag within Search Views is no longer valid RNG syntax in Odoo 19.
* **[FIX] Context Logic:** Added `my_responses` filter to `whatsapp_response_views.xml` to fix a crash caused by the Action context referencing a missing filter.

## 5. UI Standardization (Date Formatting)
* **[FIX] Numeric Date Display:** Applied `options="{'numeric': true}"` to Date/Datetime fields in List and Form views.
    * *Reason:* Odoo 19 defaults to textual date formats (e.g., "Dec 15"). The `numeric: true` option forces the standard numeric format (e.g., DD/MM/YYYY) while respecting the user's Language/Locale settings.
* **[NOTE] Known Limitations:** * *Language Dependency:* The specific numeric order (DD/MM vs MM/DD) is strictly controlled by the User's Language settings in Odoo.
    * *No "Text + Year":* There is no built-in way to display "Text + Year" (e.g., "Dec 15, 2024") in the new widget; `numeric: true` is the standard workaround.

## 6. Deprecated Modules
* **Status:** The following modules were identified as deprecated and excluded from the migration:
    * `property_listings`
    * `property_renewal`
    * `property_dashboard`