import random
import time

from odoo.tests.common import TransactionCase


class DealCommonTestCase(TransactionCase):
    """
    Base test case for Deals, Offers, Owners, Packages, and Transactions.
    Provides common setup and helper methods for creating offers with validation.
    This class is not tagged for execution itself, but should be inherited by specific test classes.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.timestamp = str(int(time.time()))

        cls.sales_manager = cls.env["res.users"].create({
            "name": "Sales Manager",
            "login": f"sales_mgr_{cls.timestamp}",
            "email": f"sales_mgr_{cls.timestamp}@test.com",
        })

    # ------------------------------------------------------
    # 1. HELPER FOR OFFER CREATION WITH AUTO-RESOLVED DEPENDENCIES
    # ------------------------------------------------------

    def create_offer(self, **kwargs):
        """
        Creates an Offer. Automatically matches fields to the real deal.offer model constraints.
        """
        # Unique suffix ensures no name collisions
        unique_suffix = f"{int(time.time() * 1000)}_{random.randint(100, 999)}"

        values = {
            "name": f"OFFER-{unique_suffix}",
            "waive_off_type": "percentage",
            "waive_off_value": 10.0,
            "is_active": True,
        }

        values.update(kwargs)

        return self.env["deal.offer"].create(values)

    # ------------------------------------------------------
    # 2. HELPER FOR PACKAGE
    # ------------------------------------------------------

    def create_package(self, **kwargs):
        unique_id = f"{random.randint(1000, 9999)}"
        values = {
            "name": f"Premium Package {unique_id}",
            "amount": 1000.00,
            "is_active": True,
        }
        values.update(kwargs)
        return self.env["deal.package"].create(values)
