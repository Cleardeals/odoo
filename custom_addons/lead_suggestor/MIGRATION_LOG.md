# Migration Log: Lead Scoring Module (Odoo 19.0)

**Module:** `leads`  
**Date:** 2025-12-15  
**Maintainer:** Engineering Team  
**Status:** ✅ Completed

## 1. Manifest & Dependencies (`__manifest__.py`)
* **[FIX] Dependency Injection:** Added `lead_suggestor` to `depends`. The module relies on JS assets (`whatsapp_action.js`) defined in `lead_suggestor`. Without this, the asset bundle fails to load.
* **[FIX] Load Order:** Reordered `data` list. Moved `lead_score_views.xml` **before** `lead_score_menu.xml`.
    * *Reason:* Odoo 19 Strictness. Menus cannot reference Actions that haven't been loaded into the registry yet.

## 2. Security & ACLs (`security.xml`)
* **[DEPRECATION] Group Categories:** Removed `category_id` field assignment from `res.groups` records.
    * *Reason:* The `category_id` field on `res.groups` was removed or restricted in Odoo 19.0. Groups now default to the standard internal categorization.
* **[FIX] Missing Access Rights:** Added access rules for `lead.import.wizard` in `ir.model.access.csv` to allow managers to run CSV imports without `AccessError`.

## 3. Python Models (`models/*.py`)
* **[FIX] `new_portal_leads.py`:** Removed deprecated Python libraries (`urllib`, `xml.etree`) that were commented out but cluttering the namespace.
* **[UPDATE] Bus Notifications:** Verified `self.env['bus.bus']._sendone()` usage for Odoo 19 compatibility.
* **[CLEANUP] `lead_score.py`:** Preserved all business logic and docstrings while ensuring imports (like `datetime`) are standard.
* **[DEPRECATION] `whatsapp_response.py`:** * Replaced legacy `name_get` method with Odoo 19 standard `_compute_display_name`.
    * Fixed `_compute_response_type` logic to match the actual Selection keys (e.g., checking for `yes_going_for_visit` instead of `yes_interested`).
* **[DEPRECATION] SQL Constraints:** Converted legacy `_sql_constraints` to the new `models.Constraint` syntax in `lead_property_interest.py`.
* **[CLEANUP] `lead_score_bq_wizard.py`:** Removed non-breaking space characters (`\xa0`) causing SyntaxErrors and verified BigQuery client integration.
* **[LOGIC] `lead_import_wizard.py`:** Updated `_find_property_by_name` to search in `property.inventory` (active model) instead of `property.listing` (deprecated model).

## 4. XML Views (`views/*.xml`)
* **[DEPRECATION] Kanban Layout:** Replaced `<t t-name="kanban-box">` with `<t t-name="card">` in both `lead_score_views.xml` and `whatsapp_response_views.xml`.
    * *Reason:* Odoo 19 replaced the legacy Kanban structure with a streamlined Card API.
    * Removed deprecated `oe_kanban_global_click` wrapper classes.
* **[DEPRECATION] Tree Views:** Renamed `<tree>` tag to `<list>` in all view files.
    * *Reason:* `tree` view definition is deprecated in favor of `list` for consistency.
* **[DEPRECATION] Search View Groups:** Removed `<group expand="0">` wrappers inside `<search>` views in `lead_score_views.xml` and `whatsapp_response_views.xml`.
    * *Reason:* Grouping filters inside a `<group>` tag within Search Views is no longer valid RNG syntax in Odoo 19. Filters must be direct children of `<search>`.
* **[FIX] Missing Filter:** Added `my_responses` filter to `whatsapp_response_views.xml`.
    * *Reason:* The Action `whatsapp_response_action_all` referenced `search_default_my_responses` in its context, but the filter did not exist, leading to a crash.

## 5. Deprecated Modules
* **Status:** The following modules were identified as deprecated and excluded from the migration:
    * `property_listings`
    * `property_renewal`
    * `property_dashboard`