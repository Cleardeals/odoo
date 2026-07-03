import time

from odoo.tests.common import TransactionCase, new_test_user


class DealCommonTestCase(TransactionCase):
    """
    Base test case for Deals, Offers, Owners, Packages, and Transactions.
    Provides common setup and helper methods for creating offers with validation.
    This class is not tagged for execution itself, but should be inherited by specific test classes.
    """

    _counter = 0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.suffix = str(int(time.time()))

        cls.manager_user = new_test_user(
            cls.env,
            login=f"manager_{cls.suffix}",
            name="Test Manager",
            groups="base.group_user,deals.group_deal_manager",
        )

        cls.deo_user = new_test_user(
            cls.env,
            login=f"deo_{cls.suffix}",
            name="Test DEO",
            groups="base.group_user,deals.group_data_entry_operator",
        )

        cls.test_property = cls.env["property.base"].search([], limit=1)
        if not cls.test_property:
            cls.test_property = cls.env["property.base"].create(
                {"name": "Test Property"}
            )

        cls.test_bde = cls.env["leads.bde"].search([], limit=1)
        if not cls.test_bde:
            cls.test_bde = cls.env["leads.bde"].create({"name": "Test BDE"})

    def _next_id(self):
        """Returns a unique, deterministic token for the current test run."""
        DealCommonTestCase._counter += 1
        return f"{self.suffix}_{DealCommonTestCase._counter}"

    def create_offer(self, **kwargs):
        """
        Creates an Offer. Automatically matches fields to the real deal.offer model constraints.
        """

        values = {
            "name": f"OFFER-{self._next_id()}",
            "waive_off_type": "percentage",
            "waive_off_value": 10.0,
            "is_active": True,
        }

        values.update(kwargs)
        return self.env["deal.offer"].create(values)

    def create_package(self, **kwargs):
        """
        Creates a Package. Automatically matches fields to the real deal.package model constraints.
        """

        values = {
            "name": f"Premium Package-{self._next_id()}",
            "amount": 35400.00,
            "is_active": True,
        }
        values.update(kwargs)
        return self.env["deal.package"].create(values)

    def create_owner(self, **kwargs):
        """
        Creates an Owner. Automatically matches fields to the real deal.owner model constraints.
        """
        unique_id = self._next_id()
        values = {
            "name": f"Owner {unique_id}",
            "phone": f"9876{unique_id[-6:]}",
            "email": f"owner_{unique_id}@test.com",
            "occupation": "Engineer",
            "is_builder": False,
        }
        values.update(kwargs)
        return self.env["deal.owner"].create(values)

    def create_deal_security(self, **kwargs):
        """
        Creates a Deal Security record. Automatically matches fields to the real deal.security model constraints.
        """
        values = {
            "deal_manager_group": self.env.ref("deals.group_deal_manager").id,
            "data_entry_operator_group": self.env.ref(
                "deals.group_data_entry_operator"
            ).id,
        }

        values.update(kwargs)
        return self.env["deal.security"].create(values)

    def create_deal(self, with_offer=False, **kwargs):
        """
        Creates a Deal. Automatically matches fields to the real deal model constraints.
        """
        package = kwargs.pop("package_id", None) or self.create_package()
        owner = kwargs.pop("owner_id", None) or self.create_owner()
        property = kwargs.pop("property_id", None) or self.test_property
        bde = kwargs.pop("bde_id", None) or self.test_bde

        gross_amount = package.amount

        values = {
            "property_id": property.id,
            "bde_id": bde.id,
            "owner_id": owner.id,
            "package_id": package.id,
            "gross_amount": gross_amount,
            "deal_type": "regular",
            "deal_status": "registration",
            "is_offer": False,
        }

        if with_offer:
            offer = kwargs.pop("offer_id", None) or self.create_offer()

            if offer.waive_off_type == "fixed":
                discount = offer.waive_off_value
            elif offer.waive_off_type == "percentage":
                discount = package.amount * offer.waive_off_value / 100
            else:
                discount = 0.0

            values.update(
                {
                    "is_offer": True,
                    "offer_id": offer.id,
                    "gross_amount": package.amount - discount,
                },
            )

        values.update(kwargs)
        return self.env["deal"].create(values)

    def create_transaction(self, deal, transaction_type="registration", **kwargs):
        """
        Creates a deal.transaction linked to the given deal.
        """
        default_amount = -1000.0 if transaction_type == "refund" else 1000.0

        values = {
            "deal_id": deal.id,
            "transaction_type": transaction_type,
            "gross_amount": default_amount,
            "payment_channel": "online",
        }
        values.update(kwargs)
        return self.env["deal.transaction"].create(values)

    def _deal_in_status(self, status, closed_reason=None, gross_amount=10000.0, is_full_payment=False):
        """
        Creates a deal and transitions it to the required status.
        For is_full_payment=True, automatically adds full registration
        transaction before live/sold transition.
        """
        deal = self.create_deal(gross_amount=gross_amount, is_full_payment=is_full_payment)

        if status == "live":
            if is_full_payment:
                self.create_transaction(deal, "registration", gross_amount=gross_amount)
            deal.write({"deal_status": "live"})

        elif status == "sold":
            if is_full_payment:
                self.create_transaction(deal, "registration", gross_amount=gross_amount)
            deal.write({"deal_status": "sold"})

        elif status == "renewed":
            deal.write({"deal_status": "renewed"})

        elif status == "closed":
            deal.write({"deal_status": "closed", "closed_reason": closed_reason})

        return deal

    def _add_registration_and_close(self, reg_amount=10000.0):
        """
        Creates a deal, adds a registration transaction, then closes
        with deal_cancelled. Used as base setup for refund tests.
        """
        deal = self.create_deal(gross_amount=reg_amount)
        self.create_transaction(deal, "registration", gross_amount=reg_amount)
        deal.write({"deal_status": "closed", "closed_reason": "deal_cancelled"})
        return deal
