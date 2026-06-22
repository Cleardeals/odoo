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

        cls.deal_manager = cls.env["res.users"].create({
            "name": "Deal Manager",
            "login": f"deal_mgr_{cls.timestamp}",
            "email": f"deal_mgr_{cls.timestamp}@test.com",
        })

        cls.data_entry_operator = cls.env["res.users"].create({
            "name": "Data Entry Operator",
            "login": f"deo_{cls.timestamp}",
            "email": f"deo_{cls.timestamp}@test.com",
        })

    # ------------------------------------------------------
    # 1. HELPER FOR OFFER
    # ------------------------------------------------------

    def create_offer(self, **kwargs):
        """
        Creates an Offer. Automatically matches fields to the real deal.offer model constraints.
        """
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

    # ------------------------------------------------------
    # 3. HELPER FOR OWNER
    # ------------------------------------------------------

    def create_owner(self, **kwargs):
        unique_id = f"{random.randint(1000, 9999)}"
        values = {
            "name": f"Owner {unique_id}",
            "phone": f"555-010{unique_id[-4:]}",
            "email": f"owner{unique_id}@test.com",
            "occupation": "Engineer",
            "is_builder": False,
        }
        values.update(kwargs)
        return self.env["deal.owner"].create(values)
