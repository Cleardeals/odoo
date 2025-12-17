# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Handle external dependency gracefully
try:
    from google.cloud import bigquery
except ImportError:
    bigquery = None
    _logger.warning("google-cloud-bigquery library not found. BigQuery syncs will fail.")

BIGQUERY_PROJECT_ID = 'cleardeals-459513'
ASSIGNMENT_TABLE_ID = "active_to_active.lead_assignments"

class ActiveLeadAssignment(models.Model):
    _name = "active.lead.assignment"
    _description = "Active-to-Active Lead Assignment"
    _order = "assignment_date desc"

    lead_phone = fields.Char(string="Lead Phone", readonly=True, index=True)
    lead_name = fields.Char(string="Lead Name", readonly=True)

    assigned_property_tag = fields.Char(string="Assigned Property Tag", readonly=True, index=True)
    original_property_tag = fields.Char(string="Original Property Tag", readonly=True)
    assignment_date = fields.Date(string="Assignment Date", readonly=True)

    _sql_constraints = [
        ('lead_property_uniq', 'unique(lead_phone, assigned_property_tag)',
         'This lead/Property assignment already exists.')
    ]

    @api.model
    def _cron_fetch_bigquery_data(self):
        """
        Called by a scheduled action to fetch new assignments from BigQuery.
        """
        if not bigquery:
            _logger.error("Google Cloud BigQuery library is not installed.")
            return

        _logger.info("Starting BigQuery data fetch for Active Lead Assignments")
        
        try:
            client = bigquery.Client(project=BIGQUERY_PROJECT_ID)
        except Exception as e:
            _logger.error(f"Failed to create BigQuery client: {e}")
            raise UserError(_("Failed to create BigQuery client. Check server logs for details."))
        
        query = f"""
            SELECT
                lead_phone,
                lead_name,
                assigned_property_tag,
                original_property_tag,
                assignment_date
            FROM `{ASSIGNMENT_TABLE_ID}`
            WHERE assignment_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
            ORDER BY assignment_date DESC
        """

        try:
            query_job = client.query(query)
            results = query_job.result()

            created_count = 0
            
            # Optimization: Fetch existing keys in memory to avoid N+1 search queries
            # Key = (lead_phone, assigned_property_tag)
            existing_records = self.search_read([], ['lead_phone', 'assigned_property_tag'])
            existing_keys = {
                (rec['lead_phone'], rec['assigned_property_tag']) 
                for rec in existing_records
            }

            vals_list = []
            
            for row in results:
                # Basic validation
                if not row.lead_phone or not row.assigned_property_tag:
                    continue

                key = (row.lead_phone, row.assigned_property_tag)
                
                if key not in existing_keys:
                    vals_list.append({
                        'lead_phone': row.lead_phone,
                        'lead_name': row.lead_name,
                        'assigned_property_tag': row.assigned_property_tag,
                        'original_property_tag': row.original_property_tag,
                        'assignment_date': row.assignment_date
                    })
                    existing_keys.add(key) # Prevent duplicates in same batch

            if vals_list:
                try:
                    self.create(vals_list)
                    created_count = len(vals_list)
                    _logger.info(f"BigQuery Sync: Created {created_count} new Active Lead Assignments.")
                except Exception as e:
                    _logger.error(f"Failed to create batch assignments: {e}")
                    self.env.cr.rollback()
            else:
                _logger.info("BigQuery Sync: No new assignments found.")
            
        except Exception as e:
            _logger.error(f"Error executing BigQuery query: {e}")
            self.env.cr.rollback()