from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .test_deal_common import DealCommonTestCase


@tagged("-at_install", "post_install")
class TestDealPackage(DealCommonTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.package_model = cls.env["deal.package"]

    def test_01_create_and_read(self):
        """1. Create and read: create and check the value of the package"""
        package = self.create_package(name="Read Test Package", amount=5000.00)

        self.assertEqual(package.name, "Read Test Package")
        self.assertEqual(package.amount, 5000.00)

    def test_02_amount_is_mutable(self):
        """2. Amount is mutable: change the amount and verify"""
        package = self.create_package(amount=1000.00)

        package.write({"amount": 2500.00})

        self.assertEqual(package.amount, 2500.00)

    def test_03_amount_negative_rejected(self):
        """
        3. Amount is negative then rejected.
        Note: You must have an @api.constrains('amount') in your model for this to pass.
        """
        with self.assertRaisesRegex(ValidationError, "Amount cannot be negative"):
            self.create_package(amount=-500.00)

    def test_04_default_currency_inr(self):
        """4. Default currency (INR) check"""
        package = self.create_package()
        inr_currency = self.env.ref("base.INR")
        self.assertEqual(package.currency_id.id, inr_currency.id)
        self.assertEqual(package.currency_id.name, "INR")

    def test_05_active_default_is_true(self):
        """5. Active default is true check"""
        package = self.package_model.create(
            {
                "name": "Default Active Test",
                "amount": 100.00,
            },
        )
        self.assertTrue(package.is_active)

    def test_06_archived_record_not_in_domain(self):
        """
        6. Archived record is not in active domain.
        Note: For this to work in Odoo, you need `_active_name = "is_active"` in your model.
        """
        package = self.create_package(is_active=False)

        search_results = self.package_model.search(
            [("id", "=", package.id), ("is_active", "=", True)],
        )
        self.assertFalse(
            search_results, "Archived package should not appear in default search.",
        )

    def test_07_name_is_required(self):
        """7. Name is required to save this otherwise it is rejected."""
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            self.package_model.create(
                {
                    "amount": 1000.00,
                    # Name is missing
                },
            )

    def test_08_amount_is_required(self):
        """8. Amount is required check"""
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            self.package_model.create(
                {
                    "name": "Missing Amount Package",
                    # Amount is missing
                },
            )

    def test_09_amount_rounding(self):
        """9. Amount rounding happen or not."""
        package = self.create_package(amount=10.556)

        self.assertEqual(package.amount, 10.56)

    def test_10_tracking_true_for_changes(self):
        self.assertTrue(
            self.package_model._fields["amount"].tracking,
        )
        self.assertTrue(
            self.package_model._fields["name"].tracking,
        )
