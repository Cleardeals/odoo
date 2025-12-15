from odoo import models, fields, api, _

class SuggestionFeedbackWizard(models.TransientModel):
    _name = "suggestion.feedback.wizard"
    _description = "Wizard to log feedback for a suggested lead"
    suggestion_id = fields.Many2one('property.lead.suggestion', string="Suggested Lead", required=True)

    status = fields.Selection([
        ('new', 'New'),
        ('whatsapp_done', 'WhatsApp Done'),
        ('contacted', 'Contacted'),
        ('details_shared_of_property', 'Details Shared of Property'),
        ('not_interested', 'Not Interested'),
        ('interested', 'Interested'), 
        ('converted', 'Converted'),
        ('other', 'Other'),
    ], string="Status", default='new', index=True, required=True)
    
    rm_feedback = fields.Text(string="RM Feedback")

    def action_confirm(self):
        """Writes the feedback back to the original suggestion record."""
        self.ensure_one()
        self.suggestion_id.write({
            'status': self.status,
            'rm_feedback': self.rm_feedback
        })
        return {'type': 'ir.actions.act_window_close'}
