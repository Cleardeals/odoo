"""Auto "Details Shared of Property" when the property card is delivered.

This is the highest-risk piece of the three, because it writes to the funnel
without a human in the loop.  The tests are therefore weighted towards the ways
it could write the *wrong* thing rather than the happy path: out-of-order
receipts, a lost ``delivered``, duplicate deliveries, an inquiry an RM has
already judged, and — most importantly — a phone number carrying more than one
inquiry.
"""

from odoo.tests import tagged

from .common import WaTransactionCase

TEMPLATE = 'initial_nudge_v1_msg_2_xc'
SHARED = 'details_shared_of_property'


@tagged('post_install', '-at_install', 'wa_communication')
class TestDetailsSharedStatus(WaTransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param(
            'wa_communication.details_shared_templates', TEMPLATE)

    def _lead_conv(self):
        lead = self.make_lead(phone=self._uniq_phone()[2:])
        conv = self.make_conversation(
            phone_number='91%s' % lead.phone, lead_id=lead.id)
        return lead, conv

    def _delivered_event(self, conv, lead, **over):
        """A message_delivered OdooWaEvent for a workflow-sent card."""
        event = {
            'event_type': 'message_delivered',
            'phone': conv.phone_number,
            'actor_id': lead.id,
            'actor_type': 'buyer_inquiry',
            'wa_message_id': self._uniq('wamid_'),
            'template_name': TEMPLATE,
            'workflow_slug': 'initial_nudge_property_v1',
            'step_id': 'msg_2',
            'enrollment_id': self._uniq('enr_'),
            'occurred_at': '2026-01-01T10:00:00Z',
        }
        event.update(over)
        return event

    # ── Happy path ───────────────────────────────────────────────────────────

    def test_delivery_moves_the_inquiry_to_details_shared(self):
        lead, conv = self._lead_conv()
        self.assertEqual(lead.current_status, 'lead')

        self.Conv._process_odoo_wa_event(
            self._delivered_event(conv, lead), self._uniq('psm_'))

        lead.invalidate_recordset()
        self.assertEqual(lead.current_status, SHARED)

    def test_read_also_moves_it_when_delivered_was_lost(self):
        """read implies delivered; receipts do go missing."""
        lead, conv = self._lead_conv()
        self.Conv._process_odoo_wa_event(
            self._delivered_event(conv, lead, event_type='message_read'),
            self._uniq('psm_'))
        lead.invalidate_recordset()
        self.assertEqual(lead.current_status, SHARED)

    def test_delivery_notifies_the_owning_rm(self):
        lead, conv = self._lead_conv()
        rm = self.make_user()
        lead.write({'user_id': rm.id})

        before = self.env['cleardeals.notification'].sudo().search_count(
            [('user_id', '=', rm.id), ('notif_type', '=', 'details_shared')])
        self.Conv._process_odoo_wa_event(
            self._delivered_event(conv, lead), self._uniq('psm_'))
        after = self.env['cleardeals.notification'].sudo().search_count(
            [('user_id', '=', rm.id), ('notif_type', '=', 'details_shared')])
        self.assertEqual(after, before + 1)

    def test_delivery_explains_itself_in_the_chatter(self):
        """An RM finding a status they didn't set must be able to see why."""
        lead, conv = self._lead_conv()
        before = len(lead.message_ids)

        self.Conv._process_odoo_wa_event(
            self._delivered_event(conv, lead), self._uniq('psm_'))

        lead.invalidate_recordset()
        notes = lead.message_ids[:len(lead.message_ids) - before]
        body = ' '.join(notes.mapped('body'))
        self.assertIn('Details Shared of Property', body)
        self.assertIn(TEMPLATE, body, "names the evidence it acted on")
        self.assertIn('never overwritten', body,
                      "states the rule that protects the RM's own edits")

    def test_a_broken_note_never_undoes_the_status_change(self):
        """The note explains the outcome; it must not be able to prevent it."""
        from unittest.mock import patch
        lead, conv = self._lead_conv()

        with patch.object(type(lead), 'message_post',
                          side_effect=ValueError('chatter down')):
            self.Conv._process_odoo_wa_event(
                self._delivered_event(conv, lead), self._uniq('psm_'))

        lead.invalidate_recordset()
        self.assertEqual(lead.current_status, SHARED)

    # ── Idempotency and ordering ─────────────────────────────────────────────

    def test_duplicate_delivery_does_not_notify_twice(self):
        """A redelivered receipt is a no-op — the status guard makes it so."""
        lead, conv = self._lead_conv()
        rm = self.make_user()
        lead.write({'user_id': rm.id})
        event = self._delivered_event(conv, lead)

        self.Conv._process_odoo_wa_event(event, self._uniq('psm_'))
        count = self.env['cleardeals.notification'].sudo().search_count(
            [('user_id', '=', rm.id), ('notif_type', '=', 'details_shared')])

        self.Conv._process_odoo_wa_event(event, self._uniq('psm_'))
        self.assertEqual(
            self.env['cleardeals.notification'].sudo().search_count(
                [('user_id', '=', rm.id), ('notif_type', '=', 'details_shared')]),
            count)

    def test_delivered_before_sent_still_moves_the_status(self):
        """The out-of-order stub path must trigger the update too."""
        lead, conv = self._lead_conv()
        # No prior wa.message exists: the delivered receipt creates the stub.
        self.assertFalse(self.Msg.sudo().search_count(
            [('conversation_id', '=', conv.id), ('direction', '=', 'outbound')]))

        self.Conv._process_odoo_wa_event(
            self._delivered_event(conv, lead), self._uniq('psm_'))

        lead.invalidate_recordset()
        self.assertEqual(lead.current_status, SHARED)

    # ── Refusals ─────────────────────────────────────────────────────────────

    def test_status_already_advanced_is_left_alone(self):
        """Automation never overrules a human's judgement."""
        lead, conv = self._lead_conv()
        lead.sudo().write({'current_status': 'site_visit_done'})

        self.Conv._process_odoo_wa_event(
            self._delivered_event(conv, lead), self._uniq('psm_'))

        lead.invalidate_recordset()
        self.assertEqual(lead.current_status, 'site_visit_done')

    def test_advanced_status_sends_no_notification(self):
        """A notification about a status we didn't set is noise."""
        lead, conv = self._lead_conv()
        rm = self.make_user()
        lead.write({'user_id': rm.id})
        lead.sudo().write({'current_status': 'requirement_closed'})

        self.Conv._process_odoo_wa_event(
            self._delivered_event(conv, lead), self._uniq('psm_'))

        self.assertFalse(self.env['cleardeals.notification'].sudo().search_count(
            [('user_id', '=', rm.id), ('notif_type', '=', 'details_shared')]))

    def test_other_template_does_not_move_the_status(self):
        lead, conv = self._lead_conv()
        self.Conv._process_odoo_wa_event(
            self._delivered_event(conv, lead, template_name='some_other_tpl'),
            self._uniq('psm_'))
        lead.invalidate_recordset()
        self.assertEqual(lead.current_status, 'lead')

    def test_phone_guessed_inquiry_is_attributed_but_not_judged(self):
        """The single most dangerous case: an inquiry nobody actually named.

        When the platform sends no ``actor_id``, ``_owa_resolve_lead`` falls
        back to "newest lead on this phone".  That guess is fine for filing the
        message into a thread, and the message *is* still attributed — but it
        must not move a funnel status, because the buyer may well have three
        inquiries and the newest need not be the one the card was about.
        """
        lead, conv = self._lead_conv()
        event = self._delivered_event(conv, lead)
        event['actor_id'] = 0        # platform could not name the inquiry
        conv.sudo().write({'lead_id': False})

        self.Conv._process_odoo_wa_event(event, self._uniq('psm_'))

        # Attributed…
        msg = self.Msg.sudo().search(
            [('wa_message_id', '=', event['wa_message_id'])], limit=1)
        self.assertEqual(msg.effective_inquiry_id, lead)
        # …but not judged.
        lead.invalidate_recordset()
        self.assertEqual(lead.current_status, 'lead')

    def test_rm_repointed_segment_is_trusted(self):
        """A human attribution is authoritative even without an actor id."""
        lead, conv = self._lead_conv()
        seg = self.env['wa.conversation.segment'].sudo().create({
            'conversation_id': conv.id,
            'inquiry_id': lead.id,
            'started_by': 'rm',
        })
        msg = self.make_message(
            conv, direction='outbound', initiator='workflow', kind='template',
            status='sent', template_name=TEMPLATE, segment_id=seg.id)

        self.Conv._owa_maybe_mark_details_shared(msg)

        lead.invalidate_recordset()
        self.assertEqual(lead.current_status, SHARED)

    def test_auto_suggested_segment_is_not_trusted(self):
        """An auto-opened segment carries the same guess — don't launder it."""
        lead, conv = self._lead_conv()
        seg = self.env['wa.conversation.segment'].sudo().create({
            'conversation_id': conv.id,
            'inquiry_id': lead.id,
            'started_by': 'auto_suggested',
        })
        msg = self.make_message(
            conv, direction='outbound', initiator='workflow', kind='template',
            status='sent', template_name=TEMPLATE, segment_id=seg.id)

        self.Conv._owa_maybe_mark_details_shared(msg)

        lead.invalidate_recordset()
        self.assertEqual(lead.current_status, 'lead')

    def test_only_the_addressed_inquiry_moves(self):
        """Same buyer, two properties: the card is about exactly one of them."""
        phone = self._uniq_phone()[2:]
        lead_a = self.make_lead(phone=phone)
        lead_b = self.make_lead(phone=phone)
        conv = self.make_conversation(
            phone_number='91%s' % phone, lead_id=lead_a.id)

        self.Conv._process_odoo_wa_event(
            self._delivered_event(conv, lead_a), self._uniq('psm_'))

        lead_a.invalidate_recordset()
        lead_b.invalidate_recordset()
        self.assertEqual(lead_a.current_status, SHARED)
        self.assertEqual(lead_b.current_status, 'lead')

    # ── No feedback loop ─────────────────────────────────────────────────────

    def test_the_status_write_publishes_no_actor_event(self):
        """The engine must not react to a status the engine itself caused.

        ``details_shared_of_property`` is deliberately in neither
        ``_ACTOR_STATUS_SET`` nor ``_VISIT_STATUS_MAP``; adding it to either
        would create the loop silently, so pin it here.
        """
        lead, conv = self._lead_conv()
        with self.mock_pubsub() as published:
            self.Conv._process_odoo_wa_event(
                self._delivered_event(conv, lead), self._uniq('psm_'))

        lead.invalidate_recordset()
        self.assertEqual(lead.current_status, SHARED)
        self.assertFalse([
            p for p in published
            if p.payload.get('event_type') in (
                'actor.status_changed', 'visit.scheduled', 'visit.done',
                'visit.rescheduled')
        ])

    # ── Configuration ────────────────────────────────────────────────────────

    def test_template_list_is_configurable(self):
        """New template names get approved constantly; no deploy to track them."""
        self.env['ir.config_parameter'].sudo().set_param(
            'wa_communication.details_shared_templates',
            '%s, quick_details_share_odoo_w8' % TEMPLATE)
        lead, conv = self._lead_conv()

        self.Conv._process_odoo_wa_event(
            self._delivered_event(
                conv, lead, template_name='quick_details_share_odoo_w8'),
            self._uniq('psm_'))

        lead.invalidate_recordset()
        self.assertEqual(lead.current_status, SHARED)
