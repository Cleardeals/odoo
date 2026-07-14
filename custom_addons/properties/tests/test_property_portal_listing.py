"""
Behavioural tests for the ``property.portal.listing`` model.

The portal listing model carries real side-effects that the rest of the suite
did not exercise:

  * create()  — auto-builds ``listing_label`` and posts a chatter note.
  * write()   — tracks field changes and posts chatter; a property reassignment
                posts TWO notes (moved out of old, moved in to new).
  * unlink()  — posts a "removed" chatter note before deletion.
  * default ``portal_name`` resolved from the ``default_portal_name`` context.
  * ``_build_default_listing_label`` formatting with missing parts.
  * ondelete="cascade": deleting a property removes its portal listings.

These guard manager-visible audit history and data integrity, so they are
worth pinning down explicitly.
"""

from odoo.tests import tagged

from .test_property_common import PropertyBaseTestCase


@tagged("post_install", "-at_install")
class TestPropertyPortalListing(PropertyBaseTestCase):
    """Side-effects and helpers on property.portal.listing."""

    def _make_listing(self, prop=None, **vals):
        prop = prop or self.make_property()
        base = {
            "property_base_id": prop.id,
            "portal_name": "99acres",
            "portal_listing_id": f"ID-{self.suffix}",
        }
        base.update(vals)
        return self.env["property.portal.listing"].create(base), prop

    # ------------------------------------------------------------------ #
    # listing_label auto-build                                            #
    # ------------------------------------------------------------------ #

    def test_01_create_autobuilds_label_from_prop_portal_listing(self):
        """When listing_label is omitted, it is built as
        '<prop_id> | <portal> | <listing_id>'."""
        prop = self.make_property(prop_id="ABC123")
        listing, _ = self._make_listing(
            prop=prop, portal_name="SquareYards", portal_listing_id="SY-9"
        )
        self.assertEqual(listing.listing_label, "ABC123 | SquareYards | SY-9")

    def test_02_create_keeps_supplied_label(self):
        """An explicitly supplied label is not overwritten."""
        listing, _ = self._make_listing(listing_label="Custom Label")
        self.assertEqual(listing.listing_label, "Custom Label")

    def test_03_build_default_label_skips_missing_parts(self):
        """The label helper joins only the non-empty components."""
        prop = self.make_property(prop_id=False)
        label = self.env["property.portal.listing"]._build_default_listing_label(
            prop, "OLX", "OLX-1"
        )
        self.assertEqual(label, "OLX | OLX-1")

    # ------------------------------------------------------------------ #
    # default portal_name from context                                    #
    # ------------------------------------------------------------------ #

    def test_04_default_portal_name_from_context(self):
        """portal_name falls back to the default_portal_name context key."""
        prop = self.make_property()
        listing = (
            self.env["property.portal.listing"]
            .with_context(default_portal_name="SquareYards")
            .create(
                {
                    "property_base_id": prop.id,
                    "portal_listing_id": "CTX-1",
                }
            )
        )
        self.assertEqual(listing.portal_name, "SquareYards")

    # ------------------------------------------------------------------ #
    # chatter side-effects                                                 #
    # ------------------------------------------------------------------ #

    def test_05_create_posts_added_chatter(self):
        """Creating a listing posts an 'added' note on the property."""
        listing, prop = self._make_listing(
            portal_name="MagicBricks", portal_listing_id="MB-1"
        )
        bodies = prop.message_ids.mapped("body")
        self.assertTrue(any("Portal listing added" in b for b in bodies))
        self.assertTrue(any("MB-1" in b for b in bodies))

    def test_06_write_field_change_posts_updated_chatter(self):
        """Editing the listing ID posts an 'updated' note with old → new."""
        listing, prop = self._make_listing(portal_listing_id="OLD-1")
        listing.write({"portal_listing_id": "NEW-1"})
        bodies = prop.message_ids.mapped("body")
        self.assertTrue(any("Portal listing updated" in b for b in bodies))
        self.assertTrue(any("OLD-1" in b and "NEW-1" in b for b in bodies))

    def test_07_reassignment_posts_moved_out_and_in(self):
        """Moving a listing to another property posts on BOTH properties."""
        listing, old_prop = self._make_listing(portal_listing_id="MOVE-1")
        new_prop = self.make_property()

        listing.write({"property_base_id": new_prop.id})

        self.assertTrue(
            any("moved out" in b.lower() for b in old_prop.message_ids.mapped("body"))
        )
        self.assertTrue(
            any("moved in" in b.lower() for b in new_prop.message_ids.mapped("body"))
        )

    def test_08_unlink_posts_removed_chatter(self):
        """Deleting a listing posts a 'removed' note on the property."""
        listing, prop = self._make_listing(portal_listing_id="DEL-1")
        listing.unlink()
        self.assertTrue(
            any(
                "Portal listing removed" in b
                for b in prop.message_ids.mapped("body")
            )
        )

    # ------------------------------------------------------------------ #
    # cascade delete                                                       #
    # ------------------------------------------------------------------ #

    def test_09_deleting_property_cascades_listings(self):
        """ondelete='cascade' removes a property's portal listings with it."""
        listing, prop = self._make_listing(portal_listing_id="CASCADE-1")
        listing_id = listing.id
        prop.unlink()
        self.assertFalse(
            self.env["property.portal.listing"].browse(listing_id).exists()
        )
