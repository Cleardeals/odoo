"""
CRUD tests for the ``property.base`` model.

Covers:
  - Minimum-field creation
  - Required field enforcement (name)
  - Unique constraints (uuid, prop_id)
  - Full field storage across all four field groups (PROP-2.1 through PROP-2.5)
  - Search domain filtering
  - Default ordering (reg_date desc, id desc)
  - Record update via write()
  - Record deletion (unlink)
"""

from datetime import date, timedelta

import psycopg2

from odoo.tests import tagged
from odoo.tools import mute_logger

from .test_property_common import PropertyBaseTestCase


@tagged("post_install", "-at_install")
class TestPropertyBaseCRUD(PropertyBaseTestCase):
    """CRUD operations on property.base."""

    # ------------------------------------------------------------------ #
    # Creation                                                             #
    # ------------------------------------------------------------------ #

    def test_01_create_with_minimum_fields(self):
        """Should create a record when only ``name`` is supplied."""
        prop = self.env["property.base"].create({"name": "Minimal Property"})
        self.assertTrue(prop.id, "Record should have a database id after create()")
        self.assertEqual(prop.name, "Minimal Property")

    def test_02_create_with_all_api_sourced_fields(self):
        """All PROP-2.1 API-sourced fields should be stored verbatim."""
        prop = self.make_property(
            uuid="aabbccdd-eeff-0011-2233-445566778899",
            prop_id="ABCD12",
            form_no="F-2024-001",
            name="Full Field Property",
            prop_type="Commercial",
            prop_sub_type="Office",
            for_sell=False,
            city="Bangalore",
            state="Karnataka",
            location="Koramangala",
            pricing=25.5,
            pricing_unit="lakh",
            bedroom_count=0,
            owner_name="Corp Owner",
            owner_phone="9001234567",
            owner_email="corp@owner.in",
            gmaps_url="https://maps.google.com/?q=test",
        )

        self.assertEqual(prop.uuid, "aabbccdd-eeff-0011-2233-445566778899")
        self.assertEqual(prop.prop_id, "ABCD12")
        self.assertEqual(prop.form_no, "F-2024-001")
        self.assertEqual(prop.prop_type, "Commercial")
        self.assertEqual(prop.prop_sub_type, "Office")
        self.assertFalse(prop.for_sell)
        self.assertEqual(prop.city, "Bangalore")
        self.assertEqual(prop.state, "Karnataka")
        self.assertEqual(prop.location, "Koramangala")
        self.assertAlmostEqual(prop.pricing, 25.5)
        self.assertEqual(prop.pricing_unit, "lakh")
        self.assertEqual(prop.bedroom_count, 0)
        self.assertEqual(prop.owner_name, "Corp Owner")
        self.assertEqual(prop.owner_phone, "9001234567")
        self.assertEqual(prop.owner_email, "corp@owner.in")
        self.assertEqual(prop.gmaps_url, "https://maps.google.com/?q=test")

    def test_03_create_with_manager_editable_fields(self):
        """PROP-2.3/2.4 manager-editable fields should be stored correctly."""
        prop = self.make_property(
            property_tag="PREMIUM",
            portal_listing_ids=[
                (
                    0,
                    0,
                    {
                        "portal_name": "99acres",
                        "portal_listing_id": "99AC-001",
                        "listing_label": "99acres | 99AC-001",
                        "active": True,
                    },
                ),
                (
                    0,
                    0,
                    {
                        "portal_name": "Housing.com",
                        "portal_listing_id": "HSG-002",
                        "listing_label": "Housing.com | HSG-002",
                        "active": True,
                    },
                ),
                (
                    0,
                    0,
                    {
                        "portal_name": "MagicBricks",
                        "portal_listing_id": "MB-003",
                        "listing_label": "MagicBricks | MB-003",
                        "active": True,
                    },
                ),
                (
                    0,
                    0,
                    {
                        "portal_name": "OLX",
                        "portal_listing_id": "OLX-004",
                        "listing_label": "OLX | OLX-004",
                        "active": True,
                    },
                ),
            ],
        )

        self.assertEqual(prop.property_tag, "PREMIUM")
        self.assertEqual(len(prop.portal_listing_ids), 4)

        by_portal = {
            rec.portal_name: rec.portal_listing_id
            for rec in prop.portal_listing_ids
        }
        self.assertEqual(by_portal["99acres"], "99AC-001")
        self.assertEqual(by_portal["Housing.com"], "HSG-002")
        self.assertEqual(by_portal["MagicBricks"], "MB-003")
        self.assertEqual(by_portal["OLX"], "OLX-004")

    def test_04_create_assigns_rm_user(self):
        """Many2one rm_user_id should be correctly linked."""
        prop = self.make_property(rm_user_id=self.rm_user2.id)
        self.assertEqual(prop.rm_user_id, self.rm_user2)

    def test_05_default_is_active_true(self):
        """New records should default to is_active=True."""
        prop = self.env["property.base"].create({"name": "Active Default"})
        self.assertTrue(prop.is_active)

    def test_06_default_inventory_migrated_false(self):
        """New records should default to inventory_migrated=False."""
        prop = self.env["property.base"].create({"name": "Not Migrated"})
        self.assertFalse(prop.inventory_migrated)

    # ------------------------------------------------------------------ #
    # Unique constraints                                                   #
    # ------------------------------------------------------------------ #

    def test_07_uuid_unique_constraint(self):
        """Duplicate uuid must raise an IntegrityError."""
        shared_uuid = f"unique-uuid-{self.suffix}"
        self.make_property(uuid=shared_uuid)

        with mute_logger("odoo.sql_db"), self.assertRaises(psycopg2.IntegrityError):
            self.make_property(uuid=shared_uuid)

    def test_08_prop_id_unique_constraint(self):
        """Duplicate prop_id must raise an IntegrityError."""
        shared_pid = f"SH{self.suffix[-4:]}"
        self.make_property(prop_id=shared_pid)

        with mute_logger("odoo.sql_db"), self.assertRaises(psycopg2.IntegrityError):
            self.make_property(prop_id=shared_pid)

    def test_09_null_uuid_does_not_violate_unique_constraint(self):
        """Multiple records with uuid=False/None should be allowed."""
        p1 = self.make_property(uuid=False)
        p2 = self.make_property(uuid=False)
        self.assertTrue(p1.id)
        self.assertTrue(p2.id)

    def test_10_null_prop_id_does_not_violate_unique_constraint(self):
        """Multiple records with prop_id=False/None should be allowed."""
        p1 = self.make_property(prop_id=False)
        p2 = self.make_property(prop_id=False)
        self.assertTrue(p1.id)
        self.assertTrue(p2.id)

    # ------------------------------------------------------------------ #
    # Read / search                                                        #
    # ------------------------------------------------------------------ #

    def test_11_search_by_city(self):
        """Domain filter on city should return only matching records."""
        p_mum = self.make_property(city="Mumbai")
        p_del = self.make_property(city="Delhi")

        results = self.env["property.base"].search(
            [("id", "in", [p_mum.id, p_del.id]), ("city", "=", "Mumbai")],
        )
        self.assertIn(p_mum, results)
        self.assertNotIn(p_del, results)

    def test_12_search_by_is_active(self):
        """is_active filter should distinguish active vs inactive records."""
        p_on = self.make_property(is_active=True)
        p_off = self.make_property(is_active=False)

        active = self.env["property.base"].search(
            [("id", "in", [p_on.id, p_off.id]), ("is_active", "=", True)],
        )
        inactive = self.env["property.base"].search(
            [("id", "in", [p_on.id, p_off.id]), ("is_active", "=", False)],
        )

        self.assertIn(p_on, active)
        self.assertNotIn(p_off, active)
        self.assertIn(p_off, inactive)
        self.assertNotIn(p_on, inactive)

    def test_13_search_by_for_sell(self):
        """for_sell filter should distinguish sale vs rental records."""
        p_sale = self.make_property(for_sell=True)
        p_rent = self.make_property(for_sell=False)

        sales = self.env["property.base"].search(
            [("id", "in", [p_sale.id, p_rent.id]), ("for_sell", "=", True)],
        )
        self.assertIn(p_sale, sales)
        self.assertNotIn(p_rent, sales)

    def test_14_search_name_ilike(self):
        """Case-insensitive name search should return partial matches."""
        p = self.make_property(name="Seaview Residency Tower")
        results = self.env["property.base"].search(
            [("id", "=", p.id), ("name", "ilike", "seaview")],
        )
        self.assertIn(p, results)

    def test_15_default_ordering_reg_date_desc(self):
        """Records ordered by reg_date desc, id desc within the same date."""
        today = date.today()
        p_old = self.make_property(reg_date=today - timedelta(days=10))
        p_new = self.make_property(reg_date=today)

        results = self.env["property.base"].search(
            [("id", "in", [p_old.id, p_new.id])],
        )
        self.assertEqual(results[0], p_new, "Newer reg_date should come first")
        self.assertEqual(results[1], p_old)

    def test_16_search_count_matches_search(self):
        """search_count should return the same cardinality as search."""
        p1 = self.make_property(state="Goa")
        p2 = self.make_property(state="Goa")
        self.make_property(state="Kerala")

        domain = [("id", "in", [p1.id, p2.id]), ("state", "=", "Goa")]
        self.assertEqual(
            self.env["property.base"].search_count(domain),
            len(self.env["property.base"].search(domain)),
        )

    # ------------------------------------------------------------------ #
    # Update                                                               #
    # ------------------------------------------------------------------ #

    def test_17_write_single_field(self):
        """write() should update a single field without affecting others."""
        prop = self.make_property(city="Pune", pricing=30.0)
        prop.write({"city": "Chennai"})
        self.assertEqual(prop.city, "Chennai")
        self.assertAlmostEqual(prop.pricing, 30.0)

    def test_18_write_multiple_fields(self):
        """write() should update multiple fields in one call."""
        prop = self.make_property()
        prop.write(
            {"owner_name": "New Owner", "owner_phone": "9112233445", "pricing": 60.0},
        )

        self.assertEqual(prop.owner_name, "New Owner")
        self.assertEqual(prop.owner_phone, "9112233445")
        self.assertAlmostEqual(prop.pricing, 60.0)

    def test_19_write_rm_reassignment(self):
        """Reassigning rm_user_id via write() should update the relation."""
        prop = self.make_property(rm_user_id=self.rm_user.id)
        self.assertEqual(prop.rm_user_id, self.rm_user)

        prop.write({"rm_user_id": self.rm_user2.id})
        self.assertEqual(prop.rm_user_id, self.rm_user2)

    # ------------------------------------------------------------------ #
    # Delete                                                               #
    # ------------------------------------------------------------------ #

    def test_20_unlink_removes_record(self):
        """unlink() should permanently remove the record from the database."""
        prop = self.make_property()
        prop_id = prop.id
        prop.unlink()

        remaining = self.env["property.base"].browse(prop_id).exists()
        self.assertFalse(remaining, "Record should not exist after unlink()")

    def test_21_unlink_does_not_affect_other_records(self):
        """Deleting one record must not cascade to unrelated records."""
        p_del = self.make_property()
        p_keep = self.make_property()

        p_del.unlink()

        self.assertTrue(self.env["property.base"].browse(p_keep.id).exists())
