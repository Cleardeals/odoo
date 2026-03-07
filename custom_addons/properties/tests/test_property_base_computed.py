"""
Tests for all computed fields on ``property.base``.

Covers:
  - build_property_link() helper (slugification edge cases)
  - _compute_property_link  (stored, depends on name + prop_id)
  - _compute_bhk            (stored, depends on bedroom_count)
  - _compute_display_fields (non-stored: prop_type_display, listing_type,
                              pricing_display, is_new)
  - _compute_gmaps_embed_html (non-stored, depends on gmaps_url)

Each compute method has its own sub-class so failures are easy to localise.
"""

from datetime import date, timedelta

from odoo.tests import tagged

from ..models.property_base import build_property_link
from .test_property_common import PropertyBaseTestCase

# =========================================================================
# build_property_link() standalone helper
# =========================================================================


@tagged("post_install", "-at_install")
class TestBuildPropertyLink(PropertyBaseTestCase):
    """Unit tests for the build_property_link() module-level helper."""

    def test_01_normal_ascii_name(self):
        result = build_property_link("Aaryan City", "GBH75X0K")
        self.assertEqual(
            result, "https://www.cleardeals.in/property/aaryan-city-GBH75X0K"
        )

    def test_02_name_with_special_characters(self):
        """Special chars like parens and dots from the NAME must be stripped from the slug."""
        result = build_property_link("B.K. Residency (Phase-2)", "AB12CD")
        # parens stripped; hyphens kept; dots in name removed from slug
        self.assertIn("AB12CD", result)
        self.assertNotIn("(", result)
        self.assertNotIn(")", result)
        # The slug part (after /property/) must not contain dots
        slug_part = result.split("/property/")[-1]
        self.assertNotIn(".", slug_part)

    def test_03_name_with_multiple_spaces(self):
        """Multiple spaces should collapse to a single hyphen."""
        result = build_property_link("Green   Meadows", "XYZ001")
        self.assertIn("green-meadows-XYZ001", result)

    def test_04_name_with_mixed_case(self):
        """Name should be lowercased in the URL slug."""
        result = build_property_link("GRAND PALACE", "GP0001")
        self.assertIn("grand-palace", result)

    def test_05_empty_name_returns_empty(self):
        """Empty name should produce an empty string."""
        self.assertEqual(build_property_link("", "ABC123"), "")

    def test_06_empty_prop_id_returns_empty(self):
        """Empty prop_id should produce an empty string."""
        self.assertEqual(build_property_link("Some Property", ""), "")

    def test_07_both_empty_returns_empty(self):
        self.assertEqual(build_property_link("", ""), "")

    def test_08_name_with_leading_trailing_spaces(self):
        """Leading/trailing whitespace should be stripped before slugification."""
        result = build_property_link("  Sky Tower  ", "ST9999")
        self.assertIn("sky-tower-ST9999", result)

    def test_09_slug_no_leading_trailing_hyphens(self):
        """Slug must not start or end with a hyphen."""
        result = build_property_link("-Test-", "T1")
        slug_part = result.split("/")[-1].replace("-T1", "")
        self.assertFalse(slug_part.startswith("-"))
        self.assertFalse(slug_part.endswith("-"))

    def test_10_returns_cleardeals_base_url(self):
        """Result must begin with the configured base URL."""
        result = build_property_link("Park Villa", "PV0001")
        self.assertTrue(result.startswith("https://www.cleardeals.in/property/"))


# =========================================================================
# _compute_property_link
# =========================================================================


@tagged("post_install", "-at_install")
class TestComputePropertyLink(PropertyBaseTestCase):
    """Tests for the stored _compute_property_link field."""

    def test_01_link_computed_on_create(self):
        """property_link should be populated immediately after create()."""
        prop = self.make_property(name="Sunrise Towers", prop_id="SR0001")
        self.assertIn("sunrise-towers-SR0001", prop.property_link)

    def test_02_link_updates_when_name_changes(self):
        """property_link should recompute when name is updated."""
        prop = self.make_property(name="Old Name", prop_id="ON0001")
        prop.write({"name": "New Name"})
        self.assertIn("new-name-ON0001", prop.property_link)

    def test_03_link_updates_when_prop_id_changes(self):
        """property_link should recompute when prop_id is updated."""
        prop = self.make_property(name="Static Name", prop_id="OLD001")
        prop.write({"prop_id": "NEW001"})
        self.assertIn("NEW001", prop.property_link)

    def test_04_link_empty_when_name_missing(self):
        """property_link should be empty string when name is falsy."""
        prop = self.make_property(name=False, prop_id="NNAME1")
        self.assertEqual(prop.property_link, "")

    def test_05_link_empty_when_prop_id_missing(self):
        """property_link should be empty string when prop_id is falsy."""
        prop = self.make_property(name="Valid Name", prop_id=False)
        self.assertEqual(prop.property_link, "")


# =========================================================================
# _compute_bhk
# =========================================================================


@tagged("post_install", "-at_install")
class TestComputeBhk(PropertyBaseTestCase):
    """Tests for the stored _compute_bhk field."""

    def test_01_one_bedroom(self):
        prop = self.make_property(bedroom_count=1)
        self.assertEqual(prop.bhk, "1 BHK")

    def test_02_two_bedrooms(self):
        prop = self.make_property(bedroom_count=2)
        self.assertEqual(prop.bhk, "2 BHK")

    def test_03_three_bedrooms(self):
        prop = self.make_property(bedroom_count=3)
        self.assertEqual(prop.bhk, "3 BHK")

    def test_04_zero_bedrooms(self):
        """0 bedrooms (commercial) should yield empty string."""
        prop = self.make_property(bedroom_count=0)
        self.assertEqual(prop.bhk, "")

    def test_05_negative_bedroom_count(self):
        """Negative count is nonsensical — should yield empty string."""
        prop = self.make_property(bedroom_count=-1)
        self.assertEqual(prop.bhk, "")

    def test_06_bhk_recomputes_on_write(self):
        """bhk should update immediately when bedroom_count changes."""
        prop = self.make_property(bedroom_count=2)
        self.assertEqual(prop.bhk, "2 BHK")
        prop.write({"bedroom_count": 4})
        self.assertEqual(prop.bhk, "4 BHK")

    def test_07_large_bedroom_count(self):
        prop = self.make_property(bedroom_count=10)
        self.assertEqual(prop.bhk, "10 BHK")


# =========================================================================
# _compute_display_fields  (prop_type_display, listing_type, pricing_display, is_new)
# =========================================================================


@tagged("post_install", "-at_install")
class TestComputeDisplayFields(PropertyBaseTestCase):
    """Tests for the non-stored _compute_display_fields compute batch."""

    # --- prop_type_display -----------------------------------------------

    def test_01_prop_type_display_capitalised(self):
        prop = self.make_property(prop_type="residential")
        self.assertEqual(prop.prop_type_display, "Residential")

    def test_02_prop_type_display_already_capitalised(self):
        prop = self.make_property(prop_type="Commercial")
        self.assertEqual(prop.prop_type_display, "Commercial")

    def test_03_prop_type_display_empty_when_type_falsy(self):
        prop = self.make_property(prop_type=False)
        self.assertEqual(prop.prop_type_display, "")

    # --- listing_type -----------------------------------------------------

    def test_04_listing_type_sell_when_for_sell_true(self):
        prop = self.make_property(for_sell=True)
        self.assertEqual(prop.listing_type, "Sell")

    def test_05_listing_type_rent_when_for_sell_false(self):
        prop = self.make_property(for_sell=False)
        self.assertEqual(prop.listing_type, "Rent")

    # --- pricing_display --------------------------------------------------

    def test_06_pricing_display_with_unit_sell(self):
        prop = self.make_property(pricing=48.0, pricing_unit="lakh", for_sell=True)
        self.assertEqual(prop.pricing_display, "48 Lakh")

    def test_07_pricing_display_with_unit_rent(self):
        """Rental pricing should include '/month' suffix."""
        prop = self.make_property(pricing=15.0, pricing_unit="thousand", for_sell=False)
        self.assertEqual(prop.pricing_display, "15 Thousand/month")

    def test_08_pricing_display_without_unit(self):
        """When pricing_unit is empty, display just the number."""
        prop = self.make_property(pricing=2.5, pricing_unit=False, for_sell=True)
        self.assertEqual(prop.pricing_display, "2.5")

    def test_09_pricing_display_empty_when_no_pricing(self):
        prop = self.make_property(pricing=0.0)
        self.assertEqual(prop.pricing_display, "")

    def test_10_pricing_display_strips_trailing_decimals(self):
        """Use :g format — 48.0 should display as '48', not '48.0'."""
        prop = self.make_property(pricing=48.0, pricing_unit="lakh", for_sell=True)
        self.assertFalse(prop.pricing_display.startswith("48.0"))
        self.assertIn("48 ", prop.pricing_display)

    # --- is_new -----------------------------------------------------------

    def test_11_is_new_true_when_reg_date_today(self):
        prop = self.make_property(reg_date=date.today())
        self.assertTrue(prop.is_new)

    def test_12_is_new_true_when_reg_date_2_days_ago(self):
        prop = self.make_property(reg_date=date.today() - timedelta(days=2))
        self.assertTrue(prop.is_new)

    def test_13_is_new_false_when_reg_date_4_days_ago(self):
        prop = self.make_property(reg_date=date.today() - timedelta(days=4))
        self.assertFalse(prop.is_new)

    def test_14_is_new_false_when_reg_date_missing(self):
        prop = self.make_property(reg_date=False)
        self.assertFalse(prop.is_new)

    def test_15_is_new_boundary_exactly_3_days_ago(self):
        """Exactly 3 days ago is still 'new' (>= three_days_ago)."""
        prop = self.make_property(reg_date=date.today() - timedelta(days=3))
        self.assertTrue(prop.is_new)


# =========================================================================
# _compute_gmaps_embed_html
# =========================================================================


@tagged("post_install", "-at_install")
class TestComputeGmapsEmbedHtml(PropertyBaseTestCase):
    """Tests for the non-stored gmaps_embed_html computed field."""

    def test_01_iframe_generated_when_url_present(self):
        prop = self.make_property(gmaps_url="https://maps.google.com/embed?test=1")
        self.assertIn("<iframe", prop.gmaps_embed_html)
        self.assertIn("https://maps.google.com/embed?test=1", prop.gmaps_embed_html)

    def test_02_fallback_paragraph_when_url_missing(self):
        prop = self.make_property(gmaps_url=False)
        self.assertNotIn("<iframe", prop.gmaps_embed_html)
        self.assertIn("No Google Maps URL", prop.gmaps_embed_html)

    def test_03_iframe_sets_full_width(self):
        prop = self.make_property(gmaps_url="https://maps.google.com/embed?x=1")
        self.assertIn('width="100%"', prop.gmaps_embed_html)

    def test_04_iframe_has_allowfullscreen(self):
        prop = self.make_property(gmaps_url="https://maps.google.com/embed?x=1")
        self.assertIn("allowfullscreen", prop.gmaps_embed_html)

    def test_05_html_recomputes_when_url_changes(self):
        prop = self.make_property(gmaps_url=False)
        self.assertNotIn("<iframe", prop.gmaps_embed_html)

        prop.write({"gmaps_url": "https://maps.google.com/embed?new=1"})
        self.assertIn("<iframe", prop.gmaps_embed_html)
