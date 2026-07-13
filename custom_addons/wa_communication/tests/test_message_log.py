"""Message Log analytics (``wa.message.log``) — summary totals.

Regression net for the header stat bar, especially the total-cost aggregate:
Odoo 17+ ``_read_group`` returns tuples, not dicts, so the sum must be read
positionally.  The old dict-key access silently fell back to ₹0.00 — invisible
while all costs were 0, then wrong once per-row costs were populated.
"""

from odoo.tests import tagged

from .common import WaTransactionCase


@tagged('post_install', '-at_install', 'wa_communication')
class TestMessageLogTotals(WaTransactionCase):

    def setUp(self):
        super().setUp()
        self.Log = self.env['wa.message.log']

    def test_total_cost_sums_across_rows(self):
        conv = self.make_conversation()
        for cost in (0.95, 0.95, 0.86):
            self.make_message(
                conv, direction='outbound', kind='template', status='read',
                initiator='workflow', cost_inr=cost,
                occurred_at='2026-07-13 10:00:00')
        res = self.Log.get_messages()
        self.assertAlmostEqual(res['totals']['total_cost'], 2.76, places=2)

    def test_total_cost_zero_when_no_costs(self):
        conv = self.make_conversation()
        self.make_message(conv, direction='inbound', occurred_at='2026-07-13 10:00:00')
        res = self.Log.get_messages()
        self.assertEqual(res['totals']['total_cost'], 0.0)

    def test_detail_panel_shows_cost_breakdown(self):
        conv = self.make_conversation()
        msg = self.make_message(
            conv, direction='outbound', kind='template', status='read',
            initiator='workflow', cost_inr=0.94941, cost_whatsapp_inr=0.86,
            cost_interakt_markup=0.09, occurred_at='2026-07-13 10:00:00')
        detail = self.Log.get_message_detail(msg.id)
        self.assertEqual(detail['whatsapp_cost'], '₹0.8600')
        self.assertEqual(detail['interakt_markup'], '₹0.0900')
        self.assertEqual(detail['actual_cost'], '₹0.9494')
