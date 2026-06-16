"""Tests for the "By Property" WhatsApp engagement dashboard.

The test environment carries almost no real per-property message data, so this
suite seeds every case deterministically and asserts exact numbers.  It covers
the three ``wa.dashboard`` RPC methods — ``get_property_engagement``,
``get_inquiry_engagement``, ``get_whatsapp_rescue`` — plus the
``hard_to_reach_since`` capture that the rescue metric depends on.

Conventions: see ``.claude/skills/writing-odoo-tests`` and ``tests/common.py``.
Key facts the fixtures rely on:
* a wa.message rolls up to a property/inquiry via the *stored* computed
  ``effective_property_id`` / ``effective_inquiry_id`` = ``segment_id.inquiry_id
  or lead_id`` — so attribution can come from either ``lead_id`` or a segment;
* outcomes are read from ``lead.site.visit`` (+ its status flags), whose statuses
  are seeded with external ids ``leads.lead_site_visit_status_*``;
* ``hard_to_reach_since`` is stamped (never cleared) when ``current_status``
  enters ringing/call-back/busy/switched-off.
"""

from datetime import datetime, timedelta

from odoo.tests import tagged

from .common import WaTransactionCase

# A fixed analysis window; all "in-window" message times sit inside it.
WIN_FROM = '2026-03-01'
WIN_TO = '2026-04-01'
IN_WIN = '2026-03-10 10:00:00'
# A wide window for rescue tests (cohort keyed on hard_to_reach_since).
WIDE_FROM = '2026-01-01'
WIDE_TO = '2026-12-31'


@tagged('post_install', '-at_install', 'wa_communication')
class TestPropertyDashboard(WaTransactionCase):
    """Per-property / per-inquiry engagement + the WhatsApp-rescue metric."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Dash = cls.env['wa.dashboard']
        cls.rm = cls.make_user()

    # ── fixture helpers ──────────────────────────────────────────────────────

    _pseq = 0

    def _prop(self, tag='PROP'):
        return self.env['property.base'].sudo().create({
            'name': 'Property %s' % tag,
            'property_tag': tag,
            'uuid': self._uniq('uuid_'),
            'prop_id': self._uniq('pid_'),
        })

    def _inq(self, prop, phone=None, inquiry_type='primary', status='lead'):
        return self.make_lead(
            property_base_id=prop.id,
            user_id=self.rm.id,
            inquiry_type=inquiry_type,
            current_status=status,
            **({'phone': phone} if phone else {}),
        )

    def _conv(self, phone=None):
        return self.make_conversation(phone_number=phone or self._uniq_phone())

    def _msg(self, conv, occurred_at=IN_WIN, direction='inbound',
             initiator='buyer', lead=None, **kw):
        vals = {'direction': direction, 'initiator': initiator,
                'occurred_at': occurred_at}
        if lead is not None:
            vals['lead_id'] = lead.id
        vals.update(kw)
        if direction == 'outbound':
            vals.setdefault('kind', 'freetext')
        return self.make_message(conv, **vals)

    def _segment(self, conv, inquiry):
        return self.env['wa.conversation.segment'].sudo().create({
            'conversation_id': conv.id,
            'inquiry_id': inquiry.id,
            'started_by': 'rm',
        })

    def _visit(self, inquiry, code='completed', scheduled='2026-03-15 10:00:00'):
        status = self.env.ref('leads.lead_site_visit_status_%s' % code)
        return self.env['lead.site.visit'].sudo().create({
            'inquiry_id': inquiry.id,
            'status_id': status.id,
            'scheduled_datetime': scheduled,
        })

    def _engagement(self, **kw):
        kw.setdefault('date_from', WIN_FROM)
        kw.setdefault('date_to', WIN_TO)
        return self.Dash.get_property_engagement(**kw)

    def _row_for(self, result, prop):
        pid = prop.id if prop else False
        for r in result['rows']:
            if r['property_id'] == pid:
                return r
        return None

    # ── 1. per-property aggregates ───────────────────────────────────────────

    def test_01_property_aggregates(self):
        prop = self._prop('A1')
        inq = self._inq(prop)
        conv = self._conv()
        self._msg(conv, direction='outbound', initiator='rm', lead=inq, cost_inr=1.5)
        self._msg(conv, occurred_at='2026-03-11 09:00:00',
                  direction='outbound', initiator='rm', lead=inq)
        self._msg(conv, occurred_at='2026-03-12 09:00:00',
                  direction='inbound', initiator='buyer', lead=inq)

        row = self._row_for(self._engagement(), prop)
        self.assertIsNotNone(row)
        self.assertEqual(row['messages_total'], 3)
        self.assertEqual(row['inbound'], 1)
        self.assertEqual(row['outbound'], 2)
        self.assertEqual(row['leads_engaged'], 1)
        self.assertEqual(row['replied'], 1)
        self.assertEqual(row['cost'], 1.5)
        self.assertTrue(row['last_activity'].startswith('2026-03-12'))

    # ── 2. ranking + paging ──────────────────────────────────────────────────

    def test_02_ranking_and_paging(self):
        pa, pb, pc = self._prop('RA'), self._prop('RB'), self._prop('RC')
        for prop, n in ((pa, 5), (pb, 2), (pc, 1)):
            inq = self._inq(prop)
            conv = self._conv()
            for _i in range(n):
                self._msg(conv, direction='outbound', initiator='rm', lead=inq)

        res = self._engagement(sort='messages')
        order = [r['property_id'] for r in res['rows']]
        self.assertEqual(order[:3], [pa.id, pb.id, pc.id])
        self.assertEqual(res['total'], 3)

        first_two = self._engagement(sort='messages', limit=2)
        self.assertEqual([r['property_id'] for r in first_two['rows']], [pa.id, pb.id])
        self.assertEqual(first_two['total'], 3)

        paged = self._engagement(sort='messages', limit=2, offset=1)
        self.assertEqual([r['property_id'] for r in paged['rows']], [pb.id, pc.id])

    def test_02b_sort_by_cost(self):
        pa, pb = self._prop('CA'), self._prop('CB')
        ia, ib = self._inq(pa), self._inq(pb)
        ca, cb = self._conv(), self._conv()
        self._msg(ca, direction='outbound', initiator='rm', lead=ia, cost_inr=1.0)
        self._msg(cb, direction='outbound', initiator='rm', lead=ib, cost_inr=9.0)
        rows = self._engagement(sort='cost')['rows']
        self.assertEqual(rows[0]['property_id'], pb.id)

    # ── 3. date window ───────────────────────────────────────────────────────

    def test_03_date_window(self):
        prop = self._prop('W')
        inq = self._inq(prop)
        conv = self._conv()
        self._msg(conv, occurred_at='2026-03-01 00:00:00', lead=inq)   # included (>=from)
        self._msg(conv, occurred_at=IN_WIN, lead=inq)                  # included
        self._msg(conv, occurred_at='2026-02-15 10:00:00', lead=inq)   # before window
        self._msg(conv, occurred_at='2026-04-01 00:00:00', lead=inq)   # ==to, excluded (<)

        row = self._row_for(self._engagement(), prop)
        self.assertEqual(row['messages_total'], 2)

    # ── 4. attribution via segment + re-point ────────────────────────────────

    def test_04_segment_attribution_and_repoint(self):
        pa, pb, pc = self._prop('SA'), self._prop('SB'), self._prop('SC')
        ia, ib, ic = self._inq(pa), self._inq(pb), self._inq(pc)
        conv = self._conv()
        # Message routed (lead_id) to A, but a segment re-files it under B.
        seg = self._segment(conv, ib)
        msg = self._msg(conv, lead=ia, segment_id=seg.id)
        # A second message attributed only by lead_id stays on A.
        self._msg(conv, occurred_at='2026-03-11 10:00:00', lead=ia)

        res = self._engagement()
        self.assertEqual(self._row_for(res, pb)['messages_total'], 1)
        self.assertEqual(self._row_for(res, pa)['messages_total'], 1)
        self.assertIsNone(self._row_for(res, pc))

        # Re-point the segment to C — the message moves with it.
        seg.inquiry_id = ic.id
        msg.invalidate_recordset(['effective_property_id', 'effective_inquiry_id'])
        res2 = self._engagement()
        self.assertEqual(self._row_for(res2, pc)['messages_total'], 1)
        self.assertIsNone(self._row_for(res2, pb))
        self.assertEqual(self._row_for(res2, pa)['messages_total'], 1)

    # ── 5. unassigned bucket ─────────────────────────────────────────────────

    def test_05_unassigned_bucket(self):
        conv = self._conv()
        self._msg(conv)  # no lead, no segment -> no property
        row = self._row_for(self._engagement(), None)
        self.assertIsNotNone(row)
        self.assertEqual(row['property_name'], 'Unassigned')
        self.assertEqual(row['messages_total'], 1)
        self.assertEqual(row['leads_engaged'], 0)

    # ── 6. one phone, two properties ─────────────────────────────────────────

    def test_06_one_phone_two_properties(self):
        pa, pb = self._prop('PA'), self._prop('PB')
        ia = self._inq(pa, phone='9123456780')
        ib = self._inq(pb, phone='9123456780')
        conv = self._conv(phone='919123456780')
        self._msg(conv, lead=ia)
        self._msg(conv, occurred_at='2026-03-11 10:00:00', lead=ib)

        res = self._engagement()
        self.assertEqual(self._row_for(res, pa)['messages_total'], 1)
        self.assertEqual(self._row_for(res, pb)['messages_total'], 1)

    # ── 7. first-response latency + median ───────────────────────────────────

    def test_07_first_response_latency(self):
        prop = self._prop('RT')
        i1, i2, i3, i4 = (self._inq(prop) for _ in range(4))
        c1, c2, c3, c4 = (self._conv() for _ in range(4))
        # i1: buyer 10:00 -> rm 10:00:30  => 30s
        self._msg(c1, occurred_at='2026-03-10 10:00:00', lead=i1)
        self._msg(c1, occurred_at='2026-03-10 10:00:30',
                  direction='outbound', initiator='rm', lead=i1)
        # i2: buyer only => None
        self._msg(c2, occurred_at='2026-03-10 10:00:00', lead=i2)
        # i3: rm before any buyer => None
        self._msg(c3, occurred_at='2026-03-10 09:00:00',
                  direction='outbound', initiator='rm', lead=i3)
        self._msg(c3, occurred_at='2026-03-10 10:00:00', lead=i3)
        # i4: buyer 10:00, buyer 10:05, rm 10:10 => 600s (from first inbound)
        self._msg(c4, occurred_at='2026-03-10 10:00:00', lead=i4)
        self._msg(c4, occurred_at='2026-03-10 10:05:00', lead=i4)
        self._msg(c4, occurred_at='2026-03-10 10:10:00',
                  direction='outbound', initiator='rm', lead=i4)

        drill = {r['inquiry_id']: r
                 for r in self.Dash.get_inquiry_engagement(prop.id, WIN_FROM, WIN_TO)}
        self.assertEqual(drill[i1.id]['response_secs'], 30.0)
        self.assertIsNone(drill[i2.id]['response_secs'])
        self.assertIsNone(drill[i3.id]['response_secs'])
        self.assertEqual(drill[i4.id]['response_secs'], 600.0)

        # median of [30, None, None, 600] -> median([30, 600]) = 315
        row = self._row_for(self._engagement(), prop)
        self.assertEqual(row['response_secs_median'], 315.0)

    # ── 8. reply rate + divide-by-zero guard ─────────────────────────────────

    def test_08_reply_rate(self):
        prop = self._prop('RR')
        i1, i2 = self._inq(prop), self._inq(prop)
        c1, c2 = self._conv(), self._conv()
        self._msg(c1, lead=i1)  # buyer inbound -> replied
        self._msg(c2, direction='outbound', initiator='rm', lead=i2)  # no reply
        row = self._row_for(self._engagement(), prop)
        self.assertEqual(row['leads_engaged'], 2)
        self.assertEqual(row['replied'], 1)
        self.assertEqual(row['reply_rate'], 50.0)

        # Unassigned bucket has 0 engaged inquiries -> rate guard yields 0.0.
        conv = self._conv()
        self._msg(conv)
        urow = self._row_for(self._engagement(), None)
        self.assertEqual(urow['reply_rate'], 0.0)

    # ── 9. outcomes from lead.site.visit ─────────────────────────────────────

    def test_09_outcomes_from_site_visit(self):
        prop = self._prop('OUT')
        done = self._inq(prop)
        sched = self._inq(prop)
        cancel = self._inq(prop)
        noshow = self._inq(prop)
        resched = self._inq(prop)
        no_wa = self._inq(prop)  # has a completed visit but NO WhatsApp message

        for inq in (done, sched, cancel, noshow, resched):
            conv = self._conv()
            self._msg(conv, lead=inq)

        self._visit(done, 'completed')
        self._visit(sched, 'scheduled')
        self._visit(cancel, 'cancelling')
        self._visit(noshow, 'did_not_show_up')
        # reschedule-style chain: a cancelled attempt then a completed one.
        self._visit(resched, 'cancelling', scheduled='2026-03-14 10:00:00')
        self._visit(resched, 'completed', scheduled='2026-03-16 10:00:00')
        # no_wa: completed visit, but excluded because it never engaged on WA.
        self._visit(no_wa, 'completed')

        row = self._row_for(self._engagement(), prop)
        self.assertEqual(row['leads_engaged'], 5)        # no_wa excluded
        self.assertEqual(row['visits_done'], 2)          # done + resched, counted once each
        self.assertEqual(row['visits_scheduled'], 1)     # sched (cancelled/no-show not 'done')
        self.assertEqual(row['conversion_rate'], 40.0)   # 2 / 5

    # ── 10. cost ─────────────────────────────────────────────────────────────

    def test_10_cost(self):
        prop = self._prop('COST')
        inq = self._inq(prop)
        conv = self._conv()
        self._msg(conv, direction='outbound', initiator='rm', lead=inq, cost_inr=1.25)
        self._msg(conv, occurred_at='2026-03-11 10:00:00',
                  direction='outbound', initiator='rm', lead=inq, cost_inr=2.5)
        self._msg(conv, occurred_at='2026-03-12 10:00:00', lead=inq)  # no cost
        row = self._row_for(self._engagement(), prop)
        self.assertEqual(row['cost'], 3.75)

        # property with only zero-cost messages -> 0.0
        p2 = self._prop('COST0')
        i2 = self._inq(p2)
        c2 = self._conv()
        self._msg(c2, lead=i2)
        self.assertEqual(self._row_for(self._engagement(), p2)['cost'], 0.0)

    # ── 11. drill-down ───────────────────────────────────────────────────────

    def test_11_inquiry_drilldown(self):
        prop = self._prop('DR')
        primary = self._inq(prop, inquiry_type='primary')
        recommended = self._inq(prop, inquiry_type='recommended')
        conv = self._conv()
        # primary spans two segments (both pointing at it) -> aggregated to one row.
        s1, s2 = self._segment(conv, primary), self._segment(conv, primary)
        self._msg(conv, lead=primary, segment_id=s1.id)
        self._msg(conv, occurred_at='2026-03-11 10:00:00', lead=primary, segment_id=s2.id)
        self._msg(conv, occurred_at='2026-03-12 10:00:00', lead=recommended)

        rows = self.Dash.get_inquiry_engagement(prop.id, WIN_FROM, WIN_TO)
        by_inq = {r['inquiry_id']: r for r in rows}
        self.assertEqual(set(by_inq), {primary.id, recommended.id})
        self.assertEqual(by_inq[primary.id]['messages_total'], 2)
        self.assertEqual(by_inq[primary.id]['inquiry_type'], 'primary')
        self.assertEqual(by_inq[recommended.id]['inquiry_type'], 'recommended')
        self.assertTrue(by_inq[primary.id]['conversation_id'])

        # unknown property id -> []
        self.assertEqual(self.Dash.get_inquiry_engagement(0, WIN_FROM, WIN_TO), [])

    # ── 12. empty / edge / search ────────────────────────────────────────────

    def test_12_empty_and_search(self):
        # Empty window (no messages at all in 2025) -> no rows, no error.
        empty = self.Dash.get_property_engagement(date_from='2025-01-01', date_to='2025-02-01')
        self.assertEqual(empty['rows'], [])
        self.assertEqual(empty['total'], 0)

        pa = self._prop('GREENVALLEY')
        pb = self._prop('BLUELAKE')
        ia, ib = self._inq(pa), self._inq(pb)
        ca, cb = self._conv(), self._conv()
        self._msg(ca, lead=ia)
        self._msg(cb, lead=ib)
        res = self._engagement(search='green')
        self.assertEqual([r['property_id'] for r in res['rows']], [pa.id])

    # ── 13. workflow filter ──────────────────────────────────────────────────

    def test_13_workflow_filter(self):
        prop = self._prop('WF')
        inq = self._inq(prop)
        conv = self._conv()
        self._msg(conv, direction='outbound', initiator='workflow', lead=inq,
                  kind='template', workflow_slug='nurturing')
        self._msg(conv, occurred_at='2026-03-11 10:00:00',
                  direction='outbound', initiator='workflow', lead=inq,
                  kind='template', workflow_slug='post_visit')

        res = self._engagement(workflow_slugs=['nurturing'])
        self.assertEqual(self._row_for(res, prop)['messages_total'], 1)

    # ── 14. hard_to_reach_since capture ──────────────────────────────────────

    def test_14_hard_to_reach_capture(self):
        inq = self._inq(self._prop('HTR'))
        self.assertFalse(inq.hard_to_reach_since)

        inq.current_status = 'ringing'           # enter -> stamped
        first = inq.hard_to_reach_since
        self.assertTrue(first)

        inq.current_status = 'busy'              # within set -> unchanged
        self.assertEqual(inq.hard_to_reach_since, first)

        inq.current_status = 'site_visit_scheduled'  # leave -> retained (not cleared)
        self.assertEqual(inq.hard_to_reach_since, first)

        # Re-entry after recovering re-stamps to a newer time.
        inq.with_context(wa_skip_htr=True).hard_to_reach_since = datetime(2020, 1, 1)
        inq.current_status = 'lead'
        inq.current_status = 'call_back_later'   # re-enter from non-hard
        self.assertGreater(inq.hard_to_reach_since, datetime(2020, 1, 1))

    # ── 15-20. WhatsApp rescue metric ────────────────────────────────────────

    def _rescue_lead(self, prop, stuck='2026-03-01 00:00:00'):
        """An inquiry stamped hard-to-reach at *stuck*, with a conversation."""
        inq = self._inq(prop)
        inq.with_context(wa_skip_htr=True).hard_to_reach_since = stuck
        return inq, self._conv()

    def _rescue(self, **kw):
        kw.setdefault('date_from', WIDE_FROM)
        kw.setdefault('date_to', WIDE_TO)
        return self.Dash.get_whatsapp_rescue(**kw)

    def test_15_rescue_positive(self):
        prop = self._prop('R15')
        inq, conv = self._rescue_lead(prop)
        # buyer replied after becoming stuck, then a visit was booked (now) & completed.
        self._msg(conv, occurred_at='2026-03-02 10:00:00', lead=inq)
        self._visit(inq, 'completed')

        out = self._rescue()['overall']
        self.assertEqual(out['cohort'], 1)
        self.assertEqual(out['rescue_engaged'], 1)
        self.assertEqual(out['rescued'], 1)
        self.assertEqual(out['rescued_to_visit'], 1)
        self.assertEqual(out['rescue_engagement_rate'], 100.0)
        self.assertEqual(out['wa_attributed_close_rate'], 100.0)

    def test_16_rescue_negative_ordering(self):
        prop = self._prop('R16')
        inq, conv = self._rescue_lead(prop)
        # Visit booked now (June 2026); buyer "reply" timestamped AFTER it (2027)
        # -> WA reply did not precede progression -> not attributed.
        self._visit(inq, 'completed')
        self._msg(conv, occurred_at='2027-01-01 10:00:00', lead=inq)

        out = self._rescue()['overall']
        self.assertEqual(out['cohort'], 1)
        self.assertEqual(out['rescue_engaged'], 1)   # replied after stuck
        self.assertEqual(out['rescued'], 0)          # but not before progression

    def test_17_rescue_engaged_no_progress(self):
        prop = self._prop('R17')
        inq, conv = self._rescue_lead(prop)
        self._msg(conv, occurred_at='2026-03-02 10:00:00', lead=inq)  # replied, no visit
        out = self._rescue()['overall']
        self.assertEqual(out['rescue_engaged'], 1)
        self.assertEqual(out['rescued'], 0)

    def test_18_rescue_progressed_without_wa(self):
        prop = self._prop('R18')
        inq, conv = self._rescue_lead(prop)
        # No buyer WA reply at all, but a visit happened.
        self._msg(conv, occurred_at='2026-03-02 10:00:00',
                  direction='outbound', initiator='rm', lead=inq)
        self._visit(inq, 'completed')
        out = self._rescue()['overall']
        self.assertEqual(out['cohort'], 1)
        self.assertEqual(out['rescue_engaged'], 0)
        self.assertEqual(out['rescued'], 0)

    def test_19_rescue_never_stuck(self):
        prop = self._prop('R19')
        inq = self._inq(prop)  # never hard-to-reach -> hard_to_reach_since unset
        conv = self._conv()
        self._msg(conv, occurred_at='2026-03-02 10:00:00', lead=inq)
        self._visit(inq, 'completed')
        out = self._rescue()['overall']
        self.assertEqual(out['cohort'], 0)
        self.assertEqual(out['rescued'], 0)

    def test_20_rescue_rates_and_guards(self):
        # Empty cohort -> rates are 0, never divide-by-zero.
        out = self._rescue(date_from='2024-01-01', date_to='2024-02-01')['overall']
        self.assertEqual(out['cohort'], 0)
        self.assertEqual(out['rescue_engagement_rate'], 0.0)
        self.assertEqual(out['wa_attributed_close_rate'], 0.0)

        # Two stuck, one engaged, that one not yet to a completed visit:
        prop = self._prop('R20')
        i1, c1 = self._rescue_lead(prop)
        i2, _c2 = self._rescue_lead(prop)
        self._msg(c1, occurred_at='2026-03-02 10:00:00', lead=i1)
        self._visit(i1, 'scheduled')  # booked after reply but not completed
        out = self._rescue()['overall']
        self.assertEqual(out['cohort'], 2)
        self.assertEqual(out['rescue_engaged'], 1)
        self.assertEqual(out['rescue_engagement_rate'], 50.0)
        self.assertEqual(out['rescued'], 1)
        self.assertEqual(out['rescued_to_visit'], 0)
        self.assertEqual(out['wa_attributed_close_rate'], 0.0)
