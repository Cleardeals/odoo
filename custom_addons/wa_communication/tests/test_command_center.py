"""Tests for the WhatsApp-native Command Center + lens RPCs on wa.dashboard.

Covers the business-hours helper, get_command_center, get_worklists,
get_rm_leaderboard and get_campaign_performance with deterministic fixtures.
"""

from datetime import datetime, timedelta

from odoo import fields
from odoo.tests import tagged

from .common import WaTransactionCase

WIN_FROM = '2026-03-01'
WIN_TO = '2026-04-01'


@tagged('post_install', '-at_install', 'wa_communication')
class TestBusinessHours(WaTransactionCase):
    """`_business_seconds` — company window 09:00–19:00 IST + 45m grace, 7 days."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Dash = cls.env['wa.dashboard']

    def test_within_day(self):
        # 10:00–10:30 IST == 04:30–05:00 UTC, fully inside the window.
        secs = self.Dash._business_seconds(
            datetime(2026, 3, 2, 4, 30), datetime(2026, 3, 2, 5, 0))
        self.assertEqual(secs, 1800.0)

    def test_overnight_counts_only_working_time(self):
        # 18:00 IST day1 → 10:00 IST day2. Window+grace = [08:15, 19:45] IST.
        # day1 18:00–19:45 = 6300s; day2 08:15–10:00 = 6300s → 12600s.
        secs = self.Dash._business_seconds(
            datetime(2026, 3, 2, 12, 30), datetime(2026, 3, 3, 4, 30))
        self.assertEqual(secs, 12600.0)

    def test_grace_buffer_extends_window(self):
        # 19:00–19:40 IST: only on-time because the 45m grace pushes end to 19:45.
        secs = self.Dash._business_seconds(
            datetime(2026, 3, 2, 13, 30), datetime(2026, 3, 2, 14, 10))
        self.assertEqual(secs, 2400.0)

    def test_fully_outside_is_zero(self):
        # 21:00–22:00 IST (15:30–16:30 UTC) is past 19:45 → no working time.
        secs = self.Dash._business_seconds(
            datetime(2026, 3, 2, 15, 30), datetime(2026, 3, 2, 16, 30))
        self.assertEqual(secs, 0.0)


@tagged('post_install', '-at_install', 'wa_communication')
class TestCommandCenterRPCs(WaTransactionCase):
    """Command Center KPIs, worklists, RM and campaign lenses."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Dash = cls.env['wa.dashboard']

    # ── fixture helpers ──────────────────────────────────────────────────────

    def _prop(self):
        return self.env['property.base'].sudo().create({
            'name': 'P ' + self._uniq(), 'property_tag': self._uniq('T'),
            'uuid': self._uniq('u'), 'prop_id': self._uniq('p'),
        })

    def _inq(self, prop, status='lead'):
        return self.make_lead(property_base_id=prop.id, current_status=status)

    def _conv(self, assigned=None):
        kw = {} if assigned is None else {'assigned_user_id': assigned}
        return self.make_conversation(**kw)

    def _msg(self, conv, occ, direction='inbound', initiator='buyer', lead=None, **kw):
        vals = dict(direction=direction, initiator=initiator, occurred_at=occ)
        if lead is not None:
            vals['lead_id'] = lead.id
        vals.update(kw)
        if direction == 'outbound':
            vals.setdefault('kind', 'freetext')
        return self.make_message(conv, **vals)

    # ── Command Center ───────────────────────────────────────────────────────

    def test_command_center_core_kpis(self):
        prop = self._prop()
        a = self._inq(prop)
        b = self._inq(prop)
        c = self._inq(prop)   # never messaged; only sends an unprompted inbound
        # a: messaged + replied + RM response (business hours, ~30 min)
        ca = self._conv()
        self._msg(ca, '2026-03-10 04:30:00', direction='outbound', initiator='rm',
                  lead=a, status='read', cost_inr=1.0)        # 10:00 IST
        self._msg(ca, '2026-03-10 04:35:00', direction='inbound', initiator='buyer', lead=a)
        self._msg(ca, '2026-03-10 05:00:00', direction='outbound', initiator='rm',
                  lead=a, status='delivered', cost_inr=1.0)    # reply 25m later
        # b: messaged, never replied + one failure
        cb = self._conv()
        self._msg(cb, '2026-03-11 05:00:00', direction='outbound', initiator='rm',
                  lead=b, status='delivered', cost_inr=1.0)
        self._msg(cb, '2026-03-11 06:00:00', direction='outbound', initiator='rm',
                  lead=b, status='failed', cost_inr=0.0)
        # an unprompted buyer inbound (lead we never messaged) must NOT push reply rate >100%
        cc = self._conv()
        self._msg(cc, '2026-03-12 05:00:00', direction='inbound', initiator='buyer', lead=c)

        cc_data = self.Dash.get_command_center(date_from=WIN_FROM, date_to=WIN_TO)
        # messaged = {a, b}; replied-to-us = {a}  → 50%
        self.assertEqual(cc_data['reply_rate'], 50.0)
        self.assertEqual(cc_data['replied'], 1)
        self.assertEqual(cc_data['leads_messaged'], 2)
        self.assertEqual(cc_data['msgs_sent'], 4)       # 3 rm sends counted + the failed one
        self.assertEqual(cc_data['failed'], 1)
        self.assertEqual(cc_data['spend'], 3.0)
        self.assertEqual(cc_data['cost_per_reply'], 3.0)
        self.assertEqual(cc_data['first_response_median'], 1500.0)  # 25 min, in business hrs
        self.assertEqual(cc_data['sla_pct'], 100.0)     # within 60-min SLA
        self.assertIn('deltas', cc_data)
        self.assertEqual(cc_data['sla_minutes'], 60)
        # Channel-health fields the Command Center cards now render.
        self.assertEqual(cc_data['failed_breakdown'], {'Failed': 1})
        self.assertEqual(cc_data['blocks'], 0)
        self.assertEqual(cc_data['opt_out_rate'], 0.0)
        self.assertEqual(cc_data['delta_units']['opt_out_rate'], 'pts')

    def test_command_center_empty_window_no_crash(self):
        # No messages / no responses → median is None; deltas must be None, not crash.
        cc = self.Dash.get_command_center(date_from='2025-01-01', date_to='2025-02-01')
        self.assertEqual(cc['reply_rate'], 0.0)
        self.assertIsNone(cc['first_response_median'])
        # median has no data in either period → % delta is None
        self.assertIsNone(cc['deltas']['first_response_median'])
        # reply rate is a points delta: 0% vs 0% = 0.0 pts (not None)
        self.assertEqual(cc['deltas']['reply_rate'], 0.0)
        self.assertEqual(cc['delta_units']['reply_rate'], 'pts')

    def test_trends_granularity_adapts_to_range(self):
        # An outbound + a buyer reply on a single day.
        ca = self._conv()
        a = self._inq(self._prop())
        self._msg(ca, '2026-03-10 05:00:00', direction='outbound', initiator='rm',
                  lead=a, status='delivered', cost_inr=1.0)
        self._msg(ca, '2026-03-10 05:30:00', direction='inbound', initiator='buyer', lead=a)

        # ≤2-day range → hourly buckets (also a regression guard for the hourly SQL).
        hourly = self.Dash.get_trends(
            date_from='2026-03-10T00:00:00', date_to='2026-03-10T23:59:59')
        self.assertTrue(hourly)
        self.assertEqual(hourly[0]['granularity'], 'hour')
        self.assertTrue(any(r['sent'] for r in hourly))
        self.assertTrue(any(r['replies'] for r in hourly))

        # Longer range → daily buckets.
        daily = self.Dash.get_trends(
            date_from='2026-03-08T00:00:00', date_to='2026-03-13T00:00:00')
        self.assertEqual(daily[0]['granularity'], 'day')

    # ── Worklists ────────────────────────────────────────────────────────────

    def test_worklists_needs_reply(self):
        a = self._inq(self._prop())
        b = self._inq(self._prop())
        recent = fields.Datetime.now() - timedelta(hours=2)
        old = fields.Datetime.now() - timedelta(days=2)
        # unanswered: latest message is a buyer inbound
        c1 = self._conv()
        self._msg(c1, recent, direction='inbound', initiator='buyer', lead=a)
        # answered: latest is an RM outbound → excluded
        c2 = self._conv()
        self._msg(c2, old, direction='inbound', initiator='buyer', lead=b)
        self._msg(c2, fields.Datetime.now() - timedelta(hours=1),
                  direction='outbound', initiator='rm', lead=b)

        wl = self.Dash.get_worklists()
        conv_ids = [r['conversation_id'] for r in wl['needs_reply']['rows']]
        self.assertIn(c1.id, conv_ids)
        self.assertNotIn(c2.id, conv_ids)
        self.assertGreaterEqual(wl['needs_reply']['buckets']['0-4h'], 1)

    def test_worklists_unassigned(self):
        a = self._inq(self._prop())
        c = self.make_conversation(assigned_user_id=False)
        c.write({'last_message_at': fields.Datetime.now() - timedelta(hours=3)})
        self._msg(c, fields.Datetime.now() - timedelta(hours=3),
                  direction='inbound', initiator='buyer', lead=a)
        wl = self.Dash.get_worklists()
        self.assertIn(c.id, [r['conversation_id'] for r in wl['unassigned']['rows']])

    # ── By RM ────────────────────────────────────────────────────────────────

    def test_rm_leaderboard_attribution(self):
        rm1 = self.make_user()
        rm2 = self.make_user()
        prop = self._prop()
        a, b = self._inq(prop), self._inq(prop)
        # rm1 conversation: replied (credited via sender_user_id)
        c1 = self._conv(assigned=rm1.id)
        self._msg(c1, '2026-03-10 04:30:00', direction='outbound', initiator='rm',
                  lead=a, sender_user_id=rm1.id, status='read', cost_inr=2.0)
        self._msg(c1, '2026-03-10 04:35:00', direction='inbound', initiator='buyer', lead=a)
        self._msg(c1, '2026-03-10 05:00:00', direction='outbound', initiator='rm',
                  lead=a, sender_user_id=rm1.id, status='delivered', cost_inr=1.0)
        # rm2 conversation: messaged, no reply
        c2 = self._conv(assigned=rm2.id)
        self._msg(c2, '2026-03-11 05:00:00', direction='outbound', initiator='rm',
                  lead=b, sender_user_id=rm2.id, status='delivered', cost_inr=1.0)

        rows = {r['rm_id']: r for r in self.Dash.get_rm_leaderboard(
            date_from=WIN_FROM, date_to=WIN_TO)['rows']}
        self.assertEqual(rows[rm1.id]['reply_rate'], 100.0)
        self.assertEqual(rows[rm1.id]['spend'], 3.0)
        self.assertEqual(rows[rm1.id]['first_response_median'], 1500.0)
        self.assertEqual(rows[rm2.id]['reply_rate'], 0.0)
        # rm1 (higher reply rate) sorts first
        first = self.Dash.get_rm_leaderboard(date_from=WIN_FROM, date_to=WIN_TO)['rows'][0]
        self.assertEqual(first['rm_id'], rm1.id)

    # ── By Campaign / Template ───────────────────────────────────────────────

    def test_campaign_performance(self):
        prop = self._prop()
        a, b = self._inq(prop), self._inq(prop)
        cc = self._conv()
        # workflow 'nurture' + template 'welcome_v1': one replied, one not
        self._msg(cc, '2026-03-10 05:00:00', direction='outbound', initiator='workflow',
                  lead=a, kind='template', workflow_slug='nurture',
                  template_name='welcome_v1', status='read', cost_inr=0.8)
        self._msg(cc, '2026-03-10 05:05:00', direction='inbound', initiator='buyer', lead=a)
        cc2 = self._conv()
        self._msg(cc2, '2026-03-11 05:00:00', direction='outbound', initiator='workflow',
                  lead=b, kind='template', workflow_slug='nurture',
                  template_name='welcome_v1', status='opted_out', cost_inr=0.8)

        perf = self.Dash.get_campaign_performance(date_from=WIN_FROM, date_to=WIN_TO)
        wf = {r['name']: r for r in perf['workflows']}['nurture']
        self.assertEqual(wf['sent'], 2)
        self.assertEqual(wf['leads'], 2)
        self.assertEqual(wf['reply_rate'], 50.0)   # a replied, b didn't
        self.assertEqual(wf['opt_out'], 1)
        self.assertEqual(wf['cost'], 1.6)
        # Workflow rows carry the pause/resume control fields + a failure rate.
        self.assertIn('id', wf)
        self.assertIn('is_active', wf)
        self.assertEqual(wf['failure_rate'], 50.0)   # the opted-out send counts as failed
        tpl = {r['name']: r for r in perf['templates']}['welcome_v1']
        self.assertEqual(tpl['sent'], 2)
