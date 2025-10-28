# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from google.cloud import bigquery
import logging
# import pytz # No longer needed
# from datetime import datetime # No longer needed

_logger = logging.getLogger(__name__)

# --- CONFIG: Pointing to Customer_Data as the main source ---
MASTER_PROPERTY_TABLE = "cleardeals-459513.cleardeals_dataset.Customer_Data"
BIGQUERY_PROJECT_ID = "cleardeals-459513"

class PropertyInventory(models.Model):
    _name = 'property.inventory'
    _description = 'Master Property Inventory for RM Dashboard'
    _order = 'new_suggestion_count desc, property_tag'
    _rec_name = 'property_tag'

    property_tag = fields.Char(string="Property Tag", readonly=True, index=True, required=True)
    rm_user_id = fields.Many2one('res.users', string="Assigned RM", readonly=True, index=True)

    suggestion_ids = fields.One2many(
        'property.lead.suggestion',
        'property_inventory_id',
        string="Suggested Leads"
    )

    suggestion_count = fields.Integer(
        string="Total Suggestions",
        compute='_compute_suggestion_counts',
        store=True
    )
    new_suggestion_count = fields.Integer(
        string="New Suggestions",
        compute='_compute_suggestion_counts',
        store=True
    )

    _sql_constraints = [
        ('property_tag_uniq', 'unique(property_tag)', 'Property Tag must be unique.')
    ]

    @api.depends('suggestion_ids', 'suggestion_ids.status')
    def _compute_suggestion_counts(self):
        """Calculates total and new suggestions for the Kanban/Form view."""
        for prop in self:
            prop.suggestion_count = len(prop.suggestion_ids)
            prop.new_suggestion_count = len(prop.suggestion_ids.filtered(lambda s: s.status == 'new'))

    @api.model
    def _cron_sync_properties(self):
        """
        Cron Job: DELETES ALL existing data and syncs the master list of
        ACTIVE properties from BigQuery Customer_Data.
        - Gets the LATEST record for each distinct Tag based on Created_Date.
        - Calculates current status (Active, Expired, Sold) based on the logic
          from utils.py.
        - Filters to keep ONLY 'Active' properties.
        - Extracts the Tag and Assignee (RM name).
        - Creates properties in Odoo, matching Assignee to res.users.name.
        """
        _logger.info("Starting ACTIVE Property Inventory sync from BigQuery Customer_Data...")
        try:
            client = bigquery.Client(project=BIGQUERY_PROJECT_ID)
        except Exception as e:
            _logger.error(f"Failed to create BigQuery client: {e}")
            return

        # --- <<< NEW: DELETE EXISTING DATA FIRST >>> ---
        try:
            _logger.info("Deleting ALL existing property lead suggestions...")
            suggestions_to_delete = self.env['property.lead.suggestion'].search([])
            suggestions_to_delete.unlink()
            _logger.info(f"Deleted {len(suggestions_to_delete)} suggestions.")

            _logger.info("Deleting ALL existing property inventory records...")
            inventory_to_delete = self.env['property.inventory'].search([])
            inventory_to_delete.unlink()
            _logger.info(f"Deleted {len(inventory_to_delete)} inventory records.")
            # Commit the deletions before proceeding
            self.env.cr.commit()
        except Exception as delete_err:
            _logger.error(f"Error deleting existing records: {delete_err}")
            self.env.cr.rollback()
            return # Stop sync if deletion fails
        # --- <<< END DELETION BLOCK >>> ---


        # --- REVISED QUERY WITH ACTIVE FILTER ---
        # The current date logic is now handled *inside* the BigQuery query
        # using CURRENT_DATE('Asia/Kolkata') for timezone-aware comparison,
        # which matches the logic from utils.py.
        
        query = f"""
            WITH LatestPropertyData AS (
                -- Step 1: Find the absolute latest record for each Tag
                SELECT
                    *,
                    ROW_NUMBER() OVER(
                        PARTITION BY Tag
                        ORDER BY SAFE.PARSE_TIMESTAMP('%d-%m-%Y %H:%M:%S', Created_Date) DESC,
                                 upload_timestamp DESC -- Add upload_timestamp as tie-breaker
                    ) as rn
                FROM `{MASTER_PROPERTY_TABLE}`
                WHERE Tag IS NOT NULL AND TRIM(Tag) != ''
            ),
            PropertiesWithStatus AS (
                -- Step 2: Calculate the status for the latest record of each property
                SELECT
                    Tag AS property_tag,
                    Assignee AS assigned_rm,
                    Property_Status,
                    SAFE.PARSE_DATE('%d-%m-%Y', Service_Expiry_Date) as expiry_date,
                    -- Logic to determine current calculated status (matching utils.py)
                    CASE
                        WHEN Property_Status IN ('Sold-CD', 'Sold-Others', 'Rented-CD') THEN 'Sold'
                        WHEN SAFE.PARSE_DATE('%d-%m-%Y', Service_Expiry_Date) < CURRENT_DATE('Asia/Kolkata') THEN 'Expired'
                        ELSE 'Active'
                    END AS calculated_status
                FROM LatestPropertyData
                WHERE rn = 1
            )
            -- Step 3: Select ONLY the properties calculated as 'Active'
            SELECT
                property_tag,
                assigned_rm
            FROM PropertiesWithStatus
            WHERE calculated_status = 'Active'
        """
        # --- END REVISED QUERY ---

        try:
            _logger.info(f"Running BigQuery query to fetch active properties...")
            query_job = client.query(query)
            results = list(query_job.result()) # Fetch all results
            _logger.info(f"Fetched {len(results)} active properties from BigQuery.")

            Users = self.env['res.users']
            synced_count = 0
            missing_rm_count = 0
            processed_tags = set()

            # --- Deactivation Logic REMOVED ---
            # No longer needed as we delete everything first.
            # --- End Deactivation Logic ---


            for row in results:
                # Basic validation
                if not row.property_tag or row.property_tag in processed_tags:
                    continue
                processed_tags.add(row.property_tag)

                # Find the Odoo user for the RM (Assignee)
                rm_user_id = False
                assigned_rm_name = row.assigned_rm # Get the name from the Assignee column
                if assigned_rm_name:
                    try:
                        clean_rm_name = str(assigned_rm_name).strip()
                        if clean_rm_name:
                            rm_user = Users.search([('name', '=', clean_rm_name)], limit=1)
                            if rm_user:
                                rm_user_id = rm_user.id
                            else:
                                missing_rm_count += 1
                                _logger.warning(f"Property '{row.property_tag}': RM '{clean_rm_name}' found in BQ (Assignee) but not in Odoo Users.")
                        else:
                            _logger.debug(f"Property '{row.property_tag}': Assignee column was empty or whitespace.")
                    except Exception as user_search_err:
                        _logger.error(f"Error searching for RM user '{assigned_rm_name}' for property '{row.property_tag}': {user_search_err}")


                vals = {
                    'property_tag': row.property_tag,
                    'rm_user_id': rm_user_id,
                }

                # --- Simplified Logic: Always create ---
                # Since we deleted everything, we only need to create new records.
                try:
                    self.create(vals)
                    synced_count += 1
                except Exception as db_err:
                    _logger.error(f"Database error creating property '{row.property_tag}': {db_err}")
                    self.env.cr.rollback() # Rollback this specific record
                    # Commit successful records so far if needed, or handle errors differently
                    self.env.cr.commit()

            _logger.info(f"Property Inventory Sync Summary: Processed {len(processed_tags)} unique active tags. Created {synced_count} properties.")
            if missing_rm_count > 0:
                _logger.warning(f"Could not find matching Odoo Users for {missing_rm_count} RM assignments (Assignee column) from BigQuery.")

        except Exception as e:
            _logger.error(f"Error during Property Inventory sync query execution or processing: {e}")
            self.env.cr.rollback() # Rollback the whole transaction on major error