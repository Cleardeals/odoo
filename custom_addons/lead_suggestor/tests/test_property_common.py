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
        """Helper to create Property Inventory with sensible defaults."""
        # [FIX] Use high-resolution time + random int to guarantee uniqueness
        unique_suffix = f"{int(time.time() * 100000)}_{random.randint(1000, 9999)}"

        values = {
            "property_tag": f"TEST-PROP-{unique_suffix}",
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
        """Helper to create a suggestion with defaults."""
        if property_rec is None:
            property_rec = self.create_property()

        # Unique phone logic
        unique_suffix = f"{int(time.time() * 1000)}_{random.randint(100, 999)}"
        # Ensure it fits standard phone length (10 digits) if possible, or just unique
        unique_phone = f"9{unique_suffix[-9:]}"

        values = {
            "property_inventory_id": property_rec.id,
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
