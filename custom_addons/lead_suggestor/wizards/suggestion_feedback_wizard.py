from odoo import models, fields, api, _

class SuggestionFeedbackWizard(models.TransientModel):
    _name = "suggestion.feedback.wizard"
    _description = "Wizard to log feedback for a suggested lead"
    
    suggestion_id = fields.Many2one('property_lead.suggestion', string="Suggested Lead", required=True)

    status = fields.Selection([
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('not_interested', 'Not Interested'),
        ('converted', 'Converted')
    ], string="Status", required=True)
    
    rm_feedback = fields.Text(string="RM Feedback")

    def action_confirm(self):
        """Writes the feedback back to the original suggestion record."""
        self.ensure_one()
        self.suggestion_id.write({
            'status': self.status,
            'rm_feedback': self.rm_feedback
        })
        return {'type': 'ir.actions.act_window_close'}