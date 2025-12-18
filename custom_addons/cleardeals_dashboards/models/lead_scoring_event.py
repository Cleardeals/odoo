# models/lead_scoring_event.py
from odoo import models, fields, api

class LeadScoringEvent(models.Model):
    _name = "lead.scoring.event"
    _description = "Lead Scoring Event Log"
    _order = "event_timestamp desc"
    _rec_name = "event_id"  # [MIGRATION] Added to ensure records have a display name

    lead_id = fields.Many2one('lead.scoring.lead', string="Lead", required=True, ondelete='cascade')
    
    event_id = fields.Char(string="Event ID", required=True, index=True)
    correlation_id = fields.Char(string="Correlation ID", index=True)
    
    event_timestamp = fields.Datetime(string="Timestamp")
    event_type = fields.Char(string="Type")
    message_direction = fields.Selection([('inbound', 'Inbound'), ('outbound', 'Outbound')])
    message_content = fields.Text(string="Content")
    template_name = fields.Char(string="Template Name")
    failure_reason = fields.Text(string="Failure Reason")
    raw_payload = fields.Text(string="Raw Payload")

    # THIS WAS MISSING — THIS IS THE KEY!
    final_status = fields.Char(
        string="Final Status",
        compute="_compute_final_status",
        store=False  # no need to store, fast enough for single-lead views
    )

    @api.depends('correlation_id', 'lead_id.event_ids.event_type', 'lead_id.event_ids.message_direction')
    def _compute_final_status(self):
        for event in self:
            if not event.correlation_id:
                event.final_status = "unknown"
                continue

            # Get all events for this lead with same correlation_id
            # [PERFORMANCE NOTE] This iterates over the lead's history. Efficient for single lead, slower for bulk lists.
            related_events = event.lead_id.event_ids.filtered(
                lambda r: r.correlation_id == event.correlation_id
            )

            if any(e.event_type == 'status_failed' for e in related_events):
                event.final_status = "failed"
            elif any(e.message_direction == 'inbound' for e in related_events):
                event.final_status = "replied"
            elif any(e.event_type == 'status_read' for e in related_events):
                event.final_status = "read"
            elif any(e.event_type == 'status_delivered' for e in related_events):
                event.final_status = "delivered"
            else:
                event.final_status = "sent"