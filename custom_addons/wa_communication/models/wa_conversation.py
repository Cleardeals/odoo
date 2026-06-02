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
from datetime import datetime, timezone

from odoo import api, fields, models
from odoo.exceptions import UserError

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

        lead = self.env['leads.new'].search(
            [('phone', '=', phone_number)],
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

        # For button_reply: look up the template that triggered this CTA
        template_replied_to = ''
        if msg_type == 'button_reply':
            context_msg_id = (msg.get('context') or {}).get('id', '')
            if context_msg_id:
                orig = self.env['wa.message'].sudo().search(
                    [('wa_message_id', '=', context_msg_id)], limit=1
                )
                if orig:
                    template_replied_to = orig.template_name or ''

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

        self.env['wa.message'].sudo().create({
            'conversation_id': conv.id,
            'wa_message_id': wa_msg_id or False,
            'direction': 'inbound',
            'initiator': 'buyer',
            'kind': _WA_TYPE_TO_KIND.get(msg_type, 'unknown'),
            'body': body,
            'media_url': media_url or False,
            'template_replied_to': template_replied_to or False,
            'status': 'delivered',
            'sender_name': sender_name,
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
            msg.write({
                'wa_message_id':   wa_message_id or msg.wa_message_id,
                'status':          'sent',
                'status_updated_at': fields.Datetime.now(),
            })
        else:
            # Workflow-initiated send: Odoo never created a wa.message for this
            conv  = self._owa_get_conversation(phone)
            lead  = self._owa_resolve_lead(actor_id, actor_type, phone)
            self.env['wa.message'].sudo().create({
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
            })
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
            msg.write({
                'status':          'delivered',
                'cost_inr':        cost_inr,
                'delivered_at':    occurred_at,
                'status_updated_at': fields.Datetime.now(),
            })
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
            msg.write({
                'status':          'read',
                'seen_at':         occurred_at,
                'status_updated_at': fields.Datetime.now(),
            })
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

        # Deduplicate by wa_message_id
        if wa_message_id and self._owa_find_message(wa_message_id=wa_message_id):
            _logger.debug("wa_push: lead_replied duplicate wa_message_id=%s", wa_message_id)
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
        self.env['wa.message'].sudo().create({
            'conversation_id':   conv.id,
            'wa_message_id':     wa_message_id or False,
            'direction':         'inbound',
            'initiator':         'buyer',
            'kind':              kind,
            'body':              body,
            'media_url':         media_url,
            'media_filename':    media_filename,
            'template_replied_to': template_replied_to or False,
            'lead_id':           lead.id if lead else False,
            'platform_actor_id': actor_id or 0,
            'status':            'delivered',
            'occurred_at':       occurred_at,
        })

        conv.sudo().write({
            'last_message_at':      occurred_at,
            'last_message_preview': message_text[:100],
            'unread_count':         conv.unread_count + 1,
        })

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

    def send_message(
        self,
        body: str,
        kind: str = 'freetext',
        template_name: str = '',
        initiator: str = 'rm',
        request_id: str = '',
        workflow_slug: str = '',
        step_id: str = '',
        enrollment_id: str = '',
    ) -> 'models.Model':
        """Send a WA message from this conversation.

        Creates a queued ``wa.message`` and publishes a send request to the
        ``cd-prod-odoo-wa-requests`` Pub/Sub topic.  The WA bridge sends the
        actual WA message and delivers status receipts back via the inbound
        push path.

        The publish is deferred until after the current SQL transaction
        commits so that a rollback does not trigger a spurious WA send.

        :param body:          Message text (required when ``kind='freetext'``).
        :param kind:          Message kind — one of the ``wa.message.kind``
                              Selection values.  Default ``'freetext'``.
        :param template_name: Template name (required when ``kind='template'``).
        :param initiator:     Who is sending — ``'rm'`` (default) or
                              ``'workflow'`` for automated sends.
        :param request_id:    OdooWaRequest UUID for tracking.
        :param workflow_slug: Workflow context for automated sends.
        :param step_id:       Workflow step for automated sends.
        :param enrollment_id: Enrollment UUID for automated sends.
        :return:              The newly created ``wa.message`` record.
        :raises UserError:    If the conversation has no phone number.
        """
        self.ensure_one()
        if not self.phone_number:
            raise UserError(
                "Cannot send — this conversation has no phone number."
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
            'request_id': effective_request_id,
            'workflow_slug': workflow_slug or False,
            'step_id': step_id or False,
            'enrollment_id': enrollment_id or False,
            'lead_id': self.lead_id.id if self.lead_id else False,
            'status': 'queued',
            'occurred_at': fields.Datetime.now(),
        })

        topic = self.env['ir.config_parameter'].sudo().get_param(
            _TOPIC_WA_REQUESTS, 'cd-prod-odoo-wa-requests'
        )
        # Payload matches OdooWaRequest (shared/models.py in the WA platform).
        # Mandatory fields: request_type, request_id (UUID str), phone.
        # message_text carries the body for freetext; template_name for templates.
        request_data = {
            'request_type': 'send',
            'request_id': effective_request_id,
            'phone': self.phone_number,
            'kind': kind,
            'message_text': body or None,
            'template_name': template_name or None,
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
