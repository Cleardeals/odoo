# Migration Plan: Odoo 18 (GCP) to Odoo 19

**Project:** Lead Scoring & Dashboard Migration
**Source:** Odoo 18 (GCP / Live)
**Destination:** Odoo 19 (Community Edition)
**Status:** Draft / Verified

---

## 🛑 Phase 0: Pre-Migration & Safety (The "Cutover" Window)
*Since `new_portal_leads` receives real-time data, you must define a "Maintenance Window" where you stop operations to ensure no data is lost during the transfer.*

* [ ] **Schedule Maintenance:** Notify users that the system will be read-only or down.
* [ ] **Stop Odoo 18 Service:** (Optional but Recommended) Stop the Odoo 18 service to prevent new leads from entering during the export.
    * `sudo service odoo stop`
* [ ] **Snapshot GCP:** Create a full disk snapshot of the Odoo 18 VM instance on Google Cloud Console.
    * *Label:* `pre-migration-backup-odoo18`
* [ ] **Verify Codebase:** Ensure the Odoo 19 custom modules (`leads`, `cleardeals_dashboards`) are pushed to the new server/local path.

---

## 🏗️ Phase 1: Infrastructure Setup (Odoo 19)

* [ ] **Initialize DB:** Create a fresh, empty Odoo 19 database (e.g., `odoo_19_prod`).
* [ ] **Install Modules:**
    * Install `leads` (Lead Scoring).
    * Install `cleardeals_dashboards`.
    * *Verify:* Check that the table `leads_new` exists in Postgres.
* [ ] **Prerequisite Check (Code):**
    * Verify `leads.new` model has the temporary migration field:
        * `x_migrated_date = fields.Datetime(string="Migration Timestamp")`
    * Verify `leads.new` model contains the helper method `_compute_create_date_only()` (or standard compute logic) if you plan to use it in Step 4.

---

## 👥 Phase 2: Core Data (Users & Employees)
*Must be done BEFORE importing leads so that "Assigned RM" fields map correctly.*

* [ ] **Export from Odoo 18:**
    * Navigate to **Settings > Users**.
    * Export all active users (CSV).
    * **Columns:** `Name`, `Login (Email)`, `Related Partner`, `Custom Fields`.
* [ ] **Clean Data:**
    * Remove `Administrator` and `OdooBot` rows.
* [ ] **Import to Odoo 19:**
    * Use Odoo Import Wizard.
    * **Map:** Login -> Login, Name -> Name.
* [ ] **Password Reset:**
    * Select all imported users -> **Action** -> **Send Password Reset Instructions**.
    * *(Alternative: SQL Injection of hashes if you have direct DB access).*

---

## 🚀 Phase 3: Module Migration (`new_portal_leads`)

### Step 3.1: Data Extraction (The "Freeze")
* [ ] **Action:** Go to Odoo 18 (Source).
* [ ] **Navigate:** `Lead Scoring` > `New Portal Leads`.
* [ ] **Filter:** Remove filters to see ALL records.
* [ ] **Export:** Select all records -> Action -> Export.
* [ ] **Template:** Select your saved export template `odoo_migration_template`.
    * *Critical Columns:* `Lead Name`, `Phone`, `Portal Source`, `Assigned RM`, `Status`, **`Created On`**.
* [ ] **Format:** Export as **XLSX**.

### Step 3.2: Data Import
* [ ] **Action:** Go to Odoo 19 (Destination).
* [ ] **Navigate:** `Lead Scoring` > `New Portal Leads`.
* [ ] **Upload:** Upload the XLSX file.
* [ ] **Mapping:**
    * Map `Created On` (from Excel) ➔ `x_migrated_date` (Migration Timestamp).
    * **Leave Blank (Computed Fields):** `Site Visit Date`, `Main Property`, `First Contact`, `Whatsapp URL`.
        * *Reason:* These will be auto-calculated by Odoo 19 logic upon creation.
* [ ] **Execute:** Click **Test**, then **Import**.
    * *Outcome:* Records appear with "Today" as creation date.

### Step 3.3: SQL Timestamp Correction
* [ ] **Connect:** SSH into the Odoo 19 server (or open local terminal).
* [ ] **Open SQL:** `psql -U odoo -d odoo_19_prod`
* [ ] **Execute Query:**
    ```sql
    UPDATE leads_new
    SET create_date = x_migrated_date
    WHERE x_migrated_date IS NOT NULL;
    ```
* [ ] **Verify:** `SELECT count(*) FROM leads_new WHERE create_date = x_migrated_date;`

### Step 3.4: Recompute Logic
* [ ] **Create Server Action:**
    * **Name:** Recompute Creation Date
    * **Model:** New Leads from Portals (`leads.new`)
    * **Action To Do:** Execute Python Code
    * **Code:**
        ```python
        # Ensures dependent logic runs using the new SQL-injected dates
        for record in records:
            record._compute_create_date_only()
        ```
* [ ] **Trigger:**
    * Go to List View > Select All Records.
    * Action > **Recompute Creation Date**.

---

## 🧹 Phase 4: Post-Migration Cleanup

* [ ] **Verify Data:**
    * Check Total Count (Odoo 18 vs Odoo 19).
    * Spot check 5 random records: Does `Created On` match the original excel?
    * Check Computed Fields: Is `Whatsapp URL` generated?
* [ ] **Remove Artifacts:**
    * Delete the **Server Action** created in Step 3.4.
    * (Optional) Remove the `x_migrated_date` field from the Python model and upgrade the module.
* [ ] **DNS/Network:** Point domain (if applicable) to new Odoo 19 IP.

---

## 🔙 Rollback Plan
*If critical failure occurs:*
1.  Restore the GCP Snapshot `pre-migration-backup-odoo18`.
2.  Restart Odoo 18 service.
3.  Resume operations on Odoo 18.