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
import re
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

# Monotonic rank of the happy-path delivery lifecycle.  Interakt/Pub/Sub deliver
# status webhooks AT-LEAST-ONCE and with NO ordering guarantee, so a redelivered
# (or simply late) ``message_delivered`` can arrive AFTER ``message_read`` — if we
# wrote status blindly it would knock a read message back to "delivered" (grey
# double-tick) even though ``seen_at`` is set.  Statuses only ever move FORWARD
# through these ranks; terminal failure states are handled separately and are not
# in this map (a failure should always be recorded).
_STATUS_RANK = {
    'queued':    0,
    'pending':   0,
    'sent':      1,
    'delivered': 2,
    'read':      3,
}


def _max_status(current: str, incoming: str) -> str:
    """Return whichever of *current* / *incoming* is further along the lifecycle.

    Only applies to the ranked happy-path statuses.  If either status is not in
    ``_STATUS_RANK`` (e.g. a failure state), *incoming* wins so failures and other
    non-lifecycle transitions are never suppressed.
    """
    if current not in _STATUS_RANK or incoming not in _STATUS_RANK:
        return incoming
    return current if _STATUS_RANK[current] >= _STATUS_RANK[incoming] else incoming


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
    active_segment_id = fields.Many2one(
        'wa.conversation.segment',
        string='Active Segment',
        ondelete='set null',
        copy=False,
        help="The inquiry segment new messages currently file into.  Drives the "
             "'Discussing: <property>' context in the inbox.  Dormant unless "
             "wa_communication.segments_enabled is on.",
    )
    segment_ids = fields.One2many(
        'wa.conversation.segment',
        'conversation_id',
        string='Segments',
    )
    inquiry_ids = fields.Many2many(
        'leads.new',
        string='Inquiries',
        compute='_compute_inquiry_ids',
        help="All leads.new inquiries that share this conversation's phone "
             "(one per property).  Drives the inbox inquiry switcher.",
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

    # Odoo 19 removed ``_sql_constraints``; constraints are declared as
    # ``models.Constraint`` class attributes instead.
    _phone_unique = models.Constraint(
        'UNIQUE(phone_number)',
        'A conversation already exists for this phone number.',
    )

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

    def _compute_inquiry_ids(self):
        Lead = self.env['leads.new'].sudo()
        for rec in self:
            phone10 = self._owa_standardize_lead_phone(rec.phone_number)
            rec.inquiry_ids = (
                Lead.search([('phone', '=', phone10)], order='create_date desc')
                if phone10 else Lead.browse()
            )

    # ------------------------------------------------------------------
    # Inquiry segments — correctable attribution (Part 1)
    # ------------------------------------------------------------------

    @api.model
    def _owa_segments_enabled(self) -> bool:
        """Master feature flag.  When off, no segment is created or attached and
        the conversation behaves exactly as before this feature existed."""
        return self.env['ir.config_parameter'].sudo().get_param(
            'wa_communication.segments_enabled', '') in ('1', 'true', 'True')

    def _owa_activate_segment(self, segment) -> None:
        """Make *segment* the sole active segment of this conversation."""
        self.ensure_one()
        (self.segment_ids - segment).filtered('is_active').write({'is_active': False})
        if not segment.is_active:
            segment.is_active = True
        if self.active_segment_id != segment:
            self.active_segment_id = segment

    def _owa_ensure_segment(self, inquiry=None, label=None, started_by='system',
                            activate=True):
        """Return a segment for *inquiry* (or a labelled one), creating it if needed.

        Idempotent: if a segment for the same inquiry already exists it is reused
        rather than duplicated.  When ``activate`` is True it also becomes the
        conversation's active segment; pass ``activate=False`` to file a message
        under an inquiry without hijacking the RM's current active context (e.g. a
        swipe-reply to an *older* property's message).  Returns ``False`` when the
        feature flag is off so callers become no-ops.
        """
        self.ensure_one()
        if not self._owa_segments_enabled():
            return False
        Segment = self.env['wa.conversation.segment'].sudo()
        seg = False
        if inquiry:
            seg = self.segment_ids.filtered(
                lambda s: s.inquiry_id.id == inquiry.id
            )[:1]
        if not seg:
            seg = Segment.create({
                'conversation_id': self.id,
                'inquiry_id': inquiry.id if inquiry else False,
                'label': label or (inquiry.property_base_id.property_tag if inquiry else False),
                'started_by': started_by,
            })
        elif label and not seg.label:
            seg.label = label
        if activate:
            self._owa_activate_segment(seg)
        return seg

    @api.model
    def start_segment(self, conversation_id, inquiry_id=None, label=None):
        """RM action: open/activate a segment, optionally on a not-yet-created
        inquiry (label-only).  Returns the segment id."""
        conv = self.browse(conversation_id)
        inquiry = self.env['leads.new'].browse(inquiry_id) if inquiry_id else None
        seg = conv._owa_ensure_segment(inquiry=inquiry, label=label, started_by='rm')
        return seg.id if seg else False

    @api.model
    def relink_segment(self, segment_id, inquiry_id):
        """Point an existing segment at *inquiry_id* — reclassifies the whole span.
        Used when an RM corrects attribution or when an inquiry is created later."""
        seg = self.env['wa.conversation.segment'].browse(segment_id)
        seg.inquiry_id = inquiry_id or False
        if inquiry_id and not seg.label:
            seg.label = seg.inquiry_id.property_base_id.property_tag
        return True

    @api.model
    def move_message_to_segment(self, message_id, segment_id):
        """Move a single mis-filed message to another segment (audited)."""
        msg = self.env['wa.message'].browse(message_id)
        msg.segment_id = segment_id or False
        return True

    @api.model
    def set_active_segment(self, conversation_id, segment_id):
        """Make an existing segment the conversation's active one (RM accepting a
        'switch to <property>?' suggestion).  Returns the segment id, or False."""
        conv = self.browse(conversation_id)
        seg = self.env['wa.conversation.segment'].browse(segment_id)
        if not (conv.exists() and seg.exists() and seg.conversation_id == conv):
            return False
        conv._owa_activate_segment(seg)
        return seg.id

    # ------------------------------------------------------------------
    # Inbound — conversation lookup / creation
    # ------------------------------------------------------------------

    @staticmethod
    def _owa_canonical_wa_phone(phone_number: str) -> str:
        """Canonical conversation key: 12-digit E.164 without '+', i.e. ``91`` + 10.

        WhatsApp / Interakt address Indian numbers as ``91XXXXXXXXXX``.  We
        normalize the conversation KEY itself (not just the lead lookup) so the
        same contact can never end up with separate 10-digit and 12-digit
        conversation rows.  Non-standard shapes are returned digit-stripped so
        equal numbers still collapse together.
        """
        if not phone_number:
            return phone_number
        digits = re.sub(r'\D', '', phone_number)
        if len(digits) == 10:
            return '91' + digits
        if len(digits) == 12 and digits.startswith('91'):
            return digits
        return digits or phone_number

    @api.model
    def _get_or_create_for_phone(
        self, phone_number: str, sender_name: str = ''
    ) -> 'WaConversation':
        """Return the conversation for ``phone_number``, creating it if needed.

        The phone is canonicalized to 12-digit E.164 so lookups and inserts are
        format-agnostic.  On creation, auto-links to the most recent ``leads.new``
        record whose ``phone`` field matches.  The create is race-safe: a
        concurrent insert that wins the ``UNIQUE(phone_number)`` index is caught
        and the existing row returned instead of creating a duplicate.

        :param phone_number: WA phone number (any shape; canonicalized internally).
        :param sender_name:  Display name from the WA contact object
                             (used only for logging; not stored).
        :return: Existing or newly created ``wa.conversation`` record.
        """
        phone_number = self._owa_canonical_wa_phone(phone_number)
        conv = self.search([('phone_number', '=', phone_number)], limit=1)
        if conv:
            return conv

        # leads.new stores a standardized 10-digit number; normalize to that for
        # the lead lookup so any inbound phone shape links reliably.
        lead_phone = self._owa_standardize_lead_phone(phone_number)
        lead = self.env['leads.new'].sudo().search(
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
        # Race-safe insert: two concurrent Pub/Sub deliveries for the same number
        # both reach here; the second hits the unique index. Catch it and return
        # the row the winner created instead of raising / duplicating.
        try:
            with self.env.cr.savepoint():
                return self.create({
                    'phone_number': phone_number,
                    'lead_id': lead.id if lead else False,
                })
        except psycopg2.errors.UniqueViolation:
            existing = self.search([('phone_number', '=', phone_number)], limit=1)
            if existing:
                return existing
            raise

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
        # Normalize the WA phone (E.164-without-plus) to the canonical 10-digit
        # leads format so the fallback search reliably matches an existing lead.
        lead_phone = self._owa_standardize_lead_phone(phone)
        return self.env['leads.new'].sudo().search(
            [('phone', '=', lead_phone)], order='create_date desc', limit=1
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
            # Never move status backwards — a redelivered message_sent must not
            # downgrade a row already marked delivered/read.
            vals = {
                'wa_message_id':   wa_message_id or msg.wa_message_id,
                'status':          _max_status(msg.status, 'sent'),
                'status_updated_at': fields.Datetime.now(),
            }
            vals.update(self._owa_template_content_vals(event, msg))
            msg.write(vals)
        else:
            # Workflow-initiated send: Odoo never created a wa.message for this
            conv  = self._owa_get_conversation(phone)
            lead  = self._owa_resolve_lead(actor_id, actor_type, phone)
            # Deterministic attribution: a workflow send carries the true inquiry
            # as actor_id (→ lead), so open/activate that inquiry's segment.
            seg = conv._owa_ensure_segment(inquiry=lead, started_by='auto_suggested')
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
                'segment_id':       seg.id if seg else False,
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
            # delivered_at/cost are always recorded, but status only advances —
            # a late/redelivered delivered event must not knock a read row back.
            vals = {
                'status':          _max_status(msg.status, 'delivered'),
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
            # seen_at is always recorded; status advances to read (and stays there
            # even if an out-of-order delivered event follows).
            vals = {
                'status':          _max_status(msg.status, 'read'),
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
        """Handle lead_replied — buyer sent a message; create wa.message + notify RM.

        Reads as a sequence: dedup → resolve conv/lead → lock → resolve the quoted
        context → drop companion duplicates → attribute a segment → persist the
        message → refresh the conversation → self-heal ownership → notify.  Each
        step's mechanics live in a named ``_owa_*`` helper below.
        """
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

        # Deduplicate by wa_message_id, with the button/CTA-collision twist.
        store_wa_message_id, quoted_src_from_collision, is_duplicate = (
            self._owa_resolve_inbound_dedup(wa_message_id, button_reply_id, message_text)
        )
        if is_duplicate:
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

        # Skip the button-tap "companion" text duplicate (same quoted source + body).
        if self._owa_is_companion_duplicate(conv, quoted_src, body):
            return

        inbound_seg = self._owa_attribute_inbound_segment(conv, quoted_src, lead)

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
            'segment_id':        inbound_seg.id if inbound_seg else False,
            'platform_actor_id': actor_id or 0,
            'status':            'delivered',
            'occurred_at':       occurred_at,
        })

        window_expires_at = self._owa_inbound_window_expiry(event, occurred_at)
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

        # Self-heal: if this is a migrated lead messaging first and nobody owns the
        # chat yet, hand it to the lead's RM (establishes ownership on both sides).
        self._owa_autoassign_to_lead_rm(conv, lead)

        # Notify the chat owner, or fan out to managers when nobody owns it.
        self._owa_notify_reply(conv, lead, phone, rm_odoo_id, actor_id, message_text)

    def _owa_resolve_inbound_dedup(self, wa_message_id, button_reply_id, message_text):
        """Resolve the storage id and button-collision source for an inbound reply.

        Returns ``(store_wa_message_id, collision_src, is_duplicate)``.  When
        ``is_duplicate`` is True the caller must drop the event.

        A quick-reply tap reuses the TEMPLATE's outbound Interakt id as the
        reply's message id (the gateway sets it for click→template correlation).
        Naively deduping on that id finds the OUTBOUND template row and silently
        drops EVERY button reply (and makes a second, different-button tap look
        like a duplicate of the first).  Detect that case: when the id only
        matches an OUTBOUND message, that message IS the one being replied to —
        store the reply under a distinct id derived from the button so each tap
        is recorded, and return it as the quoted original (``collision_src``).
        """
        store_wa_message_id = wa_message_id
        collision_src = None
        if not wa_message_id:
            return store_wa_message_id, collision_src, False

        existing = self._owa_find_message(wa_message_id=wa_message_id)
        if existing and existing.direction == 'inbound':
            _logger.debug("wa_push: lead_replied duplicate wa_message_id=%s", wa_message_id)
            return store_wa_message_id, collision_src, True
        if existing and existing.direction == 'outbound':
            collision_src = existing
            suffix = (button_reply_id or message_text or 'reply').strip().replace(' ', '_')[:40]
            store_wa_message_id = f"{wa_message_id}:r:{suffix}"
            # Re-dedup on the synthetic id so Pub/Sub redelivery of the same
            # tap doesn't create a second row.
            if self._owa_find_message(wa_message_id=store_wa_message_id):
                _logger.debug(
                    "wa_push: lead_replied duplicate synthetic id=%s", store_wa_message_id
                )
                return store_wa_message_id, collision_src, True
        return store_wa_message_id, collision_src, False

    def _owa_is_companion_duplicate(self, conv, quoted_src, body) -> bool:
        """True when an inbound reply quoting *quoted_src* with the same body
        already exists — the button-tap "companion" text duplicate.

        A quick-reply tap emits TWO inbound events from Interakt: the button
        CLICK (whose id is the template's outbound id) and a companion
        ``message_received`` TEXT (its own id) carrying the same message_context.
        The platform is meant to click-shadow the companion so only ONE reaches
        us, but that shadow is time-windowed (~4s) and can miss — on a redelivery
        or an out-of-order batch BOTH events arrive and, because the companion
        carries a different wa_message_id, the id-based dedup doesn't catch it →
        two identical bubbles.  Both events resolve to the SAME quoted source with
        the SAME body, so treat an existing inbound with the same (quoted source,
        body) as the same tap and skip.  Scoped to replies that quote a source so
        genuine repeated free-text ("ok", "ok") is never suppressed.  Runs under
        the conversation's FOR UPDATE lock (held by the caller), so two concurrent
        deliveries are serialized and the second sees the first.
        """
        if not quoted_src:
            return False
        twin = self.env['wa.message'].sudo().search([
            ('conversation_id', '=', conv.id),
            ('direction', '=', 'inbound'),
            ('quoted_message_id', '=', quoted_src.id),
            ('body', '=', body),
        ], limit=1)
        if twin:
            _logger.info(
                "wa_push: lead_replied companion duplicate skipped "
                "(conv=%s quoted=%s body=%r existing=%s)",
                conv.id, quoted_src.id, body[:40], twin.id,
            )
            return True
        return False

    def _owa_attribute_inbound_segment(self, conv, quoted_src, lead):
        """Resolve the inquiry segment an inbound reply files into (flag-gated).

        Dormant (returns ``False``) when segments are off.  Otherwise:
          * a reply that QUOTES a prior message is a deterministic signal — file
            it under THAT message's inquiry, even when the quoted message predates
            segments (use its ``lead_id``) or belongs to another property.  This
            does NOT flip the RM's active context (``activate=False``) — switching
            is a separate, RM-driven action;
          * a plain reply inherits the conversation's active segment;
          * with no segment yet, bootstrap one for the resolved inquiry.
        """
        if not conv._owa_segments_enabled():
            return False
        if quoted_src and quoted_src.segment_id:
            return quoted_src.segment_id
        if quoted_src and quoted_src.lead_id:
            return conv._owa_ensure_segment(
                inquiry=quoted_src.lead_id, started_by='auto_suggested', activate=False)
        if conv.active_segment_id:
            return conv.active_segment_id
        return conv._owa_ensure_segment(inquiry=lead, started_by='system')

    @staticmethod
    def _owa_inbound_window_expiry(event, occurred_at):
        """Window expiry for an inbound reply: the platform value when supplied,
        else ``occurred_at + 24h`` (``None`` when neither is available)."""
        raw = event.get('window_expires_at')
        if raw:
            try:
                return _parse_iso_dt(raw)
            except Exception:
                return None
        return occurred_at + timedelta(hours=24) if occurred_at else None

    def _owa_notify_reply(self, conv, lead, phone, rm_odoo_id, actor_id, message_text):
        """Notify the chat's owner of an inbound reply (persistent + live).

        Routes to the assigned RM if the chat is assigned, else the lead's routed
        RM as a fallback.  When nobody owns it (unknown number, or a lead with no
        RM), fan out to WhatsApp managers so the message isn't silently stranded.
        """
        recipient_id = self._owa_chat_recipient(conv, rm_odoo_id)
        if not recipient_id:
            self._owa_notify_unrouted(conv, lead, phone, message_text)
            return
        lead_label = self._owa_lead_label(lead, phone)
        self._push_user_notification(
            recipient_id, 'lead_replied',
            title='%s replied on WhatsApp' % lead_label,
            # Keep the actual reply text in the body so the RM can judge
            # urgency at a glance without opening the lead.
            body=(message_text[:160] if message_text else 'New WhatsApp reply'),
            payload={
                'actor_id':  actor_id,
                'lead_id':   lead.id if lead else None,
                'lead_name': lead.name if lead else '',
                'phone':     phone,
                'suppress_key': phone,
            },
        )

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

        # Self-heal ownership for a migrated lead messaging first (no-op if owned).
        self._owa_autoassign_to_lead_rm(conv, lead)

        # Notify the chat's owner (assigned RM, else routed RM fallback).
        recipient_id = self._owa_chat_recipient(conv, rm_odoo_id)
        if recipient_id:
            lead_label = self._owa_lead_label(lead, phone)
            self._push_user_notification(
                recipient_id, 'ambiguous_reply',
                title='%s sent a message that needs review' % lead_label,
                # Show the actual text so the RM can judge urgency at a glance.
                body=(message_text[:160] if message_text
                      else 'Unroutable WhatsApp reply — open the chat to review.'),
                payload={
                    'actor_id':  actor_id,
                    'lead_id':   lead.id if lead else None,
                    'lead_name': lead.name if lead else '',
                    'phone':     phone,
                    'suppress_key': phone,
                },
            )
        else:
            # No RM to route to — surface to managers for triage.
            self._owa_notify_unrouted(conv, lead, phone, message_text)

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

        # The failed send belongs to the chat's owner. Derive the conversation
        # from the message (or by phone) so an assigned chat notifies the
        # assignee rather than the lead's routed RM.
        conv = msg.conversation_id if msg else self._owa_get_conversation(phone)
        recipient_id = self._owa_chat_recipient(conv, rm_odoo_id)

        # Central notification to the RM (persistent + live popup).
        if recipient_id:
            lead_label = self._owa_lead_label(lead, phone)
            detail = (failure_reason or 'the message could not be sent').strip()
            body = ('Your WhatsApp message to %s couldn\'t be delivered (%s). '
                    'Reach out another way so the conversation isn\'t dropped.'
                    % (lead_label, detail))
            self._push_user_notification(
                recipient_id, 'permanent_failure',
                title='Your message to %s didn\'t go through' % lead_label,
                body=body[:200],
                payload={
                    'actor_id':  actor_id,
                    'lead_id':   lead.id if lead else None,
                    'lead_name': lead.name if lead else '',
                    'phone':     phone,
                    'suppress_key': phone,
                },
            )

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
        assignee = self.assigned_user_id
        existing = self.env['wa.reassignment.request'].search([
            ('conversation_id', '=', self.id),
            ('requester_id', '=', self.env.uid),
            ('state', 'in', ('pending', 'confirming')),
        ], limit=1)
        if existing:
            _logger.info(
                "request_assignment: %s already has an open request (#%s, %s) "
                "for conv %s — re-notifying assignee %s",
                self.env.user.name, existing.id, existing.state, self.id, assignee.name,
            )
            # Re-emit so the assignee gets another chance to see the card even
            # if they missed the first one (e.g. were offline).
            self._notify_assignee_of_request(existing)
            return existing.id
        req = self.env['wa.reassignment.request'].create({
            'conversation_id': self.id,
            'requester_id': self.env.uid,
            'current_assignee_id': assignee.id,
            'note': note or '',
            'state': 'pending',
        })
        _logger.info(
            "request_assignment: %s (uid=%s) requested chat %s (lead=%s) from "
            "assignee %s (uid=%s) — created request #%s, notifying channel "
            "wa_notification_%s",
            self.env.user.name, self.env.uid, self.phone_number,
            self.sudo().lead_id.name if self.lead_id else '-', assignee.name, assignee.id,
            req.id, assignee.id,
        )
        self._notify_assignee_of_request(req)
        return req.id

    def _notify_assignee_of_request(self, req) -> None:
        """Push the actionable handover card to the current assignee.

        Failures here must be loud (warning, not debug) — a swallowed bus error
        is exactly why "nothing happens" with no trace.
        """
        self.ensure_one()
        assignee = self.assigned_user_id
        if not assignee:
            return
        # The requester may not have lead-read rights ("RM See Own"); read lead
        # display data via sudo so requesting a handover never 403s.
        lead = self.sudo().lead_id
        requester_name = req.requester_id.name
        lead_label = self._owa_lead_label(lead, self.phone_number)
        self._push_user_notification(
            assignee.id, 'reassignment_request',
            title='%s wants to take over %s' % (requester_name, lead_label),
            body='%s has asked to handle %s\'s WhatsApp chat. Approve it if '
                 'you\'re no longer following up with them.' % (
                     requester_name, lead_label),
            payload={
                'request_id': req.id,
                'requester_name': requester_name,
                'phone': self.phone_number,
                'lead_id': lead.id if lead else None,
                'lead_name': lead.name if lead else '',
                'note': req.note or '',
                'conversation_id': self.id,
                'suppress_key': self.phone_number,
            },
            actionable=True,
        )

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
            reason = (event.get('failure_reason') or '').strip() \
                or "Interakt rejected the assignment."
            conv.sudo().write({'assignment_pending': False})

            target_user = (self.env['res.users'].sudo().browse(rm_odoo_id)
                           if rm_odoo_id else None)
            target_name = (target_user.name
                           if target_user and target_user.exists()
                           else "the requested RM")

            # Tell EVERYONE involved, with the reason:
            #  • the target RM (the requester / claimer who would have got it),
            #  • the approver (the request's current assignee), and
            #  • whoever currently owns the chat.
            notify_uids = set()
            if rm_odoo_id:
                notify_uids.add(rm_odoo_id)
            if req:
                notify_uids.add(req.requester_id.id)
                if req.current_assignee_id:
                    notify_uids.add(req.current_assignee_id.id)
                # Caller owns the notification fan-out below — don't double-toast.
                req._mark_failed(reason, notify=False)
            if conv.assigned_user_id:
                notify_uids.add(conv.assigned_user_id.id)

            # Persistent record in the thread (survives a missed real-time toast).
            conv._owa_log_system_event(
                "Chat could not be assigned to %s — %s" % (target_name, reason))
            conv._notify_assignment_failed(notify_uids, reason, target_name)
            _logger.info(
                "assignment failed for conv %s (target=%s): %s — notified uids=%s",
                conv.id, target_name, reason, sorted(notify_uids),
            )
            return

        new_user = self.env['res.users'].sudo().browse(rm_odoo_id) if rm_odoo_id else None
        vals = {'assignment_pending': False}
        if new_user and new_user.exists():
            vals['assigned_user_id'] = new_user.id
        conv.sudo().write(vals)

        if new_user:
            conv._owa_log_system_event("Chat assigned to %s" % new_user.name)
            lead_label = self._owa_lead_label(conv.lead_id, conv.phone_number)
            conv._push_user_notification(
                new_user.id, 'assignment_changed',
                title='%s\'s chat is now yours' % lead_label,
                body='You\'re now handling %s on WhatsApp. Open the chat, say '
                     'hello, and keep the conversation moving.' % lead_label,
                payload={
                    'phone': conv.phone_number,
                    'lead_id': conv.lead_id.id if conv.lead_id else None,
                    'lead_name': conv.lead_id.name if conv.lead_id else '',
                    'conversation_id': conv.id,
                },
            )
        if req:
            req._mark_approved()

    def _owa_standardize_lead_phone(self, phone_number: str) -> str:
        """Normalize a WA phone to the canonical 10-digit leads format.

        Reuses ``leads.new._standardize_phone`` (strips ``+``, leading ``0``,
        spaces, dashes and the ``91`` country code) so lead auto-linking is robust
        across every inbound phone shape. Falls back to a minimal 91-strip if the
        leads model is somehow unavailable.
        """
        if not phone_number:
            return ''
        try:
            return self.env['leads.new']._standardize_phone(phone_number)
        except Exception:  # noqa: BLE001 — never let normalization break inbound
            return (phone_number[2:]
                    if phone_number.startswith('91') and len(phone_number) == 12
                    else phone_number)

    @staticmethod
    def _owa_lead_label(lead, phone=None):
        """A human-friendly name for a lead in notification copy.

        Prefers the lead's name, falls back to the phone number, then a neutral
        'A lead' so messages never read awkwardly when the lead is unresolved.
        """
        if lead and getattr(lead, 'name', None):
            return lead.name
        if phone:
            return phone
        return 'A lead'

    @staticmethod
    def _owa_chat_recipient(conv, rm_odoo_id):
        """Resolve who should receive a chat notification.

        Chat notifications belong to whoever *owns the conversation* — the
        assigned RM — not the lead's salesperson. When the chat is assigned we
        notify the assignee; only when it is unassigned do we fall back to the
        platform-routed ``rm_odoo_id`` (the lead's RM) so replies on un-claimed
        chats still reach someone.
        """
        if conv and conv.assigned_user_id:
            return conv.assigned_user_id.id
        return rm_odoo_id

    def _owa_autoassign_to_lead_rm(self, conv, lead) -> None:
        """Self-heal: hand an unassigned conversation to the lead's owning RM.

        When a migrated lead messages first, the platform doesn't yet know who
        owns the chat (no ``rm_assignments`` row), but Odoo does — ``lead.user_id``.
        Publish a platform-routed assign for that RM so ownership is established on
        BOTH sides; ``assigned_user_id`` flips when ``assignment_confirmed`` returns
        and future inbounds route correctly platform-side too.

        Idempotent (guarded on unassigned + not pending) and fully defensive:
        ``_request_assign`` raises ``UserError`` when the RM has no email, and this
        runs inside the inbound savepoint, so an unguarded raise would roll back the
        just-created inbound message. On any problem we skip silently — the caller's
        manager-triage fallback still surfaces the message.
        """
        if not conv or not lead:
            return
        if conv.assigned_user_id or conv.assignment_pending:
            return
        rm = lead.user_id
        if not rm or not rm.email:
            return
        try:
            conv._request_assign(rm)
        except Exception:  # noqa: BLE001 — must never break inbound processing
            _logger.warning(
                "wa: auto-assign of conv %s to lead RM %s failed",
                conv.id, rm.id, exc_info=True)

    def _owa_relink_orphan_for_lead(self, lead) -> None:
        """Attach a pre-existing phone-only conversation to a newly created lead.

        When an unknown number messages first we create an orphan conversation
        (``lead_id=False``). If that contact later becomes a real lead (portal
        inquiry, manual entry, CSV import) with the same number, link the two so
        the earlier inbound history isn't stranded — and self-heal ownership to
        the lead's RM. Idempotent and defensive; never raises.
        """
        if not lead or not lead.phone:
            return
        lead_phone = self._owa_standardize_lead_phone(lead.phone)
        if not lead_phone:
            return
        # Match the orphan conversation by its normalized phone. Pre-filter in SQL
        # on the 10-digit substring (handles both '91…' and bare forms), then
        # confirm with full standardization to avoid false positives.
        candidates = self.sudo().search([
            ('lead_id', '=', False),
            ('phone_number', 'like', lead_phone),
        ])
        conv = candidates.filtered(
            lambda c: self._owa_standardize_lead_phone(c.phone_number) == lead_phone
        )[:1]
        if not conv:
            return
        # wa.message rows are append-only — only the conversation link is updated.
        conv.write({'lead_id': lead.id})
        self._owa_autoassign_to_lead_rm(conv, lead)
        conv._owa_log_system_event("Linked to lead: %s" % lead.name)
        _logger.info("wa: relinked orphan conv %s to new lead %s", conv.id, lead.id)

    def _owa_manager_ids(self) -> list:
        """User ids of all WhatsApp managers (``group_wa_manager``), or [].

        Odoo 19 renamed ``res.groups.users`` → ``user_ids``; ``all_user_ids``
        also includes users who hold the group via implication.
        """
        try:
            return self.env.ref(
                'wa_communication.group_wa_manager').sudo().all_user_ids.ids
        except Exception:  # noqa: BLE001
            return []

    def _owa_notify_unrouted(self, conv, lead, phone, message_text) -> None:
        """Notify all WhatsApp managers about an inbound nobody owns.

        Triage path: a message arrived that couldn't be auto-routed to a specific
        RM (unknown number, or a lead with no salesperson). Rather than letting it
        sit silently in the Inbox, fan out a persistent + live ``unrouted_inbound``
        notification to every manager so someone triages it (e.g. via the Inbox
        "Create lead" action). Never raises.
        """
        manager_ids = self._owa_manager_ids()
        if not manager_ids:
            return
        lead_label = self._owa_lead_label(lead, phone)
        try:
            self.env['cleardeals.notification'].notify(
                manager_ids, 'unrouted_inbound',
                title='Unassigned WhatsApp message from %s' % lead_label,
                body=(message_text[:160] if message_text
                      else 'A WhatsApp message arrived that isn\'t linked to an RM. '
                           'Open the Inbox to triage it.'),
                payload={
                    'conversation_id': conv.id if conv else None,
                    'lead_id': lead.id if lead else None,
                    'lead_name': lead.name if lead else '',
                    'phone': phone,
                    'suppress_key': phone,
                },
            )
        except Exception:  # noqa: BLE001
            _logger.warning("wa: unrouted_inbound manager notify failed",
                            exc_info=True)

    def _push_user_notification(self, user_id, ntype, title, body,
                                payload=None, actionable=False) -> None:
        """Emit a persistent + live notification via the central system.

        Thin wrapper over ``cleardeals.notification.notify`` that never lets a
        notification failure break the calling handler.
        """
        if not user_id:
            return
        try:
            self.env['cleardeals.notification'].notify(
                user_id, ntype, title=title, body=body,
                payload=payload or {}, actionable=actionable)
        except Exception:  # noqa: BLE001
            _logger.warning("wa: notify '%s' to uid=%s failed",
                            ntype, user_id, exc_info=True)

    def _notify_assignment_failed(self, user_ids, reason: str, target_name: str) -> None:
        """Push a 'reassignment_failed' toast (with the reason) to each user.

        Used when the platform reports the Interakt assignment could not be
        completed (e.g. "Agent with email not found"). Failures must be loud and
        reach BOTH the requester and the approver so the chat isn't left in a
        silent limbo.
        """
        self.ensure_one()
        lead_label = self._owa_lead_label(self.lead_id, self.phone_number)
        message = ("%s's chat couldn't be handed to %s (%s). It stays with its "
                   "current owner — please follow up so the lead isn't dropped."
                   % (lead_label, target_name, reason))
        payload = {
            'reason': reason,
            'phone': self.phone_number,
            'lead_id': self.lead_id.id if self.lead_id else None,
            'lead_name': self.lead_id.name if self.lead_id else '',
            'conversation_id': self.id,
        }
        for uid in {u for u in user_ids if u}:
            self._push_user_notification(
                uid, 'reassignment_failed',
                title='Couldn\'t reassign %s\'s chat' % lead_label,
                body=message, payload=payload)

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

    @api.model
    def search_properties(self, query: str = '', limit: int = 20) -> list[dict]:
        """Typeahead search over ``property.base`` for the Create-lead picker.

        Returns ``[{id, name}]`` so the Inbox modal can offer a lightweight
        searchable property dropdown without a full Odoo many2one widget.
        """
        domain = []
        if query:
            domain = ['|', ('name', 'ilike', query), ('property_tag', 'ilike', query)]
        props = self.env['property.base'].sudo().search(
            domain, limit=min(int(limit or 20), 50), order='id desc')
        return [{'id': p.id, 'name': p.display_name or p.name or ''} for p in props]

    @api.model
    def create_lead_from_chat(self, conversation_id: int, name: str,
                              property_base_id: int | None = None,
                              source_id: int | None = None) -> int:
        """Convert a phone-only (orphan) conversation into a real lead.

        Triage action for inbound messages from unknown numbers: an RM gives the
        contact a name and (optionally) picks the property they're interested in.
        The lead is created via the canonical ``create_lead_if_not_duplicate``
        (dedup + phone standardization), the conversation is linked + its message
        history back-filled, and ownership is established:

        - **Property selected** → the lead and conversation route to that
          property's RM (``property.base.rm_user_id``).
        - **No property** → the triaging RM (current user) takes ownership.

        :returns: the linked ``leads.new`` id (new or dedup-matched).
        """
        conv = self.sudo().browse(conversation_id)
        if not conv.exists():
            raise UserError("Conversation not found.")
        if conv.lead_id:
            # Already linked — nothing to create.
            return conv.lead_id.id
        name = (name or '').strip()
        if not name:
            raise UserError("Please enter a name for the lead.")

        Leads = self.env['leads.new']
        phone10 = self._owa_standardize_lead_phone(conv.phone_number)

        if not source_id:
            source = self.env.ref(
                'wa_communication.lead_source_whatsapp_inbound',
                raise_if_not_found=False)
            source_id = source.id if source else False
        if not source_id:
            raise UserError(
                "The 'WhatsApp Inbound' lead source is not configured. "
                "Ask an administrator to set it up.")

        vals = {'name': name, 'phone': phone10, 'source_id': source_id}
        prop = None
        if property_base_id:
            prop = self.env['property.base'].sudo().browse(int(property_base_id))
            if prop.exists():
                vals['property_base_id'] = prop.id

        # Canonical creation (handles dedup + standardization). Returns None when
        # a duplicate is detected — in that case link the existing lead instead.
        lead = Leads.create_lead_if_not_duplicate(vals)
        if not lead:
            lead = Leads.sudo().search(
                [('phone', '=', phone10)], order='create_date desc', limit=1)
        if not lead:
            raise UserError("Could not create a lead for this conversation.")

        # Resolve the owning RM: property RM first, else the triaging user.
        rm = prop.rm_user_id if (prop and prop.exists() and prop.rm_user_id) else self.env.user
        write_vals = {'user_id': rm.id, 'state': 'assigned'}
        if prop and prop.exists():
            write_vals['property_base_id'] = prop.id
        lead.sudo().write(write_vals)

        # Link the conversation to the lead. (wa.message rows are append-only, so
        # earlier messages keep their original lead_id — the conversation link is
        # the source of truth the UI reads.)
        conv.write({'lead_id': lead.id})

        # Establish chat ownership for the resolved RM (platform round-trip).
        self._owa_autoassign_to_lead_rm(conv, lead)

        # Keystone for the "inquiry created after the conversation" case: bind the
        # active (label-only) segment to the freshly-created inquiry, so its
        # messages reclassify to this property without touching their immutable
        # lead_id.  Falls back to ensuring a segment for the lead when none active.
        if conv._owa_segments_enabled():
            seg = conv.active_segment_id
            if seg and not seg.inquiry_id:
                self.relink_segment(seg.id, lead.id)
            else:
                conv._owa_ensure_segment(inquiry=lead, started_by='rm')

        conv._owa_log_system_event("Lead created from chat: %s" % lead.name)
        return lead.id

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
                'segment_id': msg.segment_id.id if msg.segment_id else None,
                'segment_label': msg.segment_id.display_name if msg.segment_id else None,
                'workflow_slug': msg.workflow_slug or None,
                'delivered_at': msg.delivered_at.isoformat() if msg.delivered_at else None,
                'seen_at': msg.seen_at.isoformat() if msg.seen_at else None,
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

        # Pending handover requests the current user may act on (they are the
        # current assignee, or a manager). Surfaced in the thread so approval is
        # PERSISTENT and discoverable — not reliant on catching a transient
        # real-time toast. The requester's own open request is excluded.
        incoming_requests = []
        is_mgr = conv._is_wa_manager()
        if conv.assigned_user_id.id == self.env.uid or is_mgr:
            pending = self.env['wa.reassignment.request'].sudo().search([
                ('conversation_id', '=', conv.id),
                ('state', '=', 'pending'),
                ('requester_id', '!=', self.env.uid),
            ])
            incoming_requests = [{
                'id': r.id,
                'requester_id': r.requester_id.id,
                'requester_name': r.requester_id.name,
                'note': r.note or '',
            } for r in pending]

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
                'is_manager': is_mgr,
                'assignment_pending': conv.assignment_pending,
                # True when the current user already has an open handover request
                # on this chat — lets the composer show "waiting for approval".
                'my_open_request': bool(self.env['wa.reassignment.request'].sudo().search_count([
                    ('conversation_id', '=', conv.id),
                    ('requester_id', '=', self.env.uid),
                    ('state', 'in', ('pending', 'confirming')),
                ])),
                # Handover requests awaiting THIS user's approval (persistent).
                'incoming_requests': incoming_requests,
                # Inquiry-attribution context (dormant unless segments_enabled).
                **conv._owa_segment_thread_context(),
            },
            'messages': messages,
            'stats': stats,
        }

    def _owa_segment_thread_context(self) -> dict:
        """Segment/inquiry context block merged into the get_thread payload.

        Returns ``segments_enabled=False`` (and nothing else) when the feature is
        off, so the inbox renders exactly as before.  When on, surfaces the active
        segment, the list of segments, and every inquiry on this phone for the
        switcher.
        """
        self.ensure_one()
        if not self._owa_segments_enabled():
            return {'segments_enabled': False}

        def _seg(s):
            return {
                'id': s.id,
                'label': s.display_name,
                'inquiry_id': s.inquiry_id.id if s.inquiry_id else None,
                'property': s.property_base_id.property_tag or None,
                'message_count': s.message_count,
            }

        return {
            'segments_enabled': True,
            'active_segment': _seg(self.active_segment_id) if self.active_segment_id else None,
            'segments': [_seg(s) for s in self.segment_ids],
            'inquiries': [{
                'id': lead.id,
                'name': lead.name or '',
                'property': lead.property_base_id.property_tag
                            or (lead.property_base_id.display_name if lead.property_base_id else None),
            } for lead in self.inquiry_ids],
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
