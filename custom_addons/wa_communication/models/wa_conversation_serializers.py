"""Read-side serializers for the inbox & thread OWL UI (get_inbox/get_thread).

Part of the ``wa.conversation`` model — see wa_conversation.py for the base
definition (fields, constraints, inbound push dispatcher).
"""
import json
import logging

from datetime import datetime, timedelta

from odoo import api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class WaConversation(models.Model):
    _inherit = 'wa.conversation'

    # ── Inbox configuration (SLA + window thresholds) ──────────────────────────

    # ir.config_parameter keys with their built-in defaults (minutes / hours).
    _INBOX_SLA_WARN_KEY = 'wa_communication.sla_warn_minutes'
    _INBOX_SLA_BREACH_KEY = 'wa_communication.sla_breach_minutes'
    _INBOX_CLOSING_SOON_KEY = 'wa_communication.window_closing_soon_hours'

    def _owa_inbox_config(self) -> dict:
        """Resolve the inbox SLA / window thresholds (configurable, with defaults)."""
        get = self.env['ir.config_parameter'].sudo().get_param

        def _num(key, default):
            try:
                return float(get(key, default))
            except (TypeError, ValueError):
                return float(default)

        return {
            'sla_warn': _num(self._INBOX_SLA_WARN_KEY, 60),       # minutes
            'sla_breach': _num(self._INBOX_SLA_BREACH_KEY, 240),   # minutes
            'closing_soon_h': _num(self._INBOX_CLOSING_SOON_KEY, 4),  # hours
        }

    # ── Filter → ORM domain (single source of truth for list AND counts) ───────

    def _owa_inbox_domain(self, filters: dict, now, cfg: dict, exclude=()) -> list:
        """Build the inbox search domain from ``filters``, skipping any axis in
        ``exclude``.  Sharing this between the list query and every facet count is
        what keeps the badges and the list provably consistent — they can never be
        computed from different populations again.
        """
        exclude = set(exclude)
        domain = []

        # Free-text search: lead name or phone.
        if 'search' not in exclude and filters.get('search'):
            s = filters['search']
            domain += ['|', ('lead_id.name', 'ilike', s), ('phone_number', 'ilike', s)]

        # Lead source (optional — the field may be absent on some installs).
        if 'source' not in exclude and filters.get('source'):
            src = filters['source']
            src_ids = src if isinstance(src, (list, tuple)) else [src]
            if 'source_id' in self.env['leads.new']._fields:
                domain.append(('lead_id.source_id', 'in', [int(i) for i in src_ids]))

        # Date range on last_message_at ("anytime" / missing → no constraint).
        if 'date' not in exclude:
            domain += self._owa_inbox_date_domain(filters, now)

        # Ownership axis (mine / unassigned / others / all).
        if 'ownership' not in exclude:
            uid = self.env.uid
            ownership = filters.get('ownership') or 'all'
            if ownership == 'mine':
                domain.append(('assigned_user_id', '=', uid))
            elif ownership == 'unassigned':
                domain.append(('assigned_user_id', '=', False))
            elif ownership == 'others':
                domain += [('assigned_user_id', '!=', False),
                           ('assigned_user_id', '!=', uid)]

        # Explicit RM multi-select (independent of the ownership tab).
        if 'rm' not in exclude and filters.get('assigned_rm_ids'):
            ids = [int(i) for i in filters['assigned_rm_ids']]
            if ids:
                domain.append(('assigned_user_id', 'in', ids))

        # Needs-reply quick filter.
        if 'needs_reply' not in exclude and filters.get('needs_reply'):
            domain.append(('unread_count', '>', 0))

        # 24h window state.
        if 'window' not in exclude:
            domain += self._owa_inbox_window_domain(filters.get('window'), now, cfg)

        # RM scoping — ALWAYS applied (never excluded by a facet). The serializers
        # run as sudo(), so this is the real access boundary for the Inbox, not a
        # record rule. Managers (and privileged/system contexts) are unrestricted.
        #
        # A non-manager RM sees every chat they are assigned OR own an inquiry in:
        # the design is "see the chats for your inquiries; you can only *reply*
        # once it's assigned to you" — replying is gated separately by _can_send,
        # which stays assignment-only. inquiry_ids is a non-stored compute, so we
        # scope on the stored ownership paths: the anchor lead, and the per-message
        # inquiry tag (which carries secondary inquiries on the same number).
        if not self._owa_inbox_unrestricted():
            uid = self.env.uid
            domain += ['|', '|',
                       ('assigned_user_id', '=', uid),
                       ('lead_id.user_id', '=', uid),
                       ('message_ids.lead_id.user_id', '=', uid)]

        return domain

    def _owa_inbox_unrestricted(self) -> bool:
        """True when the caller sees every conversation: a WhatsApp manager, or a
        privileged/system context (superuser, crons, automated jobs). A normal RM
        RPC call has ``env.su`` False and is scoped to their own chats."""
        return bool(self.env.su) or self.env.user.has_group(
            'wa_communication.group_wa_manager')

    def _owa_can_view_thread(self, conv) -> bool:
        """Whether the current user may open ``conv``'s thread.

        Managers / privileged contexts and the assignee always may.  An RM may
        also open a chat they own an inquiry in (read-only — replying is gated by
        _can_send on assignment), or one they have an OPEN handover request on so
        the "request sent — waiting for approval" state still renders for them.

        This must stay in lock-step with the Inbox list scoping in
        _owa_inbox_domain: a row that appears in the list must be openable.
        """
        if self._owa_inbox_unrestricted():
            return True
        uid = self.env.uid
        if conv.assigned_user_id.id == uid:
            return True
        if conv.lead_id.user_id.id == uid or uid in conv.message_ids.lead_id.user_id.ids:
            return True
        return bool(self.env['wa.reassignment.request'].sudo().search_count([
            ('conversation_id', '=', conv.id),
            ('requester_id', '=', self.env.uid),
            ('state', 'in', ('pending', 'confirming')),
        ]))

    def _owa_inbox_date_domain(self, filters: dict, now) -> list:
        """Date-range constraint on ``last_message_at`` (empty for anytime)."""
        date_range = filters.get('date_range') or 'anytime'
        if date_range == 'anytime':
            return []
        if date_range == 'custom':
            out = []
            if filters.get('date_from'):
                out.append(('last_message_at', '>=', filters['date_from']))
            if filters.get('date_to'):
                out.append(('last_message_at', '<=', filters['date_to']))
            return out
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if date_range == 'today':
            return [('last_message_at', '>=', midnight)]
        if date_range == 'yesterday':
            return [('last_message_at', '>=', midnight - timedelta(days=1)),
                    ('last_message_at', '<', midnight)]
        if date_range == 'last_7d':
            return [('last_message_at', '>=', now - timedelta(days=7))]
        if date_range == 'last_30d':
            return [('last_message_at', '>=', now - timedelta(days=30))]
        if date_range == 'this_month':
            return [('last_message_at', '>=', midnight.replace(day=1))]
        return []

    def _owa_inbox_window_domain(self, window, now, cfg: dict) -> list:
        """Domain for the objective 24h-window state (open/closing_soon/closed)."""
        if not window or window == 'all':
            return []
        if window == 'open':
            return [('window_expires_at', '>', now)]
        if window == 'closing_soon':
            soon = now + timedelta(hours=cfg['closing_soon_h'])
            return [('window_expires_at', '>', now), ('window_expires_at', '<=', soon)]
        if window == 'closed':
            return ['|', ('window_expires_at', '=', False),
                    ('window_expires_at', '<=', now)]
        return []

    # ── Per-row derived signals ────────────────────────────────────────────────

    def _owa_waiting_since(self, conv):
        """When the customer started waiting for a reply: the first inbound message
        newer than the latest non-system outbound (or the earliest inbound if we've
        never replied).  Returns ``None`` when nothing is awaiting a reply — more
        accurate than ``last_message_at`` when the customer sent several messages."""
        msgs = conv.message_ids.sorted('occurred_at')
        last_out = None
        for m in reversed(msgs):
            if m.direction == 'outbound' and m.kind != 'system' and m.occurred_at:
                last_out = m.occurred_at
                break
        for m in msgs:
            if (m.direction == 'inbound' and m.occurred_at
                    and (not last_out or m.occurred_at > last_out)):
                return m.occurred_at
        return None

    def _owa_window_state(self, conv, now, cfg: dict) -> str:
        """Display window state: closed / closing_soon / open."""
        exp = conv.window_expires_at
        if not exp or exp <= now:
            return 'closed'
        if exp <= now + timedelta(hours=cfg['closing_soon_h']):
            return 'closing_soon'
        return 'open'

    _INBOX_SORTS = {
        'recent':  'last_message_at desc, id desc',
        'unread':  'unread_count desc, last_message_at desc, id desc',
        'waiting': 'unread_count desc, last_message_at asc, id desc',
    }

    @api.model
    def get_inbox(self, filters: dict | None = None) -> dict:
        """Return the WhatsApp Inbox payload: ``{rows, total, counts, is_manager}``.

        The list rows, the total, and every facet count are derived from one shared
        base domain (see :meth:`_owa_inbox_domain`), so the badges always agree with
        the list.  Sorting and pagination are done server-side so "longest waiting"
        is honest across the whole population, not just the first page.
        """
        filters = filters or {}
        cfg = self._owa_inbox_config()
        now = datetime.utcnow()
        limit = min(int(filters.get('limit', 50)), 200)
        offset = int(filters.get('offset', 0))
        order = self._INBOX_SORTS.get(filters.get('sort'), self._INBOX_SORTS['waiting'])
        Conv = self.env['wa.conversation'].sudo()
        uid = self.env.uid

        base = self._owa_inbox_domain(filters, now, cfg)
        total = Conv.search_count(base)
        convs = Conv.search(base, order=order, limit=limit, offset=offset)

        rows = [self._owa_inbox_row(conv, now, cfg, uid) for conv in convs]

        return {
            'rows': rows,
            'total': total,
            'counts': self._owa_inbox_counts(filters, now, cfg),
            'is_manager': self.env.user.has_group('wa_communication.group_wa_manager'),
        }

    def _owa_inbox_row(self, conv, now, cfg: dict, uid: int) -> dict:
        """Serialize one conversation for the inbox list."""
        lead = conv.lead_id
        portal_source = ''
        if lead:
            portal_source = getattr(lead, 'portal_source', '') or getattr(lead, 'source_id', '') or ''
            if hasattr(portal_source, 'name'):
                portal_source = portal_source.name
        last_wf_msg = conv.message_ids.filtered(
            lambda m: m.workflow_slug).sorted('occurred_at', reverse=True)[:1]

        waiting_minutes, sla_band = None, None
        if conv.unread_count > 0:
            since = self._owa_waiting_since(conv)
            if since:
                waiting_minutes = max(0, int((now - since).total_seconds() // 60))
                sla_band = ('breach' if waiting_minutes >= cfg['sla_breach']
                            else 'warn' if waiting_minutes >= cfg['sla_warn'] else 'ok')

        return {
            'id': conv.id,
            'lead_id': lead.id if lead else None,
            'lead_name': lead.name if lead else None,
            'lead_source': portal_source,
            'phone': conv.phone_number,
            'last_message': conv.last_message_preview or '',
            'last_message_at': conv.last_message_at.isoformat() if conv.last_message_at else None,
            'unread_count': conv.unread_count,
            'needs_reply': conv.unread_count > 0,
            'waiting_minutes': waiting_minutes,
            'sla_band': sla_band,
            'window_state': self._owa_window_state(conv, now, cfg),
            'window_expires_at': conv.window_expires_at.isoformat() if conv.window_expires_at else None,
            'assigned_user_id': conv.assigned_user_id.id if conv.assigned_user_id else None,
            'assigned_user_name': conv.assigned_user_id.name if conv.assigned_user_id else None,
            'is_mine': bool(conv.assigned_user_id) and conv.assigned_user_id.id == uid,
            'can_send': conv._can_send(),
            'assignment_pending': conv.assignment_pending,
            'workflow_name': last_wf_msg.workflow_slug if last_wf_msg else '',
            'interakt_url': conv.interakt_inbox_url,
        }

    def _owa_inbox_counts(self, filters: dict, now, cfg: dict) -> dict:
        """Facet counts — each computed over the base domain MINUS its own axis, so
        every badge says exactly how many rows you'd get if you clicked it."""
        Conv = self.env['wa.conversation'].sudo()
        uid = self.env.uid

        # Ownership tabs: vary ownership, honour the active quick filters.
        own_base = self._owa_inbox_domain(filters, now, cfg, exclude=('ownership', 'rm'))
        ownership = {
            'mine':       Conv.search_count(own_base + [('assigned_user_id', '=', uid)]),
            'unassigned': Conv.search_count(own_base + [('assigned_user_id', '=', False)]),
            'others':     Conv.search_count(own_base + [('assigned_user_id', '!=', False),
                                                        ('assigned_user_id', '!=', uid)]),
            'all':        Conv.search_count(own_base),
        }

        # Quick chips: count within the current ownership/date/search scope,
        # independent of which quick filter is currently toggled.
        quick_base = self._owa_inbox_domain(filters, now, cfg, exclude=('needs_reply', 'window'))
        needs_reply = Conv.search_count(quick_base + [('unread_count', '>', 0)])
        closing_soon = Conv.search_count(
            quick_base + self._owa_inbox_window_domain('closing_soon', now, cfg))

        # RM facet: who owns chats in the current quick-filter scope.
        # Odoo 19 ``_read_group`` returns a list of ``(*groupby, *aggregates)``
        # tuples — here ``(user_record, count)``.
        rm_base = self._owa_inbox_domain(filters, now, cfg, exclude=('ownership', 'rm'))
        rm_groups = Conv._read_group(
            rm_base + [('assigned_user_id', '!=', False)],
            groupby=['assigned_user_id'], aggregates=['__count'])
        rms = [{
            'id': rm.id,
            'name': rm.name,
            'count': count,
        } for rm, count in rm_groups]
        rms.sort(key=lambda r: (-r['count'], r['name']))

        return {
            'ownership': ownership,
            'needs_reply': needs_reply,
            'closing_soon': closing_soon,
            'rms': rms,
        }

    @api.model
    def search_properties(self, query: str = '', limit: int = 20) -> list[dict]:
        """Typeahead search over ``property.base`` for the Create-lead picker.

        Returns ``[{id, name, tag}]`` so a lightweight searchable property dropdown
        (Inbox create-lead modal, "New topic" picker) can render without a full Odoo
        many2one widget. ``tag`` is the ``property_tag`` slug — the intentional
        display key across the WhatsApp UI.
        """
        domain = []
        if query:
            domain = ['|', ('name', 'ilike', query), ('property_tag', 'ilike', query)]
        props = self.env['property.base'].sudo().search(
            domain, limit=min(int(limit or 20), 50), order='id desc')
        return [{'id': p.id, 'name': p.display_name or p.name or '',
                 'tag': p.property_tag or ''} for p in props]

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
            # Property-anchored spans are already bound by the leads.new create hook
            # (_owa_bind_new_inquiry). Here we only catch a no-property active
            # label-only span so the orphan flow never strands one, then make sure
            # the lead has an active segment. ensure_segment dedups by inquiry, so
            # this is idempotent with the hook.
            active = conv.active_segment_id
            if active and not active.inquiry_id and not active.property_base_id:
                self.relink_segment(active.id, lead.id)
            conv._owa_ensure_segment(inquiry=lead, started_by='rm')

        conv._owa_log_system_event("Lead created from chat: %s" % lead.name)
        return lead.id

    @api.model
    def get_thread(self, conversation_id: int) -> dict:
        """Return full thread data for a conversation.

        :param conversation_id: ``wa.conversation`` record ID.
        :return: Dict with ``conversation`` metadata, ``messages`` list,
                 and ``stats`` (whole-conversation sent/delivered/read/replies,
                 excluding internal system log rows).
        """
        conv = self.env['wa.conversation'].sudo().browse(conversation_id)
        if not conv.exists():
            return {'error': 'Conversation not found'}
        # RM scoping: a non-manager may only open a conversation they own — plus
        # one they have an open handover request on (so the requester's wait-state
        # UI still works). The serializer is sudo, so guard explicitly.
        if not self._owa_can_view_thread(conv):
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
                'list_payload': self._owa_parse_list_payload(msg),
                'status': msg.status,
                'occurred_at': msg.occurred_at.isoformat() if msg.occurred_at else None,
                'sender_name': msg.sender_name or (
                    conv.lead_id.name if msg.direction == 'inbound' and conv.lead_id
                    else None
                ),
                'template_name': msg.template_name or None,
                'template_header': msg.template_header or None,
                'template_header_media_url': msg.template_header_media_url or None,
                'template_header_media_type': msg.template_header_media_type or None,
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

        # Conversation stats — must describe the SAME messages the thread above
        # shows, which is every message in the conversation (all inquiries on
        # this number), not just conv.lead_id's. Two things were wrong before:
        #   1. Stats were scoped to conv.lead_id, so a second inquiry's replies
        #      (visible in the thread) were dropped — "Replies 1" when the screen
        #      shows several.
        #   2. `system` rows (workflow enrolled/completed, assignment notices) are
        #      internal log bubbles, never sent to WhatsApp. Counting them as
        #      "Sent" inflated the total and dragged delivered/read % down.
        # A message counts as *sent* only if it was actually handed to WhatsApp,
        # i.e. reached sent/delivered/read — a `failed` send is not "sent".
        _SENT_STATES = ('sent', 'delivered', 'read')
        outbound_real = conv.message_ids.filtered(
            lambda m: m.direction == 'outbound' and m.kind != 'system'
        )
        sent_msgs = outbound_real.filtered(lambda m: m.status in _SENT_STATES)
        delivered = sent_msgs.filtered(lambda m: m.status in ('delivered', 'read'))
        read = sent_msgs.filtered(lambda m: m.status == 'read')
        replies = conv.message_ids.filtered(lambda m: m.direction == 'inbound')
        sent_n = len(sent_msgs)
        stats = {
            'sent': sent_n,
            'delivered': len(delivered),
            'read': len(read),
            'replies': len(replies),
            'delivered_pct': round(100 * len(delivered) / sent_n) if sent_n else 0,
            'read_pct': round(100 * len(read) / sent_n) if sent_n else 0,
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
                'property_base_id': s.property_base_id.id or None,
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
                'property_base_id': lead.property_base_id.id or None,
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

    def _owa_parse_list_payload(self, msg):
        """Return the parsed ``{'button', 'sections'}`` dict for a list message,
        or ``None`` when the message isn't a list / has no payload."""
        if msg.kind != 'list' or not msg.list_payload:
            return None
        try:
            data = json.loads(msg.list_payload)
        except (ValueError, TypeError):
            return None
        if isinstance(data, dict) and data.get('sections'):
            return data
        return None
