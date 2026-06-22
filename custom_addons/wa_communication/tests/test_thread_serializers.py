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
