from odoo import models, fields, api

class WhatsAppResponse(models.Model):
    _name = 'whatsapp.response'
    _description = 'WhatsApp Response from Leads'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    # Relational field
    lead_id = fields.Many2one('lead.score', string='Lead', required=True)

    # Original fields
    number = fields.Char(string='Phone Number', required=True)
    response = fields.Selection([
        ('going_for_visit', 'Going for Visit'),
        ('need_assistance', 'Need Assistance'),
        ('need_to_reschedule', 'Need to Reschedule'),
        ('liked_the_property', 'Liked the Property'),
        ('pick_a_convenient_time', 'Pick a Convenient Time'),
        ('successfully_visited', 'Successfully Visited'),
        ('schedule_a_visit', 'Schedule a Visit'),
        ('need_more_information', 'Need More Information'),
        ('call_rm', 'Call RM'),
        ('call_me_back', 'Call Me Back'),
        ('generic_response', 'Generic Response')
    ], string='Response', required=True)

    # Related fields
    assigned_rm_id = fields.Many2one('res.users', string='Assigned RM', related='lead_id.assigned_rm_id', store=True)
    property_address = fields.Char(string='Property Address', related='lead_id.property_address', store=True)
    bhk = fields.Char(string='BHK', related='lead_id.bhk', store=True)
    predicted_score = fields.Float(string='Predicted Score', related='lead_id.predicted_score', store=True)
    lead_name = fields.Char(related='lead_id.name', string='Lead Name', store=True)
    project_name = fields.Char(related='lead_id.project_name', string='Project Name', store=True)
    current_status = fields.Selection(related='lead_id.current_status', string='Lead Status', store=True)

    # Additional fields
    response_type = fields.Selection([
        ('positive', 'Positive'),
        ('neutral', 'Neutral')
    ], string='Response Type', compute='_compute_response_type', store=True)
    response_date = fields.Datetime(string='Response Date', default=fields.Datetime.now)
    is_processed = fields.Boolean(string='Processed', default=False)
    notes = fields.Text(string='Notes')

    @api.onchange('lead_id')
    def _onchange_lead_id(self):
        """Auto-fill fields based on selected lead."""
        if self.lead_id:
            self.number = self.lead_id.standardized_phone
            # Other fields are auto-filled via 'related' attributes (e.g., project_name, assigned_rm_id)

    @api.model_create_multi
    def create(self, vals_list):
        """Remove auto-linking by phone number; rely on lead_id from form."""
        return super().create(vals_list)

    def action_view_lead(self):
        """Returns action to display the related lead.score form view."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'lead.score',
            'view_mode': 'form',
            'res_id': self.lead_id.id,
            'target': 'current',
        }

    @api.depends('response')
    def _compute_response_type(self):
        """Categorize responses as positive, negative, or neutral."""
        positive_responses = ['yes_interested', 'liked_the_property', 'going_for_visit', 'successfully_visited', 'schedule_a_visit']

        for record in self:
            if record.response in positive_responses:
                record.response_type = 'positive'
            else:
                record.response_type = 'neutral'

    def action_process_response(self):
        """Mark response as processed."""
        for record in self:
            record.is_processed = True

    def name_get(self):
        """Custom display name for records."""
        result = []
        for record in self:
            name = f"Response from {record.lead_name}"
            result.append((record.id, name))
        return result