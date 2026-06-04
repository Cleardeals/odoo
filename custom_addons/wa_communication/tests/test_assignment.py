"""Tests for chat-assignment ownership gating + reassignment handshake."""

import time
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
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

    def test_assignment_failure_notifies_requester_and_approver(self):
        """A permanent Interakt failure must tell BOTH parties, with the reason,
        and leave ownership untouched + log a persistent system event."""
        with patch.object(type(self.env['cleardeals.pubsub']), 'publish_async'), \
             patch.object(type(self.env['bus.bus']), '_sendone'):
            req_id = self.conv.with_user(self.rm_b).request_assignment()
            req = self.Req.browse(req_id)
            req.with_user(self.rm_a).approve()
            self.env.cr.postcommit.run()
        self.assertEqual(req.state, 'confirming')

        captured = []
        bus_cls = type(self.env['bus.bus'])
        sys_before = self.env['wa.message'].sudo().search_count([
            ('conversation_id', '=', self.conv.id), ('kind', '=', 'system')])

        def _cap(self2, target, ntype, message):
            captured.append((target, message))

        with patch.object(bus_cls, '_sendone', _cap):
            self.conv._handle_odoo_assignment_confirmed({
                'phone': self.conv.phone_number,
                'rm_odoo_id': self.rm_b.id,
                'request_id': req.request_id,
                'success': False,
                'failure_reason': 'Agent with email not found',
            }, 'fail-1')

        self.assertEqual(req.state, 'failed')
        self.assertFalse(self.conv.assignment_pending)
        self.assertEqual(self.conv.assigned_user_id, self.rm_a,
                         "ownership must stay put on failure")
        targets = [t for (t, _m) in captured]
        self.assertIn('wa_notification_%d' % self.rm_b.id, targets,
                      "requester must be notified of the failure")
        self.assertIn('wa_notification_%d' % self.rm_a.id, targets,
                      "approver must be notified of the failure")
        # The reason is carried through to the toast payload.
        fail_msgs = [m for (_t, m) in captured
                     if isinstance(m, dict) and m.get('type') == 'reassignment_failed']
        self.assertTrue(fail_msgs)
        self.assertTrue(any('Agent with email not found' in (m.get('reason') or '')
                            for m in fail_msgs))
        # A persistent system event is appended to the thread.
        sys_after = self.env['wa.message'].sudo().search_count([
            ('conversation_id', '=', self.conv.id), ('kind', '=', 'system')])
        self.assertEqual(sys_after, sys_before + 1)

    def test_decline(self):
        with patch.object(type(self.env['cleardeals.pubsub']), 'publish_async'):
            req_id = self.conv.with_user(self.rm_b).request_assignment()
        req = self.Req.browse(req_id)
        req.with_user(self.rm_a).decline()
        self.assertEqual(req.state, 'declined')

    def test_request_assignment_when_requester_cannot_read_lead(self):
        """A requester without lead-read rights ('RM See Own') must still be able
        to request a handover — lead display data is read via sudo for the card."""
        rm_grp = 'leads.group_lead_score_rm'
        suffix = str(int(time.time()))
        owner = new_test_user(self.env, login=f'asg_own_{suffix}',
                              groups=f'base.group_user,{rm_grp}',
                              email=f'own_{suffix}@example.com')
        requester = new_test_user(self.env, login=f'asg_req_{suffix}',
                                  groups=f'base.group_user,{rm_grp}',
                                  email=f'req_{suffix}@example.com')
        source = self.env['leads.new']._get_or_create_source('AsgTest')
        lead = self.env['leads.new'].sudo().create({
            'name': 'Secret Lead', 'source_id': source.id, 'user_id': owner.id,
        })
        conv = self.Conv.create({
            'phone_number': '9199' + suffix[-8:],
            'lead_id': lead.id,
            'assigned_user_id': owner.id,
        })
        # Sanity: the requester genuinely cannot read the lead.
        with self.assertRaises(AccessError):
            self.env['leads.new'].with_user(requester).browse(lead.id).read(['name'])

        # The actual fix: requesting must NOT raise an AccessError.
        with patch.object(type(self.env['cleardeals.pubsub']), 'publish_async'), \
             patch.object(type(self.env['bus.bus']), '_sendone'):
            req_id = conv.with_user(requester).request_assignment(note='cover')
        self.assertTrue(req_id)

    def test_request_assignment_notifies_assignee(self):
        """The handover request must push a bus card to the current assignee."""
        captured = []
        bus_cls = type(self.env['bus.bus'])

        def _cap(self2, target, ntype, message):
            captured.append((target, ntype, message))

        with patch.object(bus_cls, '_sendone', _cap), \
             patch.object(type(self.env['cleardeals.pubsub']), 'publish_async'):
            self.conv.with_user(self.rm_b).request_assignment(note='please')

        target = 'wa_notification_%d' % self.rm_a.id
        matches = [m for (t, _n, m) in captured if t == target]
        self.assertTrue(matches, "assignee must receive a bus notification")
        payload = matches[0]
        self.assertEqual(payload['type'], 'reassignment_request')
        self.assertEqual(payload['requester_name'], self.rm_b.name)

    def test_request_assignment_resurfaces_for_duplicate(self):
        """A repeat request must re-notify the assignee, not silently no-op."""
        bus_cls = type(self.env['bus.bus'])
        with patch.object(type(self.env['cleardeals.pubsub']), 'publish_async'):
            with patch.object(bus_cls, '_sendone'):
                first = self.conv.with_user(self.rm_b).request_assignment()
            captured = []
            with patch.object(bus_cls, '_sendone',
                              lambda s, t, n, m: captured.append(t)):
                second = self.conv.with_user(self.rm_b).request_assignment()
        self.assertEqual(first, second, "duplicate returns the same request id")
        self.assertIn('wa_notification_%d' % self.rm_a.id, captured,
                      "duplicate request must still re-notify the assignee")

    def test_get_thread_surfaces_my_open_request(self):
        """Requester's thread flags the pending request (drives the UI wait state)."""
        with patch.object(type(self.env['cleardeals.pubsub']), 'publish_async'), \
             patch.object(type(self.env['bus.bus']), '_sendone'):
            self.conv.with_user(self.rm_b).request_assignment()
        b_thread = self.Conv.with_user(self.rm_b).get_thread(self.conv.id)
        self.assertTrue(b_thread['conversation']['my_open_request'])
        # The assignee has no open request of their own.
        a_thread = self.Conv.with_user(self.rm_a).get_thread(self.conv.id)
        self.assertFalse(a_thread['conversation']['my_open_request'])

    def test_get_thread_surfaces_incoming_requests_to_assignee(self):
        """The assignee must see the pending request in-thread (persistent approval),
        so approval never depends on catching a transient toast."""
        with patch.object(type(self.env['cleardeals.pubsub']), 'publish_async'), \
             patch.object(type(self.env['bus.bus']), '_sendone'):
            req_id = self.conv.with_user(self.rm_b).request_assignment(note='cover me')

        # Assignee (rm_a) sees the actionable request.
        a_inc = self.Conv.with_user(self.rm_a).get_thread(
            self.conv.id)['conversation']['incoming_requests']
        self.assertEqual([r['id'] for r in a_inc], [req_id])
        self.assertEqual(a_inc[0]['requester_name'], self.rm_b.name)
        self.assertEqual(a_inc[0]['note'], 'cover me')

        # A manager (not the assignee) also sees it.
        m_inc = self.Conv.with_user(self.manager).get_thread(
            self.conv.id)['conversation']['incoming_requests']
        self.assertEqual([r['id'] for r in m_inc], [req_id])

        # The requester themselves does NOT see it as actionable.
        b_inc = self.Conv.with_user(self.rm_b).get_thread(
            self.conv.id)['conversation']['incoming_requests']
        self.assertEqual(b_inc, [])

        # A bystander RM sees nothing actionable.
        other = new_test_user(self.env, login=f'asg_by_{int(time.time())}',
                              groups='base.group_user')
        o_inc = self.Conv.with_user(other).get_thread(
            self.conv.id)['conversation']['incoming_requests']
        self.assertEqual(o_inc, [])

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
