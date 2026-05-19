"""Append-only audit log for every WA ↔ Odoo Pub/Sub event."""

import json
import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class WaEventLog(models.Model):
    """Immutable log of every WA Pub/Sub message processed by Odoo.

    One row per inbound push event and per outbound publish call.  Rows are
    never updated or deleted — this is a complete audit trail.

    Use :meth:`_log` to create entries; never call ``create`` directly from
    outside this model.
    """

    _name = 'wa.event.log'
    _description = 'WhatsApp Event Log'
    _order = 'create_date desc'

    event_type = fields.Char('Event Type', required=True, index=True, readonly=True)
    direction = fields.Selection(
        [('inbound', 'Inbound'), ('outbound', 'Outbound')],
        required=True,
        index=True,
        readonly=True,
    )
    topic = fields.Char('Pub/Sub Topic', readonly=True)
    pubsub_message_id = fields.Char('Pub/Sub Message ID', index=True, readonly=True)
    payload = fields.Text('Payload (JSON)', readonly=True)
    status = fields.Selection(
        [('processed', 'Processed'), ('failed', 'Failed')],
        required=True,
        index=True,
        readonly=True,
    )
    error_message = fields.Text('Error', readonly=True)

    # ------------------------------------------------------------------
    # Immutability guard
    # ------------------------------------------------------------------

    def write(self, vals):
        raise AccessError("WhatsApp event log entries are immutable.")

    def unlink(self):
        raise AccessError("WhatsApp event log entries cannot be deleted.")

    # ------------------------------------------------------------------
    # Factory helper
    # ------------------------------------------------------------------

    @api.model
    def _log(
        self,
        *,
        event_type: str,
        direction: str,
        payload: dict | None = None,
        pubsub_message_id: str = '',
        topic: str = '',
        status: str = 'processed',
        error_message: str = '',
    ) -> 'WaEventLog':
        """Create a single event log entry.  Never raises — logging must not
        crash its caller.

        :param event_type:        Short snake_case label, e.g. ``'wa_message_inbound'``.
        :param direction:         ``'inbound'`` or ``'outbound'``.
        :param payload:           Dict that will be JSON-serialised.
        :param pubsub_message_id: GCP Pub/Sub message ID for correlation.
        :param topic:             Pub/Sub topic name (outbound events).
        :param status:            ``'processed'`` (default) or ``'failed'``.
        :param error_message:     Human-readable error if status is ``'failed'``.
        :return: The newly created ``wa.event.log`` record, or an empty
                 recordset if creation itself failed.
        """
        try:
            return self.create({
                'event_type': event_type,
                'direction': direction,
                'topic': topic or False,
                'pubsub_message_id': pubsub_message_id or False,
                'payload': json.dumps(payload) if payload is not None else False,
                'status': status,
                'error_message': error_message or False,
            })
        except Exception:
            _logger.exception(
                "wa.event.log._log failed — event_type=%s direction=%s",
                event_type,
                direction,
            )
            return self.browse()
