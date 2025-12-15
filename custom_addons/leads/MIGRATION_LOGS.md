# Migration Log: Lead Scoring Module (Odoo 19.0)

**Module:** `leads`  
**Date:** 2025-12-15  
**Maintainer:** Engineering Team  
**Status:** In Progress

## 1. Manifest & Dependencies (`__manifest__.py`)
* **[FIX] Dependency Injection:** Added `lead_suggestor` to `depends`. The module relies on JS assets (`whatsapp_action.js`) defined in `lead_suggestor`. Without this, the asset bundle fails to load.
* **[FIX] Load Order:** Reordered `data` list. Moved `lead_score_views.xml` **before** `lead_score_menu.xml`.
    * *Reason:* Odoo 19 Strictness. Menus cannot reference Actions that haven't been loaded into the registry yet.

## 2. Security & ACLs (`security.xml`)
* **[DEPRECATION] Group Categories:** Removed `category_id` field assignment from `res.groups` records.
    * *Reason:* The `category_id` field on `res.groups` was removed or restricted in Odoo 19.0. Groups now default to the standard internal categorization or require a different linkage method.

## 3. Python Models (`models/*.py`)
* **[FIX] `new_portal_leads.py`:** Removed deprecated Python libraries (`urllib`, `xml.etree`) that were commented out but cluttering the namespace.
* **[UPDATE] Bus Notifications:** Verified `self.env['bus.bus']._sendone()` usage for Odoo 19 compatibility.
* **[CLEANUP] `lead_score.py`:** Preserved all business logic and docstrings while ensuring imports (like `datetime`) are standard.

## 4. XML Views (`views/*.xml`)
* **[DEPRECATION] Kanban Layout:** Replaced `<t t-name="kanban-box">` with `<t t-name="card">`.
    * *Reason:* Odoo 19 replaced the legacy Kanban structure with a streamlined Card API.
* **[DEPRECATION] Tree Views:** Renamed `<tree>` tag to `<list>`.
    * *Reason:* `tree` view definition is deprecated in favor of `list` for consistency.
* **[DEPRECATION] Search View Groups:** Removed `<group expand="0">` wrappers inside `<search>` views.
    * *Reason:* Grouping filters inside a `<group>` tag within Search Views is no longer valid RNG syntax in Odoo 19. Filters must be direct children of `<search>`.

## 5. Next Steps
* [ ] Verify `whatsapp_response_views.xml` for similar Search View syntax errors.
* [ ] Run full regression test suite (`test_lead_score.py`).

## 6. Whatsapp Logic (`models/whatsapp_response.py`)
* **[DEPRECATION] `name_get`:** Replaced legacy `name_get` method with Odoo 19 standard `_compute_display_name`.
* **[LOGIC FIX] Response Type:** The `_compute_response_type` method was checking against hardcoded strings that did not match the field's `Selection` keys (e.g., checked for 'yes_interested' but key is 'yes_going_for_visit'). Updated list to match keys, ensuring Positive responses are correctly tagged.
* **[FIX] `_sql_constraints`:** Confirmed removal of legacy constraints from `lead_property_interest.py` (previous step) resolved the SQL warning.


## 7. BigQuery Wizard (`models/lead_score_bq_wizard.py`)
* **[CLEANUP] Source Code:** Sanitized file to remove non-breaking space characters (`\xa0`) that cause SyntaxErrors in Python 3.
* **[VERIFICATION] Logic:** Verified Odoo 19 compatibility for `TransientModel`, `exceptions.UserError`, and `google.cloud.bigquery` integration. No functional changes required.