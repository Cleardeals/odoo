"""
Tests for date field storage and display formatting on ``property.base``.

Covers:
  - service_expiry_date storage and retrieval
  - welcome_call_date storage and retrieval
  - _compute_date_displays: DD/MM/YYYY formatting
  - Leading-zero handling (day 01-09, month 01-09)
  - Empty / False dates display as empty strings
  - Recomputation when date changes
"""

from datetime import date

from odoo.tests import tagged

from .test_property_common import PropertyBaseTestCase


@tagged("post_install", "-at_install")
class TestPropertyBaseDates(PropertyBaseTestCase):
    """Date storage and DD/MM/YYYY display formatting."""

    # ------------------------------------------------------------------ #
    # Storage                                                              #
    # ------------------------------------------------------------------ #

    def test_01_service_expiry_date_stored_correctly(self):
        """service_expiry_date should be stored and retrieved as a date object."""
        expiry = date(2026, 12, 31)
        prop = self.make_property(service_expiry_date=expiry)
        self.assertEqual(prop.service_expiry_date, expiry)

    def test_02_welcome_call_date_stored_correctly(self):
        """welcome_call_date should be stored and retrieved as a date object."""
        welcome = date(2025, 6, 15)
        prop = self.make_property(welcome_call_date=welcome)
        self.assertEqual(prop.welcome_call_date, welcome)

    def test_03_both_date_fields_stored_independently(self):
        """Both date fields can hold different values simultaneously."""
        prop = self.make_property(
            service_expiry_date=date(2027, 1, 1),
            welcome_call_date=date(2025, 11, 11),
        )
        self.assertEqual(prop.service_expiry_date, date(2027, 1, 1))
        self.assertEqual(prop.welcome_call_date, date(2025, 11, 11))

    # ------------------------------------------------------------------ #
    # Display format: DD/MM/YYYY                                           #
    # ------------------------------------------------------------------ #

    def test_04_service_expiry_display_format(self):
        """Display format for service_expiry_date must be DD/MM/YYYY."""
        prop = self.make_property(service_expiry_date=date(2026, 3, 14))
        self.assertEqual(prop.service_expiry_date_display, "14/03/2026")

    def test_05_welcome_call_display_format(self):
        """Display format for welcome_call_date must be DD/MM/YYYY."""
        prop = self.make_property(welcome_call_date=date(2025, 12, 25))
        self.assertEqual(prop.welcome_call_date_display, "25/12/2025")

    def test_06_display_leading_zeros_day(self):
        """Single-digit day must be zero-padded in the display field."""
        prop = self.make_property(service_expiry_date=date(2026, 5, 3))
        self.assertEqual(prop.service_expiry_date_display, "03/05/2026")

    def test_07_display_leading_zeros_month(self):
        """Single-digit month must be zero-padded in the display field."""
        prop = self.make_property(welcome_call_date=date(2025, 2, 20))
        self.assertEqual(prop.welcome_call_date_display, "20/02/2025")

    def test_08_display_leading_zeros_both_day_and_month(self):
        """Both day and month should be zero-padded when single-digit."""
        prop = self.make_property(
            service_expiry_date=date(2026, 1, 5),
            welcome_call_date=date(2025, 2, 8),
        )
        self.assertEqual(prop.service_expiry_date_display, "05/01/2026")
        self.assertEqual(prop.welcome_call_date_display, "08/02/2025")

    def test_09_display_format_is_slash_separated(self):
        """Separator must be '/' not '-' or '.'."""
        prop = self.make_property(service_expiry_date=date(2026, 6, 30))
        self.assertIn("/", prop.service_expiry_date_display)
        self.assertNotIn("-", prop.service_expiry_date_display)
        self.assertNotIn(".", prop.service_expiry_date_display)

    def test_10_display_order_is_day_month_year(self):
        """Display order must be DD/MM/YYYY, not YYYY/MM/DD or MM/DD/YYYY."""
        prop = self.make_property(service_expiry_date=date(2026, 11, 7))
        # 07/11/2026 — if it were MM/DD/YYYY it would be 11/07/2026
        self.assertEqual(prop.service_expiry_date_display, "07/11/2026")

    # ------------------------------------------------------------------ #
    # Empty / False dates                                                  #
    # ------------------------------------------------------------------ #

    def test_11_empty_service_expiry_display_is_empty_string(self):
        """False/missing service_expiry_date should display as ''."""
        prop = self.make_property(service_expiry_date=False)
        self.assertEqual(prop.service_expiry_date_display, "")

    def test_12_empty_welcome_call_display_is_empty_string(self):
        """False/missing welcome_call_date should display as ''."""
        prop = self.make_property(welcome_call_date=False)
        self.assertEqual(prop.welcome_call_date_display, "")

    # ------------------------------------------------------------------ #
    # Recomputation                                                        #
    # ------------------------------------------------------------------ #

    def test_13_service_expiry_display_recomputes_on_change(self):
        """Display field must update when underlying date changes."""
        prop = self.make_property(service_expiry_date=date(2026, 1, 1))
        self.assertEqual(prop.service_expiry_date_display, "01/01/2026")

        prop.write({"service_expiry_date": date(2027, 12, 31)})
        self.assertEqual(prop.service_expiry_date_display, "31/12/2027")

    def test_14_welcome_call_display_recomputes_on_change(self):
        """welcome_call_date_display must update when date changes."""
        prop = self.make_property(welcome_call_date=date(2025, 3, 1))
        self.assertEqual(prop.welcome_call_date_display, "01/03/2025")

        prop.write({"welcome_call_date": date(2026, 9, 15)})
        self.assertEqual(prop.welcome_call_date_display, "15/09/2026")

    def test_15_display_clears_when_date_set_to_false(self):
        """Display field should become '' when date is cleared."""
        prop = self.make_property(service_expiry_date=date(2026, 6, 1))
        self.assertNotEqual(prop.service_expiry_date_display, "")

        prop.write({"service_expiry_date": False})
        self.assertEqual(prop.service_expiry_date_display, "")
