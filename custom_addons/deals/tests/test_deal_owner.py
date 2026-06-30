from psycopg2 import IntegrityError

from odoo.tests import mute_logger, tagged

from .test_deal_common import DealCommonTestCase


@tagged("-at_install", "post_install")
class TestDealOwner(DealCommonTestCase):
    """Tests for deal.owner behavior (owner table)."""

    def test_01_create_and_read_owner(self):
        """Create and read the entity of owner table."""
        owner = self.create_owner(name="Test Owner", phone="9876543210")

        self.assertEqual(owner.name, "Test Owner")
        self.assertEqual(owner.phone, "9876543210")

    def test_02_isbuilder_default_false(self):
        """is_builder default is false."""
        owner = self.create_owner(name="Builder Test", phone="0987654321")
        self.assertFalse(owner.is_builder)

    def test_03_name_is_required(self):
        """Name is required to save this otherwise it is rejected."""
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            self.env["deal.owner"].create(
                {
                    "phone": "9876543210",
                    # Name is missing
                },
            )

    def test_04_phone_is_required(self):
        """Phone is required to save this otherwise it is rejected."""
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            self.env["deal.owner"].create(
                {
                    "name": "Test Owner",
                    # Phone is missing
                },
            )

    def test_05_tracking_true_for_all_changes(self):
        """Tracking true for all changes."""
        owner_model = self.env["deal.owner"]
        self.assertTrue(bool(owner_model._fields["name"].tracking))
        self.assertTrue(bool(owner_model._fields["phone"].tracking))
        self.assertTrue(bool(owner_model._fields["is_builder"].tracking))

    def test_06_phone_is_unique(self):
        """Phone is unique, so creating two owners with the same phone should raise an error."""
        self.create_owner(name="Owner One", phone="9867321456")
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            self.create_owner(name="Owner Two", phone="9867321456")

    def test_07_cannot_delete_owner_linked_to_deal(self):
        """Cannot delete an owner if it is linked to a deal."""
        owner = self.create_owner(name="Owner To Delete", phone="9876543211")
        deal = self.create_deal(owner_id=owner)

        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            owner.unlink()
