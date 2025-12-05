from odoo import models, fields

class NewLeadEvent(models.Model):
    _name = "leads.new.event"
    _description = "New Lead Workflow Event Log"
    _order = "event_timestamp desc"

    # Link back to Dashboard
    dashboard_id = fields.Many2one('leads.new.dashboard', string="Dashboard Lead", required=True, ondelete='cascade')
    
    event_id = fields.Char(string="Event ID", required=True, index=True)
    correlation_id = fields.Char(string="Correlation ID", index=True) 
    
    # This is the field the XML is looking for
    event_timestamp = fields.Datetime(string="Timestamp")
    
    event_type = fields.Char(string="Type")
    message_direction = fields.Selection([('inbound', 'Inbound'), ('outbound', 'Outbound')])
    message_content = fields.Text(string="Content")
    
    # We populate this from BigQuery SQL directly
    template_name = fields.Char(string="Template Name") 
    
    failure_reason = fields.Text(string="Failure Reason")
    raw_payload = fields.Text(string="Raw Payload")