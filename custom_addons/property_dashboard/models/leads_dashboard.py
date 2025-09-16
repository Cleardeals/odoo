from odoo import api, models
import logging

_logger = logging.getLogger(__name__)

class LeadsDashboard(models.TransientModel):
    _name = 'leads.dashboard'
    _description = 'Leads Dashboard Backend Model'

    @api.model
    def get_leads_kpis(self):
        """ Gathers and returns KPI data for the leads dashboard/"""

        try:
            lead_model = self.env['lead.score']
        except KeyError:
            _logger.error("❌ Model 'lead.score' not found. Ensure the module is installed.")
            return {'error': "The 'leads' module or  'lead.score' model is not available."}
        
        total_leads = lead_model.search_count([])
        actionable_leads = lead_model.search_count([('is_actionable_today', '=', True)])

        # Chart: Leads by Stage

        stage_data = lead_model.read_group(
            [],
            ['current_status'],
            ['current_status']
        )

        stage_chart = {
            'labels': [d.get('current_status', 'unknown') for d in stage_data],
            'values': [d.get('current_status_count', 0) for d in stage_data],
        }

        return {
            'total_leads': total_leads,
            'actionable_leads': actionable_leads,
            'stage_chart': stage_chart,
        }