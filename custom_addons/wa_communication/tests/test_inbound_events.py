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

    def test_message_sent_stores_header_media_on_workflow_message(self):
        """A media-header template send (workflow) lands its header image/video on
        the new wa.message so the bubble can render it above the body."""
        conv = self.make_conversation()
        self._process({
            'event_type': 'message_sent',
            'phone': conv.phone_number,
            'request_id': 'wf-hdr-1',
            'wa_message_id': 'wamid.hdr1',
            'workflow_slug': 'initial_nudge_property_v1',
            'step_id': 'msg_2',
            'template_name': 'initial_nudge_v1_msg_2',
            'rendered_body': 'Property details…',
            'header_media_url': 'https://cdn/p/hero.jpg',
            'header_media_type': 'image',
            'occurred_at': '2026-01-02T10:00:00Z',
        })
        created = self.Msg.sudo().search(
            [('wa_message_id', '=', 'wamid.hdr1')], limit=1)
        self.assertEqual(created.template_header_media_url, 'https://cdn/p/hero.jpg')
        self.assertEqual(created.template_header_media_type, 'image')

    def test_message_sent_backfills_header_media_onto_queued_rm_message(self):
        """The rendered message_sent (from the Interakt webhook) enriches a row that
        already exists, filling its header media without clobbering."""
        conv = self.make_conversation()
        msg = self._queued_rm_msg(conv, 'req-hdr-2')
        self._process({
            'event_type': 'message_sent',
            'phone': conv.phone_number,
            'request_id': 'req-hdr-2',
            'wa_message_id': 'wamid.hdr2',
            'rendered_body': 'Body',
            'header_media_url': 'https://cdn/x/promo.mp4',
            'header_media_type': 'video',
            'occurred_at': '2026-01-02T10:00:00Z',
        })
        msg.invalidate_recordset()
        self.assertEqual(msg.template_header_media_url, 'https://cdn/x/promo.mp4')
        self.assertEqual(msg.template_header_media_type, 'video')

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

    def test_message_delivered_stores_full_cost_breakdown(self):
        """The delivered event carries the WhatsApp/markup/total split — all three
        must land on the message so the detail panel shows them."""
        conv = self.make_conversation()
        msg = self._queued_rm_msg(conv, 'req-bd', wa_message_id='wamid.bd',
                                  status='sent')
        self._process({
            'event_type': 'message_delivered',
            'wa_message_id': 'wamid.bd',
            'cost_inr': 0.94941,
            'cost_whatsapp_inr': 0.86,
            'cost_interakt_markup': 0.09,
            'occurred_at': '2026-01-02T11:00:00Z',
        })
        msg.invalidate_recordset()
        self.assertAlmostEqual(msg.cost_inr, 0.94941, places=4)
        self.assertAlmostEqual(msg.cost_whatsapp_inr, 0.86, places=4)
        self.assertAlmostEqual(msg.cost_interakt_markup, 0.09, places=4)

    def test_message_read_captures_cost_when_delivered_missed(self):
        """Fallback: if the delivered event was lost, cost arriving on the read
        event is captured (the platform forwards the effective cost)."""
        conv = self.make_conversation()
        msg = self._queued_rm_msg(conv, 'req-rc', wa_message_id='wamid.rc',
                                  status='sent')
        self._process({
            'event_type': 'message_read',
            'wa_message_id': 'wamid.rc',
            'cost_inr': 0.94941,
            'cost_whatsapp_inr': 0.86,
            'cost_interakt_markup': 0.09,
            'occurred_at': '2026-01-02T12:00:00Z',
        })
        msg.invalidate_recordset()
        self.assertEqual(msg.status, 'read')
        self.assertAlmostEqual(msg.cost_inr, 0.94941, places=4)
        self.assertAlmostEqual(msg.cost_whatsapp_inr, 0.86, places=4)

    def test_message_read_does_not_overwrite_existing_cost(self):
        """A read event must never clobber a cost the delivered event already set."""
        conv = self.make_conversation()
        msg = self._queued_rm_msg(conv, 'req-rc2', wa_message_id='wamid.rc2',
                                  status='delivered')
        msg.write({'cost_inr': 0.94941, 'cost_whatsapp_inr': 0.86,
                   'cost_interakt_markup': 0.09})
        self._process({
            'event_type': 'message_read',
            'wa_message_id': 'wamid.rc2',
            'cost_inr': 5.0,   # a bogus later value must be ignored
            'occurred_at': '2026-01-02T12:00:00Z',
        })
        msg.invalidate_recordset()
        self.assertAlmostEqual(msg.cost_inr, 0.94941, places=4)

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

    # ── status monotonicity (out-of-order / redelivered webhooks) ─────────────

    def test_read_status_not_downgraded_by_late_delivered(self):
        """A delivered event arriving AFTER read must not revert the blue tick."""
        conv = self.make_conversation()
        msg = self._queued_rm_msg(conv, 'req-mono1', wa_message_id='wamid.mono1',
                                  status='sent')
        # read first…
        self._process({
            'event_type': 'message_read',
            'wa_message_id': 'wamid.mono1',
            'occurred_at': '2026-01-02T12:00:00Z',
        })
        # …then a late/redelivered delivered.
        self._process({
            'event_type': 'message_delivered',
            'wa_message_id': 'wamid.mono1',
            'cost_inr': 0.65,
            'occurred_at': '2026-01-02T11:00:00Z',
        })
        msg.invalidate_recordset()
        self.assertEqual(msg.status, 'read',
                         "status must stay 'read' — never downgrade to delivered")
        self.assertTrue(msg.seen_at, "seen_at stays set")
        self.assertEqual(msg.cost_inr, 0.65,
                         "delivered metadata is still recorded")

    def test_delivered_status_not_downgraded_by_redelivered_sent(self):
        """A redelivered message_sent must not knock a delivered row back to sent."""
        conv = self.make_conversation()
        msg = self._queued_rm_msg(conv, 'req-mono2', wa_message_id='wamid.mono2',
                                  status='sent')
        self._process({
            'event_type': 'message_delivered',
            'wa_message_id': 'wamid.mono2',
            'occurred_at': '2026-01-02T11:00:00Z',
        })
        # Pub/Sub redelivers the earlier message_sent.
        self._process({
            'event_type': 'message_sent',
            'phone': conv.phone_number,
            'request_id': 'req-mono2',
            'wa_message_id': 'wamid.mono2',
            'occurred_at': '2026-01-02T10:00:00Z',
        })
        msg.invalidate_recordset()
        self.assertEqual(msg.status, 'delivered',
                         "status must stay 'delivered' — never downgrade to sent")

    # ── out-of-order receipts BEFORE message_sent (workflow sends) ─────────────

    def test_workflow_delivered_before_sent_creates_row_and_keeps_cost(self):
        """A workflow send's delivered receipt that beats message_sent must NOT
        be dropped — a row is created carrying delivered + cost, and the later
        message_sent enriches it in place (no duplicate, no downgrade)."""
        conv = self.make_conversation()
        before = self.Msg.sudo().search_count([('conversation_id', '=', conv.id)])
        # delivered arrives first (only workflow context: enrollment_id/step_id)
        self._process({
            'event_type': 'message_delivered',
            'phone': conv.phone_number,
            'wa_message_id': 'wamid.ooo1',
            'enrollment_id': 'enr-ooo1',
            'step_id': 'step-1',
            'cost_inr': 0.72,
            'occurred_at': '2026-01-02T11:00:00Z',
        })
        created = self.Msg.sudo().search([('wa_message_id', '=', 'wamid.ooo1')])
        self.assertEqual(len(created), 1, "delivered must create the row")
        self.assertEqual(created.status, 'delivered')
        self.assertEqual(created.cost_inr, 0.72)
        self.assertEqual(created.direction, 'outbound')
        # now the delayed message_sent arrives — must enrich, not duplicate
        self._process({
            'event_type': 'message_sent',
            'phone': conv.phone_number,
            'wa_message_id': 'wamid.ooo1',
            'enrollment_id': 'enr-ooo1',
            'step_id': 'step-1',
            'workflow_slug': 'welcome_flow',
            'template_name': 'welcome',
            'occurred_at': '2026-01-02T10:00:00Z',
        })
        rows = self.Msg.sudo().search([('wa_message_id', '=', 'wamid.ooo1')])
        self.assertEqual(len(rows), 1, "message_sent must enrich, not duplicate")
        self.assertEqual(rows.status, 'delivered',
                         "status must not downgrade to sent")
        self.assertEqual(rows.workflow_slug, 'welcome_flow',
                         "sent enriches the stub with workflow context")
        self.assertEqual(
            self.Msg.sudo().search_count([('conversation_id', '=', conv.id)]),
            before + 1, "exactly one row for the whole sent/delivered pair")

    def test_workflow_read_before_sent_creates_row_with_seen_at(self):
        conv = self.make_conversation()
        self._process({
            'event_type': 'message_read',
            'phone': conv.phone_number,
            'wa_message_id': 'wamid.ooo2',
            'enrollment_id': 'enr-ooo2',
            'occurred_at': '2026-01-02T12:00:00Z',
        })
        created = self.Msg.sudo().search([('wa_message_id', '=', 'wamid.ooo2')])
        self.assertEqual(len(created), 1)
        self.assertEqual(created.status, 'read')
        self.assertTrue(created.seen_at)

    def test_delivered_before_sent_without_workflow_context_is_not_stubbed(self):
        """An RM-manual send owns a queued row keyed by request_id that a
        delivered receipt (keyed by wa_message_id only) cannot match yet.  We
        must NOT create a stub for it — that would duplicate the RM message.
        With no enrollment/step context, the receipt is dropped (logged), not
        materialised into a phantom row."""
        conv = self.make_conversation()
        before = self.Msg.sudo().search_count([('conversation_id', '=', conv.id)])
        self._process({
            'event_type': 'message_delivered',
            'phone': conv.phone_number,
            'wa_message_id': 'wamid.rm-ooo',
            'cost_inr': 0.65,
            'occurred_at': '2026-01-02T11:00:00Z',
        })
        self.assertEqual(
            self.Msg.sudo().search_count([('conversation_id', '=', conv.id)]),
            before, "no phantom row for an RM send without workflow context")

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

    def test_lead_replied_notifies_assigned_rm_not_routed_rm(self):
        """A reply on an assigned chat must notify the assignee, not the lead RM."""
        assignee = self.make_user()
        routed = self.make_user()
        conv = self.make_conversation(assigned_user_id=assignee.id)
        self._process({
            'event_type': 'lead_replied',
            'phone': conv.phone_number,
            'wa_message_id': 'wamid.assigned-notif',
            'message_text': 'Hello there',
            'occurred_at': '2026-03-01T08:00:00Z',
            'rm_odoo_id': routed.id,
        })
        Notif = self.env['cleardeals.notification'].sudo()
        recipients = Notif.search(
            [('notif_type', '=', 'lead_replied')]).mapped('user_id').ids
        self.assertIn(assignee.id, recipients,
                      "the assigned RM must receive the reply notification")
        self.assertNotIn(routed.id, recipients,
                         "the lead's routed RM must NOT receive it when assigned")

    def test_lead_replied_falls_back_to_routed_rm_when_unassigned(self):
        """An unassigned chat still notifies the platform-routed lead RM."""
        routed = self.make_user()
        conv = self.make_conversation(assigned_user_id=False)
        self._process({
            'event_type': 'lead_replied',
            'phone': conv.phone_number,
            'wa_message_id': 'wamid.unassigned-notif',
            'message_text': 'Anyone there?',
            'occurred_at': '2026-03-01T08:00:00Z',
            'rm_odoo_id': routed.id,
        })
        Notif = self.env['cleardeals.notification'].sudo()
        recipients = Notif.search(
            [('notif_type', '=', 'lead_replied')]).mapped('user_id').ids
        self.assertIn(routed.id, recipients,
                      "unassigned chats fall back to the routed lead RM")

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

    def test_lead_replied_companion_text_does_not_duplicate_button(self):
        """One tap → button click + companion text must record ONE inbound bubble.

        The button click reuses the template's id; the companion message_received
        carries its own id but the SAME message_context (source_message_id =
        template).  When the platform's click-shadow misses (redelivery / batch),
        both reach Odoo — the second must be deduped against the first.
        """
        conv = self.make_conversation()
        tpl = self.Msg.sudo().create({
            'conversation_id': conv.id,
            'direction': 'outbound',
            'initiator': 'workflow',
            'kind': 'template',
            'template_name': 'site_visit',
            'wa_message_id': 'wamid.tpl2',
            'status': 'delivered',
            'occurred_at': '2026-03-01 07:00:00',
        })
        # 1) Button click — id collides with the outbound template.
        self._process({
            'event_type': 'lead_replied',
            'phone': conv.phone_number,
            'wa_message_id': 'wamid.tpl2',
            'button_reply_id': 'Schedule Visit',
            'message_text': 'Schedule Visit',
            'occurred_at': '2026-03-01T08:00:00Z',
        }, msg_id='tap-click')
        # 2) Companion text — its OWN id, but references the same template.
        self._process({
            'event_type': 'lead_replied',
            'phone': conv.phone_number,
            'wa_message_id': 'wamid.companion-text',
            'source_message_id': 'wamid.tpl2',
            'message_text': 'Schedule Visit',
            'occurred_at': '2026-03-01T08:00:01Z',
        }, msg_id='tap-companion')

        inbound = self.Msg.sudo().search([
            ('conversation_id', '=', conv.id),
            ('direction', '=', 'inbound'),
        ])
        self.assertEqual(len(inbound), 1,
                         "button click + companion text = ONE inbound bubble")
        self.assertEqual(inbound.quoted_message_id, tpl)

    def test_lead_replied_companion_dedup_is_order_independent(self):
        """Companion dedup must hold when the TEXT arrives before the CLICK.

        Interakt does not guarantee ordering — the message_received companion can
        reach Odoo before its button click.  Either ordering must still yield ONE
        bubble: whichever half lands first is recorded, the second (its
        complementary kind) is dropped.
        """
        conv = self.make_conversation()
        tpl = self.Msg.sudo().create({
            'conversation_id': conv.id,
            'direction': 'outbound',
            'initiator': 'workflow',
            'kind': 'template',
            'template_name': 'site_visit',
            'wa_message_id': 'wamid.tplX',
            'status': 'delivered',
            'occurred_at': '2026-03-01 07:00:00',
        })
        # 1) Companion TEXT arrives FIRST (its own id, references the template).
        self._process({
            'event_type': 'lead_replied',
            'phone': conv.phone_number,
            'wa_message_id': 'wamid.companion-first',
            'source_message_id': 'wamid.tplX',
            'message_text': 'Schedule Visit',   # no button_reply_id → text_reply
            'occurred_at': '2026-03-01T08:00:00Z',
        }, msg_id='text-first')
        # 2) Button CLICK arrives SECOND (id collides with the template).
        self._process({
            'event_type': 'lead_replied',
            'phone': conv.phone_number,
            'wa_message_id': 'wamid.tplX',
            'button_reply_id': 'Schedule Visit',
            'message_text': 'Schedule Visit',
            'occurred_at': '2026-03-01T08:00:01Z',
        }, msg_id='click-second')

        inbound = self.Msg.sudo().search([
            ('conversation_id', '=', conv.id),
            ('direction', '=', 'inbound'),
        ])
        self.assertEqual(len(inbound), 1,
                         "text-first then click = ONE bubble (order-independent)")
        self.assertEqual(inbound.quoted_message_id, tpl)

    def test_lead_replied_repeated_identical_swipe_reply_is_not_dropped(self):
        """Regression: two genuine swipe-replies with the SAME body to the SAME
        quoted message must BOTH be recorded — they are not a button companion.

        A real quick-reply companion is one button_reply (the click) + one
        text_reply (the message_received): complementary kinds.  Two genuine
        swipe text-replies are BOTH text_reply.  The companion dedup used to key
        only on (quoted source, body), so it could not tell them apart and
        silently dropped the second identical swipe-reply — a real buyer message
        that never reached Odoo.  Reported live: replying "Hi" to an old message
        you had already replied "Hi" to was rejected.
        """
        conv = self.make_conversation()
        old = self.Msg.sudo().create({
            'conversation_id': conv.id,
            'direction': 'outbound',
            'initiator': 'rm',
            'kind': 'freetext',
            'body': 'Are you still interested?',
            'wa_message_id': 'wamid.old',
            'status': 'delivered',
            'occurred_at': '2026-03-01 07:00:00',
        })
        for i, mid in enumerate(('r1', 'r2'), start=1):
            self._process({
                'event_type': 'lead_replied',
                'phone': conv.phone_number,
                'wa_message_id': 'wamid.%s' % mid,   # each reply has its OWN real id
                'source_message_id': 'wamid.old',    # swipe-reply quotes the old msg
                'message_text': 'Hi',
                # NO button_reply_id → genuine text swipe-reply (kind=text_reply)
                'occurred_at': '2026-03-01T08:0%d:00Z' % i,
            }, msg_id='swipe-%s' % mid)

        inbound = self.Msg.sudo().search([
            ('conversation_id', '=', conv.id),
            ('direction', '=', 'inbound'),
        ])
        self.assertEqual(
            len(inbound), 2,
            "both identical swipe-replies must be recorded — a repeated buyer "
            "message must never be silently dropped",
        )
        self.assertTrue(all(m.kind == 'text_reply' for m in inbound))
        self.assertTrue(all(m.quoted_message_id == old for m in inbound))

    def test_lead_replied_multiple_buttons_all_tapped_interleaved(self):
        """Lead taps 3 different quick-reply buttons on one template.

        That is 6 webhooks — a button_reply click + a text_reply companion for
        each of A/B/C — delivered in an arbitrary, interleaved order.  Dedup is
        scoped by body, so the three buttons never cross-collapse, and each
        (click, companion) pair collapses regardless of order → exactly THREE
        bubbles, one per button the lead actually pressed.
        """
        conv = self.make_conversation()
        self.Msg.sudo().create({
            'conversation_id': conv.id,
            'direction': 'outbound',
            'initiator': 'workflow',
            'kind': 'template',
            'template_name': 'multi_cta',
            'wa_message_id': 'wamid.multi',
            'status': 'delivered',
            'occurred_at': '2026-03-01 07:00:00',
        })

        def click(label):
            return {
                'event_type': 'lead_replied', 'phone': conv.phone_number,
                'wa_message_id': 'wamid.multi', 'button_reply_id': label,
                'message_text': label, 'occurred_at': '2026-03-01T08:00:00Z',
            }

        def companion(label, mid):
            return {
                'event_type': 'lead_replied', 'phone': conv.phone_number,
                'wa_message_id': 'wamid.companion-%s' % mid,
                'source_message_id': 'wamid.multi', 'message_text': label,
                'occurred_at': '2026-03-01T08:00:01Z',
            }

        # Deliberately interleaved / out-of-order across the three buttons.
        sequence = [
            (companion('B', 'cb'), 'cb'), (click('A'), 'ka'), (click('C'), 'kc'),
            (companion('A', 'ca'), 'ca'), (companion('C', 'cc'), 'cc'), (click('B'), 'kb'),
        ]
        for event, mid in sequence:
            self._process(event, msg_id='multi-%s' % mid)

        inbound = self.Msg.sudo().search([
            ('conversation_id', '=', conv.id),
            ('direction', '=', 'inbound'),
        ])
        self.assertEqual(len(inbound), 3,
                         "three distinct buttons tapped = three bubbles")
        self.assertEqual(
            sorted(inbound.mapped('body')), ['A', 'B', 'C'],
            "one bubble per distinct button label",
        )

    def test_lead_replied_button_tap_and_distinct_swipe_both_recorded(self):
        """A button tap and a genuine swipe-reply (different body) to the same
        template are two separate messages — both must show."""
        conv = self.make_conversation()
        self.Msg.sudo().create({
            'conversation_id': conv.id,
            'direction': 'outbound',
            'initiator': 'workflow',
            'kind': 'template',
            'template_name': 'site_visit',
            'wa_message_id': 'wamid.tplBS',
            'status': 'delivered',
            'occurred_at': '2026-03-01 07:00:00',
        })
        # Button tap.
        self._process({
            'event_type': 'lead_replied', 'phone': conv.phone_number,
            'wa_message_id': 'wamid.tplBS', 'button_reply_id': 'Schedule Visit',
            'message_text': 'Schedule Visit', 'occurred_at': '2026-03-01T08:00:00Z',
        }, msg_id='bt-tap')
        # Genuine swipe-reply with a DIFFERENT body, quoting the same template.
        self._process({
            'event_type': 'lead_replied', 'phone': conv.phone_number,
            'wa_message_id': 'wamid.swipe-distinct',
            'source_message_id': 'wamid.tplBS',
            'message_text': 'Actually can we do next week?',
            'occurred_at': '2026-03-01T08:01:00Z',
        }, msg_id='bt-swipe')

        inbound = self.Msg.sudo().search([
            ('conversation_id', '=', conv.id),
            ('direction', '=', 'inbound'),
        ])
        self.assertEqual(len(inbound), 2,
                         "button tap + distinct swipe-reply = two bubbles")

    def test_lead_replied_same_button_double_tap_is_single_bubble(self):
        """Tapping the SAME button twice collapses to one bubble.

        This is the existing synthetic-id double-tap guard ({template}:r:{label});
        documented here so the behaviour is explicit and locked.
        """
        conv = self.make_conversation()
        self.Msg.sudo().create({
            'conversation_id': conv.id,
            'direction': 'outbound',
            'initiator': 'workflow',
            'kind': 'template',
            'template_name': 'site_visit',
            'wa_message_id': 'wamid.tplDT',
            'status': 'delivered',
            'occurred_at': '2026-03-01 07:00:00',
        })
        for i in (1, 2):
            self._process({
                'event_type': 'lead_replied', 'phone': conv.phone_number,
                'wa_message_id': 'wamid.tplDT', 'button_reply_id': 'Yes',
                'message_text': 'Yes', 'occurred_at': '2026-03-01T08:00:00Z',
            }, msg_id='dt-%d' % i)

        inbound = self.Msg.sudo().search([
            ('conversation_id', '=', conv.id),
            ('direction', '=', 'inbound'),
        ])
        self.assertEqual(len(inbound), 1,
                         "same button tapped twice = one bubble (double-tap guard)")

    def test_lead_replied_repeated_freetext_without_quote_not_dropped(self):
        """Two identical plain replies with NO quoted source must both show.

        The companion dedup only applies to replies that quote a source, so plain
        repeated free-text ("ok", "ok") is never suppressed.
        """
        conv = self.make_conversation()
        for i, mid in enumerate(('f1', 'f2'), start=1):
            self._process({
                'event_type': 'lead_replied', 'phone': conv.phone_number,
                'wa_message_id': 'wamid.%s' % mid, 'message_text': 'ok',
                'occurred_at': '2026-03-01T08:0%d:00Z' % i,
            }, msg_id='ft-%s' % mid)

        inbound = self.Msg.sudo().search([
            ('conversation_id', '=', conv.id),
            ('direction', '=', 'inbound'),
        ])
        self.assertEqual(len(inbound), 2,
                         "repeated non-quoted free-text must both be recorded")

    def test_lead_replied_distinct_buttons_are_not_deduped(self):
        """Two DIFFERENT taps on the same template stay as two separate replies."""
        conv = self.make_conversation()
        self.Msg.sudo().create({
            'conversation_id': conv.id,
            'direction': 'outbound',
            'initiator': 'workflow',
            'kind': 'template',
            'template_name': 'site_visit',
            'wa_message_id': 'wamid.tpl3',
            'status': 'delivered',
            'occurred_at': '2026-03-01 07:00:00',
        })
        for label, mid in (('Schedule Visit', 'a'), ('More Options', 'b')):
            self._process({
                'event_type': 'lead_replied',
                'phone': conv.phone_number,
                'wa_message_id': 'wamid.tpl3',
                'button_reply_id': label,
                'message_text': label,
                'occurred_at': '2026-03-01T08:00:00Z',
            }, msg_id='tap-%s' % mid)
        inbound = self.Msg.sudo().search([
            ('conversation_id', '=', conv.id),
            ('direction', '=', 'inbound'),
        ])
        self.assertEqual(len(inbound), 2,
                         "different button labels must each be recorded")

    def test_lead_replied_preview_tracks_newest_message_not_last_processed(self):
        """Webhooks can arrive out of order. The inbox preview + last_message_at
        must reflect the message with the NEWEST occurred_at, not whichever was
        processed last — otherwise an older message clobbers the preview."""
        conv = self.make_conversation()
        # Newest message arrives/processes FIRST…
        self._process({
            'event_type': 'lead_replied', 'phone': conv.phone_number,
            'wa_message_id': 'wamid.newest', 'message_text': 'Need details of 2 BHK',
            'occurred_at': '2026-03-01T10:02:00Z',
        })
        # …an OLDER message is processed AFTER it (out of order).
        self._process({
            'event_type': 'lead_replied', 'phone': conv.phone_number,
            'wa_message_id': 'wamid.older', 'message_text': 'https://youtube.com/x',
            'occurred_at': '2026-03-01T10:00:00Z',
        })
        conv.invalidate_recordset()
        self.assertEqual(conv.last_message_preview, 'Need details of 2 BHK',
                         "preview must show the newest message, not the last processed")
        self.assertEqual(conv.last_message_at, datetime(2026, 3, 1, 10, 2, 0))

    def test_lead_replied_reopens_expired_window(self):
        """An inbound reply on a conversation whose 24h window has already closed
        must reopen it — otherwise the RM couldn't free-text back."""
        past = datetime(2026, 1, 1, 0, 0, 0)
        conv = self.make_conversation(window_expires_at=past)
        conv.invalidate_recordset()
        self.assertFalse(
            conv.window_expires_at and conv.window_expires_at > datetime.utcnow(),
            "precondition: window is closed")
        self._process({
            'event_type': 'lead_replied',
            'phone': conv.phone_number,
            'wa_message_id': 'wamid.reopen',
            'message_text': 'still there?',
            'occurred_at': '2026-06-01T08:00:00Z',
        })
        conv.invalidate_recordset()
        expected = datetime(2026, 6, 1, 8, 0, 0) + timedelta(hours=24)
        self.assertEqual(conv.window_expires_at, expected,
                         "reply must reopen the 24h window from the reply time")

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

    def test_lead_replied_stop_message_lands_as_inbound_bubble(self):
        """A STOP/opt-out is still a lead message — it must show in the chat.

        The platform records the opt-out itself but forwards the message as a
        normal lead_replied; nothing in Odoo may filter or special-case it.
        """
        conv = self.make_conversation()
        start_unread = conv.unread_count
        self._process({
            'event_type': 'lead_replied',
            'phone': conv.phone_number,
            'wa_message_id': 'wamid.stop1',
            'message_text': 'STOP',
            'message_kind': 'Text',
            'occurred_at': '2026-03-01T08:00:00Z',
        })
        conv.invalidate_recordset()
        stop_msg = self.Msg.sudo().search([('wa_message_id', '=', 'wamid.stop1')])
        self.assertEqual(len(stop_msg), 1, "STOP message must land in the inbox")
        self.assertEqual(stop_msg.direction, 'inbound')
        self.assertEqual(stop_msg.body, 'STOP')
        self.assertEqual(conv.unread_count, start_unread + 1,
                         "RM must be alerted to the opt-out")

    # ── Rich inbound kinds (location / sticker / contact / list) ──────────────

    def _reply_kind(self, conv, wa_id, interakt_kind, **extra):
        """Fire a lead_replied with a given Interakt content type; return the row."""
        event = {
            'event_type': 'lead_replied',
            'phone': conv.phone_number,
            'wa_message_id': wa_id,
            'message_kind': interakt_kind,
            'occurred_at': '2026-03-01T08:00:00Z',
        }
        event.update(extra)
        self._process(event, wa_id)
        return self.Msg.sudo().search([('wa_message_id', '=', wa_id)])

    def test_lead_replied_location_json_blob_becomes_readable_with_maps_link(self):
        """A shared location arrives as a JSON blob — it must be parsed into a
        readable name/address body + a Maps link (stored in media_url), never
        shown as raw JSON."""
        conv = self.make_conversation()
        blob = (
            '{"address": "402, Aditya Plaza Complex, Satellite, Ahmedabad", '
            '"latitude": 23.02196268, "longitude": 72.52544203, '
            '"name": "Vishwa ENT Hospital", "url": "https://maps.example/x"}'
        )
        msg = self._reply_kind(conv, 'wamid.loc', 'Location', message_text=blob)
        self.assertEqual(msg.kind, 'location')
        self.assertNotIn('{', msg.body, "raw JSON must not leak into the body")
        self.assertIn('Vishwa ENT Hospital', msg.body)
        self.assertIn('Aditya Plaza', msg.body)
        self.assertEqual(msg.media_url, 'https://maps.example/x')

    def test_lead_replied_location_without_url_builds_google_maps_link(self):
        conv = self.make_conversation()
        blob = '{"latitude": 23.0225, "longitude": 72.5714, "name": "Pin"}'
        msg = self._reply_kind(conv, 'wamid.loc2', 'Location', message_text=blob)
        self.assertEqual(msg.kind, 'location')
        self.assertEqual(msg.media_url,
                         'https://www.google.com/maps?q=23.0225,72.5714')

    def test_lead_replied_location_detected_by_shape_even_when_typed_text(self):
        """Robustness: even if Interakt tags the location as plain Text, the
        JSON shape (latitude+longitude) reclassifies it to a location bubble."""
        conv = self.make_conversation()
        blob = '{"latitude": 19.07, "longitude": 72.87, "address": "Mumbai"}'
        msg = self._reply_kind(conv, 'wamid.loc3', 'Text', message_text=blob)
        self.assertEqual(msg.kind, 'location')
        self.assertIn('Mumbai', msg.body)

    def test_lead_replied_sticker_maps_to_sticker_kind_with_media(self):
        conv = self.make_conversation()
        msg = self._reply_kind(conv, 'wamid.stk', 'Sticker',
                               media_url='https://cdn.interakt.ai/x/sticker.webp')
        self.assertEqual(msg.kind, 'sticker')
        self.assertEqual(msg.media_url, 'https://cdn.interakt.ai/x/sticker.webp')

    def test_lead_replied_contact_vcard_blob_becomes_name_and_phone(self):
        """A shared contact arrives as a vCard JSON list — parse to 'Name · phone'."""
        conv = self.make_conversation()
        blob = (
            '[{"name": {"firstName": "Dhaval", "middleName": "Sir", '
            '"lastName": "CD", "formattedName": "Dhaval Sir CD"}, '
            '"phones": [{"phone": "+91 84017 32226", "type": "MOBILE"}], '
            '"vcard": "BEGIN:VCARD...", "origin": "other"}]'
        )
        msg = self._reply_kind(conv, 'wamid.ct', 'Contact', message_text=blob)
        self.assertEqual(msg.kind, 'contact')
        self.assertNotIn('vcard', msg.body.lower(),
                         "raw vcard must not leak into the body")
        self.assertIn('Dhaval Sir CD', msg.body)
        self.assertIn('+91 84017 32226', msg.body)

    def test_lead_replied_plain_json_text_is_not_misclassified(self):
        """A normal reply that merely looks like JSON but lacks location/contact
        shape stays a text_reply (no false positive)."""
        conv = self.make_conversation()
        msg = self._reply_kind(conv, 'wamid.js', 'Text',
                               message_text='{"foo": "bar"}')
        self.assertEqual(msg.kind, 'text_reply')

    def test_lead_replied_list_reply_maps_to_list_reply_kind(self):
        conv = self.make_conversation()
        msg = self._reply_kind(conv, 'wamid.lst', 'ListReply',
                               message_text='2 BHK')
        self.assertEqual(msg.kind, 'list_reply')
        self.assertEqual(msg.body, '2 BHK')

    def test_lead_replied_list_reply_json_blob_becomes_selected_title(self):
        """A list selection arrives as a JSON blob — store only the picked row's
        title (what WhatsApp shows), never the raw JSON.  The inbox preview
        (last_message_preview) must also be the clean title, not the blob."""
        conv = self.make_conversation()
        blob = ('{"type": "list_reply", "list_reply": '
                '{"id": "row_1", "title": "Property A", "description": "3bhk"}}')
        msg = self._reply_kind(conv, 'wamid.lr', 'Text', message_text=blob)
        self.assertEqual(msg.kind, 'list_reply')
        self.assertEqual(msg.body, 'Property A')
        self.assertNotIn('{', msg.body)
        conv.invalidate_recordset()
        self.assertEqual(conv.last_message_preview, 'Property A',
                         "inbox preview must show the clean title, not raw JSON")
        self.assertNotIn('{', conv.last_message_preview or '')

    def test_lead_replied_unmapped_kind_stored_as_unknown_not_text(self):
        """A brand-new Interakt content type must land as 'unknown', never be
        silently mislabelled as a text reply — so it's visible and greppable."""
        conv = self.make_conversation()
        msg = self._reply_kind(conv, 'wamid.new', 'HologramMessage',
                               message_text='<binary>')
        self.assertEqual(len(msg), 1, "unmapped kind must still land in the inbox")
        self.assertEqual(msg.kind, 'unknown')

    def test_lead_replied_no_message_kind_falls_back_to_text_or_button(self):
        """Legacy events with no message_kind keep the button/text heuristic."""
        conv = self.make_conversation()
        text_msg = self._reply_kind(conv, 'wamid.legacy_txt', '',
                                    message_text='hello')
        self.assertEqual(text_msg.kind, 'text_reply')
        btn_msg = self._reply_kind(conv, 'wamid.legacy_btn', '',
                                   message_text='Yes', button_reply_id='btn_yes')
        self.assertEqual(btn_msg.kind, 'button_reply')

    # ── Inbound media landing ─────────────────────────────────────────────────

    def test_lead_replied_image_lands_with_media_fields(self):
        conv = self.make_conversation()
        msg = self._reply_kind(
            conv, 'wamid.img', 'Image',
            media_url='https://cdn.interakt.ai/a/photo.jpeg',
            media_filename='photo.jpeg',
        )
        self.assertEqual(msg.kind, 'image')
        self.assertEqual(msg.media_url, 'https://cdn.interakt.ai/a/photo.jpeg')
        self.assertEqual(msg.media_filename, 'photo.jpeg')

    def test_lead_replied_document_lands_with_filename(self):
        conv = self.make_conversation()
        msg = self._reply_kind(
            conv, 'wamid.doc', 'Document',
            media_url='https://cdn.interakt.ai/x/deed.pdf',
            media_filename='deed.pdf',
        )
        self.assertEqual(msg.kind, 'document')
        self.assertEqual(msg.media_filename, 'deed.pdf')

    def test_lead_replied_uncaptioned_media_none_caption_scrubbed(self):
        """Interakt's literal "None" caption on uncaptioned media must not leak
        into the bubble body."""
        conv = self.make_conversation()
        msg = self._reply_kind(
            conv, 'wamid.img2', 'Image',
            message_text='None',
            media_url='https://cdn.interakt.ai/a/p.jpeg',
        )
        self.assertEqual(msg.kind, 'image')
        self.assertEqual(msg.body, '')
