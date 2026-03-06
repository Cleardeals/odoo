import random
import time
from datetime import date, timedelta

from odoo.tests.common import TransactionCase


class PropertyInventoryTestCase(TransactionCase):
    """
    Base test case with common setup for property inventory tests.
    Provides reusable fixtures and helper methods.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Generate unique identifiers to avoid conflicts
        cls.timestamp = str(int(time.time()))

        # Create test RM user
        cls.rm_user = cls.env["res.users"].create(
            {
                "name": "Test RM",
                "login": f"test_rm_{cls.timestamp}",
                "email": f"test_rm_{cls.timestamp}@example.com",
            },
        )

        # Create a Second RM for testing assignments
        cls.rm_user2 = cls.env["res.users"].create(
            {
                "name": "Second RM",
                "login": f"second_rm_{cls.timestamp}",
                "email": f"rm2_{cls.timestamp}@test.com",
            },
        )

    def create_property(self, **kwargs):
        """Helper to create a property.base record with sensible defaults.

        Uses property.base — the canonical model after the lead_suggestor
        migration.  All suggestion-related tests should use this helper.
        """
        unique_suffix = f"{int(time.time() * 100000)}_{random.randint(1000, 9999)}"

        values = {
            "name": f"Test Property {unique_suffix}",
            # prop_id drives the computed property_link field
            "prop_id": f"TP{unique_suffix[-6:]}",
            "property_tag": f"TEST-PROP-{unique_suffix}",
            "rm_user_id": self.rm_user.id,
            "is_active": True,
            "service_expiry_date": date.today() + timedelta(days=30),
            "welcome_call_date": date.today(),
            # bedroom_count drives the computed bhk field (e.g. "3 BHK")
            "bedroom_count": 3,
            "location": "Test Location",
            "city": "Test City",
        }
        values.update(kwargs)
        return self.env["property.base"].create(values)

    def create_inventory(self, **kwargs):
        """Helper to create a property.inventory record (legacy model).

        Used only by tests that specifically target the property.inventory
        model (e.g. the BQ sync cron and the expiry-cleanup cron).
        """
        unique_suffix = f"{int(time.time() * 100000)}_{random.randint(1000, 9999)}"

        values = {
            "property_tag": f"TEST-INV-{unique_suffix}",
            "rm_user_id": self.rm_user.id,
            "is_active": True,
            "service_expiry_date": date.today() + timedelta(days=30),
            "welcome_call_date": date.today(),
            "bhk": "3 BHK",
            "location": "Test Location",
            "city": "Test City",
            "property_link": "https://test.com/property",
        }
        values.update(kwargs)
        return self.env["property.inventory"].create(values)

    def create_suggestion(self, property_rec=None, **kwargs):
        """Helper to create a property.lead.suggestion with defaults.

        property_rec should be a property.base record.  property_tag is
        explicitly copied from the property so it survives even before the
        FK backfill runs.
        """
        if property_rec is None:
            property_rec = self.create_property()

        # Unique phone logic
        unique_suffix = f"{int(time.time() * 1000)}_{random.randint(100, 999)}"
        unique_phone = f"9{unique_suffix[-9:]}"

        values = {
            "property_base_id": property_rec.id,
            "property_tag": property_rec.property_tag,
            "suggested_lead_phone": unique_phone,
            "lead_name": "Test Lead",
            "original_property_tag": "OLD-PROP-001",
            "original_property_similarity": 85.0,
            "generation_date": date.today(),
            "contact_type": "New",
            "status": "new",
        }
        values.update(kwargs)
        return self.env["property.lead.suggestion"].create(values)
