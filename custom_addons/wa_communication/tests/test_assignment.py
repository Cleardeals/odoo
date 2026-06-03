"""Tests for chat-assignment ownership gating + reassignment handshake."""

import time
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

_PUBSUB = 'odoo.addons.cleardeals_pubsub.models.pubsub_publisher'


@tagged('post_install', '-at_install', 'wa_communication')
class TestAssignment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Conv = cls.env['wa.conversation']
        cls.Req = cls.env['wa.reassignment.request']
        suffix = str(int(time.time()))
        cls.rm_a = new_test_user(
            cls.env, login=f'asg_a_{suffix}', groups='base.group_user')
        cls.rm_b = new_test_user(
            cls.env, login=f'asg_b_{suffix}', groups='base.group_user')
        cls.manager = new_test_user(
            cls.env, login=f'asg_mgr_{suffix}',
            groups='base.group_user,wa_communication.group_wa_manager')
        cls.conv = cls.Conv.create({
            'phone_number': '919800000001',
            'assigned_user_id': cls.rm_a.id,
        })

    # ── Send gate ─────────────────────────────────────────────────────────────

    def test_assignee_can_send(self):
        with patch.object(type(self.env['cleardeals.pubsub']), 'publish_async'):
            msg = self.conv.with_user(self.rm_a).send_message(
                kind='template', template_name='t')
        self.assertEqual(msg.kind, 'template')

    def test_non_assignee_blocked(self):
        with self.assertRaises(UserError):
            self.conv.with_user(self.rm_b).send_message(
                kind='template', template_name='t')

    def test_manager_can_send_any(self):
        with patch.object(type(self.env['cleardeals.pubsub']), 'publish_async'):
            msg = self.conv.with_user(self.manager).send_message(
                kind='template', template_name='t')
        self.assertEqual(msg.kind, 'template')

    # ── _request_assign does not flip ownership ───────────────────────────────

    def test_request_assign_publishes_without_flipping(self):
        captured = []

        def _pub(self2, topic, payload):
            captured.append(payload)

        with patch.object(type(self.env['cleardeals.pubsub']), 'publish_async', _pub):
            self.conv._request_assign(self.rm_b)
            self.env.cr.postcommit.run()

        self.assertEqual(self.conv.assigned_user_id, self.rm_a,
                         "ownership must NOT flip before confirmation")
        self.assertTrue(self.conv.assignment_pending)
        self.assertEqual(captured[-1]['request_type'], 'assign')
        self.assertEqual(captured[-1]['rm_odoo_id'], self.rm_b.id)

    # ── assignment_confirmed handler ──────────────────────────────────────────

    def test_assignment_confirmed_success_flips(self):
        self.conv.assignment_pending = True
        self.conv._handle_odoo_assignment_confirmed({
            'phone': self.conv.phone_number,
            'rm_odoo_id': self.rm_b.id,
            'success': True,
        }, 'msg-1')
        self.assertEqual(self.conv.assigned_user_id, self.rm_b)
        self.assertFalse(self.conv.assignment_pending)

    def test_assignment_confirmed_failure_keeps_owner(self):
        self.conv.assignment_pending = True
        self.conv._handle_odoo_assignment_confirmed({
            'phone': self.conv.phone_number,
            'rm_odoo_id': self.rm_b.id,
            'success': False,
        }, 'msg-2')
        self.assertEqual(self.conv.assigned_user_id, self.rm_a)
        self.assertFalse(self.conv.assignment_pending)

    # ── Reassignment handshake ────────────────────────────────────────────────

    def test_request_and_approve_flow(self):
        # RM B requests; only the current assignee (RM A) may approve.
        with patch.object(type(self.env['cleardeals.pubsub']), 'publish_async'):
            req_id = self.conv.with_user(self.rm_b).request_assignment(note='please')
        req = self.Req.browse(req_id)
        self.assertEqual(req.state, 'pending')

        # A bystander (not the assignee, not a manager) cannot approve.
        other = new_test_user(self.env, login=f'asg_x_{int(time.time())}',
                              groups='base.group_user')
        with self.assertRaises(UserError):
            req.with_user(other).approve()

        # The assignee approves → request moves to confirming, ownership not yet flipped.
        with patch.object(type(self.env['cleardeals.pubsub']), 'publish_async'):
            req.with_user(self.rm_a).approve()
            self.env.cr.postcommit.run()
        self.assertEqual(req.state, 'confirming')
        self.assertEqual(self.conv.assigned_user_id, self.rm_a)

        # Platform confirms → ownership flips, request approved.
        self.conv._handle_odoo_assignment_confirmed({
            'phone': self.conv.phone_number,
            'rm_odoo_id': self.rm_b.id,
            'request_id': req.request_id,
            'success': True,
        }, 'msg-3')
        self.assertEqual(self.conv.assigned_user_id, self.rm_b)
        self.assertEqual(req.state, 'approved')

    def test_decline(self):
        with patch.object(type(self.env['cleardeals.pubsub']), 'publish_async'):
            req_id = self.conv.with_user(self.rm_b).request_assignment()
        req = self.Req.browse(req_id)
        req.with_user(self.rm_a).decline()
        self.assertEqual(req.state, 'declined')

    def test_unassigned_self_claim(self):
        conv = self.Conv.create({'phone_number': '919800000002'})
        captured = []

        def _pub(self2, topic, payload):
            captured.append(payload)

        with patch.object(type(self.env['cleardeals.pubsub']), 'publish_async', _pub):
            conv.with_user(self.rm_b).action_claim()
            self.env.cr.postcommit.run()
        self.assertTrue(conv.assignment_pending)
        self.assertEqual(captured[-1]['rm_odoo_id'], self.rm_b.id)
