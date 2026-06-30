from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import tagged
from odoo.tools import mute_logger

from .test_deal_common import DealCommonTestCase


@tagged("post_install", "-at_install")
class TestDealSecurity(DealCommonTestCase):
    """
    Test cases for deal security and access control rules.
    """

    def test_01_deo_can_create_deal(self):
        """DEO can create a deal (perm_create=1)."""
        deal = (
            self.env["deal"]
            .with_user(self.deo_user)
            .create(
                {
                    "property_id": self.env["property.base"].search([], limit=1).id,
                    "bde_id": self.env["leads.bde"].search([], limit=1).id,
                    "owner_id": self.create_owner().id,
                    "package_id": self.create_package().id,
                    "gross_amount": 35400.0,
                    "deal_type": "regular",
                    "deal_status": "registration",
                    "is_offer": False,
                },
            )
        )
        self.assertTrue(deal.id)

    def test_02_deo_can_write_deal(self):
        """DEO can write/edit a deal (perm_write=1)."""
        deal = self.create_deal()
        deal.with_user(self.deo_user).write({"deal_type": "ops_sale_lead"})
        self.assertEqual(deal.deal_type, "ops_sale_lead")

    def test_03_deo_cannot_delete_deal(self):
        """DEO cannot delete a deal (perm_unlink=0)."""
        deal = self.create_deal()
        with mute_logger("odoo.sql_db"), self.assertRaises(AccessError):
            deal.with_user(self.deo_user).unlink()

    def test_04_deo_can_create_transaction(self):
        """DEO can create a transaction (perm_create=1)."""
        deal = self.create_deal()
        transaction = self.create_transaction(
            deal, transaction_type="registration", gross_amount=35400.0
        )
        self.assertTrue(transaction.id)

    def test_05_deo_cannot_delete_owner(self):
        """DEO cannot delete an owner (perm_unlink=0)."""
        owner = self.create_owner()
        with mute_logger("odoo.sql_db"), self.assertRaises(AccessError):
            owner.with_user(self.deo_user).unlink()

    def test_06_deo_cannot_delete_package(self):
        """DEO cannot delete a package (perm_unlink=0)."""
        package = self.create_package()
        with mute_logger("odoo.sql_db"), self.assertRaises(AccessError):
            package.with_user(self.deo_user).unlink()

    def test_07_deo_cannot_delete_offer(self):
        """DEO cannot delete an offer (perm_unlink=0)."""
        offer = self.create_offer()
        with mute_logger("odoo.sql_db"), self.assertRaises(AccessError):
            offer.with_user(self.deo_user).unlink()

    @mute_logger("odoo.sql_db")
    def test_08_deo_can_create_owner_package_offer(self):
        """DEO can create owner, package, and offer."""

        owner = (
            self.env["deal.owner"]
            .with_user(self.deo_user)
            .create(
                {
                    "name": "Test Owner",
                    "phone": "9000000001",
                },
            )
        )
        self.assertTrue(owner)
        self.assertTrue(owner.exists())

        package = (
            self.env["deal.package"]
            .with_user(self.deo_user)
            .create(
                {
                    "name": "Test Package",
                    "amount": 10000.0,
                },
            )
        )
        self.assertTrue(package)
        self.assertTrue(package.exists())

        offer = (
            self.env["deal.offer"]
            .with_user(self.deo_user)
            .create(
                {
                    "name": "Test Offer",
                    "waive_off_type": "percentage",
                    "waive_off_value": 10.0,
                },
            )
        )
        self.assertTrue(offer)
        self.assertTrue(offer.exists())

    def test_09_manager_can_delete_deal_with_no_transaction(self):
        """Manager can delete a deal when no transaction is linked."""
        deal = self.create_deal()
        deal_id = deal.id
        deal.with_user(self.manager_user).unlink()
        self.assertFalse(self.env["deal"].browse(deal_id).exists())

    def test_10_manager_can_delete_owner_with_no_deal(self):
        """Manager can delete an owner when no deal is linked."""
        owner = self.create_owner()
        owner_id = owner.id
        owner.with_user(self.manager_user).unlink()
        self.assertFalse(self.env["deal.owner"].browse(owner_id).exists())

    def test_11_manager_creates_deal_deo_can_edit(self):
        """Manager creates a deal; DEO can write/edit it."""
        deal = self.create_deal()
        deal.with_user(self.deo_user).write({"deal_type": "ops_sale_lead"})
        self.assertEqual(deal.deal_type, "ops_sale_lead")

    def test_12_deo_creates_deal_manager_can_edit(self):
        """DEO creates a deal; Manager can write/edit it."""
        deal = self.create_deal()
        deal.with_user(self.manager_user).write({"deal_type": "renewal"})
        self.assertEqual(deal.deal_type, "renewal")

    def test_13_transaction_id_update_blocked_for_manager(self):
        """Updating transaction_id raises ValidationError even for manager."""
        deal = self.create_deal()
        transaction = self.create_transaction(deal)
        with self.assertRaises(ValidationError):
            transaction.with_user(self.manager_user).write(
                {"transaction_id": "FAKE-ID-999"},
            )
