"""Containment for handovers whose confirmation never arrives.

``confirming`` is the only ``wa.reassignment.request`` state that cannot be left
by a user action — it exits when the platform sends back
``assignment_confirmed``. Any failure to deliver that event used to strand the
request permanently:

* nothing timed out, so the row sat forever (request #15 sat for 8 days);
* ``approve()`` / ``decline()`` returned silently on a non-pending request, so
  the assignee's buttons did nothing with no explanation;
* ``confirming`` counts as an open request, so the requester was locked out of
  asking again.

These tests cover the two halves of the fix: the sweeper that releases stuck
rows, and the audible refusal that replaced the silent ``return``.
"""

import time
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

_PUBSUB = 'odoo.addons.cleardeals_pubsub.models.pubsub_publisher'


@tagged('post_install', '-at_install', 'wa_communication')
class TestStuckHandoverSweeper(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Conv = cls.env['wa.conversation']
        cls.Req = cls.env['wa.reassignment.request']
        suffix = str(int(time.time()))
        cls.owner = new_test_user(
            cls.env, login=f'swp_own_{suffix}', groups='base.group_user',
            email=f'swp_own_{suffix}@example.com')
        cls.asker = new_test_user(
            cls.env, login=f'swp_ask_{suffix}', groups='base.group_user',
            email=f'swp_ask_{suffix}@example.com')

    def _confirming_request(self, age_minutes=0):
        """A request parked in 'confirming', optionally aged into the past."""
        conv = self.Conv.create({
            'phone_number': '9198000%05d' % (int(time.time() * 100) % 100000),
            'assigned_user_id': self.owner.id,
        })
        req = self.Req.create({
            'conversation_id': conv.id,
            'requester_id': self.asker.id,
            'current_assignee_id': self.owner.id,
            'state': 'confirming',
            'request_id': 'corr-%s' % conv.id,
        })
        conv.write({'assignment_pending': True})
        if age_minutes:
            stale = fields.Datetime.now() - timedelta(minutes=age_minutes)
            # write_date is what the sweeper ages on; it is not writable
            # through the ORM, so set it directly.
            self.env.cr.execute(
                "UPDATE wa_reassignment_request SET write_date = %s WHERE id = %s",
                (stale, req.id))
            req.invalidate_recordset()
        return conv, req

    # ── The sweep ────────────────────────────────────────────────────────────

    def test_stuck_request_is_released_to_failed(self):
        conv, req = self._confirming_request(age_minutes=30)

        released = self.Req._cron_release_stuck_confirming()

        self.assertEqual(released, 1)
        req.invalidate_recordset()
        self.assertEqual(req.state, 'failed')
        self.assertTrue(req.resolved_at)

    def test_sweep_clears_the_conversation_spinner(self):
        """Leaving assignment_pending set keeps the composer locked."""
        conv, _req = self._confirming_request(age_minutes=30)

        self.Req._cron_release_stuck_confirming()

        conv.invalidate_recordset()
        self.assertFalse(conv.assignment_pending)

    def test_sweep_lets_the_requester_ask_again(self):
        """The point of releasing: the requester is no longer locked out."""
        conv, _req = self._confirming_request(age_minutes=30)
        self.Req._cron_release_stuck_confirming()

        still_open = self.Req.search_count([
            ('conversation_id', '=', conv.id),
            ('requester_id', '=', self.asker.id),
            ('state', 'in', ('pending', 'confirming')),
        ])
        self.assertEqual(still_open, 0, "no open request blocks a new one")

        with patch.object(type(self.env['cleardeals.pubsub']), 'publish_async'):
            new_id = conv.with_user(self.asker).request_assignment()
        new_req = self.Req.browse(new_id)
        self.assertEqual(new_req.state, 'pending')
        self.assertNotEqual(new_id, _req.id, "a genuinely new request")

    def test_sweep_notifies_the_requester(self):
        conv, _req = self._confirming_request(age_minutes=30)
        before = self.env['cleardeals.notification'].sudo().search_count(
            [('user_id', '=', self.asker.id),
             ('notif_type', '=', 'reassignment_failed')])

        self.Req._cron_release_stuck_confirming()

        after = self.env['cleardeals.notification'].sudo().search_count(
            [('user_id', '=', self.asker.id),
             ('notif_type', '=', 'reassignment_failed')])
        self.assertEqual(after, before + 1)

    def test_sweep_logs_a_system_event_on_the_thread(self):
        """Survives a missed toast — the thread explains what happened."""
        conv, _req = self._confirming_request(age_minutes=30)

        self.Req._cron_release_stuck_confirming()

        logs = self.env['wa.message'].sudo().search(
            [('conversation_id', '=', conv.id), ('kind', '=', 'system')])
        self.assertTrue(
            logs.filtered(lambda m: 'released' in (m.body or '')),
            "the release is recorded on the conversation")

    # ── What the sweep must NOT touch ────────────────────────────────────────

    def test_fresh_confirming_request_is_left_alone(self):
        """A handover in flight must not be killed mid-round-trip."""
        _conv, req = self._confirming_request(age_minutes=0)

        released = self.Req._cron_release_stuck_confirming()

        self.assertEqual(released, 0)
        req.invalidate_recordset()
        self.assertEqual(req.state, 'confirming')

    def test_pending_request_is_left_alone(self):
        """Awaiting a human decision is not the same as stranded."""
        conv, req = self._confirming_request(age_minutes=90)
        req.write({'state': 'pending'})

        released = self.Req._cron_release_stuck_confirming()

        self.assertEqual(released, 0)
        req.invalidate_recordset()
        self.assertEqual(req.state, 'pending')

    def test_timeout_is_configurable(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'wa_communication.confirming_timeout_minutes', '120')
        _conv, req = self._confirming_request(age_minutes=30)

        self.assertEqual(self.Req._cron_release_stuck_confirming(), 0,
                         "30 min is inside a 120 min window")
        req.invalidate_recordset()
        self.assertEqual(req.state, 'confirming')

    def test_bad_timeout_config_falls_back_to_the_default(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'wa_communication.confirming_timeout_minutes', 'not-a-number')
        self.assertEqual(self.Req._confirming_timeout_minutes(), 5)


@tagged('post_install', '-at_install', 'wa_communication')
class TestResolveFeedback(TransactionCase):
    """approve()/decline() must never swallow a click."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Conv = cls.env['wa.conversation']
        cls.Req = cls.env['wa.reassignment.request']
        suffix = str(int(time.time()))
        cls.owner = new_test_user(
            cls.env, login=f'fb_own_{suffix}', groups='base.group_user',
            email=f'fb_own_{suffix}@example.com')
        cls.asker = new_test_user(
            cls.env, login=f'fb_ask_{suffix}', groups='base.group_user',
            email=f'fb_ask_{suffix}@example.com')

    def _request(self, state):
        conv = self.Conv.create({
            'phone_number': '9198100%05d' % (int(time.time() * 100) % 100000),
            'assigned_user_id': self.owner.id,
        })
        return self.Req.create({
            'conversation_id': conv.id,
            'requester_id': self.asker.id,
            'current_assignee_id': self.owner.id,
            'state': state,
        })

    def test_decline_on_confirming_explains_itself(self):
        """The reported symptom: Decline pressed, nothing happened, no reason."""
        req = self._request('confirming')
        with self.assertRaises(UserError) as ctx:
            req.with_user(self.owner).decline()
        self.assertIn('already being handed over', str(ctx.exception))

    def test_approve_on_confirming_explains_itself(self):
        req = self._request('confirming')
        with self.assertRaises(UserError) as ctx:
            req.with_user(self.owner).approve()
        self.assertIn('already being handed over', str(ctx.exception))

    def test_approve_on_confirming_does_not_republish(self):
        """A second publish would mint a new correlation id and orphan the first."""
        req = self._request('confirming')
        with patch.object(type(self.env['cleardeals.pubsub']),
                          'publish_async') as pub:
            with self.assertRaises(UserError):
                req.with_user(self.owner).approve()
        self.assertFalse(pub.called)

    def test_acting_on_a_resolved_request_says_so(self):
        req = self._request('declined')
        with self.assertRaises(UserError) as ctx:
            req.with_user(self.owner).approve()
        self.assertIn('already been declined', str(ctx.exception))

    def test_pending_request_still_approves(self):
        """The happy path is untouched."""
        req = self._request('pending')
        with patch.object(type(self.env['cleardeals.pubsub']), 'publish_async'):
            req.with_user(self.owner).approve()
        self.assertEqual(req.state, 'confirming')
        self.assertTrue(req.request_id)

    def test_pending_request_still_declines(self):
        req = self._request('pending')
        req.with_user(self.owner).decline()
        self.assertEqual(req.state, 'declined')
        self.assertTrue(req.resolved_at)

    def test_permission_check_still_runs_first(self):
        """A stranger gets the access message, not the state message."""
        req = self._request('confirming')
        with self.assertRaises(UserError) as ctx:
            req.with_user(self.asker).decline()
        self.assertIn('Only the current assignee', str(ctx.exception))
