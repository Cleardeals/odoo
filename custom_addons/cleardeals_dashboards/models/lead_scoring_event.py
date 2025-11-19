from odoo import models, fields

class LeadScoringEvent(models.Model):
    _name = "lead.scoring.event"
    _description = "Lead Scoring Event Log"
    _order = "event_timestamp desc"

    lead_id = fields.Many2one('lead.scoring.lead', string="Lead", required=True, ondelete='cascade')
    
    event_id = fields.Char(string="Event ID", required=True, index=True)
    # NEW FIELD: To identify unique messages across multiple status updates
    correlation_id = fields.Char(string="Correlation ID", index=True) 
    
    event_timestamp = fields.Datetime(string="Timestamp")
    event_type = fields.Char(string="Type")
    message_direction = fields.Selection([('inbound', 'Inbound'), ('outbound', 'Outbound')])
    message_content = fields.Text(string="Content")
    template_name = fields.Char(string="Template Name") 
    failure_reason = fields.Text(string="Failure Reason")
    raw_payload = fields.Text(string="Raw Payload")