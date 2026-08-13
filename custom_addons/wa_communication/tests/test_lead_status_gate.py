"""Lead status gate — an inquiry cannot leave "Lead" without a WhatsApp attempt.

Covers both halves of the rule:

* ``leads.new.create`` always parks a new inquiry at ``lead``, whoever creates
  it and whatever status they ask for;
* an RM may only move it off ``lead`` once an outbound ``wa.message`` exists for
  **that** inquiry.

The cases worth reading first are the ones that pin the *boundaries* of the
gate, because they are what stop it becoming a blunt instrument:
:meth:`test_change_between_non_lead_statuses_is_never_gated`,
:meth:`test_attempt_on_one_inquiry_does_not_unlock_another`, and
:meth:`test_manager_is_not_gated`.
"""

from odoo import api
from odoo.exceptions import UserError
from odoo.tests import new_test_user, tagged

from .common import WaTransactionCase

RM_GROUP = 'leads.group_lead_score_rm'
MANAGER_GROUP = 'leads.group_lead_score_manager'


@tagged('post_install', '-at_install', 'wa_communication')
class TestLeadStatusGate(WaTransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rm = new_test_user(
            cls.env, login=cls._uniq('gate_rm_'),
            groups='base.group_user,%s' % RM_GROUP,
            email='%s@example.com' % cls._uniq('gate_rm_'),
        )
        cls.manager = new_test_user(
            cls.env, login=cls._uniq('gate_mgr_'),
            groups='base.group_user,%s,%s' % (RM_GROUP, MANAGER_GROUP),
            email='%s@example.com' % cls._uniq('gate_mgr_'),
        )

    def _lead(self, **vals):
        vals.setdefault('phone', self._uniq_phone()[2:])
        lead = self.make_lead(**vals)
        lead.write({'user_id': self.rm.id})
        return lead

    def _anonymous_env(self):
        """An env with no acting user, as the auth='none' push route has.

        Built with ``uid=None`` rather than ``env(user=...)``: only the former
        makes ``env.user`` an empty recordset, which is the condition that
        breaks ``has_group()``.
        """
        return api.Environment(self.env.cr, None, {})

    def _attempt(self, lead, **vals):
        """Record an outbound WhatsApp message against *lead*."""
        conv = self.make_conversation(
            phone_number='91%s' % lead.phone, lead_id=lead.id)
        vals.setdefault('status', 'queued')
        return self.make_message(
            conv, direction='outbound', initiator='rm', kind='template',
            lead_id=lead.id, **vals)

    # ── 3a. Creation always starts at "Lead" ────────────────────────────────

    def test_create_forces_lead_status(self):
        """A caller asking for another status at create time is overruled."""
        lead = self.make_lead(current_status='site_visit_done')
        self.assertEqual(lead.current_status, 'lead')

    def test_create_defaults_to_lead_status(self):
        self.assertEqual(self.make_lead().current_status, 'lead')

    # ── 3b. The gate ─────────────────────────────────────────────────────────

    def test_rm_cannot_leave_lead_without_an_attempt(self):
        lead = self._lead()
        with self.assertRaises(UserError) as ctx:
            lead.with_user(self.rm).write({'current_status': 'requirement_closed'})
        self.assertIn("haven't messaged this buyer", str(ctx.exception))
        self.assertEqual(lead.current_status, 'lead')

    def test_queued_message_unlocks_the_status(self):
        """A send that has not left Odoo yet still counts — it was attempted."""
        lead = self._lead()
        self._attempt(lead, status='queued')
        lead.with_user(self.rm).write({'current_status': 'requirement_closed'})
        self.assertEqual(lead.current_status, 'requirement_closed')

    def test_failed_message_unlocks_the_status(self):
        """Delivery is not the bar: the RM did their part."""
        lead = self._lead()
        self._attempt(lead, status='failed')
        lead.with_user(self.rm).write({'current_status': 'busy'})
        self.assertEqual(lead.current_status, 'busy')

    def test_meta_blocked_message_unlocks_the_status(self):
        lead = self._lead()
        self._attempt(lead, status='meta_blocked')
        lead.with_user(self.rm).write({'current_status': 'switched_off'})
        self.assertEqual(lead.current_status, 'switched_off')

    def test_inbound_message_does_not_count_as_an_attempt(self):
        """The buyer writing to us is not the RM having reached out."""
        lead = self._lead()
        conv = self.make_conversation(
            phone_number='91%s' % lead.phone, lead_id=lead.id)
        self.make_message(conv, direction='inbound', lead_id=lead.id)
        with self.assertRaises(UserError):
            lead.with_user(self.rm).write({'current_status': 'busy'})

    def test_change_between_non_lead_statuses_is_never_gated(self):
        """Only the exit from "Lead" is guarded — everything after is free.

        This is what makes the gate safe to switch on across the whole history:
        inquiries that already moved on are untouched.
        """
        lead = self._lead()
        lead.sudo().write({'current_status': 'busy'})   # system write, ungated
        lead.with_user(self.rm).write({'current_status': 'requirement_closed'})
        self.assertEqual(lead.current_status, 'requirement_closed')

    def test_attempt_on_one_inquiry_does_not_unlock_another(self):
        """Same buyer, two properties — one message must not unlock both."""
        phone = self._uniq_phone()[2:]
        lead_a = self._lead(phone=phone)
        lead_b = self._lead(phone=phone)
        self._attempt(lead_a)

        lead_a.with_user(self.rm).write({'current_status': 'busy'})
        self.assertEqual(lead_a.current_status, 'busy')

        with self.assertRaises(UserError):
            lead_b.with_user(self.rm).write({'current_status': 'busy'})

    def test_manager_is_not_gated(self):
        """Managers own corrections and cleanup."""
        lead = self._lead()
        lead.with_user(self.manager).write({'current_status': 'requirement_closed'})
        self.assertEqual(lead.current_status, 'requirement_closed')

    def test_anonymous_context_does_not_crash_the_gate(self):
        """The Pub/Sub push route is auth='none', so there is no acting user.

        env.uid is None there and env.user is an EMPTY res.users recordset.
        has_group() calls ensure_one(), so touching it raised "Expected
        singleton: res.users()" and took down the whole event handler — which
        is how this gate managed to break the automatic status update it was
        supposed to leave alone.
        """
        lead = self._lead()
        anon = lead.with_env(self._anonymous_env())
        self.assertFalse(anon.env.user, "env.user must be an empty recordset")

        # The regression: merely asking the gate a question blew up.
        self.assertFalse(anon._wa_user_is_gated())

        # ...and the write the handler actually performs goes through.  sudo()
        # mirrors _owa_maybe_mark_details_shared; without it Odoo's own
        # check_access needs a user and fails deeper in core, which is a
        # property of anonymous writes generally and not of this gate.
        anon.sudo().write({'current_status': 'details_shared_of_property'})
        lead.invalidate_recordset()
        self.assertEqual(lead.current_status, 'details_shared_of_property')

    def test_anonymous_context_can_compute_the_ui_flag(self):
        lead = self._lead()
        anon = lead.with_env(self._anonymous_env())
        anon.invalidate_recordset()
        self.assertTrue(anon.wa_status_change_allowed)

    def test_system_write_is_not_gated(self):
        """OdooBot / the Pub/Sub push user are not RMs, so they pass through.

        This is what lets the gate have no bypass flag: the automated paths are
        already outside it by virtue of who they run as.
        """
        lead = self._lead()
        lead.sudo().write({'current_status': 'details_shared_of_property'})
        self.assertEqual(lead.current_status, 'details_shared_of_property')

    # ── Segment re-pointing ──────────────────────────────────────────────────

    def test_repointed_segment_moves_the_attempt(self):
        """Correcting which inquiry a thread was about moves the credit with it.

        The gate matches on ``effective_inquiry_id``, so an RM who fixes the
        attribution unlocks the inquiry that was really messaged — and only it.
        """
        phone = self._uniq_phone()[2:]
        lead_a = self._lead(phone=phone)
        lead_b = self._lead(phone=phone)
        conv = self.make_conversation(
            phone_number='91%s' % phone, lead_id=lead_a.id)
        seg = self.env['wa.conversation.segment'].sudo().create({
            'conversation_id': conv.id,
            'inquiry_id': lead_a.id,
        })
        msg = self.make_message(
            conv, direction='outbound', initiator='rm', kind='template',
            status='sent', lead_id=lead_a.id, segment_id=seg.id)
        self.assertEqual(msg.effective_inquiry_id, lead_a)

        # The RM realises the conversation was really about property B.
        seg.sudo().write({'inquiry_id': lead_b.id})
        msg.invalidate_recordset()
        self.assertEqual(msg.effective_inquiry_id, lead_b)

        lead_b.with_user(self.rm).write({'current_status': 'busy'})
        self.assertEqual(lead_b.current_status, 'busy')
        with self.assertRaises(UserError):
            lead_a.with_user(self.rm).write({'current_status': 'busy'})

    # ── The UI hint ──────────────────────────────────────────────────────────

    def test_status_change_allowed_flag_tracks_the_gate(self):
        lead = self._lead()
        as_rm = lead.with_user(self.rm)
        as_rm.invalidate_recordset()
        self.assertFalse(as_rm.wa_status_change_allowed)

        self._attempt(lead)
        as_rm.invalidate_recordset()
        self.assertTrue(as_rm.wa_status_change_allowed)

    def test_status_change_allowed_is_true_for_managers(self):
        lead = self._lead()
        as_mgr = lead.with_user(self.manager)
        as_mgr.invalidate_recordset()
        self.assertTrue(as_mgr.wa_status_change_allowed)

    def test_status_change_allowed_is_true_once_past_lead(self):
        lead = self._lead()
        lead.sudo().write({'current_status': 'busy'})
        as_rm = lead.with_user(self.rm)
        as_rm.invalidate_recordset()
        self.assertTrue(as_rm.wa_status_change_allowed)

    def test_status_change_allowed_computes_correctly_in_batch(self):
        """The flag renders in the list view, so it is computed for many rows.

        Pins the batched read_group path: a mix of attempted and un-attempted
        inquiries must each get their own answer, not one shared verdict.
        """
        messaged = self._lead()
        self._attempt(messaged)
        silent_a = self._lead()
        silent_b = self._lead()

        batch = (messaged | silent_a | silent_b).with_user(self.rm)
        batch.invalidate_recordset()
        allowed = {
            rec.id: rec.wa_status_change_allowed for rec in batch
        }
        self.assertTrue(allowed[messaged.id])
        self.assertFalse(allowed[silent_a.id])
        self.assertFalse(allowed[silent_b.id])
