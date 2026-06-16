import random
import time
from datetime import date, timedelta

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
        Creates an Offer. If you don't pass an owner_id or package_id, 
        it will automatically create them for you!
        """
        # Automatically resolve dependencies if not provided!
        if "owner_id" not in kwargs:
            kwargs["owner_id"] = self.create_owner().id

        if "package_id" not in kwargs:
            kwargs["package_id"] = self.create_package().id

        unique_suffix = f"{int(time.time() * 1000)}_{random.randint(100, 999)}"

        values = {
            "name": f"OFFER-{unique_suffix}",
            "status": "draft",
            "offer_date": date.today(),
            "valid_until": date.today() + timedelta(days=7),
            "amount": 5000.00,
        }

        # This will merge the owner_id, package_id, and anything else you passed
        values.update(kwargs)

        # REPLACE with your actual offer model name
        return self.env["your.offer.model"].create(values)
