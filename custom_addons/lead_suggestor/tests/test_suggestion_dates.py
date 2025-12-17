from odoo.tests import tagged
from datetime import date
from .test_property_common import PropertyInventoryTestCase

@tagged('post_install', '-at_install')
class TestSuggestionDates(PropertyInventoryTestCase):
    """Test date handling for suggestions"""

    def test_01_generation_date_default_today(self):
        """New suggestion should defailt to today's date."""
        suggestion = self.create_suggestion()

        self.assertEqual(suggestion.generation_date, date.today())

    def test_02_generation_date_display_format(self):
        """Generation date disply should be DD/MM/YYYY. """
        suggestion = self.create_suggestion(
            generation_date = date(2024, 3, 5)
        )

        self.assertEqual(
            suggestion.generation_date_display,
            '05/03/2024',
            "Display format should be DD/MM/YYYY"
        )

    def test_03_generation_date_display_with_zeros(self):
        """Display should include leading zeros."""
        suggestion = self.create_suggestion(
            generation_date = date(2024, 1, 8)
        )

        self.assertEqual(
            suggestion.generation_date_display,
            '08/01/2024',
            "Display format should include leading zeros"
        )

    def test_04_generation_date_recompute(self):
        """Display should recompute when date changes"""
        suggestion = self.create_suggestion(
            generation_date = date(2024, 1, 1)
        )
        self.assertEqual(
            suggestion.generation_date_display,
            '01/01/2024',
            "Initial display format incorrect"
        )

        suggestion.generation_date = date(2024, 12, 31)
        self.assertEqual(
            suggestion.generation_date_display,
            '31/12/2024',
            "Display format should update after date change"
        )

        