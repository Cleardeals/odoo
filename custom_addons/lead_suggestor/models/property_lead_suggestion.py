from odoo import models, fields, api, _
from google.cloud import bigquery
import logging

_logger = logging.getLogger(__name__)

SUGGESTIONS_TABLE_ID = "cleardeals-459513.active_to_active.suggested_leads_for_properties"
BIGQUERY_PROJECT_ID = "cleardeals-459513"

class PropertyLeadSuggestion(models.Model):
    _name = "property.lead.suggestion"
    _description = "Suggested Leads for a Property"
    _order = "generation_date desc, status asc"
    _rec_name = "suggested_lead_phone"

    property_inventory_id = fields.Many2one('property.inventory', string="Property", required=True, ondelete='cascade')

    property_tag = fields.Char(related = 'property_inventory_id.property_tag', string="Property Tag", store=True)

    suggested_lead_phone = fields.Char(string="Suggested Lead Phone", required=True, readonly=True)
    lead_name = fields.Char(string="Lead Name", readonly=True)

    # --- Match Details
    original_property_tag = fields.Char(string="Original Property Tag", readonly=True, required=True)
    original_property_similarity = fields.Float(
        string="Similarity (%)", 
        digits=(16, 2), 
        readonly=True,
        group_operator="avg"
    )

    generation_date = fields.Date(string="Generation Date", readonly=True, default=fields.Date.context_today)

    status = fields.Selection([
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('not_interested', 'Not Interested'),
        ('interested', 'Interested'),
        ('converted', 'Converted')
    ], string="Status", default='new', required=True, index=True)


    rm_feedback = fields.Text(string="RM Feedback")

    _sql_constraints = [
        ('prop_lead_uniq', 'unique(property_inventory_id, suggested_lead_phone)', 'This lead has already been suggested for this property.')
    ]

    def action_log_feedback(self):
        """
        Opens a wizard to log feedback for this suggested lead.
        """

        self.ensure_one
        return {
                        'type': 'ir.actions.act_window',
            'name': _('Log Feedback for %s', self.lead_name or self.suggested_lead_phone),
            'res_model': 'suggestion.feedback.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_suggestion_id': self.id,
                'default_status': self.status,
                'default_rm_feedback': self.rm_feedback,
            }
        }
    
    @api.model
    def _cron_sync_suggestions(self):
        """
        Cron Job: Syncs new suggestions from the BigQuery table.
        It only fetches suggestions from the last 3 days to keep it efficient.
        """
        _logger.info("Starting Lead Suggestions sync...")
        try:
            client = bigquery.Client(project=BIGQUERY_PROJECT_ID)
        except Exception as e:
            _logger.error(f"Failed to create BigQuery client: {e}")
            return
            
        # Fetch new suggestions from the last 3 days
        query = f"""
            SELECT
                active_property_tag,
                suggested_lead_phone,
                lead_name,
                original_property_tag,
                original_property_similarity,
                generation_date
            FROM `{SUGGESTIONS_TABLE_ID}`
            WHERE generation_date >= DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL 3 DAY)
        """
        
        try:
            query_job = client.query(query)
            results = query_job.result()
            
            PropertyInventory = self.env['property.inventory']
            synced_count = 0
            
            for row in results:
                # Find the parent property in Odoo
                prop = PropertyInventory.search([('property_tag', '=', row.active_property_tag)], limit=1)
                if not prop:
                    _logger.warning(f"Skipping suggestion, property '{row.active_property_tag}' not found in Odoo.")
                    continue
                
                # Check if this suggestion already exists
                existing = self.search([
                    ('property_inventory_id', '=', prop.id),
                    ('suggested_lead_phone', '=', row.suggested_lead_phone)
                ], limit=1)
                
                if not existing:
                    self.create({
                        'property_inventory_id': prop.id,
                        'suggested_lead_phone': row.suggested_lead_phone,
                        'lead_name': row.lead_name,
                        'original_property_tag': row.original_property_tag,
                        'original_property_similarity': (row.original_property_similarity or 0) * 100.0,
                        'generation_date': row.generation_date,
                        'status': 'new',
                    })
                    synced_count += 1
            
            _logger.info(f"Successfully synced {synced_count} new lead suggestions.")

        except Exception as e:
            _logger.error(f"Error during Lead Suggestions sync: {e}")
            self.env.cr.rollback()


