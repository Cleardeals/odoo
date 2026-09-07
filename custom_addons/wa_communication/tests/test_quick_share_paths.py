"""Every route into "Share Property Details", proven to end somewhere sane.

The button is reachable from any inquiry, and the state of the WhatsApp side
varies independently of the lead: the number may have no thread at all, a thread
nobody owns, one the RM owns, or one another RM owns.  The inquiry may be the
thread's anchor or the fourth one on that number.  Each combination has to
either send correctly or fail with a sentence the RM can act on — never a
traceback, and never a message filed against the wrong property.

Two populations matter most in practice:

* a genuinely new number (an inquiry created today for a buyer nobody has
  messaged), which must end with the RM owning the new thread; and
* the backlog of old inquiries parked at "Lead" with no thread at all, which is
  the population the status gate is aimed at — those RMs must be able to send,
  or the gate traps them.
"""

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import WaTransactionCase


@tagged('post_install', '-at_install', 'wa_communication')
class TestQuickSharePaths(WaTransactionCase):

    def _property(self, **vals):
        base = {
            'name': 'Path Property',
            'prop_id': self._uniq('PP'),
            'location': 'Bodakdev',
            'bedroom_count': 2,
            'prop_sub_type': 'Apartment',
            'property_size': '900 sqft',
            'furnishing_type': 'Unfurnished',
            'primary_image_url': 'https://img.example.com/p.jpg',
            'tour_360_url': 'https://tour.example.com/p',
        }
        base.update(vals)
        return self.env['property.base'].sudo().create(base)

    def _lead(self, phone=None, **vals):
        prop = vals.pop('property', None) or self._property()
        return self.make_lead(
            phone=phone or self._uniq_phone()[2:],
            property_base_id=prop.id, **vals), prop

    def _last_outbound(self, conv):
        return self.Msg.sudo().search(
            [('conversation_id', '=', conv.id), ('direction', '=', 'outbound')],
            order='id desc', limit=1)

    # ── Path 1: brand-new number, no thread has ever existed ────────────────

    def test_new_number_creates_a_thread_owned_by_the_sender(self):
        """The RM who opens the conversation owns it — no handover needed."""
        lead, prop = self._lead()
        self.assertFalse(self.Conv.sudo().search(
            [('phone_number', '=', '91%s' % lead.phone)]))

        with self.mock_pubsub() as published:
            conv_id = self.Conv.send_property_details_for_lead(lead.id)

        conv = self.Conv.sudo().browse(conv_id)
        self.assertTrue(conv.exists())
        self.assertEqual(conv.assigned_user_id.id, self.env.uid)
        self.assertEqual(conv.lead_id, lead)
        self.assertEqual(published[-1].payload['kind'], 'template')

    def test_new_number_files_the_send_under_the_right_property(self):
        lead, prop = self._lead()
        with self.mock_pubsub():
            conv = self.Conv.sudo().browse(
                self.Conv.send_property_details_for_lead(lead.id))

        msg = self._last_outbound(conv)
        self.assertEqual(msg.effective_inquiry_id, lead)
        self.assertEqual(msg.segment_id.inquiry_id, lead)
        self.assertEqual(msg.segment_id.property_base_id, prop)

    # ── Path 2: the backlog — an old inquiry with no thread ─────────────────

    def test_old_lead_with_no_thread_can_be_messaged(self):
        """The status-gate population: parked at "Lead", never messaged.

        If this path failed, the gate would trap exactly the inquiries it was
        built to police.
        """
        lead, prop = self._lead()
        self.assertEqual(lead.current_status, 'lead')
        self.assertFalse(lead._wa_has_send_attempt())

        with self.mock_pubsub():
            conv = self.Conv.sudo().browse(
                self.Conv.send_property_details_for_lead(lead.id))

        lead.invalidate_recordset()
        self.assertTrue(lead._wa_has_send_attempt(),
                        "the send must satisfy the status gate")
        self.assertEqual(self._last_outbound(conv).effective_inquiry_id, lead)

    def test_the_send_unlocks_the_status_for_a_gated_rm(self):
        """End to end: gated RM, no history, send, status now changeable."""
        from odoo.tests import new_test_user
        rm = new_test_user(
            self.env, login=self._uniq('path_rm_'),
            groups='base.group_user,leads.group_lead_score_rm',
            email='%s@example.com' % self._uniq('path_rm_'))
        lead, _prop = self._lead()
        lead.write({'user_id': rm.id})

        with self.assertRaises(UserError):
            lead.with_user(rm).write({'current_status': 'busy'})

        with self.mock_pubsub():
            self.Conv.with_user(rm).send_property_details_for_lead(lead.id)

        lead.invalidate_recordset()
        lead.with_user(rm).write({'current_status': 'busy'})
        self.assertEqual(lead.current_status, 'busy')

    # ── Path 3-5: an existing thread, in each ownership state ───────────────

    def test_unassigned_thread_is_claimed_by_the_sender(self):
        lead, _prop = self._lead()
        conv = self.make_conversation(
            phone_number='91%s' % lead.phone, assigned_user_id=False)

        with self.mock_pubsub():
            self.Conv.send_property_details_for_lead(lead.id)

        conv.invalidate_recordset()
        self.assertEqual(conv.assigned_user_id.id, self.env.uid)

    def test_thread_already_mine_just_sends(self):
        lead, _prop = self._lead()
        conv = self.make_conversation(phone_number='91%s' % lead.phone)

        with self.mock_pubsub():
            returned = self.Conv.send_property_details_for_lead(lead.id)

        self.assertEqual(returned, conv.id)
        self.assertEqual(self._last_outbound(conv).template_name,
                         self.Conv._quick_share_template()[0])

    def test_thread_owned_by_another_rm_is_refused_clearly(self):
        """Per the handover decision: refuse, and say so — never a traceback."""
        other = self.make_user()
        lead, _prop = self._lead()
        conv = self.make_conversation(
            phone_number='91%s' % lead.phone, assigned_user_id=other.id)

        with self.assertRaises(UserError) as ctx:
            with self.mock_pubsub():
                self.Conv.send_property_details_for_lead(lead.id)

        self.assertTrue(str(ctx.exception).strip())
        self.assertFalse(self._last_outbound(conv),
                         "a refused send must not leave a queued message")

    # ── Phone shapes ────────────────────────────────────────────────────────

    def test_twelve_digit_lead_phone_reuses_the_same_thread(self):
        """No second thread for the same buyer written a different way."""
        lead, _prop = self._lead()
        conv = self.make_conversation(phone_number='91%s' % lead.phone)
        lead.sudo().write({'phone': '91%s' % lead.phone})

        with self.mock_pubsub():
            returned = self.Conv.send_property_details_for_lead(lead.id)

        self.assertEqual(returned, conv.id)
        self.assertEqual(self.Conv.sudo().search_count(
            [('phone_number', '=', conv.phone_number)]), 1)

    # ── Refusals, each with a usable message ────────────────────────────────

    def test_lead_without_property_is_refused_and_creates_nothing(self):
        lead = self.make_lead(phone=self._uniq_phone()[2:])
        before = self.Conv.sudo().search_count([])

        with self.assertRaises(UserError) as ctx:
            self.Conv.send_property_details_for_lead(lead.id)

        self.assertIn('no property linked', str(ctx.exception))
        self.assertEqual(self.Conv.sudo().search_count([]), before)

    def test_lead_without_phone_is_refused_and_creates_nothing(self):
        prop = self._property()
        lead = self.make_lead(phone=False, property_base_id=prop.id)
        before = self.Conv.sudo().search_count([])

        with self.assertRaises(UserError) as ctx:
            self.Conv.send_property_details_for_lead(lead.id)

        self.assertIn('no phone number', str(ctx.exception))
        self.assertEqual(self.Conv.sudo().search_count([]), before)

    def test_incomplete_property_is_refused_and_creates_nothing(self):
        prop = self._property(location=False)
        lead = self.make_lead(
            phone=self._uniq_phone()[2:], property_base_id=prop.id)
        before = self.Conv.sudo().search_count([])

        with self.assertRaises(UserError) as ctx:
            self.Conv.send_property_details_for_lead(lead.id)

        self.assertIn('Locality', str(ctx.exception))
        self.assertEqual(self.Conv.sudo().search_count([]), before)

    def test_deleted_lead_is_refused(self):
        lead, _prop = self._lead()
        lead_id = lead.id
        lead.sudo().unlink()
        with self.assertRaises(UserError) as ctx:
            self.Conv.send_property_details_for_lead(lead_id)
        self.assertIn('not found', str(ctx.exception))

    # ── Feature-flag interaction ────────────────────────────────────────────

    def test_send_still_works_with_segments_disabled(self):
        """The attribution feature is flag-gated; the send must not depend on it."""
        self.env['ir.config_parameter'].sudo().set_param(
            'wa_communication.segments_enabled', '0')
        self.addCleanup(
            self.env['ir.config_parameter'].sudo().set_param,
            'wa_communication.segments_enabled', '1')

        lead, _prop = self._lead()
        with self.mock_pubsub() as published:
            conv = self.Conv.sudo().browse(
                self.Conv.send_property_details_for_lead(lead.id))

        self.assertEqual(published[-1].payload['kind'], 'template')
        msg = self._last_outbound(conv)
        self.assertFalse(msg.segment_id)
        self.assertEqual(msg.effective_inquiry_id, lead,
                         "falls back to lead_id when there is no segment")
