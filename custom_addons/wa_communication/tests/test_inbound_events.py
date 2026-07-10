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
