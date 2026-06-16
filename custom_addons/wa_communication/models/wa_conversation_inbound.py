"""Inbound WA Cloud API webhook handlers (legacy/direct-push format).

Part of the ``wa.conversation`` model — see wa_conversation.py for the base
definition (fields, constraints, inbound push dispatcher).
"""
import logging

from odoo import api, fields, models
from .wa_conversation import (
    _WA_TYPE_TO_KIND,
    _WA_STATUS_MAP,
    _wa_ts_to_dt,
    _extract_body,
    _extract_media_url,
)

_logger = logging.getLogger(__name__)

class WaConversation(models.Model):
    _inherit = 'wa.conversation'

    def _handle_inbound_wa_message(
        self, msg: dict, value: dict, pubsub_message_id: str
    ) -> None:
        """Create a ``wa.message`` record for one inbound WA message.

        Deduplicates by ``wa_message_id``.  Finds or creates the
        ``wa.conversation`` for the sender's phone number, then creates the
        ``wa.message``.  Updates ``last_message_at`` and ``unread_count`` on
        the conversation.

        :param msg:               Single message object from ``value.messages``.
        :param value:             Full ``change.value`` dict (contains contacts).
        :param pubsub_message_id: GCP message ID for the audit log.
        """
        wa_msg_id: str = msg.get('id', '')
        from_phone: str = msg.get('from', '')
        msg_type: str = msg.get('type', 'unknown')
        ts_str: str = msg.get('timestamp', '')

        contacts = value.get('contacts') or []
        sender_name: str = (
            contacts[0].get('profile', {}).get('name', '') if contacts else ''
        )

        # Resolve message body and media URL from the appropriate sub-object
        body = _extract_body(msg, msg_type)
        media_url = _extract_media_url(msg, msg_type)

        # Resolve context (swipe-reply or button-tap) — find the quoted message
        template_replied_to = ''
        quoted_body = False
        quoted_sender = False
        context_msg_id = (msg.get('context') or {}).get('id', '')
        if context_msg_id:
            orig = self.env['wa.message'].sudo().search(
                [('wa_message_id', '=', context_msg_id)], limit=1
            )
            if orig:
                template_replied_to = orig.template_name or ''
                # For genuine text swipe-replies: populate the quoted block
                if msg_type != 'button_reply':
                    quoted_body = orig.body or orig.template_name or ''
                    quoted_sender = orig.sender_name or ('Workflow' if orig.initiator == 'workflow' else 'RM')

        created_at = _wa_ts_to_dt(ts_str)

        # Deduplicate by WA message ID
        if wa_msg_id:
            existing = self.env['wa.message'].sudo().search(
                [('wa_message_id', '=', wa_msg_id)], limit=1
            )
            if existing:
                _logger.debug(
                    "wa_push: duplicate wa_message_id=%s — skipping", wa_msg_id
                )
                return

        conv = self.sudo()._get_or_create_for_phone(from_phone, sender_name)

        # For inbound: prefer WA profile name, fall back to linked lead name
        display_sender = sender_name or (conv.lead_id.name if conv.lead_id else 'Customer')

        self.env['wa.message'].sudo().create({
            'conversation_id': conv.id,
            'wa_message_id': wa_msg_id or False,
            'direction': 'inbound',
            'initiator': 'buyer',
            'kind': _WA_TYPE_TO_KIND.get(msg_type, 'unknown'),
            'body': body,
            'media_url': media_url or False,
            'template_replied_to': template_replied_to or False,
            'quoted_body': quoted_body or False,
            'quoted_sender': quoted_sender or False,
            'status': 'delivered',
            'sender_name': display_sender,
            'lead_id': conv.lead_id.id if conv.lead_id else False,
            'occurred_at': created_at,
            'raw_payload': msg,
        })

        self.env.cr.execute(
            'SELECT id FROM wa_conversation WHERE id = %s FOR UPDATE',
            (conv.id,)
        )

        conv.invalidate_recordset()

        conv.sudo().write({
            'last_message_at': created_at,
            'last_message_preview': body[:100] if body else '',
            'unread_count': conv.unread_count + 1,
        })

        self.env['wa.event.log'].sudo()._log(
            event_type='wa_message_inbound',
            direction='inbound',
            pubsub_message_id=pubsub_message_id,
            payload={
                'wa_message_id': wa_msg_id,
                'from': from_phone,
                'type': msg_type,
                'sender_name': sender_name,
                'raw': msg,
            },
            status='processed',
        )

    def _handle_wa_status_update(
        self, status: dict, pubsub_message_id: str
    ) -> None:
        """Update ``wa.message.status`` from a WA delivery/read receipt.

        :param status:            Single status object from ``value.statuses``.
        :param pubsub_message_id: GCP message ID for the audit log.
        """
        wa_msg_id: str = status.get('id', '')
        new_status: str = status.get('status', '')
        odoo_status = _WA_STATUS_MAP.get(new_status, '')

        if not odoo_status or not wa_msg_id:
            return

        msg = self.env['wa.message'].sudo().search(
            [('wa_message_id', '=', wa_msg_id)], limit=1
        )
        if msg:
            msg.write({
                'status': odoo_status,
                'status_updated_at': fields.Datetime.now(),
            })

        self.env['wa.event.log'].sudo()._log(
            event_type='wa_status_update',
            direction='inbound',
            pubsub_message_id=pubsub_message_id,
            payload={'wa_message_id': wa_msg_id, 'new_status': new_status, 'raw': status},
            status='processed',
        )

    def _handle_wa_message_ack(
        self, payload: dict, pubsub_message_id: str
    ) -> None:
        """Handle a bridge ACK that assigns a WA message ID to an outbound msg.

        Expected payload shape::

            {
              "type": "message_sent_ack",
              "odoo_message_id": 123,
              "wa_message_id": "wamid.xxxx"
            }

        :param payload:           Decoded Pub/Sub message data.
        :param pubsub_message_id: GCP message ID for the audit log.
        """
        odoo_msg_id: int = payload.get('odoo_message_id', 0)
        wa_msg_id: str = payload.get('wa_message_id', '')

        if not odoo_msg_id or not wa_msg_id:
            _logger.warning(
                "wa_push: message_sent_ack missing fields — payload=%s",
                payload,
            )
            return

        msg = self.env['wa.message'].sudo().browse(odoo_msg_id)
        if msg.exists():
            msg.write({
                'wa_message_id': wa_msg_id,
                'status': 'sent',
                'status_updated_at': fields.Datetime.now(),
            })

        self.env['wa.event.log'].sudo()._log(
            event_type='wa_message_ack',
            direction='inbound',
            pubsub_message_id=pubsub_message_id,
            payload={'odoo_message_id': odoo_msg_id, 'wa_message_id': wa_msg_id, 'raw': payload},
            status='processed',
        )
