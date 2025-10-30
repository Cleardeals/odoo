# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from google.cloud import bigquery
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)

# --- CONFIG: Pointing to Customer_Data as the main source ---
MASTER_PROPERTY_TABLE = "cleardeals-459513.cleardeals_dataset.Customer_Data"
BIGQUERY_PROJECT_ID = "cleardeals-459513"

class PropertyInventory(models.Model):
    _name = 'property.inventory'
    _description = 'Master Property Inventory for RM Dashboard'
    _order = 'service_expiry_date asc, property_tag'
    _rec_name = 'property_tag'

    property_tag = fields.Char(string="Property Tag", readonly=True, index=True, required=True)
    owner_name = fields.Char(string="Owner Name", readonly=True)
    owner_phone = fields.Char(string="Owner Phone", readonly=True)
    rm_user_id = fields.Many2one('res.users', string="Assigned RM", readonly=True, index=True)
    service_expiry_date = fields.Date(string="Service Expiry Date", readonly=True, index=True)
    service_expiry_date_str = fields.Char(string="Expiry Date (Display)", readonly=True)
    
    # Status field to track if property is active
    is_active = fields.Boolean(string="Is Active", default=True, readonly=True, index=True)

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
        Cron Job: Syncs ACTIVE properties from BigQuery Customer_Data.
        1. Gets LATEST record for each Tag (deduplication by Created_Date DESC)
        2. Calculates status: Sold/Expired/Active
        3. Only syncs properties with status = 'Active'
        """
        _logger.info("Starting ACTIVE Property Inventory sync from BigQuery Customer_Data...")
        
        try:
            client = bigquery.Client(project=BIGQUERY_PROJECT_ID)
        except Exception as e:
            _logger.error(f"Failed to create BigQuery client: {e}")
            return

        # --- DELETE EXISTING DATA FIRST ---
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
            return

        query = f"""
            WITH LatestPropertyData AS (
                -- Step 1: Deduplicate - Get the LATEST record for each Tag
                SELECT
                    *,
                    ROW_NUMBER() OVER(
                        PARTITION BY Tag
                        ORDER BY SAFE.PARSE_TIMESTAMP('%d-%m-%Y %H:%M:%S', Created_Date) DESC,
                                 upload_timestamp DESC
                    ) as rn
                FROM `{MASTER_PROPERTY_TABLE}`
                WHERE Tag IS NOT NULL AND TRIM(Tag) != ''
            ),
            PropertiesWithStatus AS (
                -- Step 2: Calculate status based on Property_Status and Service_Expiry_Date
                SELECT
                    Tag AS property_tag,
                    REGEXP_EXTRACT(Name, r'(?:Mr\\.|Mrs\\.|Dr\\.)\\s?([A-Za-z\\s]+)') AS owner_name,
                    Phone AS owner_phone,
                    Assignee AS assigned_rm,
                    Service_Expiry_Date,
                    Property_Status,
                    -- Parse expiry date with both formats
                    COALESCE(
                        SAFE.PARSE_DATE('%d/%m/%Y', Service_Expiry_Date),
                        SAFE.PARSE_DATE('%d-%m-%Y', Service_Expiry_Date)
                    ) as expiry_date,
                    CASE
                        WHEN Property_Status IN ('Sold-CD', 'Sold-Others', 'Rented-CD') THEN 'Sold'
                        WHEN COALESCE(
                            SAFE.PARSE_DATE('%d/%m/%Y', Service_Expiry_Date),
                            SAFE.PARSE_DATE('%d-%m-%Y', Service_Expiry_Date)
                        ) < CURRENT_DATE('Asia/Kolkata') THEN 'Expired'
                        ELSE 'Active'
                    END AS calculated_status
                FROM LatestPropertyData
                WHERE rn = 1  -- Only the latest record per Tag
            )
            -- Step 3: Select ONLY Active properties
            SELECT
                property_tag,
                owner_name,
                owner_phone,
                assigned_rm,
                Service_Expiry_Date,
                expiry_date,
                calculated_status
            FROM PropertiesWithStatus
            WHERE calculated_status = 'Active'
            ORDER BY expiry_date ASC NULLS LAST
        """
        
        try:
            _logger.info(f"Running BigQuery query to fetch active properties...")
            query_job = client.query(query)
            results = list(query_job.result())
            _logger.info(f"✅ Fetched {len(results)} active properties from BigQuery.")
            
            Users = self.env['res.users']
            synced_count = 0
            skipped_null_date = 0
            missing_rm_count = 0
            processed_tags = set()

            for row in results:
                # Basic validation
                if not row.property_tag or row.property_tag in processed_tags:
                    continue
                processed_tags.add(row.property_tag)

                if row.expiry_date is None:
                    skipped_null_date += 1
                    _logger.debug(f"Skipping '{row.property_tag}': NULL expiry_date despite Active status")
                    continue

                # Find the Odoo user for the RM (Assignee)
                rm_user_id = False
                assigned_rm_name = row.assigned_rm
                if assigned_rm_name:
                    try:
                        clean_rm_name = str(assigned_rm_name).strip()
                        if clean_rm_name:
                            rm_user = Users.search([('name', '=', clean_rm_name)], limit=1)
                            if rm_user:
                                rm_user_id = rm_user.id
                            else:
                                missing_rm_count += 1
                                _logger.warning(f"Property '{row.property_tag}': RM '{clean_rm_name}' not found in Odoo Users.")
                    except Exception as user_search_err:
                        _logger.error(f"Error searching for RM user '{assigned_rm_name}': {user_search_err}")

                # Parse expiry date
                service_expiry_date = None
                service_expiry_date_str = row.Service_Expiry_Date if row.Service_Expiry_Date else ''
                
                try:
                    # BigQuery returns date objects directly
                    if isinstance(row.expiry_date, str):
                        service_expiry_date = datetime.strptime(row.expiry_date, '%Y-%m-%d').date()
                    else:
                        service_expiry_date = row.expiry_date
                except Exception as date_err:
                    _logger.warning(f"Property '{row.property_tag}': Error converting expiry date: {date_err}")
                    continue

                # Prepare values for creation
                vals = {
                    'property_tag': row.property_tag,
                    'owner_name': row.owner_name if row.owner_name else '',
                    'owner_phone': row.owner_phone if row.owner_phone else '',
                    'rm_user_id': rm_user_id,
                    'service_expiry_date': service_expiry_date,
                    'service_expiry_date_str': service_expiry_date_str,
                    'is_active': True,
                }

                # Create the property record
                try:
                    self.create(vals)
                    synced_count += 1
                except Exception as db_err:
                    _logger.error(f"Database error creating property '{row.property_tag}': {db_err}")
                    self.env.cr.rollback()
                    self.env.cr.commit()

            _logger.info(f"")
            _logger.info(f"========== Property Inventory Sync Summary ==========")
            _logger.info(f"  Total records fetched from BQ: {len(results)}")
            _logger.info(f"  Processed unique tags: {len(processed_tags)}")
            _logger.info(f"  Successfully created: {synced_count}")
            _logger.info(f"  Skipped (NULL expiry date): {skipped_null_date}")
            if missing_rm_count > 0:
                _logger.warning(f"  Missing RM assignments: {missing_rm_count}")
            _logger.info(f"=====================================================")

        except Exception as e:
            _logger.error(f"Error during Property Inventory sync: {e}")
            import traceback
            _logger.error(traceback.format_exc())
            self.env.cr.rollback()

    @api.model
    def _cron_cleanup_expired_properties(self):
        """
        Separate cron job to mark properties as inactive if they've expired.
        Run this daily to check expiry dates.
        """
        _logger.info("Starting cleanup of expired properties...")
        try:
            today = fields.Date.today()
            expired_properties = self.search([
                ('service_expiry_date', '<', today),
                ('is_active', '=', True)
            ])
            
            if expired_properties:
                expired_properties.write({'is_active': False})
                _logger.info(f"Marked {len(expired_properties)} properties as inactive (expired)")
            else:
                _logger.info("No expired properties found")
                
        except Exception as e:
            _logger.error(f"Error during expired properties cleanup: {e}")