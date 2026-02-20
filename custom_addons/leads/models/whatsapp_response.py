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

    # [FIX] Logic: Ensure these keys match the list in _compute_response_type
    response = fields.Selection([
        ('yes_going_for_visit', 'Yes, going for the visit'),
        ('need_help', 'Need Help'),
        ('yes_visit_done', 'Yes, Visit done'),
        ('yes_liked_the_property', 'Yes, Liked the Property'),
        ('call_the_expert', 'Call the Expert'),
        ('no_reschedule_visit', 'No, Reschedule visit'),
        ('abhi_call_kare', 'Abhi Call Kare'),
        ('slot_book_kre', 'Slot book kre'),
        ('schedule_visit_now', 'Schedule Visit Now'),
        ('talk_to_a_property_expert', 'Talk to a Property Expert'),
        ('generic_response', 'Generic Response'),
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
        ('neutral', 'Neutral'),
    ], string='Response Type', compute='_compute_response_type', store=True)

    response_date = fields.Datetime(string='Response Date', default=fields.Datetime.now)
    is_processed = fields.Boolean(string='Processed', default=False)
    notes = fields.Text(string='Notes')

    @api.onchange('lead_id')
    def _onchange_lead_id(self):
        """Auto-fill fields based on selected lead."""
        if self.lead_id:
            self.number = self.lead_id.standardized_phone

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
        """
        Categorize responses as positive or neutral.
        [FIX] Updated list to match actual Selection keys defined above.
        """
        positive_responses = [
            'yes_going_for_visit',
            'yes_visit_done',
            'yes_liked_the_property',
            'slot_book_kre',
            'schedule_visit_now',
        ]

        for record in self:
            if record.response in positive_responses:
                record.response_type = 'positive'
            else:
                record.response_type = 'neutral'

    def action_process_response(self):
        """Mark response as processed."""
        for record in self:
            record.is_processed = True

    # [MIGRATION 19.0] Replaced name_get with _compute_display_name
    def _compute_display_name(self):
        for record in self:
            record.display_name = f"Response from {record.lead_name or 'Unknown'}"
