# Migration Log: Cleardeals Dashboards (Odoo 19.0)

**Module:** `cleardeals_dashboards`
**Date:** 2025-12-18
**Maintainer:** Nirat Patel
**Status:** ✅ Deployment Ready

---

## 1. Manifest & Configuration (`__manifest__.py`)
* **[UPDATE] Version:** Bumped version to `19.0.1.0`.
* **[VERIFICATION] Load Order:** Confirmed `views` are loaded before `menus` to satisfy Odoo 19 strict registry checks.
* **[FIX] Web Icon:** Updated `web_icon` syntax in `menus.xml` to the `module,path` format (comma-separated) required for the Odoo 19 App Switcher.

---

## 2. Security (`security/security.xml`)
* **[DEPRECATION] Group Categories:** Removed `category_id` field assignment from `res.groups` records.
    * *Reason:* The `category_id` field on `res.groups` is restricted/deprecated in Odoo 19.0.

---

## 3. XML Views (`views/*.xml`)

### General UI Standardization
* **[DEPRECATION] Tree Views:** Renamed all `<tree>` tags to `<list>` across all view files.
* **[DEPRECATION] Search View Groups:** Removed `<group expand="0">` wrappers inside all `<search>` views. Filters are now direct children of `<search>`.
* **[FIX] Date Formatting:** Applied `options="{'numeric': true}"` to all Date/Datetime fields in lists.
    * *Reason:* Forces standard numeric format (e.g., 18/12/2025) instead of Odoo 19's default textual format (e.g., "Dec 18").

### Specific View Fixes
* **`property_daily_stat_views.xml`:**
    * **[CRITICAL FIX] Load Order:** Moved `<search>` view definition **above** the `<act_window>` action.
        * *Reason:* Fixed `ValueError: External ID not found` during installation.
    * **[MAJOR] Kanban Modernization:** Replaced legacy `<t t-name="kanban-box">` with the new Odoo 19 `<t t-name="card">` API.
    * **[CLEANUP]** Removed deprecated `oe_kanban_global_click` classes.

* **`new_lead_dashboard_views.xml`:**
    * **[CRITICAL FIX] Graph/Pivot Views:** Removed explicit `<field name="__count" type="measure"/>` lines.
        * *Reason:* Fixed `ParseError: Field "__count" does not exist`. The count measure is now handled automatically or via `pivot_measures` in the context.

---

## 4. Python Models (`models/*.py`)

### General Architecture & Reliability
* **[FIX] Safe Imports:** Wrapped `from google.cloud import bigquery` in `try-except` blocks across all models.
    * *Reason:* Prevents Odoo server startup crashes if the external library is missing.
* **[FIX] Record Naming:** Added `_rec_name` to almost all models (e.g., `active_lead_assignment.py`, `lead_scoring_event.py`, `renewal_property_owner.py`).
    * *Reason:* Ensures readable breadcrumbs and Many2one displays (e.g., "John Doe" instead of "renewal.property.owner,1").

### Odoo 19 API Updates
* **[DEPRECATION] Constraints:** Converted legacy `_sql_constraints` lists to the new `_constraint_name = models.Constraint(...)` syntax.
    * *Ref:* `active_lead_assignment.py`, `property_daily_stat.py`, etc.
* **[DEPRECATION] Aggregation:** Replaced `group_operator="avg"` with `aggregator="avg"` in field definitions.
    * *Ref:* `active_template_stats.py`, `renewal_template_stats.py`.
* **[FIX] Tracking:** Removed `tracking=True` from models that do not inherit `mail.thread`.
    * *Ref:* `renewal_property_owner.py`.

### Specific Logic Fixes
* **`property_daily_stat.py`:**
    * **[FIX] Typo:** Renamed method `_get_koi_total_assignments` to `_get_kpi_total_assignments`.
* **`property_lead_suggestion.py`:**
    * **[PERFORMANCE]** Validated `store=True` on related fields to ensure high-performance dashboard grouping.
* **`lead_scoring_event.py`:**
    * **[PERFORMANCE]** Validated `store=False` on the complex `final_status` compute field to prevent database write bottlenecks.
* **BigQuery Integrations:**
    * **[LOGIC]** Preserved complex SQL logic and double JSON parsing for template extraction in `renewal_property_owner.py` and `new_lead_dashboard.py`.

---

## 5. Summary
The module has been fully refactored to comply with Odoo 19 standards. All critical installation errors (XML ordering, invalid fields) and runtime warnings (deprecated attributes) have been resolved.