"""Outbound messaging — send_message / send_first_message / templates.

Part of the ``wa.conversation`` model — see wa_conversation.py for the base
definition (fields, constraints, inbound push dispatcher).
"""
import logging
import uuid

from odoo import api, fields, models
from odoo.exceptions import UserError
from . import interakt_client
from .wa_conversation import _TOPIC_WA_REQUESTS

_logger = logging.getLogger(__name__)

class WaConversation(models.Model):
    _inherit = 'wa.conversation'

    _WINDOWED_KINDS = frozenset({'freetext', 'image', 'video', 'document', 'audio'})

    def send_message(
        self,
        body: str = '',
        kind: str = 'freetext',
        template_name: str = '',
        template_language: str = '',
        initiator: str = 'rm',
        request_id: str = '',
        workflow_slug: str = '',
        step_id: str = '',
        enrollment_id: str = '',
        media_url: str = '',
        media_filename: str = '',
        body_values: list | None = None,
        header_values: list | None = None,
    ) -> 'models.Model':
        """Send a WA message from this conversation.

        Creates a queued ``wa.message`` and publishes a send request to the
        ``cd-prod-odoo-wa-requests`` Pub/Sub topic.  The WA bridge sends the
        actual WA message and delivers status receipts back via the inbound
        push path.

        The publish is deferred until after the current SQL transaction
        commits so that a rollback does not trigger a spurious WA send.

        :param body:           Message text (required for freetext kind).
        :param kind:           Message kind — one of the ``wa.message.kind`` values.
        :param template_name:  Template name (required when kind='template').
        :param initiator:      Who is sending — 'rm' (default) or 'workflow'.
        :param request_id:     OdooWaRequest UUID for tracking.
        :param workflow_slug:  Workflow context for automated sends.
        :param step_id:        Workflow step for automated sends.
        :param enrollment_id:  Enrollment UUID for automated sends.
        :param media_url:      Public media URL (image/video/document/audio).
        :param media_filename: Filename hint for documents.
        :param body_values:    Template body variable substitutions.
        :param header_values:  Template header variable substitutions.
        :return:               The newly created ``wa.message`` record.
        :raises UserError:     If the conversation has no phone number, or if the
                               24h free-text window is closed for a non-template kind.
        """
        self.ensure_one()
        if not self.phone_number:
            raise UserError(
                "Cannot send — this conversation has no phone number."
            )

        # Ownership gate: an RM may only send on a chat assigned to them.
        # Managers can send on any chat; system/workflow sends bypass the gate.
        if initiator == 'rm':
            self._assert_can_send()

        # Hard-block non-template sends when the 24h window is closed.
        if kind in self._WINDOWED_KINDS and initiator == 'rm':
            self._compute_window_state()
            if self.window_state == 'closed':
                raise UserError(
                    "The 24-hour WhatsApp window is closed for this contact. "
                    "You can only send template messages until the customer replies."
                )

        import uuid as _uuid
        # Always produce a valid UUID request_id: the bridge stores it in
        # WaSendPayload.enrollment_id and echoes it back on OdooWaEvent so
        # Odoo can correlate status receipts with this wa.message record.
        effective_request_id = request_id if request_id else str(_uuid.uuid4())

        # File the send into the conversation's active inquiry segment (flag-gated).
        # The RM is the source of truth for which property a free-text send is about
        # and sets it via the inbox banner; we honour the current active segment, or
        # bootstrap one for the linked lead if none is active yet.
        send_seg = False
        if self._owa_segments_enabled():
            send_seg = self.active_segment_id or self._owa_ensure_segment(
                inquiry=self.lead_id or None, started_by='rm')

        wa_msg = self.env['wa.message'].create({
            'conversation_id': self.id,
            'direction': 'outbound',
            'initiator': initiator,
            'kind': kind,
            'body': body,
            'template_name': template_name or False,
            'media_url': media_url or False,
            'media_filename': media_filename or False,
            'request_id': effective_request_id,
            'workflow_slug': workflow_slug or False,
            'step_id': step_id or False,
            'enrollment_id': enrollment_id or False,
            'lead_id': self.lead_id.id if self.lead_id else False,
            'segment_id': send_seg.id if send_seg else False,
            'sender_name': self.env.user.name if initiator == 'rm' else None,
            'status': 'queued',
            'occurred_at': fields.Datetime.now(),
        })

        topic = self.env['ir.config_parameter'].sudo().get_param(
            _TOPIC_WA_REQUESTS, 'cd-prod-odoo-wa-requests'
        )
        # Payload matches OdooWaRequest (shared/models.py in the WA platform).
        request_data = {
            'request_type': 'send',
            'request_id': effective_request_id,
            'phone': self.phone_number,
            'kind': kind,
            'message_text': body or None,
            'template_name': template_name or None,
            'template_language': template_language or None,
            'media_url': media_url or None,
            'media_filename': media_filename or None,
            'body_values': body_values or [],
            'header_values': header_values or [],
            'rm_odoo_id': self.env.uid,
            'rm_name': self.env.user.name if self.env.user else None,
        }

        # Defer publish until after the transaction commits.
        def _publish():
            self.env['cleardeals.pubsub'].publish_async(topic, request_data)

        self.env.cr.postcommit.add(_publish)

        self.env['wa.event.log'].sudo()._log(
            event_type='wa_message_outbound',
            direction='outbound',
            topic=topic,
            payload={
                'phone': self.phone_number,
                'kind': kind,
                'message_text': (body or '')[:100],
                'request_id': effective_request_id,
                'wa_message_id': wa_msg.id,
            },
            status='processed',
        )
        return wa_msg

    def mark_as_read(self) -> None:
        """Reset the unread counter for this conversation."""
        self.ensure_one()
        self.write({'unread_count': 0})

    @api.model
    def fetch_templates(self, template_name: str | None = None) -> list[dict]:
        """Fetch APPROVED WhatsApp templates live from Interakt for the picker.

        Odoo holds the Interakt API key (system params) and queries the
        Get-All-Templates endpoint on demand — there is no local cache. Each
        returned template carries its rendered skeleton (header/body/footer),
        button labels, and an ordered list of ``{{N}}`` variable slots so the
        RM can fill them before sending.

        :raises UserError: if the key is unset or Interakt is unreachable.
        """
        return interakt_client.fetch_templates(self.env, template_name=template_name)

    @api.model
    def send_first_message(
        self,
        phone: str,
        lead_id: int | None = None,
        template_name: str = '',
        template_language: str = '',
        body_values: list | None = None,
        header_values: list | None = None,
    ) -> int:
        """Start a new WA conversation and send the first outbound template.

        Called from the lead tab when a lead has no existing ``wa.conversation``.
        Creates (or retrieves) the conversation record, links the lead, auto-claims
        the chat for the sending RM, then sends the template via the normal
        outbound path.

        The ownership gate in :meth:`send_message` is satisfied because we write
        ``assigned_user_id`` *before* calling it — whoever fires the first shot
        owns the conversation going forward (no Interakt handshake needed here
        because the chat does not yet exist on the platform; the first template
        message itself creates it there).

        :param phone:              Raw phone from the lead record (10 or 12 digits).
        :param lead_id:            ``leads.new`` id to link. Optional.
        :param template_name:      Interakt-approved template name (required).
        :param template_language:  Template language code, e.g. ``'en'``.
        :param body_values:        Ordered ``{{N}}`` substitution values.
        :param header_values:      Ordered header variable substitutions.
        :returns:                  The ``wa.conversation`` id so the caller can
                                   load the thread immediately.
        :raises UserError:         Missing phone/template, or send failure.
        """
        if not phone:
            raise UserError(
                "A phone number is required to start a WhatsApp conversation.")
        if not template_name:
            raise UserError(
                "A template message is required for the first outreach.")

        # Normalise to 12-digit E.164 (without '+').
        full_phone = ('91' + phone) if len(phone) == 10 else phone

        # Get or create the conversation record (idempotent).
        conv = self.sudo()._get_or_create_for_phone(full_phone)

        # Link the lead if provided and not already set.
        if lead_id and not conv.lead_id:
            conv.sudo().write({'lead_id': lead_id})

        # Auto-claim: whoever sends the first message owns the chat.
        # Write directly — no Interakt assignment handshake needed because the
        # conversation doesn't exist on the platform yet.
        if not conv.assigned_user_id:
            conv.sudo().write({'assigned_user_id': self.env.uid})

        # Standard outbound path.  Ownership gate passes because env.uid is now
        # the assigned_user_id.
        conv.send_message(
            kind='template',
            template_name=template_name,
            template_language=template_language,
            body_values=body_values or [],
            header_values=header_values or [],
        )
        return conv.id
