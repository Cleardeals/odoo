"""
Unit tests for the pure parsing/normalisation helpers in property_sync.py.

These functions translate the messy shapes of the website API into clean
property.base values.  They were only exercised end-to-end before; here we pin
their behaviour and edge cases directly so a regression in parsing is caught
immediately, independent of the cron.

Covered:
  * _normalize_owner_phone   — strips formatting / country code to 10 digits.
  * _parse_bedroom_count     — '3 BHK' -> 3, junk -> 0.
  * _parse_reg_date          — ISO datetime -> YYYY-MM-DD, empty -> False.
  * _parse_pricing / _parse_pricing_unit — for_sell routing to sell vs rent.
  * _map_api_record          — full API item -> vals dict, nested fallbacks.
"""

from odoo.tests import TransactionCase, tagged

from odoo.addons.properties.models.property_sync import (
    _map_api_record,
    _normalize_owner_phone,
    _parse_bedroom_count,
    _parse_pricing,
    _parse_pricing_unit,
    _parse_reg_date,
)


@tagged("post_install", "-at_install")
class TestPropertySyncHelpers(TransactionCase):
    """Pure-function parsing helpers — no DB state needed."""

    # ------------------------------------------------------------------ #
    # _normalize_owner_phone                                              #
    # ------------------------------------------------------------------ #

    def test_phone_10_digit_passthrough(self):
        self.assertEqual(_normalize_owner_phone("9876543210"), "9876543210")

    def test_phone_strips_formatting(self):
        self.assertEqual(_normalize_owner_phone("+91 98765-43210"), "9876543210")

    def test_phone_11_digit_leading_zero(self):
        self.assertEqual(_normalize_owner_phone("09876543210"), "9876543210")

    def test_phone_12_digit_country_code(self):
        self.assertEqual(_normalize_owner_phone("919876543210"), "9876543210")

    def test_phone_empty_returns_empty(self):
        self.assertEqual(_normalize_owner_phone(""), "")
        self.assertEqual(_normalize_owner_phone(None), "")

    def test_phone_unrecognised_preserved_raw(self):
        """An unexpected length is returned as-is so data is never lost."""
        self.assertEqual(_normalize_owner_phone("12345"), "12345")

    # ------------------------------------------------------------------ #
    # _parse_bedroom_count                                                 #
    # ------------------------------------------------------------------ #

    def test_bedroom_with_suffix(self):
        self.assertEqual(_parse_bedroom_count("3 BHK"), 3)

    def test_bedroom_no_space(self):
        self.assertEqual(_parse_bedroom_count("2BHK"), 2)

    def test_bedroom_none_and_empty(self):
        self.assertEqual(_parse_bedroom_count(None), 0)
        self.assertEqual(_parse_bedroom_count(""), 0)

    def test_bedroom_non_numeric(self):
        self.assertEqual(_parse_bedroom_count("Studio"), 0)

    # ------------------------------------------------------------------ #
    # _parse_reg_date                                                      #
    # ------------------------------------------------------------------ #

    def test_reg_date_iso_datetime(self):
        self.assertEqual(
            _parse_reg_date("2026-03-02T00:00:00.000Z"), "2026-03-02"
        )

    def test_reg_date_already_clean(self):
        self.assertEqual(_parse_reg_date("2026-03-02"), "2026-03-02")

    def test_reg_date_empty_returns_false(self):
        self.assertIs(_parse_reg_date(None), False)
        self.assertIs(_parse_reg_date(""), False)

    # ------------------------------------------------------------------ #
    # _parse_pricing / _parse_pricing_unit                                #
    # ------------------------------------------------------------------ #

    def test_pricing_for_sale_uses_sell_block(self):
        item = {
            "for_sell": True,
            "sell_pricing": {"offer_price": 48.0, "offer_price_unit": "lakh"},
            "rent_pricing": {"rent_price": 20.0, "rent_price_unit": "thousand"},
        }
        self.assertEqual(_parse_pricing(item), 48.0)
        self.assertEqual(_parse_pricing_unit(item), "lakh")

    def test_pricing_for_rent_uses_rent_block(self):
        item = {
            "for_sell": False,
            "sell_pricing": {"offer_price": 48.0, "offer_price_unit": "lakh"},
            "rent_pricing": {"rent_price": 20.0, "rent_price_unit": "thousand"},
        }
        self.assertEqual(_parse_pricing(item), 20.0)
        self.assertEqual(_parse_pricing_unit(item), "thousand")

    def test_pricing_missing_blocks_return_zero(self):
        self.assertEqual(_parse_pricing({"for_sell": True}), 0.0)
        self.assertEqual(_parse_pricing({"for_sell": False}), 0.0)
        self.assertEqual(_parse_pricing_unit({"for_sell": True}), "")

    # ------------------------------------------------------------------ #
    # _map_api_record                                                      #
    # ------------------------------------------------------------------ #

    def test_map_api_record_full_item(self):
        item = {
            "id": "uuid-1",
            "prop_id": "PID1",
            "form_no": "FORM-1",
            "property_name": "Tower A",
            "reg_date": "2026-03-02T00:00:00.000Z",
            "prop_type": "residential",
            "for_sell": True,
            "prop_sub_type": "Apartment",
            "exec_name": "Vivek Vaghela",
            "owner_name": "Owner",
            "owner_contact_no": "+91 98765-43210",
            "owner_email": "o@x.com",
            "gmaps_url": "http://maps",
            "state": {"name": "Maharashtra"},
            "city": {"name": "Mumbai"},
            "location_area": {"name": "Andheri"},
            "details": {"bedroom_count": "3 BHK"},
            "sell_pricing": {"offer_price": 48.0, "offer_price_unit": "lakh"},
        }
        vals = _map_api_record(item)

        self.assertEqual(vals["uuid"], "uuid-1")
        self.assertEqual(vals["name"], "Tower A")
        self.assertEqual(vals["reg_date"], "2026-03-02")
        self.assertEqual(vals["state"], "Maharashtra")
        self.assertEqual(vals["city"], "Mumbai")
        self.assertEqual(vals["location"], "Andheri")
        self.assertEqual(vals["owner_phone"], "9876543210")
        self.assertEqual(vals["bedroom_count"], 3)
        self.assertEqual(vals["pricing"], 48.0)
        self.assertEqual(vals["pricing_unit"], "lakh")
        self.assertEqual(vals["_exec_name"], "Vivek Vaghela")
        # Manager-editable fields must never be produced by the API mapper.
        for forbidden in (
            "property_tag",
            "service_expiry_date",
            "welcome_call_date",
            "ninety_nine_acres_id",
        ):
            self.assertNotIn(forbidden, vals)

    def test_map_api_record_missing_nested_objects(self):
        """Absent nested location/details objects fall back to empties."""
        vals = _map_api_record({"id": "u", "property_name": "X", "for_sell": False})
        self.assertEqual(vals["state"], "")
        self.assertEqual(vals["city"], "")
        self.assertEqual(vals["location"], "")
        self.assertEqual(vals["bedroom_count"], 0)
        self.assertEqual(vals["pricing"], 0.0)
        self.assertEqual(vals["owner_phone"], "")
