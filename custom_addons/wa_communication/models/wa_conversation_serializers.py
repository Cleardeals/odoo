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
