from odoo.tests import tagged
from datetime import date
from .test_property_common import PropertyInventoryTestCase

@tagged('post_install', '-at_install')
class TestPropertyInventoryDates(PropertyInventoryTestCase):
    """Test date field storrage and display formatting"""

    def test_01_service_expiry_date_storage(self):
        """Should correctly store service expiry date."""
        expiry = date(2026, 3, 14)
        prop = self.create_property(service_expiry_date=expiry)

        self.assertEqual(prop.service_expiry_date, expiry)

    
    def test_02_welcome_call_date_storage(self):
        """Should correctly store welcome call date."""
        welcome = date(2025, 12, 25)
        prop = self.create_property(welcome_call_date=welcome)
        self.assertEqual(prop.welcome_call_date, welcome)

    def test_03_service_expiry_display_format(self):
        """Service expiry display should be in DD-MM-YYYY format."""
        expiry = date(2026, 3, 14)
        prop = self.create_property(service_expiry_date=expiry)

        self.assertEqual(
            prop.service_expiry_date_display,
            '14/03/2026',
            "Display format should be DD/MM/YYYY"
        )

    def test_04_welcome_call_display_format(self):
        """Welcome call display should be in DD-MM-YYYY format."""
        welcome = date(2025, 12, 25)
        prop = self.create_property(welcome_call_date=welcome)
        self.assertEqual(
            prop.welcome_call_date_display,
            '25/12/2025',
            "Display format should be DD/MM/YYYY"
        )

    def test_05_date_display_with_leading_zeros(self):
        """Display format should include leading zeros."""
        prop = self.create_property(
            service_expiry_date = date(2026, 1, 5),
            welcome_call_date = date(2025, 2, 8)
        )

        self.assertEqual(
            prop.service_expiry_date_display,
            '05/01/2026',
            "Service expiry should have leading zeros in display"
        )

        self.assertEqual(
            prop.welcome_call_date_display,
            '08/02/2025',
            "Welcome call date should have leading zeros in display"
        )

    def test_06_empty_date_display(self):
        """Empty dates should display as empty strings."""
        prop = self.create_property(
            service_expiry_date = False,
            welcome_call_date = False
        )

        self.assertEqual(prop.service_expiry_date_display, '', "Empty service expiry should display as empty string")
        self.assertEqual(prop.welcome_call_date_display, '', "Empty welcome call date should display as empty string")

    def test_07_date_recompute_on_change(self):
        """Display dates should recompute when date fields change."""
        prop = self.create_property(
            service_expiry_date = date(2026, 1, 1),
        )

        self.assertEqual(prop.service_expiry_date_display, '01/01/2026', "Initial display should match initial date")

        # change the date
        prop.service_expiry_date = date(2026, 12, 31)
        self.assertEqual(prop.service_expiry_date_display, '31/12/2026', "Display should update after date change")

        