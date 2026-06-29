"""
Access-control tests for the Properties module.

These pin down the security model that the rest of the suite assumed but never
asserted at the ORM level:

  * RMs (group_property_rm) can READ only properties where they are the RM.
  * RMs cannot write / create / unlink (read-only ACL).
  * Managers (group_property_manager) see and edit ALL properties.
  * The portal-listing record rule scopes RMs to listings on their own
    properties.

Getting these wrong silently leaks other RMs' data or blocks managers, so they
deserve explicit coverage.
"""

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .test_property_common import PropertyBaseTestCase


@tagged("post_install", "-at_install")
class TestPropertySecurity(PropertyBaseTestCase):
    """Record-rule and ACL enforcement on property.base / portal.listing."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group_rm = cls.env.ref("properties.group_property_rm")
        group_mgr = cls.env.ref("properties.group_property_manager")

        cls.rm_only = cls.env["res.users"].create(
            {
                "name": f"RM Only {cls.suffix}",
                "login": f"rmonly_{cls.suffix}",
                "email": f"rmonly_{cls.suffix}@test.internal",
                "group_ids": [(6, 0, [group_rm.id])],
            }
        )
        cls.manager = cls.env["res.users"].create(
            {
                "name": f"Manager {cls.suffix}",
                "login": f"mgr_{cls.suffix}",
                "email": f"mgr_{cls.suffix}@test.internal",
                "group_ids": [(6, 0, [group_mgr.id])],
            }
        )

        # One property owned by the RM, one owned by someone else.
        cls.own_prop = cls.make_property(rm_user_id=cls.rm_only.id)
        cls.other_prop = cls.make_property(rm_user_id=cls.rm_user2.id)

    # ------------------------------------------------------------------ #
    # RM read scoping                                                      #
    # ------------------------------------------------------------------ #

    def test_01_rm_sees_only_own_properties(self):
        visible = (
            self.env["property.base"]
            .with_user(self.rm_only)
            .search([("id", "in", [self.own_prop.id, self.other_prop.id])])
        )
        self.assertEqual(visible, self.own_prop)

    def test_02_rm_cannot_read_other_property(self):
        with self.assertRaises(AccessError):
            self.other_prop.with_user(self.rm_only).read(["name"])

    # ------------------------------------------------------------------ #
    # RM is read-only (ACL)                                                #
    # ------------------------------------------------------------------ #

    def test_03_rm_cannot_write_even_own_property(self):
        with mute_logger("odoo.addons.base.models.ir_rule"), self.assertRaises(
            AccessError
        ):
            self.own_prop.with_user(self.rm_only).write({"city": "NewCity"})

    def test_04_rm_cannot_create_property(self):
        with self.assertRaises(AccessError):
            self.env["property.base"].with_user(self.rm_only).create(
                {"name": "RM should not create"}
            )

    def test_05_rm_cannot_unlink_property(self):
        with self.assertRaises(AccessError):
            self.own_prop.with_user(self.rm_only).unlink()

    # ------------------------------------------------------------------ #
    # Manager full access                                                  #
    # ------------------------------------------------------------------ #

    def test_06_manager_sees_all_properties(self):
        visible = (
            self.env["property.base"]
            .with_user(self.manager)
            .search([("id", "in", [self.own_prop.id, self.other_prop.id])])
        )
        self.assertEqual(visible, self.own_prop | self.other_prop)

    def test_07_manager_can_write_any_property(self):
        self.other_prop.with_user(self.manager).write({"city": "MgrCity"})
        self.other_prop.invalidate_recordset()
        self.assertEqual(self.other_prop.city, "MgrCity")

    # ------------------------------------------------------------------ #
    # Portal listing scoping                                               #
    # ------------------------------------------------------------------ #

    def test_08_rm_sees_only_own_property_listings(self):
        own_listing = self.env["property.portal.listing"].create(
            {
                "property_base_id": self.own_prop.id,
                "portal_name": "SquareYards",
                "portal_listing_id": f"OWN-{self.suffix}",
            }
        )
        other_listing = self.env["property.portal.listing"].create(
            {
                "property_base_id": self.other_prop.id,
                "portal_name": "SquareYards",
                "portal_listing_id": f"OTHER-{self.suffix}",
            }
        )

        visible = (
            self.env["property.portal.listing"]
            .with_user(self.rm_only)
            .search([("id", "in", [own_listing.id, other_listing.id])])
        )
        self.assertEqual(visible, own_listing)
