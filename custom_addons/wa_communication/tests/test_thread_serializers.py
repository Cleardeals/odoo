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

    # ── get_inbox ─────────────────────────────────────────────────────────────

    def test_inbox_status_filter_needs_reply(self):
        c1 = self.make_conversation()
        c1.sudo().write({'unread_count': 2,
                         'last_message_at': datetime.utcnow()})
        c2 = self.make_conversation()
        c2.sudo().write({'unread_count': 0,
                         'last_message_at': datetime.utcnow()})
        rows = self.Conv.get_inbox({'status': 'needs_reply'})
        ids = {r['id'] for r in rows}
        self.assertIn(c1.id, ids)
        self.assertNotIn(c2.id, ids)

    def test_inbox_search_matches_phone(self):
        conv = self.make_conversation(phone_number='919812345678')
        conv.sudo().write({'last_message_at': datetime.utcnow()})
        rows = self.Conv.get_inbox({'search': '9812345678'})
        self.assertIn(conv.id, {r['id'] for r in rows})

    def test_inbox_assigned_rm_filter(self):
        other = self.make_user()
        mine = self.make_conversation()
        theirs = self.make_conversation(assigned_user_id=other.id)
        for c in (mine, theirs):
            c.sudo().write({'last_message_at': datetime.utcnow()})
        rows = self.Conv.get_inbox({'assigned_rm': other.id})
        ids = {r['id'] for r in rows}
        self.assertIn(theirs.id, ids)
        self.assertNotIn(mine.id, ids)

    def test_inbox_row_carries_gating_fields(self):
        conv = self.make_conversation()
        conv.sudo().write({'last_message_at': datetime.utcnow()})
        row = next(r for r in self.Conv.get_inbox({}) if r['id'] == conv.id)
        self.assertIn('can_send', row)
        self.assertIn('assignment_pending', row)
        self.assertIn('window_state', row)
        self.assertTrue(row['can_send'])  # assigned to me by default

    # ── get_inbox_counts ──────────────────────────────────────────────────────

    def test_inbox_counts_structure(self):
        counts = self.Conv.get_inbox_counts()
        self.assertIn('status', counts)
        self.assertIn('assigned_rms', counts)
        self.assertEqual(
            set(counts['status'].keys()), {'needs_reply', 'active', 'completed'})

    # ── _inbox_conv_status ────────────────────────────────────────────────────

    def test_inbox_conv_status_logic(self):
        conv = self.make_conversation()
        conv.unread_count = 1
        self.assertEqual(self.Conv._inbox_conv_status(conv, True), 'needs_reply')
        conv.unread_count = 0
        self.assertEqual(self.Conv._inbox_conv_status(conv, True), 'active')
        self.assertEqual(self.Conv._inbox_conv_status(conv, False), 'completed')
