"""Outbound ``send_message`` — payload shape, 24h window gate, mark_as_read.

The ownership gate (assignee vs manager) is covered in ``test_assignment``; here
we focus on the *send mechanics*: what record gets queued, what payload is
published, and when the 24-hour free-text window blocks a send.
"""

from datetime import datetime, timedelta

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import WaTransactionCase


@tagged('post_install', '-at_install', 'wa_communication')
class TestSendMessage(WaTransactionCase):

    def _open_window(self, conv):
        """Push the 24h window open by setting a future expiry."""
        conv.sudo().write({
            'window_expires_at': datetime.utcnow() + timedelta(hours=5),
        })

    def _close_window(self, conv):
        """Force the window closed (past expiry)."""
        conv.sudo().write({
            'window_expires_at': datetime.utcnow() - timedelta(hours=1),
        })

    # ── Basic queue + publish ─────────────────────────────────────────────────

    def test_freetext_queues_message_and_publishes_send(self):
        conv = self.make_conversation()
        self._open_window(conv)
        with self.mock_pubsub() as published:
            msg = conv.send_message(body='Hello there', kind='freetext')

        self.assertEqual(msg.kind, 'freetext')
        self.assertEqual(msg.direction, 'outbound')
        self.assertEqual(msg.initiator, 'rm')
        self.assertEqual(msg.status, 'queued')
        self.assertEqual(msg.body, 'Hello there')
        # A correlation request_id must always be assigned.
        self.assertTrue(msg.request_id, "send must assign a request_id for correlation")

        self.assertTrue(published, "freetext send must publish a request")
        payload = published[-1].payload
        self.assertEqual(payload['request_type'], 'send')
        self.assertEqual(payload['kind'], 'freetext')
        self.assertEqual(payload['phone'], conv.phone_number)
        self.assertEqual(payload['message_text'], 'Hello there')
        self.assertEqual(payload['request_id'], msg.request_id)
        self.assertEqual(payload['rm_odoo_id'], self.env.uid)

    def test_freetext_send_updates_inbox_preview_and_timestamp(self):
        """Sending bumps the chat up the 'recent' list and previews the sent
        message — WhatsApp-style (your own reply is the last line)."""
        conv = self.make_conversation()
        self._open_window(conv)
        with self.mock_pubsub():
            conv.send_message(body='On my way to the site', kind='freetext')
        conv.invalidate_recordset()
        self.assertEqual(conv.last_message_preview, 'On my way to the site')
        self.assertTrue(conv.last_message_at, "send must set last_message_at for sorting")

    def test_media_send_forwards_media_fields(self):
        conv = self.make_conversation()
        self._open_window(conv)
        with self.mock_pubsub() as published:
            msg = conv.send_message(
                body='', kind='image',
                media_url='https://cdn.example/p.jpg',
                media_filename='p.jpg')

        self.assertEqual(msg.kind, 'image')
        self.assertEqual(msg.media_url, 'https://cdn.example/p.jpg')
        payload = published[-1].payload
        self.assertEqual(payload['kind'], 'image')
        self.assertEqual(payload['media_url'], 'https://cdn.example/p.jpg')
        self.assertEqual(payload['media_filename'], 'p.jpg')

    def test_template_send_carries_values(self):
        conv = self.make_conversation()
        # Window deliberately closed — templates must still go through.
        self._close_window(conv)
        with self.mock_pubsub() as published:
            msg = conv.send_message(
                kind='template', template_name='welcome',
                body_values=['Nirat', 'today'], header_values=['HDR'])

        self.assertEqual(msg.kind, 'template')
        self.assertEqual(msg.template_name, 'welcome')
        payload = published[-1].payload
        self.assertEqual(payload['template_name'], 'welcome')
        self.assertEqual(payload['body_values'], ['Nirat', 'today'])
        self.assertEqual(payload['header_values'], ['HDR'])

    # ── 24h window hard-block ─────────────────────────────────────────────────

    def test_freetext_blocked_when_window_closed(self):
        conv = self.make_conversation()
        self._close_window(conv)
        with self.assertRaises(UserError):
            conv.send_message(body='too late', kind='freetext')

    def test_media_blocked_when_window_closed(self):
        conv = self.make_conversation()
        self._close_window(conv)
        for kind in ('image', 'video', 'document', 'audio'):
            with self.assertRaises(UserError):
                conv.send_message(
                    body='', kind=kind, media_url='https://x/y')

    def test_no_window_means_closed(self):
        # A brand-new conversation has no window_expires_at → window is closed.
        conv = self.make_conversation()
        self.assertFalse(conv.window_expires_at)
        with self.assertRaises(UserError):
            conv.send_message(body='hi', kind='freetext')

    def test_template_allowed_when_window_closed(self):
        conv = self.make_conversation()
        self._close_window(conv)
        with self.mock_pubsub():
            msg = conv.send_message(kind='template', template_name='t')
        self.assertEqual(msg.status, 'queued')

    # ── Workflow / system initiator bypasses both gates ───────────────────────

    def test_workflow_initiator_bypasses_window_and_ownership(self):
        # Assigned to someone else AND window closed: a workflow send still works.
        other = self.make_user()
        conv = self.make_conversation(assigned_user_id=other.id)
        self._close_window(conv)
        with self.mock_pubsub() as published:
            msg = conv.send_message(
                body='', kind='template', template_name='nudge',
                initiator='workflow', workflow_slug='reengage', step_id='s1')

        self.assertEqual(msg.initiator, 'workflow')
        # Workflow sends carry no RM sender name.
        self.assertFalse(msg.sender_name)
        self.assertTrue(published)

    # ── Guards ────────────────────────────────────────────────────────────────

    def test_outbound_message_writes_event_log(self):
        conv = self.make_conversation()
        self._open_window(conv)
        with self.mock_pubsub():
            conv.send_message(body='log me', kind='freetext')
        log = self.env['wa.event.log'].sudo().search(
            [('event_type', '=', 'wa_message_outbound')],
            order='create_date desc', limit=1)
        self.assertTrue(log, "an outbound send must leave an audit log row")
        self.assertEqual(log.direction, 'outbound')

    # ── send_list_message ─────────────────────────────────────────────────────

    def _sections(self):
        return [{'title': 'Homes', 'rows': [
            {'id': 'r1', 'title': '2 BHK', 'description': 'Ready to move'},
            {'title': '3 BHK'},  # no id → auto-filled
        ]}]

    def test_list_message_queues_and_publishes(self):
        conv = self.make_conversation()
        self._open_window(conv)
        with self.mock_pubsub() as published:
            msg = conv.send_list_message(
                body='Pick a home type', button_text='View options',
                sections=self._sections())

        self.assertEqual(msg.kind, 'list')
        self.assertEqual(msg.direction, 'outbound')
        self.assertEqual(msg.status, 'queued')
        self.assertEqual(msg.body, 'Pick a home type')
        # list_payload stores button + normalized sections (row id auto-filled).
        import json
        payload_stored = json.loads(msg.list_payload)
        self.assertEqual(payload_stored['button'], 'View options')
        rows = payload_stored['sections'][0]['rows']
        self.assertEqual(rows[0]['id'], 'r1')
        self.assertTrue(rows[1]['id'], "missing row id must be auto-filled")

        payload = published[-1].payload
        self.assertEqual(payload['request_type'], 'send')
        self.assertEqual(payload['kind'], 'list')
        self.assertEqual(payload['message_text'], 'Pick a home type')
        self.assertEqual(payload['list_button_text'], 'View options')
        self.assertEqual(payload['list_sections'][0]['title'], 'Homes')

    def test_list_message_blocked_when_window_closed(self):
        conv = self.make_conversation()
        self._close_window(conv)
        with self.assertRaises(UserError):
            conv.send_list_message(body='hi', button_text='Menu',
                                   sections=self._sections())

    def test_list_message_empty_sections_raises(self):
        conv = self.make_conversation()
        self._open_window(conv)
        with self.assertRaises(UserError):
            conv.send_list_message(body='hi', button_text='Menu',
                                   sections=[{'title': 'S', 'rows': [{'title': '  '}]}])

    def test_list_message_over_10_rows_raises(self):
        conv = self.make_conversation()
        self._open_window(conv)
        rows = [{'title': f'row {i}'} for i in range(11)]
        with self.assertRaises(UserError):
            conv.send_list_message(body='hi', button_text='Menu',
                                   sections=[{'title': 'S', 'rows': rows}])

    def test_list_message_serializes_into_thread(self):
        conv = self.make_conversation()
        self._open_window(conv)
        with self.mock_pubsub():
            conv.send_list_message(body='menu', button_text='Open',
                                   sections=self._sections())
        thread = conv.get_thread(conv.id)
        list_row = next(m for m in thread['messages'] if m['kind'] == 'list')
        self.assertEqual(list_row['list_payload']['button'], 'Open')
        self.assertEqual(list_row['list_payload']['sections'][0]['rows'][0]['title'],
                         '2 BHK')

    # ── mark_as_read ──────────────────────────────────────────────────────────

    def test_mark_as_read_resets_unread(self):
        conv = self.make_conversation()
        conv.sudo().write({'unread_count': 4})
        conv.mark_as_read()
        self.assertEqual(conv.unread_count, 0)
