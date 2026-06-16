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

Model layout (one model, several files)
---------------------------------------
``wa.conversation`` is large, so its methods are split by responsibility across
partial-class files — each declares ``_inherit = 'wa.conversation'`` and is
merged into the single model at registry build time:

- this file — record definition (fields, constraints, computes), the inbound
  push dispatcher :meth:`_process_push_event`, core lookups and the shared
  ``_owa_*`` helpers used by the others.
- ``wa_conversation_segments.py``   — inquiry-segment attribution.
- ``wa_conversation_inbound.py``    — WA Cloud webhook handlers.
- ``wa_conversation_events.py``     — OdooWaEvent handlers.
- ``wa_conversation_assignment.py`` — ownership / reassignment handshake.
- ``wa_conversation_outbound.py``   — outbound send paths.
- ``wa_conversation_serializers.py``— inbox/thread read serializers for the UI.

Module-level constants and free functions live here and are imported by the
other files.  :meth:`_process_push_event` must stay on this base class — a test
patches it by its fully-qualified path.
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
    # Shared lookup helpers (used by the inbound, events & outbound mixins)
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


    # ------------------------------------------------------------------
    # Shared helpers — lead/RM resolution, notifications, logging
    # (used across the inbound, events, assignment & serializer mixins)
    # ------------------------------------------------------------------


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
