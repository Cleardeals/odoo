from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from .test_portal_common import PortalLeadTestCase


@tagged("post_install", "-at_install")
class TestPortalLeadDuplicateDetection(PortalLeadTestCase):
    """
    Test duplicate lead detection logic.
    """

    def test_01_no_duplicate_different_phone(self):
        """Different phone numbers should not be duplicates."""
        # 1. Create Base Lead
        self.create_portal_lead(
            phone="9876543210",
            portal_property_id=self.mb_id,  # Use dynamic ID from Common
        )

        # 2. Create Lead with Different Phone
        lead2_vals = {
            "name": "Lead 2",
            "phone": "9876543211",  # Different Phone
            "portal_property_id": self.mb_id,
            "portal_name": "MagicBricks",
        }

        lead2 = self.env["leads.new"].create_lead_if_not_duplicate(lead2_vals)
        self.assertTrue(lead2, "Should create lead with different phone numbers")

    def test_02_no_duplicate_different_property(self):
        """Different property IDs should not be duplicates."""
        # 1. Create Base Lead
        self.create_portal_lead(
            phone="9876543210",
            portal_property_id=self.mb_id,
        )

        # 2. Create Lead with Different Property ID
        lead2_vals = {
            "name": "Lead 3",
            "phone": "9876543210",  # Same Phone
            "portal_property_id": self.mb_id + "_DIFF",  # Different ID
            "portal_name": "MagicBricks",
        }

        lead2 = self.env["leads.new"].create_lead_if_not_duplicate(lead2_vals)
        self.assertTrue(lead2, "Should create lead with different property IDs")

    def test_03_duplicate_same_phone_and_property_recent(self):
        """Same phone + property within 180 days should be duplicate (return False)."""
        # 1. Create Base Lead
        self.env["leads.new"].create_lead_if_not_duplicate(
            {
                "name": "Base Lead",
                "phone": "9876543210",
                "portal_property_id": self.mb_id,
                "portal_name": "MagicBricks",
            },
        )

        # 2. Create Exact Duplicate (Same Phone, Same Property, Recent)
        lead2_vals = {
            "name": "Lead 4",
            "phone": "9876543210",
            "portal_property_id": self.mb_id,
            "portal_name": "MagicBricks",
        }

        lead2 = self.env["leads.new"].create_lead_if_not_duplicate(lead2_vals)
        self.assertFalse(lead2, "Should NOT create duplicate lead (Recent)")

    def test_04_not_duplicate_after_180_days(self):
        """Same lead after 180 days should be allowed."""
        # 1. Create Old Lead
        old_lead = self.env["leads.new"].create_lead_if_not_duplicate(
            {
                "name": "Old Lead",
                "phone": "9876543210",
                "portal_property_id": self.mb_id,
                "portal_name": "MagicBricks",
            },
        )

        # 2. Force date to 181 days ago via SQL to bypass ORM readonly check
        old_date = fields.Datetime.now() - timedelta(days=181)
        self.env.cr.execute(
            "UPDATE leads_new SET create_date = %s WHERE id = %s",
            (old_date, old_lead.id),
        )
        old_lead.invalidate_recordset()

        # 3. Create Duplicate (Should Pass now)
        new_lead_vals = {
            "name": "New Lead",
            "phone": "9876543210",
            "portal_property_id": self.mb_id,
            "portal_name": "MagicBricks",
        }

        new_lead = self.env["leads.new"].create_lead_if_not_duplicate(new_lead_vals)
        self.assertTrue(new_lead, "Should create lead after 180 days expiration")

    def test_05_duplicate_detection_returns_none(self):
        """Duplicate detection should return None and not create a new lead."""
        # 1. Create Base Lead
        self.env["leads.new"].create_lead_if_not_duplicate(
            {
                "name": "Base Lead",
                "phone": "9876543210",
                "portal_property_id": self.mb_id,
                "portal_name": "MagicBricks",
            },
        )

        # 2. Attempt Duplicate
        lead2_vals = {
            "name": "Duplicate",
            "phone": "9876543210",
            "portal_property_id": self.mb_id,
            "portal_name": "MagicBricks",
            "raw_data": "test data",
        }

        result = self.env["leads.new"].create_lead_if_not_duplicate(lead2_vals)

        # 3. Verify duplicate was silently skipped (no new lead, no chatter noise)
        self.assertIsNone(result, "Duplicate should return None, not create a new lead")
        duplicate_count = self.env["leads.new"].search_count(
            [
                ("phone", "=", "9876543210"),
                ("portal_property_id", "=", self.mb_id),
            ],
        )
        self.assertEqual(
            duplicate_count,
            1,
            "Only one lead should exist for this phone/property",
        )

    def test_06_duplicate_same_property_different_portal_ids(self):
        """Same phone + same mapped property via different portal IDs is duplicate."""
        listing_model = self.env["property.portal.listing"]

        alternate_99_id = f"99_ALT_{self.suffix}"
        listing_model.create(
            {
                "property_base_id": self.test_property.id,
                "portal_name": "99acres",
                "portal_listing_id": alternate_99_id,
                "listing_label": "Alt 99",
            },
        )

        first_vals = {
            "name": "Lead MB",
            "phone": "9876543210",
            "portal_property_id": self.mb_id,
            "portal_name": "MagicBricks",
        }
        first_lead = self.env["leads.new"].create_lead_if_not_duplicate(first_vals)
        self.assertTrue(first_lead)

        second_vals = {
            "name": "Lead 99",
            "phone": "9876543210",
            "portal_property_id": alternate_99_id,
            "portal_name": "99acres",
        }
        duplicate = self.env["leads.new"].create_lead_if_not_duplicate(second_vals)
        self.assertIsNone(duplicate, "Should dedupe by resolved property_base_id")
