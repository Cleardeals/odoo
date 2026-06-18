"""Tests for the obligation-based By-RM service scorecard.

Covers the assignment-history ledger (write/create hook), the obligation engine
(first-contact vs continuation, hit/miss, clock transfer on reassignment,
automation exclusion), the score/context split, team summary + trend, and the
operations RPC (coverage heatmap + load balance).

All message timestamps sit inside the business window (09:00–19:00 IST + 45m
grace → 02:45–14:15 UTC) so latencies are positive and the 60-minute SLA bites
predictably.
"""

from odoo.tests import tagged

from .common import WaTransactionCase

WIN_FROM = '2026-03-01'
WIN_TO = '2026-04-01'


@tagged('post_install', '-at_install', 'wa_communication')
class TestAssignmentLog(WaTransactionCase):
    """The append-only ownership ledger + its create/write hook."""

    def test_create_unassigned_logs_nothing(self):
        conv = self.make_conversation(assigned_user_id=False)
        self.assertEqual(len(conv.assignment_log_ids), 0)

    def test_create_with_owner_logs_initial(self):
        rm = self.make_user()
        conv = self.make_conversation(assigned_user_id=rm.id)
        self.assertEqual(len(conv.assignment_log_ids), 1)
        self.assertEqual(conv.assignment_log_ids.owner_user_id, rm)

    def test_write_logs_each_change_once(self):
        rm1, rm2 = self.make_user(), self.make_user()
        conv = self.make_conversation(assigned_user_id=False)
        conv.write({'assigned_user_id': rm1.id})
        conv.write({'assigned_user_id': rm2.id})
        conv.write({'assigned_user_id': rm2.id})        # no-op, must not log
        conv.write({'assigned_user_id': False})         # un-assign logs too
        owners = conv.assignment_log_ids.sorted('effective_from').mapped(
            lambda r: r.owner_user_id.id or False)
        self.assertEqual(owners, [rm1.id, rm2.id, False])


@tagged('post_install', '-at_install', 'wa_communication')
class TestObligationScorecard(WaTransactionCase):
    """get_rm_leaderboard + get_rm_operations on deterministic fixtures."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Dash = cls.env['wa.dashboard']
        cls.Log = cls.env['wa.conversation.assignment.log']

    # ── fixture helpers ──────────────────────────────────────────────────────

    def _conv(self, assigned=False):
        return self.make_conversation(assigned_user_id=assigned)

    def _msg(self, conv, occ, direction='inbound', initiator='buyer', **kw):
        vals = dict(direction=direction, initiator=initiator, occurred_at=occ)
        if direction == 'outbound':
            vals.setdefault('kind', 'freetext')
        vals.update(kw)
        return self.make_message(conv, **vals)

    def _alog(self, conv, user, when):
        """Stamp an explicit ownership interval (controls the timeline directly)."""
        return self.Log.sudo().create({
            'conversation_id': conv.id,
            'owner_user_id': user.id if user else False,
            'effective_from': when,
        })

    def _rows(self, date_from=WIN_FROM, date_to=WIN_TO):
        board = self.Dash.get_rm_leaderboard(date_from=date_from, date_to=date_to)
        return board, {r['rm_id']: r for r in board['rows']}

    # ── obligation engine ────────────────────────────────────────────────────

    def test_first_contact_and_continuation_hits(self):
        rm = self.make_user()
        c = self._conv(assigned=rm.id)
        self._msg(c, '2026-03-10 04:30:00')                                   # buyer opens
        self._msg(c, '2026-03-10 04:55:00', direction='outbound', initiator='rm')  # 25m hit
        self._msg(c, '2026-03-10 05:30:00')                                   # buyer again
        self._msg(c, '2026-03-10 05:50:00', direction='outbound', initiator='rm')  # 20m hit

        _, rows = self._rows()
        r = rows[rm.id]
        self.assertEqual(r['obligations'], 2)
        self.assertEqual(r['answered'], 2)
        self.assertEqual(r['reliability'], 100.0)
        self.assertEqual(r['follow_through'], 100.0)
        self.assertEqual(r['ghosts'], 0)
        self.assertEqual(r['sustained'], 1)
        self.assertEqual(r['speed_p90_secs'], 1500.0)   # the first-contact latency

    def test_ghosted_continuation_is_a_miss(self):
        rm = self.make_user()
        c = self._conv(assigned=rm.id)
        self._msg(c, '2026-03-10 04:30:00')                                   # buyer opens
        self._msg(c, '2026-03-10 04:55:00', direction='outbound', initiator='rm')  # first-contact hit
        self._msg(c, '2026-03-10 05:30:00')                                   # buyer again, ghosted

        _, rows = self._rows()
        r = rows[rm.id]
        self.assertEqual(r['obligations'], 2)
        self.assertEqual(r['answered'], 1)
        self.assertEqual(r['reliability'], 50.0)
        self.assertEqual(r['follow_through'], 0.0)
        self.assertEqual(r['ghosts'], 1)

    def test_automation_does_not_satisfy_obligation(self):
        rm = self.make_user()
        c = self._conv(assigned=rm.id)
        self._msg(c, '2026-03-10 04:30:00')                                   # buyer opens
        self._msg(c, '2026-03-10 04:40:00', direction='outbound', initiator='workflow',
                  kind='template')
        self._msg(c, '2026-03-10 04:45:00', direction='outbound', initiator='system',
                  kind='template')
        # No human reply → the obligation stays open and breaches.
        _, rows = self._rows()
        r = rows[rm.id]
        self.assertEqual(r['obligations'], 1)
        self.assertEqual(r['answered'], 0)
        self.assertEqual(r['reliability'], 0.0)

    def test_clock_transfer_credits_owner_at_answer(self):
        rm1, rm2 = self.make_user(), self.make_user()
        c = self._conv(assigned=False)                  # clean timeline
        self._alog(c, rm1, '2026-03-10 04:00:00')
        self._alog(c, rm2, '2026-03-10 04:50:00')       # reassigned before the answer
        self._msg(c, '2026-03-10 04:30:00')                                   # buyer (owner rm1)
        self._msg(c, '2026-03-10 05:00:00', direction='outbound', initiator='rm')  # answer (owner rm2)

        _, rows = self._rows()
        self.assertEqual(rows[rm2.id]['obligations'], 1)
        self.assertEqual(rows[rm2.id]['reliability'], 100.0)
        # rm1 held it when it arrived but handed it off — not on the hook.
        self.assertNotIn(rm1.id, rows)

    def test_clock_transfer_credits_owner_at_breach(self):
        rm1, rm2 = self.make_user(), self.make_user()
        c = self._conv(assigned=False)
        self._alog(c, rm1, '2026-03-10 04:00:00')
        self._alog(c, rm2, '2026-03-10 04:50:00')
        self._msg(c, '2026-03-10 04:30:00')             # buyer, never answered → breach

        _, rows = self._rows()
        # The unanswered chat is on rm2's desk at breach time.
        self.assertEqual(rows[rm2.id]['obligations'], 1)
        self.assertEqual(rows[rm2.id]['reliability'], 0.0)
        self.assertNotIn(rm1.id, rows)

    # ── score vs context ─────────────────────────────────────────────────────

    def test_buyer_reply_rate_is_context_not_attribution(self):
        rm = self.make_user()
        c1 = self._conv(assigned=rm.id)
        self._msg(c1, '2026-03-10 04:30:00', direction='outbound', initiator='rm',
                  sender_user_id=rm.id)
        self._msg(c1, '2026-03-10 04:35:00')            # buyer replies in c1
        c2 = self._conv(assigned=rm.id)
        self._msg(c2, '2026-03-10 05:00:00', direction='outbound', initiator='rm',
                  sender_user_id=rm.id)                 # no buyer reply in c2

        _, rows = self._rows()
        self.assertEqual(rows[rm.id]['buyer_reply_rate'], 50.0)

    # ── team summary + trend ─────────────────────────────────────────────────

    def test_team_summary_and_reliability_trend(self):
        rm = self.make_user()
        # Previous period (one breach → 0% reliability).
        cp = self._conv(assigned=rm.id)
        self._msg(cp, '2026-02-15 04:30:00')            # buyer, never answered
        # Current period (one clean hit → 100% reliability).
        cc = self._conv(assigned=rm.id)
        self._msg(cc, '2026-03-10 04:30:00')
        self._msg(cc, '2026-03-10 04:55:00', direction='outbound', initiator='rm')

        board, rows = self._rows()
        self.assertIn('reliability', board['team'])
        self.assertEqual(board['team']['rm_count'], 1)
        self.assertIn('rms_below_target', board['team'])
        self.assertIn('overdue_now', board['team'])
        # Reliability climbed 0% → 100% = +100 pts.
        self.assertEqual(rows[rm.id]['reliability_delta'], 100.0)

    # ── operations RPC ───────────────────────────────────────────────────────

    def test_operations_heatmap_and_load_shapes(self):
        rm = self.make_user()
        c = self._conv(assigned=rm.id)
        self._msg(c, '2026-03-10 04:30:00')
        self._msg(c, '2026-03-10 04:55:00', direction='outbound', initiator='rm')

        ops = self.Dash.get_rm_operations(date_from=WIN_FROM, date_to=WIN_TO)
        self.assertTrue(ops['heatmap'])
        cell = ops['heatmap'][0]
        self.assertIn('weekday', cell)
        self.assertIn('arrivals', cell)
        self.assertIn('answered', cell)
        self.assertIsInstance(ops['load'], list)
        self.assertIn('business_start', ops)
