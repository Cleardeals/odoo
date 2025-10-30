from odoo import models, fields, api, _
from odoo.exceptions import UserError
from google.cloud import bigquery
import logging

_logger = logging.getLogger(__name__)

BIGQUERY_PROJECT_ID = 'cleardeals-459513'
ASSIGNMENT_TABLE_ID = "active_to_active.lead_assignments"

class ActiveLeadAssignment(models.Model):
    _name = "active.lead.assignment"
    _description = "Active-to-Active Lead Assignment"
    _order = "assignment_date desc"


    lead_phone = fields.Char(string="Lead Phone", readonly=True)
    lead_name = fields.Char(string="Lead Name", readonly=True)

    assigned_property_tag = fields.Char(string="Assigned Property Tag", readonly=True)
    original_property_tag = fields.Char(string="Original Property Tag", readonly=True)
    assignment_date = fields.Date(string="Assignment Date", readonly=True)

    _sql_constraints = [
        ('lead_property_uniq', 'unique(lead_phone, assigned_property_tag)',
        'This lead/Property assignment already exists.')
    ]

    @api.model
    def _cron_fetch_bigquery_data(self):
        """Called by a scheduled action to fetch new assignments from BigQuery.
            This method now links assignments to existing lead.score records
        """
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

            LeadScore = self.env['lead.score']
            created_count = 0
            missing_lead_count = 0

            for row in results:
                exists = self.search_count([
                    ('lead_phone', '=', row.lead_phone),
                    ('assigned_property_tag', '=', row.assigned_property_tag)
                ])

                if not exists:
                    try:
                        self.create({
                            'lead_phone': row.lead_phone,
                            'lead_name': row.lead_name,
                            'assigned_property_tag': row.assigned_property_tag,
                            'original_property_tag': row.original_property_tag,
                            'assignment_date': row.assignment_date
                        })
                        created_count += 1
                    except Exception as e:
                        _logger.error(f"Error creating Active Lead Assignment for lead {row.lead_phone}: {e}")
                        self.env.cr.rollback()

            _logger.info(f"BigQuery data fetch complete. Created {created_count} new assignments. {missing_lead_count} leads missing in lead.score.")
            
        except Exception as e:
            _logger.error(f"Error executing BigQuery query: {e}")
            self.env.cr.rollback()
