from odoo.exceptions import ValidationError
from odoo.tests.common import tagged
from odoo.tools import mute_logger

from .test_deal_common import DealCommonTestCase


@tagged("post_install", "-at_install")
class TestDealTransaction(DealCommonTestCase):
    """
    Test cases for Transaction model.
    """

    def test_01_net_amount_computed_from_gross(self):
        """net_amount = gross_amount / 1.18"""
        deal = self._deal_in_status("registration", gross_amount=35400.0)
        test_transaction = self.create_transaction(deal, "registration", gross_amount=11800.0)
        self.assertAlmostEqual(test_transaction.net_amount, 11800.0 / 1.18, places=2)

    def test_02_net_amount_rounds_correctly(self):
        """net_amount rounds to 2 decimal places."""
        deal = self._deal_in_status("registration", gross_amount=35400.0)
        test_transaction = self.create_transaction(deal, "registration", gross_amount=1000.0)
        self.assertAlmostEqual(test_transaction.net_amount, round(1000.0 / 1.18, 2), places=2)

    def test_03_net_amount_negative_for_refund(self):
        """net_amount is negative for refund (gross_amount is negative)."""
        deal = self._add_registration_and_close(reg_amount=10000.0)
        test_transaction = self.create_transaction(deal, "refund", gross_amount=-5900.0)
        self.assertAlmostEqual(test_transaction.net_amount, -5900.0 / 1.18, places=2)

    def test_04_refund_positive_rejected_negative_accepted(self):
        """Refund: positive gross rejected, negative accepted."""
        deal = self._add_registration_and_close()
        with self.assertRaisesRegex(ValidationError, "Refund transactions cannot have positive gross amounts"):
            self.create_transaction(deal, "refund", gross_amount=1000.0)
        test_transaction = self.create_transaction(deal, "refund", gross_amount=-1000.0)
        self.assertTrue(test_transaction.id)

    def test_05_registration_positive_accepted_negative_rejected(self):
        """Registration: positive accepted, negative rejected."""
        deal = self._deal_in_status("registration", gross_amount=10000.0)
        with self.assertRaisesRegex(ValidationError, "Registration transactions cannot have negative gross amounts"):
            self.create_transaction(deal, "registration", gross_amount=-1000.0)
        test_transaction = self.create_transaction(deal, "registration", gross_amount=1000.0)
        self.assertTrue(test_transaction.id)

    def test_06_sold_positive_accepted_negative_rejected(self):
        """Sold: positive accepted, negative rejected."""
        deal = self._deal_in_status("sold", gross_amount=10000.0)
        with self.assertRaisesRegex(ValidationError, "Sold transactions cannot have negative gross amounts"):
            self.create_transaction(deal, "sold", gross_amount=-1000.0)
        test_transaction = self.create_transaction(deal, "sold", gross_amount=1000.0)
        self.assertTrue(test_transaction.id)

    def test_07_sequence_structure(self):
        """transaction_id follows format YY-YY/STATE/CITY/NNNN"""
        city_property = self.env["property.base"].create({
            "name": "City Sequence Property",
            "city": "Ahmedabad",
            "state": "Gujarat",
        })
        deal = self.create_deal(gross_amount=10000.0, property_id=city_property)
        test_transaction = self.create_transaction(deal, "registration", gross_amount=1000.0)
        self.assertRegex(test_transaction.transaction_id, r"^\d{2}-\d{2}/.+$")

    def test_08_sequence_auto_increments(self):
        """Consecutive transactions on same city get incrementing numbers."""
        deal = self._deal_in_status("registration", gross_amount=20000.0)
        test_transaction1 = self.create_transaction(deal, "registration", gross_amount=1000.0)
        test_transaction2 = self.create_transaction(deal, "registration", gross_amount=1000.0)
        num1 = int(test_transaction1.transaction_id[-4:])
        num2 = int(test_transaction2.transaction_id[-4:])
        self.assertGreater(num2, num1)

    def test_09_registration_status_accepts_registration_type(self):
        """deal_status=registration → registration transaction accepted."""
        deal = self._deal_in_status("registration", gross_amount=10000.0)
        test_transaction = self.create_transaction(deal, "registration", gross_amount=1000.0)
        self.assertTrue(test_transaction.id)

    def test_10_registration_status_rejects_sold_type(self):
        """deal_status=registration → sold transaction rejected."""
        deal = self._deal_in_status("registration", gross_amount=10000.0)
        with self.assertRaisesRegex(ValidationError, "Sold transactions are not allowed for deals that are in registration status"):
            self.create_transaction(deal, "sold", gross_amount=1000.0)

    def test_11_registration_status_rejects_refund_type(self):
        """deal_status=registration → refund transaction rejected."""
        deal = self._deal_in_status("registration", gross_amount=10000.0)
        with self.assertRaisesRegex(ValidationError, "Refund transactions are not allowed for deals that are in registration status"):
            self.create_transaction(deal, "refund", gross_amount=-1000.0)

    def test_12_live_status_rejects_registration_type(self):
        """deal_status=live → registration rejected."""
        deal = self._deal_in_status("live", gross_amount=10000.0)
        with self.assertRaisesRegex(ValidationError, "Registration transactions are not allowed for deals that are in live status"):
            self.create_transaction(deal, "registration", gross_amount=1000.0)

    def test_13_live_status_rejects_sold_type(self):
        """deal_status=live → sold rejected."""
        deal = self._deal_in_status("live", gross_amount=10000.0)
        with self.assertRaisesRegex(ValidationError, "Sold transactions are not allowed for deals that are in live status"):
            self.create_transaction(deal, "sold", gross_amount=1000.0)

    def test_14_live_status_rejects_refund_type(self):
        """deal_status=live → refund rejected."""
        deal = self._deal_in_status("live", gross_amount=10000.0)
        with self.assertRaisesRegex(ValidationError, "Refund transactions are not allowed for deals that are in live status"):
            self.create_transaction(deal, "refund", gross_amount=-1000.0)

    def test_15_sold_status_rejects_registration_type(self):
        """deal_status=sold → registration rejected."""
        deal = self._deal_in_status("sold", gross_amount=10000.0)
        with self.assertRaisesRegex(ValidationError, "Registration transactions are not allowed for deals that are in sold status"):
            self.create_transaction(deal, "registration", gross_amount=1000.0)

    def test_16_sold_status_accepts_sold_type(self):
        """deal_status=sold → sold transaction accepted."""
        deal = self._deal_in_status("sold", gross_amount=10000.0)
        test_transaction = self.create_transaction(deal, "sold", gross_amount=1000.0)
        self.assertTrue(test_transaction.id)

    def test_17_sold_status_rejects_refund_type(self):
        """deal_status=sold → refund rejected."""
        deal = self._deal_in_status("sold", gross_amount=10000.0)
        with self.assertRaisesRegex(ValidationError, "Refund transactions are not allowed for deals that are in sold status"):
            self.create_transaction(deal, "refund", gross_amount=-1000.0)

    def test_18_renewed_status_rejects_registration_type(self):
        """deal_status=renewed → registration rejected."""
        deal = self._deal_in_status("renewed", gross_amount=10000.0)
        with self.assertRaisesRegex(ValidationError, "Registration transactions are not allowed for deals that are in renewed status"):
            self.create_transaction(deal, "registration", gross_amount=1000.0)

    def test_19_renewed_status_rejects_sold_type(self):
        """deal_status=renewed → sold rejected."""
        deal = self._deal_in_status("renewed", gross_amount=10000.0)
        with self.assertRaisesRegex(ValidationError, "Sold transactions are not allowed for deals that are in renewed status"):
            self.create_transaction(deal, "sold", gross_amount=1000.0)

    def test_20_renewed_status_rejects_refund_type(self):
        """deal_status=renewed → refund rejected."""
        deal = self._deal_in_status("renewed", gross_amount=10000.0)
        with self.assertRaisesRegex(ValidationError, "Refund transactions are not allowed for deals that are in renewed status"):
            self.create_transaction(deal, "refund", gross_amount=-1000.0)

    def test_21_closed_deal_cancelled_rejects_registration(self):
        """closed+deal_cancelled → registration rejected."""
        deal = self._deal_in_status("closed", closed_reason="deal_cancelled")
        with self.assertRaisesRegex(ValidationError, "Registration transactions are not allowed for deals that are closed due to deal cancellation"):
            self.create_transaction(deal, "registration", gross_amount=1000.0)

    def test_22_closed_package_expired_rejects_registration(self):
        """closed+package_expired → registration rejected."""
        deal = self._deal_in_status("closed", closed_reason="package_expired")
        with self.assertRaisesRegex(ValidationError, "Registration transactions are not allowed for deals that are closed due to package expiration"):
            self.create_transaction(deal, "registration", gross_amount=1000.0)

    def test_23_closed_deal_cancelled_rejects_sold(self):
        """closed+deal_cancelled → sold rejected."""
        deal = self._deal_in_status("closed", closed_reason="deal_cancelled")
        with self.assertRaisesRegex(ValidationError, "Sold transactions are not allowed for deals that are closed due to deal cancellation"):
            self.create_transaction(deal, "sold", gross_amount=1000.0)

    def test_24_closed_package_expired_rejects_sold(self):
        """closed+package_expired → sold rejected."""
        deal = self._deal_in_status("closed", closed_reason="package_expired")
        with self.assertRaisesRegex(ValidationError, "Sold transactions are not allowed for deals that are closed due to package expiration"):
            self.create_transaction(deal, "sold", gross_amount=1000.0)

    def test_25_closed_package_expired_rejects_refund(self):
        """closed+package_expired → refund rejected."""
        deal = self._deal_in_status("closed", closed_reason="package_expired")
        with self.assertRaisesRegex(ValidationError, "Refund transactions are not allowed for deals that are closed due to package expiration"):
            self.create_transaction(deal, "refund", gross_amount=-1000.0)

    def test_26_closed_deal_cancelled_accepts_refund(self):
        """closed+deal_cancelled → refund accepted."""
        deal = self._add_registration_and_close(reg_amount=10000.0)
        test_transaction = self.create_transaction(deal, "refund", gross_amount=-1000.0)
        self.assertTrue(test_transaction.id)

    def test_27_total_less_than_gross_accepted(self):
        """reg(5000)+sold(4000)=9000 < gross(10000) → accepted."""
        deal = self.create_deal(gross_amount=10000.0)
        self.create_transaction(deal, "registration", gross_amount=5000.0)
        deal.write({"deal_status": "live"})
        deal.write({"deal_status": "sold"})
        test_transaction = self.create_transaction(deal, "sold", gross_amount=4000.0)
        self.assertTrue(test_transaction.id)

    def test_28_total_equal_gross_accepted(self):
        """reg(5000)+sold(5000)=10000 == gross(10000) → accepted."""
        deal = self.create_deal(gross_amount=10000.0)
        self.create_transaction(deal, "registration", gross_amount=5000.0)
        deal.write({"deal_status": "live"})
        deal.write({"deal_status": "sold"})
        test_transaction = self.create_transaction(deal, "sold", gross_amount=5000.0)
        self.assertTrue(test_transaction.id)

    def test_29_total_greater_than_gross_rejected(self):
        """reg(5000)+sold(6000)=11000 > gross(10000) → rejected."""
        deal = self.create_deal(gross_amount=10000.0)
        self.create_transaction(deal, "registration", gross_amount=5000.0)
        deal.write({"deal_status": "live"})
        deal.write({"deal_status": "sold"})
        with self.assertRaisesRegex(ValidationError, "Total amount received from registration and sold transactions cannot exceed the gross amount of the deal"):
            self.create_transaction(deal, "sold", gross_amount=6000.0)

    def test_30_full_payment_rejects_sold_transaction(self):
        """is_full_payment=True → sold transaction always rejected."""
        deal = self._deal_in_status("sold", gross_amount=10000.0, is_full_payment=True)
        with self.assertRaisesRegex(ValidationError, "Sold transactions are not allowed when full payment is selected for the deal"):
            self.create_transaction(deal, "sold", gross_amount=1000.0)

    def test_31_not_full_payment_single_registration_exceeds_gross_rejected(self):
        """not full_payment: registration(11000) > gross(10000) → rejected."""
        deal = self.create_deal(gross_amount=10000.0)
        with self.assertRaisesRegex(ValidationError, "Refund amount cannot exceed the total amount received from registration"):
            self.create_transaction(deal, "registration", gross_amount=11000.0)

    def test_32_full_payment_single_registration_exceeds_gross_rejected(self):
        """full_payment: registration(11000) > gross(10000) → rejected."""
        deal = self.create_deal(gross_amount=10000.0, is_full_payment=True)
        with self.assertRaisesRegex(ValidationError, "Refund amount cannot exceed the total amount received from registration"):
            self.create_transaction(deal, "registration", gross_amount=11000.0)

    def test_33_not_full_payment_total_registration_exceeds_gross_rejected(self):
        """not full_payment: reg(6000)+reg(5000)=11000 > gross(10000) → rejected."""
        deal = self.create_deal(gross_amount=10000.0)
        self.create_transaction(deal, "registration", gross_amount=6000.0)
        with self.assertRaisesRegex(ValidationError, "Refund amount cannot exceed the total amount received from registration"):
            self.create_transaction(deal, "registration", gross_amount=5000.0)

    def test_34_full_payment_total_registration_exceeds_gross_rejected(self):
        """full_payment: reg(6000)+reg(5000)=11000 > gross(10000) → rejected."""
        deal = self.create_deal(gross_amount=10000.0, is_full_payment=True)
        self.create_transaction(deal, "registration", gross_amount=6000.0)
        with self.assertRaisesRegex(ValidationError, "Refund amount cannot exceed the total amount received from registration"):
            self.create_transaction(deal, "registration", gross_amount=5000.0)

    def test_35_two_partial_refunds_within_received_accepted(self):
        """refund(5000)+refund(4000)=9000 ≤ received(10000) → both accepted."""
        deal = self._add_registration_and_close(reg_amount=10000.0)
        test_transaction1 = self.create_transaction(deal, "refund", gross_amount=-5000.0)
        test_transaction2 = self.create_transaction(deal, "refund", gross_amount=-4000.0)
        self.assertTrue(test_transaction1.id)
        self.assertTrue(test_transaction2.id)

    def test_36_two_refunds_equal_received_accepted(self):
        """refund(5000)+refund(5000)=10000 == received(10000) → both accepted."""
        deal = self._add_registration_and_close(reg_amount=10000.0)
        test_transaction1 = self.create_transaction(deal, "refund", gross_amount=-5000.0)
        test_transaction2 = self.create_transaction(deal, "refund", gross_amount=-5000.0)
        self.assertTrue(test_transaction1.id)
        self.assertTrue(test_transaction2.id)

    def test_37_second_refund_exceeds_received_rejected(self):
        """refund(5000)+refund(6000)=11000 > received(10000) → second rejected."""
        deal = self._add_registration_and_close(reg_amount=10000.0)
        self.create_transaction(deal, "refund", gross_amount=-5000.0)
        with self.assertRaisesRegex(ValidationError, "Refund amount cannot exceed the total amount received from registration and sold transactions"):
            self.create_transaction(deal, "refund", gross_amount=-6000.0)

    def test_38_single_refund_equal_received_accepted(self):
        """Single refund(10000) == received(10000) → accepted."""
        deal = self._add_registration_and_close(reg_amount=10000.0)
        test_transaction = self.create_transaction(deal, "refund", gross_amount=-10000.0)
        self.assertTrue(test_transaction.id)

    def test_39_single_refund_exceeds_received_rejected(self):
        """Single refund(12000) > received(10000) → rejected."""
        deal = self._add_registration_and_close(reg_amount=10000.0)
        with self.assertRaisesRegex(ValidationError, "Refund amount cannot exceed the total amount received from registration and sold transactions"):
            self.create_transaction(deal, "refund", gross_amount=-12000.0)

    def test_40_cannot_edit_transaction_amount(self):
        """Editing gross_amount on existing transaction is rejected."""
        deal = self.create_deal(gross_amount=10000.0)
        test_transaction = self.create_transaction(deal, "registration", gross_amount=1000.0)
        with self.assertRaisesRegex(ValidationError, "Transactions cannot be modified"):
            test_transaction.write({"gross_amount": 12000.0})

    def test_41_cannot_change_type_registration_to_sold(self):
        """Changing type registration→sold is rejected."""
        deal = self.create_deal(gross_amount=10000.0)
        test_transaction = self.create_transaction(deal, "registration", gross_amount=1000.0)
        with self.assertRaisesRegex(ValidationError, "Cannot change transaction type from registration to sold"):
            test_transaction.write({"transaction_type": "sold"})

    def test_42_cannot_change_type_sold_to_registration(self):
        """Changing type sold→registration is rejected."""
        deal = self._deal_in_status("sold", gross_amount=10000.0)
        test_transaction = self.create_transaction(deal, "sold", gross_amount=1000.0)
        with self.assertRaisesRegex(ValidationError, "Cannot change transaction type from sold to registration"):
            test_transaction.write({"transaction_type": "registration"})

    def test_43_cannot_change_type_refund_to_sold(self):
        """Changing type refund→sold is rejected."""
        deal = self._add_registration_and_close()
        test_transaction = self.create_transaction(deal, "refund", gross_amount=-1000.0)
        with self.assertRaisesRegex(ValidationError, "Cannot change transaction type from refund to sold"):
            test_transaction.write({"transaction_type": "sold"})

    def test_44_cannot_change_payment_channel(self):
        """Changing payment_channel on existing transaction is rejected."""
        deal = self.create_deal(gross_amount=10000.0)
        test_transaction = self.create_transaction(deal, "registration", gross_amount=1000.0)
        with self.assertRaisesRegex(ValidationError, "Cannot change payment channel"):
            test_transaction.write({"payment_channel": "cash"})

    def test_45_cannot_delete_transaction(self):
        """Deleting a transaction raises ValidationError."""
        deal = self.create_deal(gross_amount=10000.0)
        test_transaction = self.create_transaction(deal, "registration", gross_amount=1000.0)
        with self.assertRaisesRegex(ValidationError, "Transactions cannot be deleted"):
            test_transaction.unlink()

    def test_46_cannot_delete_deal_with_transactions(self):
        """Deleting a deal with linked transactions is rejected (ondelete restrict)."""
        deal = self.create_deal(gross_amount=10000.0)
        self.create_transaction(deal, "registration", gross_amount=1000.0)
        with mute_logger("odoo.sql_db"), self.assertRaisesRegex(Exception, "Cannot delete deal with linked transactions"):
            deal.unlink()
