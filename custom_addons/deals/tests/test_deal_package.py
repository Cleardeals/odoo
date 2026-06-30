from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .test_deal_common import DealCommonTestCase


@tagged("-at_install", "post_install")
class TestDealPackage(DealCommonTestCase):
    """Tests for deal.package behavior (package table)."""

    def test_01_create_and_read(self):
        """Create and read: create and check the value of the package"""
        package = self.create_package(name="Read Test Package", amount=35400.00)

        self.assertEqual(package.name, "Read Test Package")
        self.assertEqual(package.amount, 35400.00)

    def test_02_amount_is_mutable(self):
        """Amount is mutable: change the amount and verify"""
        package = self.create_package(amount=35400.00)

        package.write({"amount": 47200.00})

        self.assertEqual(package.amount, 47200.00)

    def test_03_amount_negative_rejected(self):
        """Amount is negative then rejected."""
        with self.assertRaisesRegex(ValidationError, "Amount cannot be negative"):
            self.create_package(amount=-35400.00)

    def test_04_default_currency_inr(self):
        """Default currency (INR) check"""
        package = self.create_package()
        inr_currency = self.env.ref("base.INR")
        self.assertEqual(package.currency_id.id, inr_currency.id)
        self.assertEqual(package.currency_id.name, "INR")

    def test_05_active_default_is_true(self):
        """Active default is true check"""
        package = self.env["deal.package"].create(
            {
                "name": "Default Active Test",
                "amount": 35400.00,
            },
        )
        self.assertTrue(package.is_active)

    def test_06_archived_record_not_in_domain(self):
        """Archived record is not in active domain."""
        package = self.create_package(is_active=False)

        search_results = self.env["deal.package"].search(
            [("id", "=", package.id), ("is_active", "=", True)],
        )
        self.assertFalse(
            search_results,
            "Archived package should not appear in default search.",
        )

    def test_07_name_is_required(self):
        """Name is required to save this otherwise it is rejected."""
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            self.env["deal.package"].create(
                {
                    "amount": 35400.00,
                    # Name is missing
                },
            )

    def test_08_amount_is_required(self):
        """Amount is required check"""
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            self.env["deal.package"].create(
                {
                    "name": "Missing Amount Package",
                    # Amount is missing
                },
            )

    def test_09_amount_rounding(self):
        """Amount rounding happen or not."""
        package = self.create_package(amount=35400.505)

        self.assertEqual(package.amount, 35400.51)

    def test_10_tracking_true_for_changes(self):
        """Tracking enabled for amount and name fields."""
        package_model = self.env["deal.package"]
        self.assertTrue(package_model._fields["amount"].tracking)
        self.assertTrue(package_model._fields["name"].tracking)

    def test_11_snapshot_independence_package_amount_in_deal(self):
        """
        Snapshot independence check: package_amount in deal is a related
        field — it always reflects the live package amount.
        """
        package = self.create_package(amount=35400.0)
        deal = self.create_deal(package_id=package)

        self.assertEqual(deal.package_amount, 35400.0)
        package.write({"amount": 50000.0})
        deal.invalidate_recordset()
        self.assertEqual(
            deal.package_amount,
            50000.0,
            "package_amount is a related field — reflects live package value.",
        )
