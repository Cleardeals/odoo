"""UI serialisers — ``get_thread``, ``get_inbox``, counts, quoted-link wiring.

These power the OWL inbox and lead-tab.  A regression here silently breaks the
front-end (wrong gating, missing messages, broken stats) without any Python
traceback, so they deserve tight coverage.
"""

from datetime import datetime, timedelta

from odoo.tests import tagged

from .common import WaTransactionCase


@tagged('post_install', '-at_install', 'wa_communication')
class TestThreadSerializers(WaTransactionCase):

    # ── get_thread ────────────────────────────────────────────────────────────

    def test_get_thread_missing_returns_error(self):
        res = self.Conv.get_thread(999999999)
        self.assertEqual(res, {'error': 'Conversation not found'})

    def test_get_thread_shape_and_ordering(self):
        conv = self.make_conversation()
        self.make_message(conv, body='first', occurred_at='2026-01-01 10:00:00')
        self.make_message(conv, body='second', occurred_at='2026-01-01 11:00:00')
        res = self.Conv.get_thread(conv.id)

        self.assertIn('conversation', res)
        self.assertIn('messages', res)
        self.assertIn('stats', res)
        self.assertEqual([m['body'] for m in res['messages']], ['first', 'second'])
        convd = res['conversation']
        self.assertEqual(convd['id'], conv.id)
        self.assertEqual(convd['phone'], conv.phone_number)
        # Gating keys the composer relies on.
        for key in ('can_send', 'send_gate_reason', 'is_manager', 'assignment_pending'):
            self.assertIn(key, convd)

    def test_get_thread_can_send_reflects_ownership(self):
        other = self.make_user()
        mine = self.make_conversation()                       # assigned to me
        theirs = self.make_conversation(assigned_user_id=other.id)
        self.assertTrue(self.Conv.get_thread(mine.id)['conversation']['can_send'])
        theirs_thread = self.Conv.get_thread(theirs.id)['conversation']
        self.assertFalse(theirs_thread['can_send'])
        self.assertIn(other.name, theirs_thread['send_gate_reason'])

    def test_get_thread_window_open_flag(self):
        conv = self.make_conversation()
        conv.sudo().write({
            'window_expires_at': datetime.utcnow() + timedelta(hours=2)})
        self.assertEqual(
            self.Conv.get_thread(conv.id)['conversation']['window_state'], 'open')
        conv.sudo().write({
            'window_expires_at': datetime.utcnow() - timedelta(hours=2)})
        self.assertEqual(
            self.Conv.get_thread(conv.id)['conversation']['window_state'], 'closed')

    def test_get_thread_stats_for_linked_lead(self):
        lead = self.make_lead(phone='9123456780')
        conv = self.make_conversation(lead_id=lead.id)
        # 3 outbound (2 delivered, 1 of which read) + 1 inbound reply.
        self.make_message(conv, direction='outbound', initiator='rm',
                          kind='freetext', status='read', lead_id=lead.id)
        self.make_message(conv, direction='outbound', initiator='rm',
                          kind='freetext', status='delivered', lead_id=lead.id)
        self.make_message(conv, direction='outbound', initiator='rm',
                          kind='freetext', status='sent', lead_id=lead.id)
        self.make_message(conv, direction='inbound', initiator='buyer',
                          kind='text_reply', status='delivered', lead_id=lead.id)
        stats = self.Conv.get_thread(conv.id)['stats']
        self.assertEqual(stats['sent'], 3)
        self.assertEqual(stats['delivered'], 2)   # read counts as delivered too
        self.assertEqual(stats['read'], 1)
        self.assertEqual(stats['replies'], 1)
        self.assertEqual(stats['read_pct'], 33)

    def test_stats_exclude_system_log_rows(self):
        """`system` bubbles (enrolled/completed/assignment notices) are internal
        logs, never sent to WhatsApp — they must not count as sent nor dilute %."""
        lead = self.make_lead(phone='9123456781')
        conv = self.make_conversation(lead_id=lead.id)
        # One real template, read.
        self.make_message(conv, direction='outbound', initiator='workflow',
                          kind='template', status='read', lead_id=lead.id)
        # Three system log rows the engine writes — must be ignored.
        for st in ('enrolled', 'enrollment_completed', 'sent'):
            self.make_message(conv, direction='outbound', initiator='workflow',
                              kind='system', status=st, lead_id=lead.id)
        stats = self.Conv.get_thread(conv.id)['stats']
        self.assertEqual(stats['sent'], 1)          # not 4
        self.assertEqual(stats['read'], 1)
        self.assertEqual(stats['read_pct'], 100)    # 1/1, not 1/4 = 25

    def test_failed_send_is_not_counted_as_sent(self):
        lead = self.make_lead(phone='9123456782')
        conv = self.make_conversation(lead_id=lead.id)
        self.make_message(conv, direction='outbound', initiator='workflow',
                          kind='template', status='read', lead_id=lead.id)
        self.make_message(conv, direction='outbound', initiator='workflow',
                          kind='image', status='failed', lead_id=lead.id)
        stats = self.Conv.get_thread(conv.id)['stats']
        self.assertEqual(stats['sent'], 1)          # the failed image is not "sent"
        self.assertEqual(stats['delivered'], 1)
        self.assertEqual(stats['read_pct'], 100)

    def test_stats_span_whole_conversation_not_just_linked_lead(self):
        """The thread shows every message on the number (all inquiries), so the
        stats must too — otherwise a second inquiry's replies vanish from the
        count while still being visible above."""
        lead_a = self.make_lead(phone='9123456783')
        lead_b = self.make_lead(phone='9123456784')
        conv = self.make_conversation(lead_id=lead_a.id)
        # One template + one reply on each inquiry.
        self.make_message(conv, direction='outbound', initiator='workflow',
                          kind='template', status='read', lead_id=lead_a.id)
        self.make_message(conv, direction='outbound', initiator='workflow',
                          kind='template', status='delivered', lead_id=lead_b.id)
        self.make_message(conv, direction='inbound', initiator='buyer',
                          kind='button_reply', status='delivered', lead_id=lead_a.id)
        self.make_message(conv, direction='inbound', initiator='buyer',
                          kind='text_reply', status='delivered', lead_id=lead_b.id)
        self.make_message(conv, direction='inbound', initiator='buyer',
                          kind='text_reply', status='delivered', lead_id=lead_b.id)
        stats = self.Conv.get_thread(conv.id)['stats']
        self.assertEqual(stats['sent'], 2)          # both inquiries' sends
        self.assertEqual(stats['replies'], 3)       # not 1 (lead_a only)

    # ── quoted-link resolution ────────────────────────────────────────────────

    def test_resolve_quoted_links_by_template_name(self):
        messages = [
            {'id': 1, 'template_name': 'visit', 'body': '', 'template_header': None,
             'quoted_msg_id': None, 'template_replied_to': None, 'quoted_body': None},
            {'id': 2, 'template_name': None, 'body': 'Yes', 'template_header': None,
             'quoted_msg_id': None, 'template_replied_to': 'visit', 'quoted_body': None},
        ]
        self.Conv._owa_resolve_quoted_links(messages)
        self.assertEqual(messages[1]['quoted_msg_id'], 1)

    def test_resolve_quoted_links_by_body_snippet(self):
        messages = [
            {'id': 10, 'template_name': None, 'body': 'Please confirm your visit',
             'template_header': None, 'quoted_msg_id': None,
             'template_replied_to': None, 'quoted_body': None},
            {'id': 11, 'template_name': None, 'body': 'ok', 'template_header': None,
             'quoted_msg_id': None, 'template_replied_to': None,
             'quoted_body': 'confirm your visit'},
        ]
        self.Conv._owa_resolve_quoted_links(messages)
        self.assertEqual(messages[1]['quoted_msg_id'], 10)

    def test_resolve_quoted_links_noop_without_reference(self):
        messages = [
            {'id': 1, 'template_name': None, 'body': 'hello', 'template_header': None,
             'quoted_msg_id': None, 'template_replied_to': None, 'quoted_body': None},
        ]
        self.Conv._owa_resolve_quoted_links(messages)
        self.assertIsNone(messages[0]['quoted_msg_id'])

    # ── get_inbox: shape ──────────────────────────────────────────────────────

    def test_inbox_returns_rows_total_counts(self):
        conv = self.make_conversation()
        conv.sudo().write({'last_message_at': datetime.utcnow()})
        data = self.Conv.get_inbox({'ownership': 'all'})
        self.assertIn('rows', data)
        self.assertIn('total', data)
        self.assertIn('counts', data)
        self.assertIn('is_manager', data)
        self.assertEqual(set(data['counts'].keys()),
                         {'ownership', 'needs_reply', 'closing_soon', 'rms'})
        self.assertEqual(set(data['counts']['ownership'].keys()),
                         {'mine', 'unassigned', 'others', 'all'})

    def test_inbox_row_carries_signals(self):
        conv = self.make_conversation()
        conv.sudo().write({'last_message_at': datetime.utcnow()})
        row = next(r for r in self.Conv.get_inbox({'ownership': 'all'})['rows']
                   if r['id'] == conv.id)
        for key in ('can_send', 'assignment_pending', 'window_state',
                    'needs_reply', 'waiting_minutes', 'sla_band', 'is_mine'):
            self.assertIn(key, row)
        self.assertTrue(row['can_send'])   # assigned to me by default
        self.assertTrue(row['is_mine'])

    # ── get_inbox: filters ────────────────────────────────────────────────────

    def test_inbox_needs_reply_filter(self):
        waiting = self.make_conversation()
        waiting.sudo().write({'unread_count': 2, 'last_message_at': datetime.utcnow()})
        answered = self.make_conversation()
        answered.sudo().write({'unread_count': 0, 'last_message_at': datetime.utcnow()})
        ids = {r['id'] for r in
               self.Conv.get_inbox({'ownership': 'all', 'needs_reply': True})['rows']}
        self.assertIn(waiting.id, ids)
        self.assertNotIn(answered.id, ids)

    def test_inbox_search_matches_phone(self):
        conv = self.make_conversation(phone_number='919812345678')
        conv.sudo().write({'last_message_at': datetime.utcnow()})
        ids = {r['id'] for r in
               self.Conv.get_inbox({'ownership': 'all', 'search': '9812345678'})['rows']}
        self.assertIn(conv.id, ids)

    def test_inbox_ownership_mine_vs_unassigned(self):
        other = self.make_user()
        mine = self.make_conversation()                       # assigned to me
        theirs = self.make_conversation(assigned_user_id=other.id)
        orphan = self.make_conversation(assigned_user_id=False)
        for c in (mine, theirs, orphan):
            c.sudo().write({'last_message_at': datetime.utcnow()})

        mine_ids = {r['id'] for r in self.Conv.get_inbox({'ownership': 'mine'})['rows']}
        self.assertIn(mine.id, mine_ids)
        self.assertNotIn(theirs.id, mine_ids)
        self.assertNotIn(orphan.id, mine_ids)

        unassigned_ids = {r['id'] for r in
                          self.Conv.get_inbox({'ownership': 'unassigned'})['rows']}
        self.assertIn(orphan.id, unassigned_ids)
        self.assertNotIn(mine.id, unassigned_ids)

    def test_inbox_assigned_rm_ids_multi(self):
        """The multi-RM filter must honour EVERY selected RM (was a bug)."""
        a = self.make_user()
        b = self.make_user()
        ca = self.make_conversation(assigned_user_id=a.id)
        cb = self.make_conversation(assigned_user_id=b.id)
        cmine = self.make_conversation()
        for c in (ca, cb, cmine):
            c.sudo().write({'last_message_at': datetime.utcnow()})
        ids = {r['id'] for r in self.Conv.get_inbox(
            {'ownership': 'all', 'assigned_rm_ids': [a.id, b.id]})['rows']}
        self.assertIn(ca.id, ids)
        self.assertIn(cb.id, ids)        # both RMs honoured, not just the first
        self.assertNotIn(cmine.id, ids)

    def test_inbox_window_filters(self):
        now = datetime.utcnow()
        wopen = self.make_conversation()
        wopen.sudo().write({'window_expires_at': now + timedelta(hours=10),
                            'last_message_at': now})
        wsoon = self.make_conversation()
        wsoon.sudo().write({'window_expires_at': now + timedelta(hours=2),
                            'last_message_at': now})
        wclosed = self.make_conversation()
        wclosed.sudo().write({'window_expires_at': now - timedelta(hours=1),
                              'last_message_at': now})

        open_ids = {r['id'] for r in
                    self.Conv.get_inbox({'ownership': 'all', 'window': 'open'})['rows']}
        self.assertIn(wopen.id, open_ids)
        self.assertIn(wsoon.id, open_ids)      # closing-soon is still open
        self.assertNotIn(wclosed.id, open_ids)

        soon_ids = {r['id'] for r in self.Conv.get_inbox(
            {'ownership': 'all', 'window': 'closing_soon'})['rows']}
        self.assertIn(wsoon.id, soon_ids)
        self.assertNotIn(wopen.id, soon_ids)

        closed_ids = {r['id'] for r in
                      self.Conv.get_inbox({'ownership': 'all', 'window': 'closed'})['rows']}
        self.assertIn(wclosed.id, closed_ids)
        self.assertNotIn(wopen.id, closed_ids)

        # Row window_state reflects the same three-way split.
        row_soon = next(r for r in self.Conv.get_inbox({'ownership': 'all'})['rows']
                        if r['id'] == wsoon.id)
        self.assertEqual(row_soon['window_state'], 'closing_soon')

    # ── get_inbox: counts are consistent with the list ────────────────────────

    def test_inbox_counts_match_list(self):
        """A facet count must equal the list length when that facet is applied —
        the core fix for the badges-vs-list mismatch."""
        for _ in range(3):
            c = self.make_conversation()
            c.sudo().write({'unread_count': 1, 'last_message_at': datetime.utcnow()})
            self.make_message(c, occurred_at=datetime.utcnow())
        c0 = self.make_conversation()
        c0.sudo().write({'unread_count': 0, 'last_message_at': datetime.utcnow()})

        data = self.Conv.get_inbox({'ownership': 'all'})
        needs_reply_total = self.Conv.get_inbox(
            {'ownership': 'all', 'needs_reply': True})['total']
        self.assertEqual(data['counts']['needs_reply'], needs_reply_total)
        self.assertEqual(data['counts']['ownership']['all'], data['total'])

    # ── get_inbox: sort + pagination ──────────────────────────────────────────

    def test_inbox_sort_waiting_orders_unread_oldest_first(self):
        now = datetime.utcnow()
        recent = self.make_conversation()
        recent.sudo().write({'unread_count': 1, 'last_message_at': now})
        old = self.make_conversation()
        old.sudo().write({'unread_count': 1, 'last_message_at': now - timedelta(hours=6)})
        rows = self.Conv.get_inbox(
            {'ownership': 'all', 'needs_reply': True, 'sort': 'waiting'})['rows']
        order = [r['id'] for r in rows if r['id'] in (recent.id, old.id)]
        self.assertEqual(order, [old.id, recent.id])   # longest-waiting on top

    def test_inbox_pagination_offset(self):
        now = datetime.utcnow()
        made = []
        for i in range(5):
            c = self.make_conversation()
            c.sudo().write({'last_message_at': now - timedelta(minutes=i)})
            made.append(c.id)
        page1 = self.Conv.get_inbox(
            {'ownership': 'all', 'sort': 'recent', 'limit': 2, 'offset': 0})
        page2 = self.Conv.get_inbox(
            {'ownership': 'all', 'sort': 'recent', 'limit': 2, 'offset': 2})
        self.assertGreaterEqual(page1['total'], 5)
        ids1 = {r['id'] for r in page1['rows']}
        ids2 = {r['id'] for r in page2['rows']}
        self.assertEqual(len(page1['rows']), 2)
        self.assertFalse(ids1 & ids2)                  # pages don't overlap

    def test_inbox_sla_band_from_waiting_time(self):
        now = datetime.utcnow()
        breach = self.make_conversation()
        breach.sudo().write({'unread_count': 1, 'last_message_at': now})
        self.make_message(breach, occurred_at=now - timedelta(hours=5))
        row = next(r for r in self.Conv.get_inbox({'ownership': 'all'})['rows']
                   if r['id'] == breach.id)
        self.assertEqual(row['sla_band'], 'breach')    # >240m default threshold
        self.assertGreaterEqual(row['waiting_minutes'], 240)

    # ── RM vs Manager scoping ─────────────────────────────────────────────────

    def test_inbox_rm_sees_only_own_chats(self):
        """A non-manager only ever sees their own conversations — even when they
        ask for ownership='all'. This is the access boundary (serializer is sudo)."""
        rm = self.make_user()                      # plain RM (base.group_user)
        other = self.make_user()
        mine = self.make_conversation(assigned_user_id=rm.id)
        theirs = self.make_conversation(assigned_user_id=other.id)
        orphan = self.make_conversation(assigned_user_id=False)
        for c in (mine, theirs, orphan):
            c.sudo().write({'last_message_at': datetime.utcnow()})
        data = self.Conv.with_user(rm).get_inbox({'ownership': 'all'})
        ids = {r['id'] for r in data['rows']}
        self.assertIn(mine.id, ids)
        self.assertNotIn(theirs.id, ids)
        self.assertNotIn(orphan.id, ids)           # RM can't even see unassigned
        self.assertFalse(data['is_manager'])

    def test_inbox_manager_sees_all_chats(self):
        mgr = self.make_user(manager=True)
        other = self.make_user()
        a = self.make_conversation(assigned_user_id=mgr.id)
        b = self.make_conversation(assigned_user_id=other.id)
        orphan = self.make_conversation(assigned_user_id=False)
        for c in (a, b, orphan):
            c.sudo().write({'last_message_at': datetime.utcnow()})
        data = self.Conv.with_user(mgr).get_inbox({'ownership': 'all'})
        ids = {r['id'] for r in data['rows']}
        self.assertTrue({a.id, b.id, orphan.id} <= ids)
        self.assertTrue(data['is_manager'])

    def test_get_thread_rm_blocked_on_others_chat(self):
        rm = self.make_user()
        other = self.make_user()
        theirs = self.make_conversation(assigned_user_id=other.id)
        self.assertEqual(self.Conv.with_user(rm).get_thread(theirs.id),
                         {'error': 'Conversation not found'})
        mine = self.make_conversation(assigned_user_id=rm.id)
        self.assertIn('conversation', self.Conv.with_user(rm).get_thread(mine.id))

    def test_get_thread_manager_can_open_any_chat(self):
        mgr = self.make_user(manager=True)
        other = self.make_user()
        theirs = self.make_conversation(assigned_user_id=other.id)
        self.assertIn('conversation', self.Conv.with_user(mgr).get_thread(theirs.id))

    def test_get_thread_rm_with_open_request_can_view(self):
        """A non-owner RM with an OPEN handover request may still open the thread
        (so their 'waiting for approval' state renders)."""
        rm = self.make_user()
        other = self.make_user()
        conv = self.make_conversation(assigned_user_id=other.id)
        self.env['wa.reassignment.request'].sudo().create({
            'conversation_id': conv.id, 'requester_id': rm.id, 'state': 'pending'})
        self.assertIn('conversation', self.Conv.with_user(rm).get_thread(conv.id))

    def test_get_thread_rm_with_resolved_request_blocked(self):
        """A resolved (declined) request does NOT grant viewing access."""
        rm = self.make_user()
        other = self.make_user()
        conv = self.make_conversation(assigned_user_id=other.id)
        self.env['wa.reassignment.request'].sudo().create({
            'conversation_id': conv.id, 'requester_id': rm.id, 'state': 'declined'})
        self.assertEqual(self.Conv.with_user(rm).get_thread(conv.id),
                         {'error': 'Conversation not found'})

    # ── get_inbox: date-range filters ─────────────────────────────────────────

    def _ids_for(self, filters):
        return {r['id'] for r in self.Conv.get_inbox(dict(ownership='all', **filters))['rows']}

    def test_inbox_date_range_today_yesterday_last7(self):
        now = datetime.utcnow()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today = self.make_conversation()
        today.sudo().write({'last_message_at': now})
        yest = self.make_conversation()
        yest.sudo().write({'last_message_at': midnight - timedelta(hours=2)})
        old = self.make_conversation()
        old.sudo().write({'last_message_at': now - timedelta(days=40)})

        t = self._ids_for({'date_range': 'today'})
        self.assertIn(today.id, t)
        self.assertNotIn(yest.id, t)
        self.assertNotIn(old.id, t)

        y = self._ids_for({'date_range': 'yesterday'})
        self.assertIn(yest.id, y)
        self.assertNotIn(today.id, y)
        self.assertNotIn(old.id, y)

        seven = self._ids_for({'date_range': 'last_7d'})
        self.assertIn(today.id, seven)
        self.assertIn(yest.id, seven)
        self.assertNotIn(old.id, seven)

    def test_inbox_date_range_this_month(self):
        now = datetime.utcnow()
        recent = self.make_conversation()
        recent.sudo().write({'last_message_at': now})
        old = self.make_conversation()
        old.sudo().write({'last_message_at': now - timedelta(days=40)})
        month = self._ids_for({'date_range': 'this_month'})
        self.assertIn(recent.id, month)
        self.assertNotIn(old.id, month)

    def test_inbox_date_custom_range(self):
        now = datetime.utcnow()
        inside = self.make_conversation()
        inside.sudo().write({'last_message_at': now - timedelta(days=3)})
        outside = self.make_conversation()
        outside.sudo().write({'last_message_at': now - timedelta(days=10)})
        ids = self._ids_for({'date_range': 'custom',
                             'date_from': now - timedelta(days=5),
                             'date_to': now})
        self.assertIn(inside.id, ids)
        self.assertNotIn(outside.id, ids)

    # ── get_inbox: SLA bands + waiting clock ──────────────────────────────────

    def test_inbox_sla_bands_ok_and_warn(self):
        now = datetime.utcnow()
        ok = self.make_conversation()
        ok.sudo().write({'unread_count': 1, 'last_message_at': now})
        self.make_message(ok, occurred_at=now - timedelta(minutes=20))
        warn = self.make_conversation()
        warn.sudo().write({'unread_count': 1, 'last_message_at': now})
        self.make_message(warn, occurred_at=now - timedelta(minutes=120))
        rows = {r['id']: r for r in self.Conv.get_inbox({'ownership': 'all'})['rows']}
        self.assertEqual(rows[ok.id]['sla_band'], 'ok')          # <60m
        self.assertEqual(rows[warn.id]['sla_band'], 'warn')      # 60–240m

    def test_inbox_waiting_none_when_already_answered(self):
        """unread_count can lag reality — if our last reply is newer than the last
        inbound, nothing is awaiting a reply and waiting_minutes is None."""
        now = datetime.utcnow()
        conv = self.make_conversation()
        conv.sudo().write({'unread_count': 1, 'last_message_at': now})
        self.make_message(conv, direction='inbound', occurred_at=now - timedelta(hours=2))
        self.make_message(conv, direction='outbound', initiator='rm',
                          kind='freetext', occurred_at=now - timedelta(hours=1))
        row = next(r for r in self.Conv.get_inbox({'ownership': 'all'})['rows']
                   if r['id'] == conv.id)
        self.assertIsNone(row['waiting_minutes'])
        self.assertIsNone(row['sla_band'])

    def test_inbox_waiting_uses_oldest_unanswered_inbound(self):
        now = datetime.utcnow()
        conv = self.make_conversation()
        conv.sudo().write({'unread_count': 2, 'last_message_at': now})
        self.make_message(conv, direction='outbound', initiator='rm',
                          kind='freetext', occurred_at=now - timedelta(hours=5))
        self.make_message(conv, direction='inbound', occurred_at=now - timedelta(hours=3))
        self.make_message(conv, direction='inbound', occurred_at=now - timedelta(hours=1))
        row = next(r for r in self.Conv.get_inbox({'ownership': 'all'})['rows']
                   if r['id'] == conv.id)
        # Waiting since the FIRST unanswered inbound (~180m), not the latest (~60m).
        self.assertGreaterEqual(row['waiting_minutes'], 175)
        self.assertLess(row['waiting_minutes'], 200)
        self.assertEqual(row['sla_band'], 'warn')

    def test_inbox_waiting_ignores_system_messages(self):
        """A system event is not a reply — it must not stop the waiting clock."""
        now = datetime.utcnow()
        conv = self.make_conversation()
        conv.sudo().write({'unread_count': 1, 'last_message_at': now})
        self.make_message(conv, direction='outbound', initiator='rm',
                          kind='freetext', occurred_at=now - timedelta(hours=3))
        self.make_message(conv, direction='inbound', occurred_at=now - timedelta(hours=2))
        self.make_message(conv, direction='outbound', initiator='system',
                          kind='system', occurred_at=now - timedelta(hours=1))
        row = next(r for r in self.Conv.get_inbox({'ownership': 'all'})['rows']
                   if r['id'] == conv.id)
        self.assertGreaterEqual(row['waiting_minutes'], 115)    # still ~120m
        self.assertEqual(row['sla_band'], 'warn')

    # ── get_inbox: sort variants ──────────────────────────────────────────────

    def test_inbox_sort_unread_first(self):
        now = datetime.utcnow()
        many = self.make_conversation()
        many.sudo().write({'unread_count': 5, 'last_message_at': now - timedelta(hours=1)})
        few = self.make_conversation()
        few.sudo().write({'unread_count': 1, 'last_message_at': now})
        rows = self.Conv.get_inbox({'ownership': 'all', 'sort': 'unread'})['rows']
        order = [r['id'] for r in rows if r['id'] in (many.id, few.id)]
        self.assertEqual(order, [many.id, few.id])   # higher unread first

    # ── get_inbox: facet-count behaviour ──────────────────────────────────────

    def test_inbox_counts_rms_facet(self):
        a = self.make_user()
        b = self.make_user()
        for _ in range(2):
            self.make_conversation(assigned_user_id=a.id).sudo().write(
                {'last_message_at': datetime.utcnow()})
        self.make_conversation(assigned_user_id=b.id).sudo().write(
            {'last_message_at': datetime.utcnow()})
        self.make_conversation(assigned_user_id=False).sudo().write(
            {'last_message_at': datetime.utcnow()})
        rms = self.Conv.get_inbox({'ownership': 'all'})['counts']['rms']
        by_id = {r['id']: r for r in rms}
        self.assertEqual(by_id[a.id]['count'], 2)
        self.assertEqual(by_id[b.id]['count'], 1)
        self.assertEqual(by_id[a.id]['name'], a.name)
        order = [r['id'] for r in rms if r['id'] in (a.id, b.id)]
        self.assertEqual(order, [a.id, b.id])        # sorted by count desc

    def test_inbox_counts_closing_soon_consistent(self):
        now = datetime.utcnow()
        soon = self.make_conversation()
        soon.sudo().write({'window_expires_at': now + timedelta(hours=2),
                           'last_message_at': now})
        self.make_conversation().sudo().write(
            {'window_expires_at': now + timedelta(hours=10), 'last_message_at': now})
        data = self.Conv.get_inbox({'ownership': 'all'})
        soon_total = self.Conv.get_inbox(
            {'ownership': 'all', 'window': 'closing_soon'})['total']
        self.assertEqual(data['counts']['closing_soon'], soon_total)
        self.assertGreaterEqual(data['counts']['closing_soon'], 1)

    def test_inbox_counts_respect_active_filters(self):
        """Facet counts honour the current date + needs_reply scope (the exclude
        logic) — clicking a facet yields exactly its count."""
        now = datetime.utcnow()
        nr_today = self.make_conversation()
        nr_today.sudo().write({'unread_count': 1, 'last_message_at': now})
        answered_today = self.make_conversation()
        answered_today.sudo().write({'unread_count': 0, 'last_message_at': now})
        nr_old = self.make_conversation()
        nr_old.sudo().write({'unread_count': 1, 'last_message_at': now - timedelta(days=40)})

        data = self.Conv.get_inbox(
            {'ownership': 'all', 'date_range': 'today', 'needs_reply': True})
        self.assertEqual(data['counts']['needs_reply'], data['total'])
        self.assertEqual(data['counts']['ownership']['all'], data['total'])
        ids = {r['id'] for r in data['rows']}
        self.assertIn(nr_today.id, ids)
        self.assertNotIn(answered_today.id, ids)     # excluded by needs_reply
        self.assertNotIn(nr_old.id, ids)             # excluded by today

    def test_inbox_counts_scoped_for_rm(self):
        """An RM's facet counts are restricted to their own chats, like the list."""
        rm = self.make_user()
        other = self.make_user()
        self.make_conversation(assigned_user_id=rm.id).sudo().write(
            {'unread_count': 1, 'last_message_at': datetime.utcnow()})
        for _ in range(3):
            self.make_conversation(assigned_user_id=other.id).sudo().write(
                {'unread_count': 1, 'last_message_at': datetime.utcnow()})
        data = self.Conv.with_user(rm).get_inbox(
            {'ownership': 'all', 'needs_reply': True})
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['counts']['needs_reply'], 1)
        self.assertEqual(data['counts']['ownership']['all'], 1)
        self.assertFalse([r for r in data['counts']['rms'] if r['id'] == other.id])

    # ── get_inbox: search by lead name ────────────────────────────────────────

    def test_inbox_search_matches_lead_name(self):
        lead = self.make_lead(name='Zenobia Quicktest', phone='9123400077')
        conv = self.make_conversation(lead_id=lead.id)
        conv.sudo().write({'last_message_at': datetime.utcnow()})
        ids = self._ids_for({'search': 'Zenobia'})
        self.assertIn(conv.id, ids)

    # ── RM view-scoping: see chats for your inquiries, reply only if assigned ──

    def test_rm_sees_chat_for_inquiry_they_own_even_when_unassigned(self):
        """The reported bug: an RM owns the inquiry but the chat is unassigned/
        assigned to someone else, so the inbox came back empty. They must SEE it
        (view), while replying stays gated on assignment."""
        rm = self.make_user()
        lead = self.make_lead(user_id=rm.id)
        conv = self.make_conversation(assigned_user_id=False, lead_id=lead.id)
        conv.sudo().write({'last_message_at': datetime.utcnow()})

        as_rm = self.Conv.with_user(rm)
        rows = {r['id'] for r in as_rm.get_inbox({'ownership': 'all'})['rows']}
        self.assertIn(conv.id, rows, "RM cannot see a chat for an inquiry they own")

        # And they can OPEN it (list rows must be openable) ...
        thread = as_rm.get_thread(conv.id)
        self.assertNotIn('error', thread)
        self.assertEqual(thread['conversation']['id'], conv.id)
        # ... but NOT reply — it isn't assigned to them.
        self.assertFalse(thread['conversation']['can_send'])

    def test_rm_does_not_see_chat_for_someone_elses_inquiry(self):
        """The boundary still holds: no ownership + not assigned = not visible."""
        rm = self.make_user()
        other = self.make_user()
        lead = self.make_lead(user_id=other.id)
        conv = self.make_conversation(assigned_user_id=other.id, lead_id=lead.id)
        conv.sudo().write({'last_message_at': datetime.utcnow()})

        as_rm = self.Conv.with_user(rm)
        rows = {r['id'] for r in as_rm.get_inbox({'ownership': 'all'})['rows']}
        self.assertNotIn(conv.id, rows)
        self.assertIn('error', as_rm.get_thread(conv.id))

    def test_rm_sees_chat_where_they_own_a_tagged_message_inquiry(self):
        """Secondary inquiry: the RM owns a lead tagged on a message in a chat
        anchored to a different lead — the per-message path must surface it."""
        rm = self.make_user()
        other = self.make_user()
        anchor = self.make_lead(user_id=other.id)
        mine = self.make_lead(user_id=rm.id)
        conv = self.make_conversation(assigned_user_id=other.id, lead_id=anchor.id)
        self.make_message(conv, direction='inbound', kind='text_reply',
                          status='delivered', lead_id=mine.id)
        conv.sudo().write({'last_message_at': datetime.utcnow()})

        rows = {r['id'] for r in
                self.Conv.with_user(rm).get_inbox({'ownership': 'all'})['rows']}
        self.assertIn(conv.id, rows)
