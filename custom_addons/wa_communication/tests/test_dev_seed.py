"""Validates the dev seed/purge tool (`tools/dev_seed.py`).

The tool is run by hand against the dev DB, but this test exercises it on the
throwaway test DB so we know it executes cleanly and produces the documented,
hand-verifiable dashboard numbers — and that purge fully removes it.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from ..tools import dev_seed
from .common import WaTransactionCase


@tagged('post_install', '-at_install', 'wa_communication')
class TestDevSeed(WaTransactionCase):
    """seed() builds a correct demo slice; purge() removes it completely."""

    def _window(self):
        # Date-only strings (the format _parse_date accepts besides ISO-'T').
        now = fields.Datetime.now()
        return (now - timedelta(days=1)).strftime('%Y-%m-%d'), (now + timedelta(days=1)).strftime('%Y-%m-%d')

    def test_seed_then_purge(self):
        Dash = self.env['wa.dashboard']
        d_from, d_to = self._window()

        result = dev_seed.seed(self.env)
        props = result['properties']
        self.assertEqual(len(props), 5)

        eng = Dash.get_property_engagement(date_from=d_from, date_to=d_to)
        rows = {r['property_id']: r for r in eng['rows']}
        self.assertTrue(set(props.values()).issubset(set(rows)))

        # ── Unassigned bucket is surfaced, not dropped ──
        self.assertIn(False, rows)
        self.assertEqual(rows[False]['property_name'], 'Unassigned')

        # ── P2 Heights: b1/b2/b3 + the shared-phone inquiry m2 = 4 engaged;
        #    only b1 converted (m2's visit is just scheduled) ──
        p2 = rows[props['Demo Heights']]
        self.assertEqual(p2['leads_engaged'], 4)
        self.assertEqual(p2['visits_done'], 1)
        self.assertEqual(p2['conversion_rate'], 25.0)

        # ── P4 Riverside: reschedule chain + 2-attempt both count once each;
        #    the scheduled-then-cancelled lead is NOT a conversion ──
        p4 = rows[props['Demo Riverside']]
        self.assertEqual(p4['leads_engaged'], 3)      # r1, r2, r3
        self.assertEqual(p4['visits_done'], 2)        # r1 (rescheduled→completed) + r2 (completed)
        self.assertEqual(p4['conversion_rate'], 66.7)

        # ── P5 Skyline: no-show / scheduled / completed ──
        p5 = rows[props['Demo Skyline']]
        self.assertEqual(p5['leads_engaged'], 3)
        self.assertEqual(p5['visits_done'], 1)        # only s3
        self.assertEqual(p5['visits_scheduled'], 1)   # s2 upcoming (no-show counts as neither)

        # ── WhatsApp-rescue: deterministic from the fixed offsets ──
        resc = Dash.get_whatsapp_rescue(date_from=d_from, date_to=d_to)['overall']
        self.assertEqual(resc['cohort'], 6)           # b1,b2,b3 + g1,g2,r3 entered hard-to-reach
        self.assertEqual(resc['rescue_engaged'], 2)   # b1, b2 replied after going stuck
        self.assertEqual(resc['rescued'], 2)
        self.assertEqual(resc['rescued_to_visit'], 1)

        # ── Drill-down works (multi-property phone lands under several props) ──
        self.assertTrue(Dash.get_inquiry_engagement(props['Demo Greens'], d_from, d_to))

        # ── purge removes every demo row ──
        dev_seed.purge(self.env)
        eng2 = Dash.get_property_engagement(date_from=d_from, date_to=d_to)
        self.assertEqual(eng2['rows'], [])
        resc2 = Dash.get_whatsapp_rescue(date_from=d_from, date_to=d_to)['overall']
        self.assertEqual(resc2['cohort'], 0)
