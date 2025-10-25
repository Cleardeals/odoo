from odoo import models, fields, api, _
from odoo.exceptions import UserError
from google.cloud import bigquery
import logging

_logger = logging.getLogger(__name__)

BIGQUERY_PROJECT_ID = 'cleardeals-459513'
ELIGIBLE_PROPERTIES_TABLE_ID = "cleardeals-459513.active_to_active.eligible_properties"
ASSIGNMENT_TABLE_ID = "cleardeals-459513.active_to_active.odoo_lead_assignments"

class PropertyAssignmentStat(models.Model):
    _name = "property.assignment.stat"
    _description = "Property Assignment Statistics"
    _order = "total_assignments desc, last_assignment_date desc"
    _rec_name = 'property_tag'

    property_tag = fields.Char(string="Property Tag", readonly=True, index = True)
    last_eligible_date = fields.Date(string="Last Eligible Date", readonly=True)
    last_assignment_date = fields.Date(string="Last Assignment Date", readonly=True, index = True)
    total_assignments = fields.Integer(string="Total Assignments", readonly=True, index=True)

    _sql_constraints = [
        ('property_tag_uniq', 'unique(property_tag)', 'Property Tag must be unique.')
    ]

    @api.model
    def _cron_sync_property_stats(self):
        """Syncs property stats from BigQuery.
        Fetches all eligible properties and joins with assignment counts
        """

        _logger.info("Starting BigQuery data fetch for Property Assignment Stats")
        try:
            client = bigquery.Client(project=BIGQUERY_PROJECT_ID)
        except Exception as e:
            _logger.error(f"Failed to create BigQuery client: {e}")
            raise UserError(_("Failed to create BigQuery client. Check server logs for details."))
        
        query = f"""
            SELECT
                e.property_tag,
                e.last_eligible_date,
                COALESCE(a.assignment_count, 0) AS total_assignments
            FROM
                `{ELIGIBLE_PROPERTIES_TABLE_ID}` AS e
            LEFT JOIN (
                SELECT
                    assigned_property_tag,
                    COUNT(*) AS assignment_count
                FROM
                    `{ASSIGNMENT_TABLE_ID}`
                GROUP BY
                    assigned_property_tag
            ) AS a
            ON
                e.property_tag = a.assigned_property_tag
        """

        try:
            query_job = client.query(query)
            results = query_job.result()

            synced_count = 0
            for row in results:
                vals = {
                    'property_tag': row.property_tag,
                    'last_eligible_date': row.last_eligible_date,
                    'total_assignments': row.total_assignments
                }

                existing_record = self.search([('property_tag', '=', row.property_tag)], limit=1)
                if existing_record:
                    existing_record.write(vals)
                else:
                    self.create(vals) 
                synced_count += 1

            _logger.info(f"Property Assignment Stats sync completed. Total records synced/updated: {synced_count}")
        
        except Exception as e:
            _logger.error(f"Error during BigQuery data fetch or processing: {e}")
            self.env.cr.rollback()