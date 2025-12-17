# -*- coding: utf-8 -*-
import json
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

class RenewalInteraktEvent(models.Model):
    _name = "renewal.interakt.event"
    _description = "Renewal Campaign Interakt Event"
    _order = "event_timestamp desc"

    owner_id = fields.Many2one('renewal.property.owner', string="Property Owner", required=True, ondelete='cascade')

    # Raw BQ fields
    event_id = fields.Char(string="Event ID", required=True, index=True)
    correlation_id = fields.Char(string="Correlation ID", index=True)
    conversation_id = fields.Char(string="Owner Phone (Conversation ID)", index=True)
    event_timestamp = fields.Datetime(string="Event Timestamp", readonly=True)
    ingestion_timestamp = fields.Datetime(string="Ingestion Timestamp", readonly=True)
    event_type = fields.Char(string="Event Type", readonly=True)
    message_direction = fields.Selection([
        ('inbound', 'Inbound'),
        ('outbound', 'Outbound')
    ], string="Direction", index=True)

    message_content = fields.Text(string="Message Content")
    failure_reason = fields.Text(string="Failure Reason")
    raw_payload = fields.Text(string="Raw JSON Payload")

    # --- Computed/Parsed Fields (Essential for parent computes) ---
    template_name = fields.Char(
        string="Template Name", 
        compute="_parse_raw_payload", 
        store=True, 
        index=True
    )

    _sql_constraints = [
        ('event_id_owner_id_uniq', 'unique(event_id, owner_id)',
         'The Event ID must be unique per owner.')
    ]

    @api.depends('raw_payload')
    def _parse_raw_payload(self):
        """Parses the raw JSON payload to extract template name safely."""
        for event in self:
            event.template_name = False
            if not event.raw_payload:
                continue

            try:
                payload = json.loads(event.raw_payload)
                data = payload.get('data', {})
                if not data:
                    continue

                message_data = data.get('message', {})
                if message_data:
                    raw_template = message_data.get('raw_template')
                    
                    if isinstance(raw_template, dict):
                        event.template_name = raw_template.get('name')
                    elif isinstance(raw_template, str):
                        try:
                            # Sometimes raw_template is a JSON string inside JSON
                            template_json = json.loads(raw_template)
                            event.template_name = template_json.get('name')
                        except Exception:
                            # It might be just a string name
                            event.template_name = raw_template
                            
            except Exception as e:
                _logger.warning(f"Failed to parse raw_payload for Renewal Event {event.id}: {e}")