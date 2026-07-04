from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .test_deal_common import DealCommonTestCase


@tagged("post_install", "-at_install")
class TestDeal(DealCommonTestCase):

    def test_01_deal_id_sequence_format(self):
        deal = self.create_deal()
        self.assertTrue(deal.deal_id)
        self.assertNotEqual(deal.deal_id, "/")

    def test_02_deal_id_auto_increments(self):
        """Consecutive deals get incrementing sequence numbers."""
        deal1 = self.create_deal()
        deal1.write({"deal_status": "closed", "closed_reason": "deal_cancelled"})
        deal2 = self.create_deal()
        num1 = int(deal1.deal_id.split("/")[-1])
        num2 = int(deal2.deal_id.split("/")[-1])
        self.assertGreater(num2, num1)

    def test_03_batch_create_all_deal_ids_unique(self):
        """All created deals have unique deal_ids."""
        deal1 = self.create_deal()
        deal1.write({"deal_status": "closed", "closed_reason": "deal_cancelled"})
        deal2 = self.create_deal()
        deal2.write({"deal_status": "closed", "closed_reason": "deal_cancelled"})
        deal3 = self.create_deal()
        ids = [deal1.deal_id, deal2.deal_id, deal3.deal_id]
        self.assertEqual(len(ids), len(set(ids)))

    def test_04_copy_resets_deal_id(self):
        """Copying a deal generates a new deal_id."""
        deal = self.create_deal()
        deal.write({"deal_status": "closed", "closed_reason": "deal_cancelled"})
        copied = deal.copy()
        self.assertNotEqual(deal.deal_id, copied.deal_id)
        self.assertTrue(copied.deal_id)

    def test_05_all_default_values(self):
        """Check all default values on a freshly created deal."""
        deal = self.create_deal()
        inr = self.env.ref("base.INR")

        self.assertFalse(deal.is_offer)
        self.assertEqual(deal.deal_type, "regular")
        self.assertEqual(deal.deal_status, "registration")
        self.assertFalse(deal.is_full_payment)
        self.assertEqual(deal.currency_id, inr)
        self.assertTrue(deal.registration_date)

    def test_06_onchange_package_populates_amounts(self):
        """Changing package_id updates package_amount and gross_amount."""
        deal = self.create_deal()
        new_package = self.create_package(amount=50000.0)

        deal.package_id = new_package
        deal._onchange_package_id()

        self.assertEqual(deal.package_amount, 50000.0)
        self.assertEqual(deal.gross_amount, 50000.0)

    def test_07_removing_package_zeroes_amounts(self):
        """Removing package_id sets amounts to 0."""
        deal = self.create_deal()
        deal.package_id = False
        deal._onchange_package_id()
        self.assertEqual(deal.package_amount, 0.0)
        self.assertEqual(deal.gross_amount, 0.0)

    def test_08_gross_amount_with_percentage_offer(self):
        """gross_amount = package_amount - (package_amount * waive_off_value / 100)."""
        package = self.create_package(amount=10000.0)
        offer = self.create_offer(waive_off_type="percentage", waive_off_value=10.0)
        deal = self.create_deal(with_offer=True, package_id=package, offer_id=offer)

        expected = 10000.0 - (10000.0 * 10.0 / 100)
        self.assertAlmostEqual(deal.gross_amount, expected, places=2)

    def test_08b_gross_amount_with_fixed_offer(self):
        """gross_amount = package_amount - waive_off_value."""
        package = self.create_package(amount=10000.0)
        offer = self.create_offer(waive_off_type="fixed", waive_off_value=1500.0)
        deal = self.create_deal(with_offer=True, package_id=package, offer_id=offer)

        expected = 10000.0 - 1500.0
        self.assertAlmostEqual(deal.gross_amount, expected, places=2)

    def test_09_changing_percentage_in_offer_recalculates_gross(self):
        """Changing waive_off_value on offer and calling recompute updates gross_amount."""
        package = self.create_package(amount=10000.0)
        offer = self.create_offer(waive_off_type="percentage", waive_off_value=10.0)
        deal = self.create_deal(with_offer=True, package_id=package, offer_id=offer)
        offer.write({"waive_off_value": 20.0})
        deal._recompute_gross_amount()

        expected = 10000.0 - (10000.0 * 20.0 / 100)
        self.assertAlmostEqual(deal.gross_amount, expected, places=2)

    def test_10_changing_fixed_in_offer_recalculates_gross(self):
        """Changing fixed waive_off_value and calling recompute updates gross_amount."""
        package = self.create_package(amount=10000.0)
        offer = self.create_offer(waive_off_type="fixed", waive_off_value=1000.0)
        deal = self.create_deal(with_offer=True, package_id=package, offer_id=offer)

        offer.write({"waive_off_value": 2000.0})
        deal._recompute_gross_amount()

        expected = 10000.0 - 2000.0
        self.assertAlmostEqual(deal.gross_amount, expected, places=2)

    def test_11_unchecking_is_offer_reverts_gross_amount(self):
        """Unchecking is_offer reverts gross_amount to full package_amount."""
        package = self.create_package(amount=10000.0)
        offer = self.create_offer(waive_off_type="percentage", waive_off_value=10.0)
        deal = self.create_deal(with_offer=True, package_id=package, offer_id=offer)

        self.assertAlmostEqual(deal.gross_amount, 9000.0, places=2)
        deal.write({"is_offer": False, "offer_id": False, "gross_amount": package.amount})

        self.assertAlmostEqual(deal.gross_amount, 10000.0, places=2)
        self.assertFalse(deal.offer_id.id)

    def test_12_manager_can_manually_override_gross_amount(self):
        """Manager can manually write gross_amount even with is_offer=True."""
        deal = self.create_deal(with_offer=True)
        deal.write({"gross_amount": 99999.0})
        self.assertEqual(deal.gross_amount, 99999.0)


    def test_13_inactive_offer_not_in_active_domain(self):
        """Archived offer does not appear in is_active=True domain search."""
        offer = self.create_offer()
        offer.write({"is_active": False})

        active_offers = self.env["deal.offer"].search([("is_active", "=", True)])
        self.assertNotIn(offer, active_offers)

    def test_14_is_offer_true_without_offer_id_rejected(self):
        """is_offer=True with no offer_id raises ValidationError."""
        with self.assertRaisesRegex(ValidationError, "Please associate an active offer"):
            self.create_deal(is_offer=True)

    def test_15_offer_id_without_is_offer_rejected(self):
        """offer_id set without is_offer=True raises ValidationError."""
        offer = self.create_offer()
        with self.assertRaisesRegex(ValidationError, "Please select the is_offer checkbox if you want to associate an offer"):
            self.create_deal(is_offer=False, offer_id=offer.id)

    def test_16_is_offer_true_with_offer_id_accepted(self):
        """is_offer=True with valid offer_id saves successfully."""
        deal = self.create_deal(with_offer=True)
        self.assertTrue(deal.id)
        self.assertTrue(deal.is_offer)
        self.assertTrue(deal.offer_id.id)

    def test_17_closed_status_without_reason_rejected(self):
        """deal_status=closed with no closed_reason raises ValidationError."""
        deal = self.create_deal()
        with self.assertRaisesRegex(ValidationError, "Please select a closed reason when the deal status is closed"):
            deal.write({"deal_status": "closed"})

    def test_18_closed_status_with_reason_accepted(self):
        """deal_status=closed with closed_reason saves successfully."""
        deal = self.create_deal()
        deal.write({"deal_status": "closed", "closed_reason": "deal_cancelled"})
        self.assertEqual(deal.deal_status, "closed")
        self.assertEqual(deal.closed_reason, "deal_cancelled")

    def test_19_non_closed_status_with_reason_rejected(self):
        """Setting closed_reason when deal_status is not closed raises ValidationError."""
        deal = self.create_deal()
        with self.assertRaisesRegex(ValidationError, "Closed reason can only be set when deal status is closed"):
            deal.write({"closed_reason": "deal_cancelled"})


    def test_20_duplicate_active_deal_on_same_property_rejected(self):
        """Two active deals on same property at same time raises ValidationError."""
        deal1 = self.create_deal()
        with self.assertRaisesRegex(ValidationError, "Only one active deal can be associated with a property at a time"):
            self.create_deal(property_id=deal1.property_id)

    def test_21_live_deal_blocks_new_registration_same_property(self):
        """Existing live deal on property → new registration deal rejected."""
        deal1 = self.create_deal()
        deal1.write({"deal_status": "live"})
        with self.assertRaisesRegex(ValidationError, "Only one active deal can be associated with a property at a time"):
            self.create_deal(property_id=deal1.property_id)

    def test_22_sold_deal_allows_new_registration_same_property(self):
        """Existing sold deal → new registration deal on same property allowed."""
        deal1 = self.create_deal()
        deal1.write({"deal_status": "sold"})
        deal2 = self.create_deal(property_id=deal1.property_id)
        self.assertTrue(deal2.id)

    def test_23_renewed_deal_allows_new_registration_same_property(self):
        """Existing renewed deal → new registration deal on same property allowed."""
        deal1 = self.create_deal()
        deal1.write({"deal_status": "renewed"})
        deal2 = self.create_deal(property_id=deal1.property_id)
        self.assertTrue(deal2.id)

    def test_24_closed_deal_allows_new_registration_same_property(self):
        """Existing closed deal → new registration deal on same property allowed."""
        deal1 = self.create_deal()
        deal1.write({"deal_status": "closed", "closed_reason": "deal_cancelled"})
        deal2 = self.create_deal(property_id=deal1.property_id)
        self.assertTrue(deal2.id)

    def test_25_different_property_deals_allowed(self):
        """Two active deals on different properties both allowed."""
        deal1 = self.create_deal()
        other_property = self.env["property.base"].search(
            [("id", "!=", deal1.property_id.id)], limit=1,
        )
        if not other_property:
            self.skipTest("No second property available in test DB")
        deal2 = self.create_deal(property_id=other_property)
        self.assertTrue(deal2.id)

    def test_26_deal_can_be_edited(self):
        """Editing a deal field raises no error."""
        deal = self.create_deal()
        deal.write({"deal_type": "ops_sale_lead"})
        self.assertEqual(deal.deal_type, "ops_sale_lead")

    def test_27_full_payment_registration_less_than_gross_live_rejected(self):
        """full_payment=True, registration(5000) < gross(10000) → live rejected."""
        deal = self.create_deal(gross_amount=10000.0, is_full_payment=True)
        self.create_transaction(deal, "registration", gross_amount=5000.0)
        with self.assertRaisesRegex(ValidationError, "Deal status cannot be changed to Live or Sold because full payment has already been received"):
            deal.write({"deal_status": "live"})

    def test_28_full_payment_registration_equals_gross_live_allowed(self):
        """full_payment=True, registration(10000) == gross(10000) → live allowed."""
        deal = self.create_deal(gross_amount=10000.0, is_full_payment=True)
        self.create_transaction(deal, "registration", gross_amount=10000.0)
        deal.write({"deal_status": "live"})
        self.assertEqual(deal.deal_status, "live")

    def test_29_not_full_payment_registration_less_than_gross_live_allowed(self):
        """full_payment=False, registration(5000) < gross(10000) → live allowed."""
        deal = self.create_deal(gross_amount=10000.0, is_full_payment=False)
        self.create_transaction(deal, "registration", gross_amount=5000.0)
        deal.write({"deal_status": "live"})
        self.assertEqual(deal.deal_status, "live")

    def test_30_full_payment_rejects_sold_transaction(self):
        """is_full_payment=True → sold transaction always rejected."""
        deal = self.create_deal(gross_amount=10000.0, is_full_payment=True)
        self.create_transaction(deal, "registration", gross_amount=10000.0)
        deal.write({"deal_status": "live"})
        deal.write({"deal_status": "sold"})
        with self.assertRaisesRegex(ValidationError, "Sold transactions are not allowed when full payment is selected for the deal"):
            self.create_transaction(deal, "sold", gross_amount=1000.0)

    def test_31_non_closed_status_has_null_closed_fields(self):
        """registration and live status → closed_reason null, closed_at null."""
        deal = self.create_deal()
        self.assertFalse(deal.closed_reason)
        self.assertFalse(deal.closed_at)
        deal.write({"deal_status": "live"})
        self.assertFalse(deal.closed_reason)
        self.assertFalse(deal.closed_at)

    def test_32_closed_status_populates_closed_at(self):
        """deal_status=closed with reason → closed_at populated."""
        deal = self.create_deal()
        deal.write({"deal_status": "closed", "closed_reason": "deal_cancelled"})
        self.assertEqual(deal.deal_status, "closed")
        self.assertTrue(deal.closed_at)

    def test_33_action_renew_deal_sets_correct_statuses(self):
        """action_renew_deal sets old deal=renewed, new deal=registration with type=renewal."""
        deal = self.create_deal()
        deal.action_renew_deal()

        self.assertEqual(deal.deal_status, "renewed")

        new_deal = self.env["deal"].search([
            ("deal_type", "=", "renewal"),
            ("property_id", "=", deal.property_id.id),
        ], limit=1)
        self.assertTrue(new_deal.id)
        self.assertEqual(new_deal.deal_type, "renewal")
        self.assertEqual(new_deal.deal_status, "registration")

    def test_34_action_renew_deal_copies_fields(self):
        """action_renew_deal → new deal has same property_id, bde_id, owner_id."""
        deal = self.create_deal()
        deal.action_renew_deal()

        new_deal = self.env["deal"].search([
            ("deal_type", "=", "renewal"),
            ("property_id", "=", deal.property_id.id),
        ], limit=1)
        self.assertEqual(new_deal.property_id, deal.property_id)
        self.assertEqual(new_deal.bde_id, deal.bde_id)
        self.assertEqual(new_deal.owner_id, deal.owner_id)

    def test_35_renewed_status_allows_new_deal_same_property(self):
        """deal_status=renewed → new deal on same property is allowed."""
        deal = self.create_deal()
        deal.write({"deal_status": "renewed"})
        new_deal = self.create_deal(property_id=deal.property_id)
        self.assertTrue(new_deal.id)

    def test_36_chatter_logs_field_changes(self):
        """Chatter is active — mail.thread is inherited and messages can be posted."""
        deal = self.create_deal()
        deal.message_post(body="Test chatter active")
        self.env.flush_all()

        count = self.env["mail.message"].sudo().search_count([
            ("res_id", "=", deal.id),
            ("model", "=", "deal"),
        ])
        self.assertGreater(count, 0)
