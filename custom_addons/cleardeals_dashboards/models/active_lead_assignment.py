from odoo import models, fields, api, _
from odoo.exceptions import UserError
from google.cloud import bigquery
import logging

_logger = logging.getLogger(__name__)

BIGQUERY_PROJECT_ID = 'cleardeals-459513'
ASSIGNMENT_TABLE_ID = "active_to_active.odoo_lead_assignments"

class ActiveLeadAssignment(models.Model):
    _name = "active.lead.assignment"
    _description = "Active-to-Active Lead Assignment"
    _order = "assignment_date desc"


    lead_score_id = fields.Many2one(
        'lead.score',
        string="Lead",
        readonly=True,
        required=True,
        index=True,
        ondelete='cascade'
    )

    lead_name = fields.Char(related='lead_score_id.name', string="Lead Name", readonly=True)
    lead_phone = fields.Char(related='lead_score_id.standardized_phone', string="Lead Phone", readonly=True)

    assigned_property_tag = fields.Char(string="Assigned Property Tag", readonly=True)
    original_property_tag = fields.Char(string="Original Property Tag", readonly=True)
    assignment_date = fields.Date(string="Assignment Date", readonly=True)

    _sql_constraints = [
        ('lead_property_uniq', 'unique(lead_score_id, assigned_property_tag)',
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
                phone_from_bq = row.lead_phone
                lead_score_rec = LeadScore.search([('standardized_phone', '=', phone_from_bq)], limit=1)

                if not lead_score_rec:
                    _logger.warning(f"Skipping assignment: No lead.score found with phone {phone_from_bq}")
                    missing_lead_count += 1
                    continue
                
                exists = self.search_count([
                    ('lead_score_id', '=', lead_score_rec.id),
                    ('assigned_property_tag', '=', row.assigned_property_tag)
                ])

                if not exists:
                    try:
                        self.create({
                            'lead_score_id': lead_score_rec.id,
                            'assigned_property_tag': row.assigned_property_tag,
                            'original_property_tag': row.original_property_tag,
                            'assignment_date': row.assignment_date
                        })
                        created_count += 1
                    except Exception as create_e:
                        _logger.error(f"Failed to create assignment for lead {lead_score_rec.id} and property {row.assigned_property_tag}: {create_e}")
                        self.env.cr.rollback()
            
        except Exception as e:
            _logger.error(f"Error executing BigQuery query: {e}")
            self.env.cr.rollback()
