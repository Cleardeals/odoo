"""WhatsApp Conversation — thread per customer phone number.

Each ``wa.conversation`` record maps to one WA phone number and tracks the
full message history between Cleardeals and that customer.  It also links
to the ``leads.new`` record that best represents the customer so RMs have
full lead context alongside the chat.

Inbound routing — two formats
------------------------------
The push controller calls :meth:`_process_push_event` for every Pub/Sub event
delivered by GCP.  Two payload formats arrive on the same endpoint:

**OdooWaEvent** (from odoo-bridge S7 via ``wa-odoo-events`` topic):
Detected by the presence of an ``event_type`` key.  Dispatched to
:meth:`_process_odoo_wa_event`, which routes to one of:

- :meth:`_handle_odoo_message_sent`         — outbound message accepted by Interakt.
- :meth:`_handle_odoo_message_delivered`    — delivery receipt + cost.
- :meth:`_handle_odoo_message_read`         — read receipt.
- :meth:`_handle_odoo_message_failed`       — send failure (any reason).
- :meth:`_handle_odoo_lead_replied`         — buyer replied; creates activity.
- :meth:`_handle_odoo_ambiguous_reply`      — unroutable reply; creates activity.
- :meth:`_handle_odoo_permanent_failure`    — permanent/exhausted failure; creates activity.
- :meth:`_handle_odoo_enrollment_created`   — workflow enrollment started.
- :meth:`_handle_odoo_enrollment_completed` — workflow enrollment finished.

**WA Cloud API webhook** (legacy / direct-push format):
Detected by the ``object: 'whatsapp_business_account'`` or ``type`` key.
Dispatches to :meth:`_handle_inbound_wa_message`, :meth:`_handle_wa_status_update`,
or :meth:`_handle_wa_message_ack`.

Outbound messaging
------------------
:meth:`send_message` creates a queued ``wa.message`` and publishes an
``OdooWaRequest`` to ``odoo-wa-requests``.  odoo-bridge sends the actual
WA message and delivers status receipts back via the inbound OdooWaEvent path.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

import psycopg2.errors

from odoo import api, fields, models
from odoo.exceptions import UserError

from . import interakt_client

_logger = logging.getLogger(__name__)

# ir.config_parameter keys -------------------------------------------------
_INBOUND_AUDIENCE_KEY = 'wa_communication.inbound_push_audience'
_TOPIC_WA_REQUESTS = 'wa_communication.topic_odoo_wa_requests'

# Maps WA Cloud API webhook message type → wa.message.kind for inbound messages.
# Outbound kinds (template, freetext, image, document, video, audio) are set
# directly by the caller — they are never derived from a webhook value.
_WA_TYPE_TO_KIND = {
    'text':         'text_reply',
    'button_reply': 'button_reply',
    'image':        'image',
    'document':     'document',
    'video':        'video',
    'audio':        'audio',
    'template':     'template',
    'system':       'system',
    # reaction has no Odoo kind — logged as unknown
}

# Interakt message_content_type → wa.message kind (used by OdooWaEvent lead_replied path)
_INTERAKT_KIND_TO_ODOO = {
    'Image':    'image',
    'Document': 'document',
    'Video':    'video',
    'Audio':    'audio',
    'Text':     'text_reply',
    'Button':   'button_reply',
}

# Mapping from WA status webhook strings to wa.message.status Selection values.
_WA_STATUS_MAP = {
    'sent':      'sent',
    'delivered': 'delivered',
    'read':      'read',
    'failed':    'failed',
}

# Interakt error code → wa.message.status for OdooWaEvent failure events.
_FAILURE_CODE_TO_STATUS = {
    131026: 'meta_blocked',
    131052: 'invalid_number',
    131047: 'opted_out',
    130429: 'rate_limited',
    132000: 'template_error',
    132001: 'template_error',
}


def _parse_iso_dt(dt_str: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp string to a naive UTC datetime.

    Accepts both ``2026-05-19T10:00:00Z`` and ``2026-05-19T10:00:00+00:00``.
    Falls back to ``datetime.utcnow()`` on any parse error.
    """
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError, AttributeError):
        return datetime.utcnow()


def _wa_ts_to_dt(timestamp_str: str) -> datetime:
    """Convert a WA Unix timestamp string to a naive UTC datetime.

    Falls back to ``datetime.utcnow()`` on any parse error so callers never
    have to deal with exceptions from malformed timestamps.
    """
    try:
        return datetime.fromtimestamp(int(timestamp_str), tz=timezone.utc).replace(
            tzinfo=None
        )
    except (ValueError, TypeError, OSError):
        return datetime.utcnow()


class WaConversation(models.Model):
    """One WA conversation thread per customer phone number.

    Keyed on ``phone_number`` (the WA ID: digits only, no ``+``).  The
    optional ``lead_id`` link lets RMs see the full lead context without
    leaving the WA inbox.  When a new inbound message arrives from an unknown
    phone number, :meth:`_get_or_create_for_phone` tries to auto-link to an
    existing ``leads.new`` record with the same ``phone`` value.
    """

    _name = 'wa.conversation'
    _description = 'WhatsApp Conversation'
    _order = 'last_message_at desc, id desc'

    name = fields.Char(
        compute='_compute_name',
        store=True,
        readonly=True,
    )
    phone_number = fields.Char(
        'WA Phone Number',
        required=True,
        index=True,
        help="WA phone number in E.164 format without the leading '+', "
             "e.g. '919876543210'.",
    )
    lead_id = fields.Many2one(
        'leads.new',
        string='Lead',
        index=True,
        ondelete='set null',
        copy=False,
    )
    message_ids = fields.One2many(
        'wa.message',
        'conversation_id',
        string='Messages',
    )
    message_count = fields.Integer(
        compute='_compute_message_count',
        string='Messages',
    )
    last_message_at = fields.Datetime(
        string='Last Message',
        index=True,
        readonly=True,
        copy=False,
    )
    last_message_preview = fields.Char(
        string='Preview',
        readonly=True,
        copy=False,
    )
    unread_count = fields.Integer(
        string='Unread',
        default=0,
        readonly=True,
        copy=False,
    )
    state = fields.Selection(
        [('active', 'Active'), ('archived', 'Archived')],
        default='active',
        required=True,
        index=True,
    )
    assigned_user_id = fields.Many2one(
        'res.users',
        string='Assigned RM',
        index=True,
        ondelete='set null',
        copy=False,
        help="RM currently owning this conversation. Synced to Interakt via reassignment.",
    )
    assignment_pending = fields.Boolean(
        'Assignment Pending',
        default=False,
        copy=False,
        help="True while a reassignment request is in flight to the platform and "
             "Interakt confirmation has not yet returned. The composer shows a "
             "spinner during this window.",
    )
    window_expires_at = fields.Datetime(
        string='Window Expires',
        readonly=True,
        copy=False,
        help="UTC time when the 24h free-text window closes. "
             "Computed from last inbound message; overwritten by platform when provided.",
    )
    window_state = fields.Selection(
        [('open', 'Open'), ('closed', 'Closed')],
        string='Chat Window',
        compute='_compute_window_state',
        store=False,
        help="Whether the WhatsApp 24h free-text window is currently open.",
    )
    interakt_inbox_url = fields.Char(
        string='Interakt Inbox URL',
        compute='_compute_interakt_inbox_url',
        store=False,
    )

    _sql_constraints = [
        (
            'phone_unique',
            'UNIQUE(phone_number)',
            'A conversation already exists for this phone number.',
        ),
    ]

    # ------------------------------------------------------------------
    # Computed fields
    # ------------------------------------------------------------------

    @api.depends('lead_id.name', 'phone_number')
    def _compute_name(self):
        for rec in self:
            rec.name = rec.lead_id.name if rec.lead_id else rec.phone_number

    @api.depends('message_ids')
    def _compute_message_count(self):
        for rec in self:
            rec.message_count = len(rec.message_ids)

    def _compute_window_state(self):
        now = datetime.utcnow()
        for rec in self:
            if rec.window_expires_at and rec.window_expires_at > now:
                rec.window_state = 'open'
            else:
                rec.window_state = 'closed'

    def _compute_interakt_inbox_url(self):
        for rec in self:
            if rec.phone_number:
                rec.interakt_inbox_url = (
                    f'https://app.interakt.ai/inbox?channelPhoneNumber={rec.phone_number}'
                )
            else:
                rec.interakt_inbox_url = False

    # ------------------------------------------------------------------
    # Inbound — conversation lookup / creation
    # ------------------------------------------------------------------

    @api.model
    def _get_or_create_for_phone(
        self, phone_number: str, sender_name: str = ''
    ) -> 'WaConversation':
        """Return the conversation for ``phone_number``, creating it if needed.

        On creation, auto-links to the most recent ``leads.new`` record whose
        ``phone`` field matches ``phone_number``.

        :param phone_number: WA phone number (digits only, no ``+``).
        :param sender_name:  Display name from the WA contact object
                             (used only for logging; not stored).
        :return: Existing or newly created ``wa.conversation`` record.
        """
        conv = self.search([('phone_number', '=', phone_number)], limit=1)
        if conv:
            return conv

        # leads.new stores a standardized 10-digit number (strips leading 91).
        # wa.conversation stores the full E.164-without-plus (12 digits, e.g. 919876543210).
        # Strip the 91 country prefix for the lead lookup.
        lead_phone = phone_number[2:] if phone_number.startswith('91') and len(phone_number) == 12 else phone_number
        lead = self.env['leads.new'].search(
            [('phone', '=', lead_phone)],
            order='create_date desc',
            limit=1,
        )
        _logger.info(
            "wa.conversation: creating new thread for %s (sender_name=%r, lead=%s)",
            phone_number,
            sender_name,
            lead.id or 'none',
        )
        return self.create({
            'phone_number': phone_number,
            'lead_id': lead.id if lead else False,
        })

    # ------------------------------------------------------------------
    # Inbound — push event router
    # ------------------------------------------------------------------

    @api.model
    def _process_push_event(
        self, payload: dict, attributes: dict, pubsub_message_id: str
    ) -> None:
        """Route an inbound Pub/Sub event to the correct handler.

        Expected ``payload`` shape follows the WA Cloud API webhook format::

            {
              "object": "whatsapp_business_account",
              "entry": [{
                "changes": [{
                  "value": {
                    "messages": [...],     # inbound messages
                    "statuses": [...],     # delivery/read receipts
                  }
                }]
              }]
            }

        Unknown top-level ``value`` keys are logged to ``wa.event.log`` and
        silently dropped so GCP always receives a 200 ACK.

        :param payload:           Decoded JSON from the Pub/Sub message data.
        :param attributes:        Pub/Sub message attributes dict.
        :param pubsub_message_id: GCP message ID for deduplication / audit.
        """
        # OdooWaEvent (from odoo-bridge S7): detected by the event_type key.
        if 'event_type' in payload:
            self._process_odoo_wa_event(payload, pubsub_message_id)
            return

        try:
            entry = (payload.get('entry') or [{}])[0]
            change = (entry.get('changes') or [{}])[0]
            value = change.get('value', {})

            if value.get('messages'):
                for msg in value['messages']:
                    self._handle_inbound_wa_message(
                        msg, value, pubsub_message_id
                    )

            elif value.get('statuses'):
                for status in value['statuses']:
                    self._handle_wa_status_update(status, pubsub_message_id)

            elif payload.get('type') == 'message_sent_ack':
                # Bridge ACK: WA assigned an ID to one of our outbound msgs.
                self._handle_wa_message_ack(payload, pubsub_message_id)

            else:
                _logger.debug(
                    "wa_push: unhandled payload for message %s — value keys: %s",
                    pubsub_message_id,
                    list(value.keys()) if value else list(payload.keys()),
                )
                self.env['wa.event.log'].sudo()._log(
                    event_type='wa_unknown',
                    direction='inbound',
                    pubsub_message_id=pubsub_message_id,
                    payload=payload,
                    status='processed',
                )

        except Exception as exc:
            _logger.exception(
                "wa_push: unhandled exception for message %s", pubsub_message_id
            )
            self.env['wa.event.log'].sudo()._log(
                event_type='wa_processing_error',
                direction='inbound',
                pubsub_message_id=pubsub_message_id,
                payload={'error': str(exc)},
                status='failed',
                error_message=str(exc),
            )

    # ------------------------------------------------------------------
    # Inbound handlers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # OdooWaEvent routing (events from WA platform odoo-bridge S7)
    # ------------------------------------------------------------------

    @api.model
    def _process_odoo_wa_event(self, event: dict, pubsub_message_id: str) -> None:
        """Dispatch an OdooWaEvent to its specific handler.

        :param event:             Decoded OdooWaEvent payload dict.
        :param pubsub_message_id: GCP message ID for the audit log.
        """
        event_type = event.get('event_type', '')
        _ODOO_WA_HANDLERS = {
            'message_sent':            self._handle_odoo_message_sent,
            'message_delivered':       self._handle_odoo_message_delivered,
            'message_read':            self._handle_odoo_message_read,
            'message_failed':          self._handle_odoo_message_failed,
            'lead_replied':            self._handle_odoo_lead_replied,
            'ambiguous_reply':         self._handle_odoo_ambiguous_reply,
            'permanent_failure':       self._handle_odoo_permanent_failure,
            'retry_exhausted':         self._handle_odoo_permanent_failure,
            'enrollment_created':      self._handle_odoo_enrollment_created,
            'enrollment_completed':    self._handle_odoo_enrollment_completed,
            'enrollment_step_changed': self._handle_odoo_enrollment_step_changed,
            # Chat assignment confirmation from the platform (Interakt result:true)
            'assignment_confirmed':     self._handle_odoo_assignment_confirmed,
            # Workflow registry sync — routes to wa.workflow model
            'workflow.registry.synced': self._handle_workflow_registry_synced,
            # Workflow toggle ACK — WA platform confirms toggle was applied
            'workflow.synced':          self._handle_workflow_synced,
        }
        handler = _ODOO_WA_HANDLERS.get(event_type)
        # Log every OdooWaEvent to the webhook log BEFORE dispatching so that
        # even failed or unknown events leave an audit trail.
        try:
            self.env['wa.event.log'].sudo()._log(
                event_type=f'odoo_wa_{event_type}' if event_type else 'odoo_wa_unknown',
                direction='inbound',
                pubsub_message_id=pubsub_message_id,
                payload=event,
                status='processed',
            )
        except Exception:
            pass  # never let audit logging break event processing
        try:
            if handler:
                # Savepoint isolates the handler's DB work.  If the handler
                # raises any exception (including DeadlockDetected), the
                # savepoint rolls back cleanly — leaving the outer transaction
                # in a usable state so the error-log INSERT below can succeed.
                with self.env.cr.savepoint():
                    handler(event, pubsub_message_id)
            else:
                _logger.debug(
                    "wa_push: unhandled OdooWaEvent type=%r message=%s",
                    event_type, pubsub_message_id,
                )
        except psycopg2.errors.SerializationFailure:
            # Two concurrent Pub/Sub deliveries of the same event raced to update
            # the same wa.message row.  The other transaction won; this one is a
            # no-op.  Log at DEBUG to avoid noisy error alerts.
            _logger.debug(
                "wa_push: SerializationFailure on type=%r message=%s — concurrent "
                "delivery, row already updated by the other worker (harmless)",
                event_type, pubsub_message_id,
            )
            return
        except Exception as exc:
            _logger.exception(
                "wa_push: OdooWaEvent handler failed for type=%r message=%s",
                event_type, pubsub_message_id,
            )
            try:
                self.env['wa.event.log'].sudo()._log(
                    event_type=f'odoo_wa_{event_type}_error',
                    direction='inbound',
                    pubsub_message_id=pubsub_message_id,
                    payload={'error': str(exc), 'event': event},
                    status='failed',
                    error_message=str(exc),
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # OdooWaEvent helpers
    # ------------------------------------------------------------------

    def _owa_get_conversation(self, phone: str) -> 'WaConversation':
        """Return the conversation for *phone*, creating it if needed."""
        return self.sudo()._get_or_create_for_phone(phone)

    def _owa_find_message(
        self,
        wa_message_id: str = '',
        request_id: str = '',
        enrollment_id: str = '',
        step_id: str = '',
    ) -> 'models.Model':
        """Find an existing ``wa.message`` by identity keys.

        Tries three keys in priority order:
        1. ``wa_message_id`` — WA-assigned message ID (most specific).
        2. ``request_id``    — OdooWaRequest UUID (RM-initiated sends).
        3. ``enrollment_id`` + ``step_id`` — workflow-initiated sends where
           Interakt may return a null message ID (e.g. in emulator / sandbox).
           This prevents duplicate records when the same ``message_sent`` event
           is delivered multiple times (fan-out from several engine replicas).

        Returns an empty recordset if no key matches.
        """
        WaMsg = self.env['wa.message'].sudo()
        if wa_message_id:
            msg = WaMsg.search([('wa_message_id', '=', wa_message_id)], limit=1)
            if msg:
                return msg
        if request_id:
            msg = WaMsg.search([('request_id', '=', request_id)], limit=1)
            if msg:
                return msg
        if enrollment_id and step_id:
            msg = WaMsg.search(
                [('enrollment_id', '=', enrollment_id), ('step_id', '=', step_id)],
                limit=1,
            )
            if msg:
                return msg
        return WaMsg.browse()

    def _owa_resolve_lead(
        self, actor_id: int | None, actor_type: str, phone: str
    ) -> 'models.Model':
        """Resolve a ``leads.new`` record from actor context.

        Tries ``actor_id`` first (fast path), then falls back to a phone search.
        Returns an empty recordset for non-buyer_inquiry actor types.
        """
        if actor_type == 'buyer_inquiry' and actor_id:
            lead = self.env['leads.new'].sudo().browse(actor_id)
            if lead.exists():
                return lead
        return self.env['leads.new'].sudo().search(
            [('phone', '=', phone)], order='create_date desc', limit=1
        )

    @staticmethod
    def _owa_failure_status(failure_code: int | None) -> str:
        """Map an Interakt error code to a ``wa.message.status`` value."""
        return _FAILURE_CODE_TO_STATUS.get(failure_code, 'failed')

    def _owa_resolve_quoted_context(self, conv, template_replied_to, event):
        """Resolve the message a buyer reply refers to (swipe / button reply).

        Returns ``(quoted_body, quoted_sender, src_record_or_None)`` so the inbound
        bubble can show the quoted snippet WhatsApp-style and link to it.  Order:
          1. ``source_message_id`` (Interakt id of the quoted message) → match the
             exact ``wa.message`` by ``wa_message_id`` — works for ANY kind
             (template, RM free-text, media, buyer message), not just templates.
          2. ``template_replied_to`` → most recent earlier outbound message with
             that template name.
          3. Platform-supplied ``quoted_body`` / ``source_message_text``.
        """
        def _snippet(src):
            text = (
                (src.template_body or '').strip()
                or (src.body or '').strip()
                or (src.template_header or '').strip()
                or (src.media_filename or '').strip()
                or (src.template_name or '')
                or (f'[{src.kind}]' if src.kind else '')
            )
            sender = src.sender_name or (
                conv.lead_id.name if src.direction == 'inbound' and conv.lead_id else 'You'
            )
            return (text[:140] or None), sender

        # 1. Exact reference by Interakt message id (any message kind).
        source_message_id = event.get('source_message_id')
        if source_message_id:
            src = conv.message_ids.filtered(
                lambda m: m.wa_message_id == source_message_id
            )[:1]
            if src:
                body, sender = _snippet(src)
                return body, sender, src

        # 2. Template-name match (button replies, or when no id is supplied).
        if template_replied_to:
            orig = conv.message_ids.filtered(
                lambda m: m.direction == 'outbound'
                and m.template_name == template_replied_to
            ).sorted('occurred_at')
            if orig:
                body, sender = _snippet(orig[-1])
                return body, sender, orig[-1]

        # 3. Platform-supplied quoted text fallback (no linkable record).
        q_body = event.get('quoted_body') or event.get('source_message_text')
        if q_body:
            return q_body, (event.get('quoted_sender') or 'You'), None

        return None, None, None

    @staticmethod
    def _owa_template_content_vals(event: dict, msg) -> dict:
        """Extract rendered template content from a status event into write vals.

        wa-sender enriches ``message_delivered``/``message_read`` events with the
        template body/header/footer/buttons rendered from Interakt's
        ``raw_template`` (placeholders substituted).  Persist them so the chat
        bubble shows the real message text instead of just the template name.
        Only fills ``body`` when the message doesn't already carry text.
        """
        rendered_body = event.get('rendered_body')
        if rendered_body is None and not event.get('template_buttons'):
            return {}
        vals = {}
        # 'body' is immutable (append-only); render into the dedicated
        # template_body field instead and only when not already populated.
        if rendered_body and not (msg.template_body or '').strip():
            vals['template_body'] = rendered_body
        header = event.get('rendered_header')
        if header:
            vals['template_header'] = header
        footer = event.get('template_footer')
        if footer:
            vals['template_footer'] = footer
        buttons = event.get('template_buttons')
        if buttons:
            vals['template_buttons'] = buttons
        return vals

    # ------------------------------------------------------------------
    # OdooWaEvent handlers
    # ------------------------------------------------------------------

    def _handle_odoo_message_sent(self, event: dict, pubsub_message_id: str) -> None:
        """Handle message_sent — outbound message accepted by Interakt.

        If a ``wa.message`` already exists for this ``request_id`` (created by
        :meth:`send_message` when the RM initiated the send), update it.
        Otherwise create a new record (workflow-initiated send).
        """
        phone          = event.get('phone', '')
        wa_message_id  = event.get('wa_message_id') or ''
        request_id     = event.get('request_id') or ''
        actor_id       = event.get('actor_id')
        actor_type     = event.get('actor_type', '')
        rm_odoo_id     = event.get('rm_odoo_id')
        workflow_slug  = event.get('workflow_slug') or False
        template_name  = event.get('template_name') or False
        step_id        = event.get('step_id') or False
        enrollment_id  = event.get('enrollment_id') or False
        occurred_at    = _parse_iso_dt(event.get('occurred_at', ''))
        initiator      = 'workflow' if workflow_slug else 'rm'
        kind           = 'template' if template_name else 'freetext'

        msg = self._owa_find_message(
            wa_message_id=wa_message_id,
            request_id=request_id,
            enrollment_id=enrollment_id,
            step_id=step_id,
        )
        if msg:
            # RM-initiated send: update the queued record created by send_message()
            vals = {
                'wa_message_id':   wa_message_id or msg.wa_message_id,
                'status':          'sent',
                'status_updated_at': fields.Datetime.now(),
            }
            vals.update(self._owa_template_content_vals(event, msg))
            msg.write(vals)
        else:
            # Workflow-initiated send: Odoo never created a wa.message for this
            conv  = self._owa_get_conversation(phone)
            lead  = self._owa_resolve_lead(actor_id, actor_type, phone)
            create_vals = {
                'conversation_id':  conv.id,
                'wa_message_id':    wa_message_id or False,
                'request_id':       request_id or False,
                'direction':        'outbound',
                'initiator':        initiator,
                'kind':             kind,
                'template_name':    template_name,
                'workflow_slug':    workflow_slug,
                'step_id':          step_id,
                'enrollment_id':    enrollment_id,
                'lead_id':          lead.id if lead else False,
                'platform_actor_id': actor_id or 0,
                'status':           'sent',
                'status_updated_at': fields.Datetime.now(),
                'occurred_at':      occurred_at,
            }
            # Rendered template content (header/body/footer/buttons), if present.
            if event.get('rendered_body'):
                create_vals['template_body'] = event['rendered_body']
            if event.get('rendered_header'):
                create_vals['template_header'] = event['rendered_header']
            if event.get('template_footer'):
                create_vals['template_footer'] = event['template_footer']
            if event.get('template_buttons'):
                create_vals['template_buttons'] = event['template_buttons']
            self.env['wa.message'].sudo().create(create_vals)
            conv.sudo().write({'last_message_at': occurred_at})

    def _handle_odoo_message_delivered(
        self, event: dict, pubsub_message_id: str
    ) -> None:
        """Handle message_delivered — update status and record delivery cost."""
        wa_message_id = event.get('wa_message_id') or ''
        request_id    = event.get('request_id') or ''
        enrollment_id = event.get('enrollment_id') or ''
        step_id       = event.get('step_id') or ''
        cost_inr      = event.get('cost_inr') or 0.0
        occurred_at   = _parse_iso_dt(event.get('occurred_at', ''))

        msg = self._owa_find_message(
            wa_message_id=wa_message_id,
            request_id=request_id,
            enrollment_id=enrollment_id,
            step_id=step_id,
        )
        if msg:
            vals = {
                'status':          'delivered',
                'cost_inr':        cost_inr,
                'delivered_at':    occurred_at,
                'status_updated_at': fields.Datetime.now(),
            }
            vals.update(self._owa_template_content_vals(event, msg))
            msg.write(vals)
        else:
            _logger.debug(
                "wa_push: message_delivered — no wa.message found for "
                "wa_message_id=%r request_id=%r enrollment_id=%r step_id=%r",
                wa_message_id, request_id, enrollment_id, step_id,
            )

    def _handle_odoo_message_read(self, event: dict, pubsub_message_id: str) -> None:
        """Handle message_read — update status to read."""
        wa_message_id = event.get('wa_message_id') or ''
        request_id    = event.get('request_id') or ''
        enrollment_id = event.get('enrollment_id') or ''
        step_id       = event.get('step_id') or ''
        occurred_at   = _parse_iso_dt(event.get('occurred_at', ''))

        msg = self._owa_find_message(
            wa_message_id=wa_message_id,
            request_id=request_id,
            enrollment_id=enrollment_id,
            step_id=step_id,
        )
        if msg:
            vals = {
                'status':          'read',
                'seen_at':         occurred_at,
                'status_updated_at': fields.Datetime.now(),
            }
            vals.update(self._owa_template_content_vals(event, msg))
            msg.write(vals)
        else:
            _logger.debug(
                "wa_push: message_read — no wa.message found for "
                "wa_message_id=%r request_id=%r enrollment_id=%r step_id=%r",
                wa_message_id, request_id, enrollment_id, step_id,
            )

    def _handle_odoo_message_failed(self, event: dict, pubsub_message_id: str) -> None:
        """Handle message_failed — update status using the Interakt error code."""
        wa_message_id  = event.get('wa_message_id') or ''
        request_id     = event.get('request_id') or ''
        failure_code   = event.get('failure_code')
        failure_reason = event.get('failure_reason') or ''
        new_status     = self._owa_failure_status(failure_code)

        msg = self._owa_find_message(wa_message_id=wa_message_id, request_id=request_id)
        if msg:
            msg.write({
                'status':          new_status,
                'status_updated_at': fields.Datetime.now(),
            })
            _logger.info(
                "wa_push: message_failed — wa_message_id=%r code=%s reason=%r status→%s",
                wa_message_id, failure_code, failure_reason, new_status,
            )
        else:
            _logger.warning(
                "wa_push: message_failed — no wa.message found for "
                "wa_message_id=%r request_id=%r",
                wa_message_id, request_id,
            )

    def _handle_odoo_lead_replied(self, event: dict, pubsub_message_id: str) -> None:
        """Handle lead_replied — buyer sent a message; create wa.message + notify RM."""
        phone           = event.get('phone', '')
        wa_message_id   = event.get('wa_message_id') or ''
        actor_id        = event.get('actor_id')
        actor_type      = event.get('actor_type', '')
        rm_odoo_id      = event.get('rm_odoo_id')
        message_text    = event.get('message_text') or ''
        button_reply_id = event.get('button_reply_id')
        template_replied_to = (
            event.get('source_template_name', '')
            or event.get('template_name', '')
            or event.get('original_template_name', '')
        )
        occurred_at     = _parse_iso_dt(event.get('occurred_at', ''))
        # Media fields forwarded from the WA platform
        media_url       = event.get('media_url') or False
        media_filename  = event.get('media_filename') or False
        # Map Interakt message_content_type → Odoo kind; fall back to button/text logic
        interakt_kind   = event.get('message_kind') or ''
        kind = (
            _INTERAKT_KIND_TO_ODOO.get(interakt_kind)
            or ('button_reply' if button_reply_id else 'text_reply')
        )

        # Deduplicate by wa_message_id — with a twist for button / CTA replies.
        #
        # A quick-reply tap reuses the TEMPLATE's outbound Interakt id as the
        # reply's message id (the gateway sets it for click→template correlation).
        # Naively deduping on that id finds the OUTBOUND template row and silently
        # drops EVERY button reply (and makes a second, different-button tap look
        # like a duplicate of the first).  Detect that case: when the id only
        # matches an OUTBOUND message, that message IS the one being replied to —
        # store the reply under a distinct id derived from the button so each tap
        # is recorded, and link it as the quoted original.
        store_wa_message_id = wa_message_id
        quoted_src_from_collision = None
        if wa_message_id:
            existing = self._owa_find_message(wa_message_id=wa_message_id)
            if existing and existing.direction == 'inbound':
                _logger.debug("wa_push: lead_replied duplicate wa_message_id=%s", wa_message_id)
                return
            if existing and existing.direction == 'outbound':
                quoted_src_from_collision = existing
                suffix = (button_reply_id or message_text or 'reply').strip().replace(' ', '_')[:40]
                store_wa_message_id = f"{wa_message_id}:r:{suffix}"
                # Re-dedup on the synthetic id so Pub/Sub redelivery of the same
                # tap doesn't create a second row.
                if self._owa_find_message(wa_message_id=store_wa_message_id):
                    _logger.debug(
                        "wa_push: lead_replied duplicate synthetic id=%s", store_wa_message_id
                    )
                    return

        conv = self._owa_get_conversation(phone)
        lead = self._owa_resolve_lead(actor_id, actor_type, phone)

        # Prefer event-supplied rm_odoo_id; fall back to the RM already assigned
        # on the lead so that existing assignments are honoured without re-assigning.
        if not rm_odoo_id and lead and lead.user_id:
            rm_odoo_id = lead.user_id.id

        # Lock the conversation row BEFORE creating wa.message.  The FK
        # insert acquires FOR KEY SHARE on wa_conversation; if we also need
        # FOR UPDATE afterwards (to write last_message_at), both workers end
        # up holding KEY SHARE while waiting for the other's upgrade →
        # deadlock.  Locking first avoids that upgrade path entirely.
        self.env.cr.execute(
            'SELECT id FROM wa_conversation WHERE id = %s FOR UPDATE',
            (conv.id,)
        )
        conv.invalidate_recordset()

        # For media messages, caption may arrive as literal "None" from Interakt.
        body = message_text if message_text != 'None' else ''
        # Resolve the quoted/swipe context so the bubble can show what the buyer
        # replied to (WhatsApp-style), matched to the referenced template.
        quoted_body, quoted_sender, quoted_src = self._owa_resolve_quoted_context(
            conv, template_replied_to, event,
        )
        # Fall back to the collision-detected template (button/CTA reply) when no
        # explicit message_context reference was supplied.
        if not quoted_src and quoted_src_from_collision:
            quoted_src = quoted_src_from_collision
            if not quoted_body:
                quoted_body = (
                    (quoted_src.template_body or '').strip()
                    or (quoted_src.body or '').strip()
                    or (quoted_src.template_header or '').strip()
                    or quoted_src.template_name
                    or ''
                )[:140] or False
                quoted_sender = quoted_sender or quoted_src.sender_name or 'You'
        self.env['wa.message'].sudo().create({
            'conversation_id':   conv.id,
            'wa_message_id':     store_wa_message_id or False,
            'direction':         'inbound',
            'initiator':         'buyer',
            'kind':              kind,
            'body':              body,
            'media_url':         media_url,
            'media_filename':    media_filename,
            'template_replied_to': template_replied_to or False,
            'quoted_body':       quoted_body or False,
            'quoted_sender':     quoted_sender or False,
            'quoted_message_id': quoted_src.id if quoted_src else False,
            'lead_id':           lead.id if lead else False,
            'platform_actor_id': actor_id or 0,
            'status':            'delivered',
            'occurred_at':       occurred_at,
        })

        # Update window_expires_at from platform if provided, else derive from occurred_at.
        window_expires_at_raw = event.get('window_expires_at')
        if window_expires_at_raw:
            try:
                window_expires_at = _parse_iso_dt(window_expires_at_raw)
            except Exception:
                window_expires_at = None
        else:
            from datetime import timedelta
            window_expires_at = occurred_at + timedelta(hours=24) if occurred_at else None

        conv_vals = {
            'last_message_at':      occurred_at,
            'last_message_preview': (message_text or '')[:100],
            'unread_count':         conv.unread_count + 1,
        }
        if window_expires_at:
            conv_vals['window_expires_at'] = window_expires_at
        if lead and not conv.lead_id:
            conv_vals['lead_id'] = lead.id
        conv.sudo().write(conv_vals)

        # bus.bus notification to RM — replaces mail.activity
        if rm_odoo_id:
            lead_name = (lead.name if lead else '')
            try:
                self.env['bus.bus']._sendone(
                    f'wa_notification_{rm_odoo_id}',
                    'wa_event',
                    {
                        'type':      'lead_replied',
                        'actor_id':  actor_id,
                        'lead_id':   lead.id if lead else None,
                        'lead_name': lead_name,
                        'phone':     phone,
                        'message':   message_text[:80] if message_text else '',
                        'lead_url':  f'/web#model=leads.new&id={lead.id}' if lead else '',
                    },
                )
            except Exception:
                _logger.exception("wa_push: failed to send bus.bus for lead_replied")

    def _handle_odoo_ambiguous_reply(
        self, event: dict, pubsub_message_id: str
    ) -> None:
        """Handle ambiguous_reply — reply unroutable; create wa.message + notify RM."""
        phone          = event.get('phone', '')
        wa_message_id  = event.get('wa_message_id') or ''
        actor_id       = event.get('actor_id')
        actor_type     = event.get('actor_type', '')
        rm_odoo_id     = event.get('rm_odoo_id')
        message_text   = event.get('message_text') or ''
        occurred_at    = _parse_iso_dt(event.get('occurred_at', ''))

        if wa_message_id and self._owa_find_message(wa_message_id=wa_message_id):
            return

        conv = self._owa_get_conversation(phone)
        lead = self._owa_resolve_lead(actor_id, actor_type, phone)

        # Lock BEFORE create — same deadlock prevention as _handle_odoo_lead_replied.
        self.env.cr.execute(
            'SELECT id FROM wa_conversation WHERE id = %s FOR UPDATE',
            (conv.id,)
        )
        conv.invalidate_recordset()

        self.env['wa.message'].sudo().create({
            'conversation_id':   conv.id,
            'wa_message_id':     wa_message_id or False,
            'direction':         'inbound',
            'initiator':         'buyer',
            'kind':              'text_reply',
            'body':              message_text,
            'lead_id':           lead.id if lead else False,
            'platform_actor_id': actor_id or 0,
            'status':            'delivered',
            'occurred_at':       occurred_at,
        })

        conv.sudo().write({'last_message_at': occurred_at, 'unread_count': conv.unread_count + 1})

        # bus.bus notification to RM — replaces mail.activity
        if rm_odoo_id:
            lead_name = (lead.name if lead else '')
            try:
                self.env['bus.bus']._sendone(
                    f'wa_notification_{rm_odoo_id}',
                    'wa_event',
                    {
                        'type':      'ambiguous_reply',
                        'actor_id':  actor_id,
                        'lead_id':   lead.id if lead else None,
                        'lead_name': lead_name,
                        'phone':     phone,
                        'message':   message_text[:80] if message_text else '',
                        'lead_url':  f'/web#model=leads.new&id={lead.id}' if lead else '',
                    },
                )
            except Exception:
                _logger.exception("wa_push: failed to send bus.bus for ambiguous_reply")

    def _handle_odoo_permanent_failure(
        self, event: dict, pubsub_message_id: str
    ) -> None:
        """Handle permanent_failure and retry_exhausted — update status + notify RM."""
        wa_message_id  = event.get('wa_message_id') or ''
        request_id     = event.get('request_id') or ''
        actor_id       = event.get('actor_id')
        actor_type     = event.get('actor_type', '')
        rm_odoo_id     = event.get('rm_odoo_id')
        failure_code   = event.get('failure_code')
        failure_reason = event.get('failure_reason') or 'Send failed'
        phone          = event.get('phone', '')
        event_type     = event.get('event_type', '')
        new_status     = self._owa_failure_status(failure_code)

        msg = self._owa_find_message(wa_message_id=wa_message_id, request_id=request_id)
        if msg:
            msg.write({'status': new_status, 'status_updated_at': fields.Datetime.now()})

        lead = self._owa_resolve_lead(actor_id, actor_type, phone)

        # bus.bus notification to RM — replaces mail.activity
        if rm_odoo_id:
            lead_name = (lead.name if lead else '')
            summary = (
                f'Delivery failed: {failure_reason}'
                if event_type == 'permanent_failure'
                else f'Retries exhausted: {failure_reason}'
            )
            try:
                self.env['bus.bus']._sendone(
                    f'wa_notification_{rm_odoo_id}',
                    'wa_event',
                    {
                        'type':      'permanent_failure',
                        'actor_id':  actor_id,
                        'lead_id':   lead.id if lead else None,
                        'lead_name': lead_name,
                        'phone':     phone,
                        'message':   summary[:80],
                        'lead_url':  f'/web#model=leads.new&id={lead.id}' if lead else '',
                    },
                )
            except Exception:
                _logger.exception("wa_push: failed to send bus.bus for permanent_failure")

    def _handle_odoo_enrollment_created(
        self, event: dict, pubsub_message_id: str
    ) -> None:
        """Handle enrollment_created — system pill + wa.enrollment record."""
        phone         = event.get('phone', '')
        actor_id      = event.get('actor_id')
        actor_type    = event.get('actor_type', '')
        workflow_slug = event.get('workflow_slug') or ''
        enrollment_id = event.get('enrollment_id') or ''
        occurred_at   = _parse_iso_dt(event.get('occurred_at', ''))

        # Idempotency guard — Pub/Sub delivers at-least-once; skip if a system
        # pill for this enrollment_id already exists (duplicate delivery or push
        # subscription misconfiguration).
        if enrollment_id and self.env['wa.message'].sudo().search(
            [('enrollment_id', '=', enrollment_id), ('kind', '=', 'system')],
            limit=1,
        ):
            _logger.info(
                "wa_push: enrollment_created duplicate skipped enrollment_id=%s message=%s",
                enrollment_id, pubsub_message_id,
            )
            return

        conv = self._owa_get_conversation(phone)
        self.env.cr.execute(
            'SELECT id FROM wa_conversation WHERE id = %s FOR UPDATE',
            (conv.id,)
        )

        lead = self._owa_resolve_lead(actor_id, actor_type, phone)

        self.env['wa.message'].sudo().create({
            'conversation_id': conv.id,
            'direction':       'outbound',
            'initiator':       'system',
            'kind':            'system',
            'body':            f'Enrolled in workflow: {workflow_slug}',
            'workflow_slug':   workflow_slug or False,
            'enrollment_id':   enrollment_id or False,
            'lead_id':         lead.id if lead else False,
            'platform_actor_id': actor_id or 0,
            'status':          'enrolled',
            'occurred_at':     occurred_at,
        })

        # Track enrollment lifecycle for the Active Enrollments KPI.
        if enrollment_id:
            self.env['wa.enrollment'].sudo()._get_or_create(
                enrollment_id=enrollment_id,
                workflow_slug=workflow_slug,
                lead=lead,
                phone=phone,
                platform_actor_id=actor_id or 0,
                started_at=occurred_at,
            )

    def _handle_odoo_enrollment_completed(
        self, event: dict, pubsub_message_id: str
    ) -> None:
        """Handle enrollment_completed — system pill + mark wa.enrollment complete."""
        phone         = event.get('phone', '')
        actor_id      = event.get('actor_id')
        actor_type    = event.get('actor_type', '')
        workflow_slug = event.get('workflow_slug') or ''
        enrollment_id = event.get('enrollment_id') or ''
        occurred_at   = _parse_iso_dt(event.get('occurred_at', ''))

        # Idempotency guard — skip if a 'completed' system pill already exists.
        if enrollment_id and self.env['wa.message'].sudo().search(
            [
                ('enrollment_id', '=', enrollment_id),
                ('kind', '=', 'system'),
                ('body', 'like', 'Workflow completed:'),
            ],
            limit=1,
        ):
            _logger.info(
                "wa_push: enrollment_completed duplicate skipped enrollment_id=%s message=%s",
                enrollment_id, pubsub_message_id,
            )
            return

        conv = self._owa_get_conversation(phone)
        lead = self._owa_resolve_lead(actor_id, actor_type, phone)

        self.env['wa.message'].sudo().create({
            'conversation_id': conv.id,
            'direction':       'outbound',
            'initiator':       'system',
            'kind':            'system',
            'body':            f'Workflow completed: {workflow_slug}',
            'workflow_slug':   workflow_slug or False,
            'enrollment_id':   enrollment_id or False,
            'lead_id':         lead.id if lead else False,
            'platform_actor_id': actor_id or 0,
            'status':          'enrollment_completed',
            'occurred_at':     occurred_at,
        })

        # Mark enrollment as completed so it drops from the Active Enrollments count.
        if enrollment_id:
            enroll = self.env['wa.enrollment'].sudo().search(
                [('enrollment_id', '=', enrollment_id)], limit=1
            )
            if enroll:
                enroll.write({'state': 'completed', 'completed_at': occurred_at})

    def _handle_odoo_enrollment_step_changed(
        self, event: dict, pubsub_message_id: str
    ) -> None:
        """Handle enrollment_step_changed — no state change needed, debug log only.

        Step transitions are high-frequency and do not change the enrollment
        lifecycle state (active → completed).  Logged at DEBUG level only.
        """
        _logger.debug(
            "wa_push: enrollment_step_changed — enrollment_id=%r step_id=%r",
            event.get('enrollment_id'), event.get('step_id'),
        )

    def _handle_workflow_registry_synced(
        self, event: dict, pubsub_message_id: str
    ) -> None:
        """Handle workflow.registry.synced — upsert the wa.workflow registry.

        Delegates to :meth:`wa.workflow._process_registry_sync_event`.
        """
        self.env['wa.workflow'].sudo()._process_registry_sync_event(
            event, pubsub_message_id
        )

    def _handle_workflow_synced(
        self, event: dict, pubsub_message_id: str
    ) -> None:
        """Handle workflow.synced — WA platform ACK after applying a toggle.

        Published by the odoo-bridge service on the ``wa-workflow-sync`` topic
        after it processes a ``workflow.toggled`` control event.  Delegates to
        :meth:`wa.workflow._process_workflow_synced_event`.
        """
        self.env['wa.workflow'].sudo()._process_workflow_synced_event(
            event, pubsub_message_id
        )

    # ------------------------------------------------------------------
    # Outbound messaging
    # ------------------------------------------------------------------

    # Non-template kinds that require an open 24h window.
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

    # ------------------------------------------------------------------
    # Ownership / assignment
    # ------------------------------------------------------------------

    def _is_wa_manager(self) -> bool:
        return self.env.user.has_group('wa_communication.group_wa_manager')

    def _can_send(self) -> bool:
        """Whether the current user may send on this conversation."""
        self.ensure_one()
        if self._is_wa_manager():
            return True
        return bool(self.assigned_user_id) and self.assigned_user_id.id == self.env.uid

    def _send_gate_reason(self) -> str:
        """Human message for why the composer is locked (empty if unlocked)."""
        self.ensure_one()
        if self._can_send():
            return ''
        if not self.assigned_user_id:
            return "This chat is unassigned. Claim it to reply."
        return ("This chat is assigned to %s. Request assignment to reply."
                % self.assigned_user_id.name)

    def _assert_can_send(self) -> None:
        self.ensure_one()
        if not self._can_send():
            raise UserError(self._send_gate_reason())

    def _request_assign(self, target_user, request_id: str | None = None) -> str:
        """Publish a platform-routed assign request for ``target_user``.

        Ownership is NOT flipped here — it flips when the platform sends back an
        ``assignment_confirmed`` event (Interakt ``result:true`` + ``rm_assignments``
        updated). Sets ``assignment_pending`` so the UI shows a spinner.

        :returns: the correlation ``request_id`` used.
        """
        self.ensure_one()
        if not self.phone_number:
            raise UserError("Cannot assign — this conversation has no phone number.")
        if not target_user.email:
            raise UserError(
                "Cannot assign to %s — that user has no email (required as the "
                "Interakt agent identifier)." % target_user.name)

        import uuid as _uuid
        req_id = request_id or str(_uuid.uuid4())
        topic = self.env['ir.config_parameter'].sudo().get_param(
            _TOPIC_WA_REQUESTS, 'cd-prod-odoo-wa-requests'
        )
        request_data = {
            'request_type': 'assign',
            'request_id': req_id,
            'phone': self.phone_number,
            'rm_email': target_user.email,
            'rm_name': target_user.name,
            'rm_odoo_id': target_user.id,
            'actor_id': self.lead_id.id if self.lead_id else None,
        }
        self.sudo().write({'assignment_pending': True})

        def _publish():
            self.env['cleardeals.pubsub'].publish_async(topic, request_data)

        self.env.cr.postcommit.add(_publish)
        return req_id

    def action_claim(self) -> None:
        """Self-claim an unassigned conversation (instant, no approval)."""
        self.ensure_one()
        if self.assigned_user_id and not self._is_wa_manager():
            raise UserError(
                "This chat is already assigned to %s." % self.assigned_user_id.name)
        self._request_assign(self.env.user)

    def request_assignment(self, note: str | None = None) -> int:
        """Raise a reassignment request to the current assignee.

        Returns the ``wa.reassignment.request`` id.
        """
        self.ensure_one()
        if self._can_send():
            raise UserError("You can already reply on this chat.")
        if not self.assigned_user_id:
            # Nobody owns it — claim directly instead of a handshake.
            self.action_claim()
            return 0
        existing = self.env['wa.reassignment.request'].search([
            ('conversation_id', '=', self.id),
            ('requester_id', '=', self.env.uid),
            ('state', 'in', ('pending', 'confirming')),
        ], limit=1)
        if existing:
            return existing.id
        req = self.env['wa.reassignment.request'].create({
            'conversation_id': self.id,
            'requester_id': self.env.uid,
            'current_assignee_id': self.assigned_user_id.id,
            'note': note or '',
            'state': 'pending',
        })
        # Notify the current assignee with an actionable card.
        try:
            self.env['bus.bus']._sendone(
                'wa_notification_%d' % self.assigned_user_id.id,
                'wa_event',
                {
                    'type': 'reassignment_request',
                    'request_id': req.id,
                    'requester_name': self.env.user.name,
                    'phone': self.phone_number,
                    'lead_id': self.lead_id.id if self.lead_id else None,
                    'lead_name': self.lead_id.name if self.lead_id else '',
                    'note': note or '',
                    'conversation_id': self.id,
                },
            )
        except Exception:  # noqa: BLE001
            _logger.debug("request_assignment notify failed", exc_info=True)
        return req.id

    def action_reassign(self, lead_id: int | None = None, user_id: int | None = None) -> None:
        """Manager force-reassign (or re-link inquiry) — platform-routed.

        Managers may reassign instantly without the approval handshake; the
        ownership flip still waits for the platform's ``assignment_confirmed``.
        """
        self.ensure_one()
        if not self._is_wa_manager():
            raise UserError("Only a WhatsApp manager can force-reassign a chat.")
        if lead_id:
            self.sudo().write({'lead_id': lead_id})
        if user_id:
            target = self.env['res.users'].sudo().browse(user_id)
            self._request_assign(target)

    def _handle_odoo_assignment_confirmed(self, event: dict, pubsub_message_id: str) -> None:
        """Platform confirmed (or failed) an Interakt chat assignment.

        On success: flip ``assigned_user_id``, clear the pending marker, resolve
        any matching reassignment request, log a system message, and notify the
        new assignee so their composer unlocks. On failure: notify the requester.
        """
        phone = event.get('phone')
        rm_odoo_id = event.get('rm_odoo_id')
        request_id = event.get('request_id')
        success = event.get('success', True)

        conv = self.search([('phone_number', '=', phone)], limit=1) if phone else self
        if not conv:
            return
        conv = conv[:1]

        req = None
        if request_id:
            req = self.env['wa.reassignment.request'].sudo().search(
                [('request_id', '=', request_id)], limit=1)

        if not success:
            conv.sudo().write({'assignment_pending': False})
            if req:
                req._mark_failed(event.get('failure_reason') or '')
            return

        new_user = self.env['res.users'].sudo().browse(rm_odoo_id) if rm_odoo_id else None
        vals = {'assignment_pending': False}
        if new_user and new_user.exists():
            vals['assigned_user_id'] = new_user.id
        conv.sudo().write(vals)

        if new_user:
            conv._owa_log_system_event("Chat assigned to %s" % new_user.name)
            try:
                self.env['bus.bus']._sendone(
                    'wa_notification_%d' % new_user.id,
                    'wa_event',
                    {
                        'type': 'assignment_changed',
                        'phone': conv.phone_number,
                        'lead_id': conv.lead_id.id if conv.lead_id else None,
                        'lead_name': conv.lead_id.name if conv.lead_id else '',
                        'conversation_id': conv.id,
                        'message': "You are now assigned to this chat.",
                    },
                )
            except Exception:  # noqa: BLE001
                _logger.debug("assignment_changed notify failed", exc_info=True)
        if req:
            req._mark_approved()

    def _owa_log_system_event(self, body: str) -> None:
        """Append a system-event ``wa.message`` to this conversation's timeline."""
        self.ensure_one()
        try:
            self.env['wa.message'].sudo().create({
                'conversation_id': self.id,
                'direction': 'outbound',
                'initiator': 'system',
                'kind': 'system',
                'body': body,
                'status': 'sent',
                'occurred_at': fields.Datetime.now(),
                'lead_id': self.lead_id.id if self.lead_id else False,
            })
        except Exception:  # noqa: BLE001
            _logger.debug("system event log failed", exc_info=True)

    def _inbox_conv_status(self, conv, window_open):
        """Derive a display status for the inbox table."""
        if conv.unread_count > 0:
            return 'needs_reply'
        if window_open:
            return 'active'
        return 'completed'

    @api.model
    def get_inbox(self, filters: dict | None = None) -> list[dict]:
        """Return conversation list for the WhatsApp Inbox client action."""
        filters = filters or {}
        limit = min(int(filters.get('limit', 100)), 200)
        offset = int(filters.get('offset', 0))
        now = datetime.utcnow()

        domain = []
        if filters.get('assigned_rm'):
            domain.append(('assigned_user_id', '=', int(filters['assigned_rm'])))
        if filters.get('search'):
            s = filters['search']
            domain += ['|', ('lead_id.name', 'ilike', s), ('phone_number', 'ilike', s)]

        # Status filter
        status_f = filters.get('status')
        if status_f == 'needs_reply':
            domain.append(('unread_count', '>', 0))
        elif status_f == 'active':
            domain += [('unread_count', '=', 0), ('window_expires_at', '>', now)]
        elif status_f == 'completed':
            domain += [('unread_count', '=', 0), '|', ('window_expires_at', '=', False), ('window_expires_at', '<=', now)]

        # Date range filter on last_message_at
        date_range = filters.get('date_range')
        if date_range == 'today':
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            domain.append(('last_message_at', '>=', today))
        elif date_range == 'yesterday':
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday = today - timedelta(days=1)
            domain += [('last_message_at', '>=', yesterday), ('last_message_at', '<', today)]
        elif date_range == 'last_7d':
            domain.append(('last_message_at', '>=', now - timedelta(days=7)))
        elif date_range == 'last_30d':
            domain.append(('last_message_at', '>=', now - timedelta(days=30)))
        elif date_range == 'this_month':
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            domain.append(('last_message_at', '>=', month_start))

        convs = self.env['wa.conversation'].sudo().search(
            domain, order='last_message_at desc', limit=limit, offset=offset
        )

        rows = []
        for conv in convs:
            window_open = bool(conv.window_expires_at and conv.window_expires_at > now)
            lead = conv.lead_id
            # Try to get portal source from lead (field may not exist on all installations)
            portal_source = ''
            if lead:
                portal_source = getattr(lead, 'portal_source', '') or getattr(lead, 'source_id', '') or ''
                if hasattr(portal_source, 'name'):
                    portal_source = portal_source.name
            # Last active workflow slug from messages
            last_wf_msg = conv.message_ids.filtered(lambda m: m.workflow_slug).sorted('occurred_at', reverse=True)[:1]
            workflow_name = last_wf_msg.workflow_slug if last_wf_msg else ''
            rows.append({
                'id': conv.id,
                'lead_id': lead.id if lead else None,
                'lead_name': lead.name if lead else None,
                'lead_source': portal_source,
                'phone': conv.phone_number,
                'last_message': conv.last_message_preview or '',
                'last_message_at': conv.last_message_at.isoformat() if conv.last_message_at else None,
                'unread_count': conv.unread_count,
                'conv_status': self._inbox_conv_status(conv, window_open),
                'window_state': 'open' if window_open else 'closed',
                'window_expires_at': conv.window_expires_at.isoformat() if conv.window_expires_at else None,
                'assigned_user_id': conv.assigned_user_id.id if conv.assigned_user_id else None,
                'assigned_user_name': conv.assigned_user_id.name if conv.assigned_user_id else None,
                'can_send': conv._can_send(),
                'assignment_pending': conv.assignment_pending,
                'workflow_name': workflow_name,
                'interakt_url': conv.interakt_inbox_url,
            })
        return rows

    @api.model
    def get_inbox_counts(self) -> dict:
        """Return facet counts for the inbox sidebar filters."""
        now = datetime.utcnow()
        all_convs = self.env['wa.conversation'].sudo().search([])
        status_counts = {'needs_reply': 0, 'active': 0, 'completed': 0}
        for conv in all_convs:
            window_open = bool(conv.window_expires_at and conv.window_expires_at > now)
            status_counts[self._inbox_conv_status(conv, window_open)] += 1

        # Assigned RM counts
        rm_counts = {}
        for conv in all_convs:
            if conv.assigned_user_id:
                uid = conv.assigned_user_id.id
                rm_counts.setdefault(uid, {'id': uid, 'name': conv.assigned_user_id.name, 'count': 0})
                rm_counts[uid]['count'] += 1

        return {
            'status': status_counts,
            'assigned_rms': list(rm_counts.values()),
        }

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
    def get_thread(self, conversation_id: int) -> dict:
        """Return full thread data for a conversation.

        :param conversation_id: ``wa.conversation`` record ID.
        :return: Dict with ``conversation`` metadata, ``messages`` list,
                 and ``stats`` (sent/delivered/read counts for current inquiry).
        """
        conv = self.env['wa.conversation'].sudo().browse(conversation_id)
        if not conv.exists():
            return {'error': 'Conversation not found'}
        now = datetime.utcnow()
        window_open = bool(conv.window_expires_at and conv.window_expires_at > now)

        messages = []
        for msg in conv.message_ids.sorted('occurred_at'):
            messages.append({
                'id': msg.id,
                'direction': msg.direction,
                'initiator': msg.initiator,
                'kind': msg.kind,
                'body': msg.body or msg.template_body or '',
                'media_url': msg.media_url or None,
                'media_filename': msg.media_filename or None,
                'status': msg.status,
                'occurred_at': msg.occurred_at.isoformat() if msg.occurred_at else None,
                'sender_name': msg.sender_name or (
                    conv.lead_id.name if msg.direction == 'inbound' and conv.lead_id
                    else None
                ),
                'template_name': msg.template_name or None,
                'template_header': msg.template_header or None,
                'template_footer': msg.template_footer or None,
                'template_buttons': msg.template_buttons or self._extract_template_buttons(msg),
                'quoted_body': msg.quoted_body or None,
                'quoted_sender': msg.quoted_sender or None,
                'quoted_msg_id': msg.quoted_message_id.id if msg.quoted_message_id else None,
                'quoted_kind': msg.quoted_message_id.kind if msg.quoted_message_id else None,
                'quoted_media_url': msg.quoted_message_id.media_url if msg.quoted_message_id else None,
                'template_replied_to': msg.template_replied_to or None,
                'lead_id': msg.lead_id.id if msg.lead_id else None,
                'workflow_slug': msg.workflow_slug or None,
            })

        self._owa_resolve_quoted_links(messages)

        # Per-inquiry stats (for the current linked lead)
        stats = {'sent': 0, 'delivered': 0, 'read': 0, 'replies': 0}
        if conv.lead_id:
            lid = conv.lead_id.id
            inquiry_msgs = conv.message_ids.filtered(
                lambda m: m.lead_id.id == lid and m.direction == 'outbound'
            )
            inbound_msgs = conv.message_ids.filtered(
                lambda m: m.lead_id.id == lid and m.direction == 'inbound'
            )
            total = len(inquiry_msgs)
            delivered = len(inquiry_msgs.filtered(lambda m: m.status in ('delivered', 'read')))
            read_count = len(inquiry_msgs.filtered(lambda m: m.status == 'read'))
            stats = {
                'sent': total,
                'delivered': delivered,
                'read': read_count,
                'replies': len(inbound_msgs),
                'delivered_pct': round(100 * delivered / total) if total else 0,
                'read_pct': round(100 * read_count / total) if total else 0,
            }

        return {
            'conversation': {
                'id': conv.id,
                'phone': conv.phone_number,
                'lead_id': conv.lead_id.id if conv.lead_id else None,
                'lead_name': conv.lead_id.name if conv.lead_id else None,
                'assigned_user_id': conv.assigned_user_id.id if conv.assigned_user_id else None,
                'assigned_user_name': conv.assigned_user_id.name if conv.assigned_user_id else None,
                'window_state': 'open' if window_open else 'closed',
                'window_expires_at': conv.window_expires_at.isoformat() if conv.window_expires_at else None,
                'interakt_url': conv.interakt_inbox_url,
                'unread_count': conv.unread_count,
                # Ownership gating for the composer.
                'can_send': conv._can_send(),
                'send_gate_reason': conv._send_gate_reason(),
                'is_manager': conv._is_wa_manager(),
                'assignment_pending': conv.assignment_pending,
            },
            'messages': messages,
            'stats': stats,
        }

    @staticmethod
    def _owa_resolve_quoted_links(messages: list) -> None:
        """Set ``quoted_msg_id`` on reply messages so the UI can scroll to the original.

        A swipe/button reply carries ``quoted_body`` and/or ``template_replied_to``.
        Match each reply to the most recent *earlier* message it refers to:
          1. ``template_replied_to`` → an earlier message with that ``template_name``;
          2. otherwise ``quoted_body`` → an earlier message whose body / template
             header matches the quoted snippet.
        ``messages`` is the ordered (oldest-first) list of serialized dicts; this
        mutates it in place.
        """
        for i, m in enumerate(messages):
            if m.get('quoted_msg_id'):
                continue  # already linked exactly (quoted_message_id)
            tpl = m.get('template_replied_to')
            quoted = (m.get('quoted_body') or '').strip()
            if not tpl and not quoted:
                continue
            for j in range(i - 1, -1, -1):
                prev = messages[j]
                if tpl and prev.get('template_name') == tpl:
                    m['quoted_msg_id'] = prev['id']
                    break
                if quoted:
                    cand = (prev.get('body') or '').strip()
                    head = (prev.get('template_header') or '').strip()
                    if cand and (cand == quoted or quoted in cand or cand in quoted):
                        m['quoted_msg_id'] = prev['id']
                        break
                    if head and head == quoted:
                        m['quoted_msg_id'] = prev['id']
                        break

    def _extract_template_buttons(self, msg) -> list:
        """Return list of button label strings from template raw_payload, or []."""
        try:
            raw = msg.raw_payload
            if not raw:
                return []
            data = json.loads(raw) if isinstance(raw, str) else raw
            # Interakt template payload structure
            components = (
                data.get('template', {}).get('components', [])
                or data.get('payload', {}).get('template', {}).get('components', [])
            )
            for comp in components:
                if comp.get('type', '').lower() == 'button':
                    btns = comp.get('buttons', [])
                    return [b.get('text', '') for b in btns if b.get('text')]
        except Exception:
            pass
        return []


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _extract_body(msg: dict, msg_type: str) -> str:
    """Extract a human-readable body string from a WA message object.

    :param msg:      WA message dict (one element of ``value.messages``).
    :param msg_type: The ``type`` field from ``msg``.
    :return:         Display text, e.g. message body or ``'[Image]'``.
    """
    if msg_type == 'text':
        return (msg.get('text') or {}).get('body', '')
    if msg_type == 'image':
        return (msg.get('image') or {}).get('caption', '') or '[Image]'
    if msg_type == 'video':
        return (msg.get('video') or {}).get('caption', '') or '[Video]'
    if msg_type == 'audio':
        return '[Audio]'
    if msg_type == 'document':
        return (msg.get('document') or {}).get('caption', '') or '[Document]'
    if msg_type == 'reaction':
        return (msg.get('reaction') or {}).get('emoji', '') or '[Reaction]'
    if msg_type == 'template':
        # Template messages don't have a plain-text body in the webhook.
        name = (msg.get('template') or {}).get('name', '')
        return f'[Template: {name}]' if name else '[Template]'
    return f'[{msg_type}]'


def _extract_media_url(msg: dict, msg_type: str) -> str:
    """Extract the media URL from an inbound WA message object.

    The WA Cloud API includes a ``url`` or ``link`` key inside the media
    sub-object for image, video, document and audio messages.  Returns an
    empty string for text, button_reply and other non-media types.

    :param msg:      WA message dict.
    :param msg_type: The ``type`` field from ``msg``.
    :return:         Media URL string, or ``''`` if not a media message.
    """
    if msg_type not in ('image', 'video', 'document', 'audio'):
        return ''
    media_obj = msg.get(msg_type) or {}
    return media_obj.get('url') or media_obj.get('link') or ''
