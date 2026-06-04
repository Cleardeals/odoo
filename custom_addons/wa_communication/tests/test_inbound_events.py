"""OdooWaEvent inbound handlers — the main production traffic path.

The WA platform's ``odoo-bridge`` publishes ``OdooWaEvent`` payloads (detected
by the ``event_type`` key) that drive status transitions and inbound message
creation.  These tests call :meth:`_process_odoo_wa_event` directly so we cover
the dispatch table, the per-handler DB effects, dedup, and error isolation
without standing up the HTTP layer.
"""

from datetime import datetime, timedelta

from odoo.tests import tagged

from .common import WaTransactionCase


@tagged('post_install', '-at_install', 'wa_communication')
class TestInboundEvents(WaTransactionCase):

    def _process(self, event, msg_id='pmsg-1'):
        """Run an OdooWaEvent through the public dispatcher."""
        self.Conv._process_odoo_wa_event(event, msg_id)

    def _queued_rm_msg(self, conv, request_id, **vals):
        base = {
            'conversation_id': conv.id,
            'direction': 'outbound',
            'initiator': 'rm',
            'kind': 'freetext',
            'request_id': request_id,
            'status': 'queued',
            'occurred_at': '2026-01-01 09:00:00',
        }
        base.update(vals)
        return self.Msg.sudo().create(base)

    # ── Dispatch + audit logging ──────────────────────────────────────────────

    def test_known_event_writes_audit_log(self):
        conv = self.make_conversation()
        self._process({
            'event_type': 'message_read',
            'phone': conv.phone_number,
            'wa_message_id': 'nope',
        }, 'audit-1')
        log = self.env['wa.event.log'].sudo().search(
            [('event_type', '=', 'odoo_wa_message_read')],
            order='create_date desc', limit=1)
        self.assertTrue(log, "every OdooWaEvent must leave an audit trail")

    def test_unknown_event_type_is_logged_not_raised(self):
        # Must not raise, and should log an 'unknown' audit row.
        self._process({'event_type': 'totally_made_up'}, 'unk-1')
        log = self.env['wa.event.log'].sudo().search(
            [('event_type', '=', 'odoo_wa_totally_made_up')],
            order='create_date desc', limit=1)
        self.assertTrue(log)

    def test_empty_event_type_logged_as_unknown(self):
        self._process({'event_type': ''}, 'unk-2')
        log = self.env['wa.event.log'].sudo().search(
            [('event_type', '=', 'odoo_wa_unknown')],
            order='create_date desc', limit=1)
        self.assertTrue(log)

    # ── message_sent ──────────────────────────────────────────────────────────

    def test_message_sent_updates_queued_rm_message(self):
        conv = self.make_conversation()
        msg = self._queued_rm_msg(conv, 'req-rm-1')
        self._process({
            'event_type': 'message_sent',
            'phone': conv.phone_number,
            'request_id': 'req-rm-1',
            'wa_message_id': 'wamid.sent1',
            'occurred_at': '2026-01-02T10:00:00Z',
        })
        msg.invalidate_recordset()
        self.assertEqual(msg.status, 'sent')
        self.assertEqual(msg.wa_message_id, 'wamid.sent1')

    def test_message_sent_creates_workflow_message_when_none_exists(self):
        conv = self.make_conversation()
        before = self.Msg.sudo().search_count([('conversation_id', '=', conv.id)])
        self._process({
            'event_type': 'message_sent',
            'phone': conv.phone_number,
            'request_id': 'wf-req-1',
            'wa_message_id': 'wamid.wf1',
            'workflow_slug': 'welcome_flow',
            'step_id': 'step-1',
            'template_name': 'welcome',
            'occurred_at': '2026-01-02T10:00:00Z',
        })
        msgs = self.Msg.sudo().search([('conversation_id', '=', conv.id)])
        self.assertEqual(len(msgs) - before, 1)
        created = msgs.filtered(lambda m: m.wa_message_id == 'wamid.wf1')
        self.assertEqual(created.initiator, 'workflow')
        self.assertEqual(created.kind, 'template')
        self.assertEqual(created.workflow_slug, 'welcome_flow')

    # ── message_delivered / read / failed ─────────────────────────────────────

    def test_message_delivered_sets_status_cost_and_timestamp(self):
        conv = self.make_conversation()
        msg = self._queued_rm_msg(conv, 'req-d', wa_message_id='wamid.d1',
                                  status='sent')
        self._process({
            'event_type': 'message_delivered',
            'wa_message_id': 'wamid.d1',
            'cost_inr': 0.65,
            'occurred_at': '2026-01-02T11:00:00Z',
        })
        msg.invalidate_recordset()
        self.assertEqual(msg.status, 'delivered')
        self.assertEqual(msg.cost_inr, 0.65)
        self.assertTrue(msg.delivered_at)

    def test_message_read_sets_status_and_seen_at(self):
        conv = self.make_conversation()
        msg = self._queued_rm_msg(conv, 'req-r', wa_message_id='wamid.r1',
                                  status='delivered')
        self._process({
            'event_type': 'message_read',
            'wa_message_id': 'wamid.r1',
            'occurred_at': '2026-01-02T12:00:00Z',
        })
        msg.invalidate_recordset()
        self.assertEqual(msg.status, 'read')
        self.assertTrue(msg.seen_at)

    def test_message_failed_maps_error_code_to_status(self):
        conv = self.make_conversation()
        msg = self._queued_rm_msg(conv, 'req-f', wa_message_id='wamid.f1',
                                  status='sent')
        self._process({
            'event_type': 'message_failed',
            'wa_message_id': 'wamid.f1',
            'failure_code': 131026,
            'failure_reason': 'recipient blocked business',
        })
        msg.invalidate_recordset()
        self.assertEqual(msg.status, 'meta_blocked')

    def test_message_failed_unknown_code_is_generic_failed(self):
        conv = self.make_conversation()
        msg = self._queued_rm_msg(conv, 'req-f2', wa_message_id='wamid.f2',
                                  status='sent')
        self._process({
            'event_type': 'message_failed',
            'wa_message_id': 'wamid.f2',
            'failure_code': 999999,
        })
        msg.invalidate_recordset()
        self.assertEqual(msg.status, 'failed')

    # ── lead_replied ──────────────────────────────────────────────────────────

    def test_lead_replied_creates_inbound_and_increments_unread(self):
        conv = self.make_conversation()
        start_unread = conv.unread_count
        self._process({
            'event_type': 'lead_replied',
            'phone': conv.phone_number,
            'wa_message_id': 'wamid.reply1',
            'message_text': 'Yes I am interested',
            'occurred_at': '2026-03-01T08:00:00Z',
        })
        conv.invalidate_recordset()
        reply = self.Msg.sudo().search([('wa_message_id', '=', 'wamid.reply1')])
        self.assertEqual(len(reply), 1)
        self.assertEqual(reply.direction, 'inbound')
        self.assertEqual(reply.body, 'Yes I am interested')
        self.assertEqual(conv.unread_count, start_unread + 1)
        # Window opens 24h from the reply when the platform doesn't supply one.
        self.assertTrue(conv.window_expires_at)
        expected = datetime(2026, 3, 1, 8, 0, 0) + timedelta(hours=24)
        self.assertEqual(conv.window_expires_at, expected)

    def test_lead_replied_dedup_by_wa_message_id(self):
        conv = self.make_conversation()
        event = {
            'event_type': 'lead_replied',
            'phone': conv.phone_number,
            'wa_message_id': 'wamid.dup',
            'message_text': 'hi',
            'occurred_at': '2026-03-01T08:00:00Z',
        }
        self._process(event)
        self._process(event)  # redelivery
        count = self.Msg.sudo().search_count([('wa_message_id', '=', 'wamid.dup')])
        self.assertEqual(count, 1)

    def test_lead_replied_button_collision_stores_synthetic_id_and_quotes(self):
        """A button tap reuses the outbound template id; we must still record it."""
        conv = self.make_conversation()
        # Outbound template the buyer is replying to.
        tpl = self.Msg.sudo().create({
            'conversation_id': conv.id,
            'direction': 'outbound',
            'initiator': 'workflow',
            'kind': 'template',
            'template_name': 'site_visit',
            'wa_message_id': 'wamid.tpl',
            'status': 'delivered',
            'occurred_at': '2026-03-01 07:00:00',
        })
        self._process({
            'event_type': 'lead_replied',
            'phone': conv.phone_number,
            'wa_message_id': 'wamid.tpl',   # collides with the outbound id
            'button_reply_id': 'Yes',
            'message_text': 'Yes',
            'occurred_at': '2026-03-01T08:00:00Z',
        })
        reply = self.Msg.sudo().search([
            ('conversation_id', '=', conv.id),
            ('direction', '=', 'inbound'),
        ])
        self.assertEqual(len(reply), 1, "button reply must be recorded, not dropped")
        self.assertTrue(reply.wa_message_id.startswith('wamid.tpl:r:'))
        self.assertEqual(reply.quoted_message_id, tpl,
                         "reply should quote the outbound template it answered")

    def test_lead_replied_uses_platform_window_expiry_when_supplied(self):
        conv = self.make_conversation()
        self._process({
            'event_type': 'lead_replied',
            'phone': conv.phone_number,
            'wa_message_id': 'wamid.win',
            'message_text': 'hi',
            'occurred_at': '2026-03-01T08:00:00Z',
            'window_expires_at': '2026-03-05T00:00:00Z',
        })
        conv.invalidate_recordset()
        self.assertEqual(conv.window_expires_at, datetime(2026, 3, 5, 0, 0, 0))
