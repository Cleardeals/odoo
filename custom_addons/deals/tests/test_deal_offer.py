from time import time

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .test_deal_common import DealCommonTestCase


@tagged("-at_install", "post_install")
class TestDealOffer(DealCommonTestCase):
    """Tests for deal.offer behavior (offer table)."""

    def test_01_percentage_applies(self):
        """Percentage waive-off should reduce the base amount correctly."""
        offer = self.create_offer(waive_off_type="percentage", waive_off_value=10.0)

        result = offer.apply_waive_off(1000.0)
        self.assertAlmostEqual(result, 900.0)

    def test_02_fixed_amount_applies(self):
        """Fixed waive-off should subtract a fixed amount correctly."""
        offer = self.create_offer(waive_off_type="fixed", waive_off_value=250.0)

        result = offer.apply_waive_off(1000.0)
        self.assertAlmostEqual(result, 750.0)

    def test_03_fixed_amount_greater_than_base_returns_zero(self):
        """Fixed waive-off greater than base should clamp net amount to 0."""
        offer = self.create_offer(waive_off_type="fixed", waive_off_value=1500.0)

        result = offer.apply_waive_off(1000.0)
        self.assertEqual(result, 0.0)

    def test_04_hundred_percent_offer_net_zero_logic(self):
        """100% discount should produce net amount 0 in apply logic."""
        offer = self.create_offer(
            waive_off_type="percentage",
            waive_off_value=100.0,
        )

        result = offer.apply_waive_off(1000.0)
        self.assertEqual(result, 0.0)

    def test_05_percent_just_above_zero_allowed(self):
        """Percentage just above zero should be accepted."""
        offer = self.create_offer(waive_off_type="percentage", waive_off_value=0.01)
        self.assertTrue(offer.id)
        result = offer.apply_waive_off(1000.0)
        self.assertAlmostEqual(result, 999.9)

    def test_06_default_waive_off_type_is_percentage(self):
        """Default waive_off_type should be percentage."""
        offer = self.env["deal.offer"].create(
            {
                "name": f"Offer default type {time()}",
                "waive_off_value": 5.0,
            },
        )
        self.assertEqual(offer.waive_off_type, "percentage")

    def test_07_zero_percent_rejected(self):
        """Zero percentage should be rejected by constraints."""
        with self.assertRaisesRegex(
            ValidationError,
            "Percentage value must be greater than 0 and less than or equal to 100",
        ):
            self.create_offer(waive_off_type="percentage", waive_off_value=0.0)

    def test_08_percentage_above_hundred_rejected(self):
        """Percentage above 100 should be rejected."""
        with self.assertRaisesRegex(
            ValidationError,
            "Percentage value must be greater than 0 and less than or equal to 100",
        ):
            self.create_offer(waive_off_type="percentage", waive_off_value=100.01)

    def test_09_negative_percent_rejected(self):
        """Negative percentage should be rejected."""
        with self.assertRaisesRegex(
            ValidationError,
            "Percentage value must be greater than 0 and less than or equal to 100",
        ):
            self.create_offer(waive_off_type="percentage", waive_off_value=-1.0)

    def test_10_fixed_amount_zero_rejected(self):
        """Fixed amount equal to zero should be rejected."""
        with self.assertRaisesRegex(
            ValidationError, "Fixed amount value must be greater than 0"
        ):
            self.create_offer(waive_off_type="fixed", waive_off_value=0.0)

    def test_11_fixed_amount_negative_rejected(self):
        """Negative fixed amount should be rejected."""
        with self.assertRaisesRegex(
            ValidationError, "Fixed amount value must be greater than 0"
        ):
            self.create_offer(waive_off_type="fixed", waive_off_value=-50.0)

    def test_12_write_revalidates_percentage_or_fixed(self):
        """Write() should re-run constraints for both types."""
        offer = self.create_offer(waive_off_type="percentage", waive_off_value=20.0)

        with self.assertRaisesRegex(
            ValidationError,
            "Percentage value must be greater than 0 and less than or equal to 100",
        ):
            offer.write({"waive_off_value": -10.0})

        offer.write({"waive_off_type": "fixed", "waive_off_value": 100.0})
        result = offer.apply_waive_off(1000.0)
        self.assertAlmostEqual(result, 900.0)

        with self.assertRaisesRegex(
            ValidationError, "Fixed amount value must be greater than 0"
        ):
            offer.write({"waive_off_value": 0.0})

    def test_13_percentage_write_cases(self):
        """Percentage write matrix (<=0 reject, >100 reject, valid recalc)."""
        offer = self.create_offer(waive_off_type="percentage", waive_off_value=10.0)

        with self.assertRaisesRegex(
            ValidationError,
            "Percentage value must be greater than 0 and less than or equal to 100",
        ):
            offer.write({"waive_off_value": -0.01})

        with self.assertRaisesRegex(
            ValidationError,
            "Percentage value must be greater than 0 and less than or equal to 100",
        ):
            offer.write({"waive_off_value": 0.0})

        with self.assertRaisesRegex(
            ValidationError,
            "Percentage value must be greater than 0 and less than or equal to 100",
        ):
            offer.write({"waive_off_value": 100.01})

        offer.write({"waive_off_value": 25.0})
        result = offer.apply_waive_off(1000.0)
        self.assertAlmostEqual(result, 750.0)

    def test_14_fixed_write_cases(self):
        """Fixed write matrix (negative reject, zero reject, positive recalculate)."""
        offer = self.create_offer(waive_off_type="fixed", waive_off_value=100.0)

        with self.assertRaisesRegex(
            ValidationError, "Fixed amount value must be greater than 0"
        ):
            offer.write({"waive_off_value": -1.0})

        with self.assertRaisesRegex(
            ValidationError, "Fixed amount value must be greater than 0"
        ):
            offer.write({"waive_off_value": 0.0})

        offer.write({"waive_off_value": 250.0})
        result = offer.apply_waive_off(1000.0)
        self.assertAlmostEqual(result, 750.0)

    def test_15_type_switch_revalidates_and_recalculates(self):
        """Switching type should not error for valid values and should recalc."""
        offer = self.create_offer(waive_off_type="percentage", waive_off_value=10.0)
        result = offer.apply_waive_off(1000.0)
        self.assertAlmostEqual(result, 900.0)

        offer.write({"waive_off_type": "fixed", "waive_off_value": 150.0})
        result = offer.apply_waive_off(1000.0)
        self.assertAlmostEqual(result, 850.0)

        offer.write({"waive_off_type": "percentage", "waive_off_value": 5.0})
        result = offer.apply_waive_off(1000.0)
        self.assertAlmostEqual(result, 950.0)

    def test_16_defaults_active_domain_and_tracking(self):
        """Default active, active-domain behavior, and field tracking flags."""
        active_offer = self.create_offer(
            waive_off_type="percentage", waive_off_value=10.0
        )
        inactive_offer = self.create_offer(
            waive_off_type="fixed", waive_off_value=100.0, is_active=False
        )

        self.assertTrue(active_offer.is_active)

        offer_model = self.env["deal.offer"]
        active_records = offer_model.search(
            [
                ("id", "in", [active_offer.id, inactive_offer.id]),
                ("is_active", "=", True),
            ],
        )
        self.assertIn(active_offer, active_records)
        self.assertNotIn(inactive_offer, active_records)

        self.assertTrue(bool(offer_model._fields["name"].tracking))
        self.assertTrue(bool(offer_model._fields["waive_off_type"].tracking))
        self.assertTrue(bool(offer_model._fields["waive_off_value"].tracking))
        self.assertTrue(bool(offer_model._fields["is_active"].tracking))
