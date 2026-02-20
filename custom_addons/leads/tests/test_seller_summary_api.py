"""
Test suite for the Seller Summary API endpoint: GET /api/track/property/summary

This module tests the core business logic that powers the API controller,
which provides a high-level summary of inquiry activity for all properties
belonging to a seller (owner).

Test Categories:
- Happy Path: Valid requests with complete data
- Error Handling: Missing/invalid parameters, no properties found
- Edge Cases: Phone format variations, empty inquiries
- Data Integrity: Correct counting and categorization of leads
"""

import logging

from odoo.tests import tagged

from ..controllers.shared.phone_utils import normalize_phone_to_10_digit
from ..controllers.shared.property_resolver import (
    get_primary_leads_for_tags,
    get_properties_for_phone,
    get_recommended_leads_for_tags,
)
from .test_portal_common import PortalLeadTestCase

_logger = logging.getLogger(__name__)

KNOWN_PORTALS = ["MagicBricks", "99acres", "Housing.com", "OLX"]


@tagged("post_install", "-at_install")
class TestSellerSummaryAPI(PortalLeadTestCase):
    """
    Test suite for the Seller Summary API endpoint business logic.
    Uses FAANG-style testing with clear Arrange-Act-Assert patterns.
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures and data."""
        super().setUpClass()

        # Create multiple test properties owned by the same seller
        cls.test_property_2 = cls.env["property.inventory"].create(
            {
                "property_tag": f"TEST-PROP-2-{cls.suffix}",
                "bhk": "2 BHK",
                "location": "Second Location",
                "city": "Second City",
                "rm_user_id": cls.rm_user.id,
                "is_active": True,
                "property_link": f"https://test.com/property/TEST-PROP-2-{cls.suffix}",
                "owner_phone": "9876543210",
                "magicbricks_id": f"MB2_{cls.suffix}",
                "housing_id": f"HSG2_{cls.suffix}",
                "ninety_nine_acres_id": f"99A2_{cls.suffix}",
                "olx_id": f"OLX2_{cls.suffix}",
            },
        )

        cls.test_property_3 = cls.env["property.inventory"].create(
            {
                "property_tag": f"TEST-PROP-3-{cls.suffix}",
                "bhk": "4 BHK",
                "location": "Third Location",
                "city": "Third City",
                "rm_user_id": cls.rm_user.id,
                "is_active": True,
                "property_link": f"https://test.com/property/TEST-PROP-3-{cls.suffix}",
                "owner_phone": "9876543210",
                "magicbricks_id": f"MB3_{cls.suffix}",
                "housing_id": f"HSG3_{cls.suffix}",
                "ninety_nine_acres_id": f"99A3_{cls.suffix}",
                "olx_id": f"OLX3_{cls.suffix}",
            },
        )

        # Ensure first test property has owner phone set
        cls.test_property.write({"owner_phone": "9876543210"})

    def setUp(self):
        """Prepare test environment before each test method."""
        super().setUp()
        # Clean up any leads from previous tests
        self.env["leads.new"].search([("phone", "=", "9876543210")]).unlink()

    # ========================================================================
    # PHONE NORMALIZATION TESTS
    # ========================================================================

    def test_01_normalize_phone_10_digit_exact(self):
        """
        ARRANGE: 10-digit phone number
        ACT: Normalize it
        ASSERT: Returns the same number
        """
        # ARRANGE
        phone = "9876543210"

        # ACT
        result = normalize_phone_to_10_digit(phone)

        # ASSERT
        self.assertEqual(result, "9876543210")

    def test_02_normalize_phone_with_91_prefix(self):
        """
        ARRANGE: Phone with 91 country code
        ACT: Normalize it
        ASSERT: Returns 10-digit without prefix
        """
        # ARRANGE
        phone = "919876543210"

        # ACT
        result = normalize_phone_to_10_digit(phone)

        # ASSERT
        self.assertEqual(result, "9876543210")

    def test_03_normalize_phone_with_plus_91(self):
        """
        ARRANGE: Phone with +91 format
        ACT: Normalize it
        ASSERT: Returns 10-digit string
        """
        # ARRANGE
        phone = "+919876543210"

        # ACT
        result = normalize_phone_to_10_digit(phone)

        # ASSERT
        self.assertEqual(result, "9876543210")

    def test_04_normalize_phone_with_spaces(self):
        """
        ARRANGE: Phone with spaces and formatting
        ACT: Normalize it
        ASSERT: Returns clean 10-digit string
        """
        # ARRANGE
        phone = "  98765 43210 "

        # ACT
        result = normalize_phone_to_10_digit(phone)

        # ASSERT
        self.assertEqual(result, "9876543210")

    def test_05_normalize_invalid_phone_too_short(self):
        """
        ARRANGE: Phone number too short
        ACT: Try to normalize
        ASSERT: Returns None
        """
        # ARRANGE
        phone = "123"

        # ACT
        result = normalize_phone_to_10_digit(phone)

        # ASSERT
        self.assertIsNone(result)

    def test_06_normalize_invalid_phone_empty(self):
        """
        ARRANGE: Empty phone string
        ACT: Try to normalize
        ASSERT: Returns None
        """
        # ARRANGE
        phone = ""

        # ACT
        result = normalize_phone_to_10_digit(phone)

        # ASSERT
        self.assertIsNone(result)

    # ========================================================================
    # PROPERTY RESOLUTION TESTS
    # ========================================================================

    def test_07_get_properties_for_phone_exact_match(self):
        """
        ARRANGE: Seller with 3 properties stored with 10-digit phone
        ACT: Query properties with exact 10-digit phone
        ASSERT: Returns all 3 properties
        """
        # ARRANGE
        phone = "9876543210"

        # ACT
        properties = get_properties_for_phone(self.env, phone)

        # ASSERT
        self.assertEqual(len(properties), 3)
        tags = set(properties.mapped("property_tag"))
        expected_tags = {
            self.test_property.property_tag,
            self.test_property_2.property_tag,
            self.test_property_3.property_tag,
        }
        self.assertEqual(tags, expected_tags)

    def test_08_get_properties_for_phone_with_91_fallback(self):
        """
        ARRANGE: Properties stored with 91 prefix, query with 10-digit
        ACT: Query properties
        ASSERT: Falls back to 91-prefixed search and returns properties
        """
        # ARRANGE
        phone_10 = "9876543210"
        # Update properties to use 91 prefix
        (self.test_property | self.test_property_2 | self.test_property_3).write(
            {"owner_phone": f"91{phone_10}"},
        )

        # ACT
        properties = get_properties_for_phone(self.env, phone_10)

        # ASSERT
        self.assertEqual(len(properties), 3, "Should find properties with 91 prefix")

    def test_09_get_properties_nonexistent_phone(self):
        """
        ARRANGE: Phone with no associated properties
        ACT: Query properties
        ASSERT: Returns empty recordset
        """
        # ARRANGE
        phone = "1111111111"

        # ACT
        properties = get_properties_for_phone(self.env, phone)

        # ASSERT
        self.assertEqual(len(properties), 0)

    def test_10_get_properties_returns_all_including_inactive(self):
        """
        ARRANGE: Create one inactive property
        ACT: Query properties by phone
        ASSERT: Returns ALL properties for that phone, including inactive ones,
                because the business requirement is to show full history to the owner
        """
        # ARRANGE
        phone = "9876543210"
        self.test_property_3.write({"is_active": False})

        # ACT
        properties = get_properties_for_phone(self.env, phone)

        # ASSERT
        self.assertEqual(
            len(properties),
            3,
            "Should return all properties including inactive",
        )
        self.assertIn(self.test_property_3, properties)

    # ========================================================================
    # PRIMARY LEADS TESTS
    # ========================================================================

    def test_11_get_primary_leads_for_tags(self):
        """
        ARRANGE: Create 3 primary leads for property tags
        ACT: Query primary leads for those tags
        ASSERT: Returns all 3 leads
        """
        # ARRANGE
        phone = "9876543210"
        tags = [
            self.test_property.property_tag,
            self.test_property_2.property_tag,
            self.test_property_3.property_tag,
        ]

        # Create 3 primary leads
        lead_1 = self.create_portal_lead(
            phone="9999999999",
            property_id=self.test_property.id,
        )
        lead_2 = self.create_portal_lead(
            phone="8888888888",
            property_id=self.test_property_2.id,
        )
        lead_3 = self.create_portal_lead(
            phone="7777777777",
            property_id=self.test_property_3.id,
        )

        # ACT
        primary_leads = get_primary_leads_for_tags(self.env, tags)

        # ASSERT
        self.assertEqual(len(primary_leads), 3, "Should return all 3 primary leads")
        lead_ids = set(primary_leads.ids)
        self.assertTrue(lead_1.id in lead_ids)
        self.assertTrue(lead_2.id in lead_ids)
        self.assertTrue(lead_3.id in lead_ids)

    def test_12_get_primary_leads_empty_tags(self):
        """
        ARRANGE: Empty tags list
        ACT: Query primary leads
        ASSERT: Returns empty recordset
        """
        # ARRANGE
        tags = []

        # ACT
        primary_leads = get_primary_leads_for_tags(self.env, tags)

        # ASSERT
        self.assertEqual(len(primary_leads), 0)

    def test_13_get_primary_leads_no_matches(self):
        """
        ARRANGE: Non-existent property tags
        ACT: Query primary leads
        ASSERT: Returns empty recordset
        """
        # ARRANGE
        tags = ["NON_EXISTENT_TAG"]

        # ACT
        primary_leads = get_primary_leads_for_tags(self.env, tags)

        # ASSERT
        self.assertEqual(len(primary_leads), 0)

    # ========================================================================
    # RECOMMENDED INTERESTS TESTS
    # ========================================================================

    def test_14_get_recommended_leads_for_tags(self):
        """
        ARRANGE: Create recommended interests for property tags
        ACT: Query recommended interests
        ASSERT: Returns all interests
        """
        # ARRANGE
        tags = [
            self.test_property.property_tag,
            self.test_property_2.property_tag,
        ]

        # Create base leads
        lead_1 = self.create_portal_lead(phone="6666666666")
        lead_2 = self.create_portal_lead(phone="5555555555")

        # Create interests
        interest_1 = self.env["lead.property.interest"].create(
            {
                "lead_id": lead_1.id,
                "property_id": self.test_property.id,
            },
        )
        interest_2 = self.env["lead.property.interest"].create(
            {
                "lead_id": lead_2.id,
                "property_id": self.test_property_2.id,
            },
        )

        # ACT
        recommended = get_recommended_leads_for_tags(self.env, tags)

        # ASSERT
        self.assertEqual(len(recommended), 2, "Should return 2 recommended interests")
        interest_ids = set(recommended.ids)
        self.assertTrue(interest_1.id in interest_ids)
        self.assertTrue(interest_2.id in interest_ids)

    def test_15_get_recommended_leads_empty_tags(self):
        """
        ARRANGE: Empty tags list
        ACT: Query recommended interests
        ASSERT: Returns empty recordset
        """
        # ARRANGE
        tags = []

        # ACT
        recommended = get_recommended_leads_for_tags(self.env, tags)

        # ASSERT
        self.assertEqual(len(recommended), 0)

    # ========================================================================
    # PORTAL BREAKDOWN LOGIC TESTS
    # ========================================================================

    def test_16_portal_breakdown_known_portals(self):
        """
        ARRANGE: Create leads from known portals
        ACT: Build portal breakdown
        ASSERT: Correct counts for each portal
        """
        # ARRANGE
        tags = [self.test_property.property_tag]

        # Create leads from each portal
        self.create_portal_lead(
            phone="9999999999",
            portal_name="MagicBricks",
            property_id=self.test_property.id,
        )
        self.create_portal_lead(
            phone="8888888888",
            portal_name="99acres",
            property_id=self.test_property.id,
        )
        self.create_portal_lead(
            phone="7777777777",
            portal_name="Housing.com",
            property_id=self.test_property.id,
        )

        # Get primary leads
        primary_leads = get_primary_leads_for_tags(self.env, tags)

        # ACT - Build portal breakdown
        portal_breakdown = {p: {"primary": 0, "recommended": 0} for p in KNOWN_PORTALS}
        portal_breakdown["Unknown"] = {"primary": 0, "recommended": 0}

        for lead in primary_leads:
            portal = (
                lead.portal_name if lead.portal_name in KNOWN_PORTALS else "Unknown"
            )
            portal_breakdown[portal]["primary"] += 1

        # ASSERT
        self.assertEqual(portal_breakdown["MagicBricks"]["primary"], 1)
        self.assertEqual(portal_breakdown["99acres"]["primary"], 1)
        self.assertEqual(portal_breakdown["Housing.com"]["primary"], 1)
        self.assertEqual(portal_breakdown["OLX"]["primary"], 0)
        self.assertEqual(portal_breakdown["Unknown"]["primary"], 0)

    def test_17_portal_breakdown_unknown_portal(self):
        """
        ARRANGE: Create lead from unknown portal
        ACT: Build portal breakdown
        ASSERT: Lead counted under "Unknown"
        """
        # ARRANGE
        tags = [self.test_property.property_tag]
        unknown_portal = "CustomPortal123"

        self.create_portal_lead(
            phone="5555555555",
            portal_name=unknown_portal,
            property_id=self.test_property.id,
        )

        # Get primary leads
        primary_leads = get_primary_leads_for_tags(self.env, tags)

        # ACT - Build portal breakdown
        portal_breakdown = {p: {"primary": 0, "recommended": 0} for p in KNOWN_PORTALS}
        portal_breakdown["Unknown"] = {"primary": 0, "recommended": 0}

        for lead in primary_leads:
            portal = (
                lead.portal_name if lead.portal_name in KNOWN_PORTALS else "Unknown"
            )
            portal_breakdown[portal]["primary"] += 1

        # ASSERT
        self.assertGreater(
            portal_breakdown["Unknown"]["primary"],
            0,
            "Unknown portal should be counted",
        )

    # ========================================================================
    # INQUIRY COUNT LOGIC TESTS
    # ========================================================================

    def test_18_inquiry_count_primary_plus_recommended(self):
        """
        ARRANGE: Mix of 3 primary leads and 2 recommended interests
        ACT: Calculate totals
        ASSERT: total = 5, primary = 3, recommended = 2
        """
        # ARRANGE
        tags = [
            self.test_property.property_tag,
            self.test_property_2.property_tag,
        ]

        # Create 3 primary leads
        for i in range(3):
            self.create_portal_lead(
                phone=f"999999999{i}",
                property_id=self.test_property.id,
            )

        # Create 2 recommended interests
        lead = self.create_portal_lead(phone="4444444444")
        self.env["lead.property.interest"].create(
            {
                "lead_id": lead.id,
                "property_id": self.test_property_2.id,
            },
        )
        lead_2 = self.create_portal_lead(phone="3333333333")
        self.env["lead.property.interest"].create(
            {
                "lead_id": lead_2.id,
                "property_id": self.test_property.id,
            },
        )

        # ACT
        primary_leads = get_primary_leads_for_tags(self.env, tags)
        recommended_interests = get_recommended_leads_for_tags(self.env, tags)

        primary_count = len(primary_leads)
        recommended_count = len(recommended_interests)
        total_count = primary_count + recommended_count

        # ASSERT
        self.assertEqual(primary_count, 3)
        self.assertEqual(recommended_count, 2)
        self.assertEqual(total_count, 5)

    def test_19_inquiry_count_empty_results(self):
        """
        ARRANGE: Properties with no leads or interests
        ACT: Calculate totals
        ASSERT: All counts are 0
        """
        # ARRANGE
        phone = "2222222222"
        prop = self.env["property.inventory"].create(
            {
                "property_tag": f"EMPTY-{self.suffix}",
                "bhk": "3 BHK",
                "location": "Empty",
                "city": "City",
                "rm_user_id": self.rm_user.id,
                "is_active": True,
                "owner_phone": phone,
            },
        )

        tags = [prop.property_tag]

        # ACT
        primary_leads = get_primary_leads_for_tags(self.env, tags)
        recommended_interests = get_recommended_leads_for_tags(self.env, tags)

        # ASSERT
        self.assertEqual(len(primary_leads), 0)
        self.assertEqual(len(recommended_interests), 0)

    # ========================================================================
    # DATA INTEGRITY TESTS
    # ========================================================================

    def test_20_properties_list_all_seller_tags(self):
        """
        ARRANGE: Seller with 3 properties
        ACT: Collect property tags
        ASSERT: All tags present
        """
        # ARRANGE
        phone = "9876543210"

        # ACT
        properties = get_properties_for_phone(self.env, phone)
        tags = properties.mapped("property_tag")

        # ASSERT
        self.assertEqual(len(tags), 3)
        self.assertIn(self.test_property.property_tag, tags)
        self.assertIn(self.test_property_2.property_tag, tags)
        self.assertIn(self.test_property_3.property_tag, tags)

    def test_21_primary_lead_has_correct_properties(self):
        """
        ARRANGE: Create a lead with specific details
        ACT: Query it back
        ASSERT: All fields match
        """
        # ARRANGE
        lead_phone = "1234567890"
        lead_name = "Test Lead Name"
        lead_email = "test@example.com"

        lead = self.create_portal_lead(
            phone=lead_phone,
            name=lead_name,
            email=lead_email,
            portal_name="MagicBricks",
            property_id=self.test_property.id,
        )

        # ACT
        fetched_lead = self.env["leads.new"].browse(lead.id)

        # ASSERT
        self.assertEqual(fetched_lead.phone, lead_phone)
        self.assertEqual(fetched_lead.name, lead_name)
        self.assertEqual(fetched_lead.email, lead_email)
        self.assertEqual(fetched_lead.portal_name, "MagicBricks")

    def test_22_recommended_interest_links_correctly(self):
        """
        ARRANGE: Create lead and recommended interest
        ACT: Verify relationships
        ASSERT: All links are correct
        """
        # ARRANGE
        lead = self.create_portal_lead(phone="0987654321")
        interest = self.env["lead.property.interest"].create(
            {
                "lead_id": lead.id,
                "property_id": self.test_property.id,
            },
        )

        # ACT & ASSERT
        self.assertEqual(interest.lead_id, lead)
        self.assertEqual(interest.property_id, self.test_property)
        self.assertEqual(interest.current_status, "lead")

    def test_23_portal_breakdown_totals_consistency(self):
        """
        ARRANGE: Create mixed leads from different portals
        ACT: Build portal breakdown and sum counts
        ASSERT: Sum equals total inquiry count
        """
        # ARRANGE
        tags = [self.test_property.property_tag]

        # Create 7 leads distributed across portals
        for i in range(2):
            self.create_portal_lead(
                phone=f"999999999{i}",
                portal_name="MagicBricks",
                property_id=self.test_property.id,
            )
        for i in range(3):
            self.create_portal_lead(
                phone=f"888888888{i}",
                portal_name="99acres",
                property_id=self.test_property.id,
            )
        for i in range(2):
            self.create_portal_lead(
                phone=f"777777777{i}",
                portal_name="Housing.com",
                property_id=self.test_property.id,
            )

        # Get leads and build breakdown
        primary_leads = get_primary_leads_for_tags(self.env, tags)

        portal_breakdown = {p: {"primary": 0, "recommended": 0} for p in KNOWN_PORTALS}
        portal_breakdown["Unknown"] = {"primary": 0, "recommended": 0}

        for lead in primary_leads:
            portal = (
                lead.portal_name if lead.portal_name in KNOWN_PORTALS else "Unknown"
            )
            portal_breakdown[portal]["primary"] += 1

        # ACT - Sum portal breakdown
        total_from_breakdown = sum(
            counts["primary"] + counts["recommended"]
            for counts in portal_breakdown.values()
        )

        # ASSERT
        self.assertEqual(total_from_breakdown, 7)
        self.assertEqual(total_from_breakdown, len(primary_leads))

    # ========================================================================
    # EDGE CASES
    # ========================================================================

    def test_24_multiple_properties_same_seller_isolated(self):
        """
        ARRANGE: Another seller with same portal names
        ACT: Query properties for first seller
        ASSERT: Returns only first seller's properties
        """
        # ARRANGE
        seller_1_phone = "9876543210"
        seller_2_phone = "1234567890"

        # Create seller 2 property
        other_prop = self.env["property.inventory"].create(
            {
                "property_tag": f"OTHER-PROP-{self.suffix}",
                "bhk": "3 BHK",
                "location": "Other Location",
                "city": "Other City",
                "rm_user_id": self.rm_user.id,
                "is_active": True,
                "owner_phone": seller_2_phone,
            },
        )

        # ACT
        seller_1_props = get_properties_for_phone(self.env, seller_1_phone)
        seller_2_props = get_properties_for_phone(self.env, seller_2_phone)

        # ASSERT
        self.assertEqual(len(seller_1_props), 3)
        self.assertEqual(len(seller_2_props), 1)
        self.assertIn(other_prop, seller_2_props)
        self.assertNotIn(other_prop, seller_1_props)

    def test_25_leads_from_different_portals_counted_separately(self):
        """
        ARRANGE: Multiple leads from same property, different portals
        ACT: Build breakdown
        ASSERT: Each portal has correct count
        """
        # ARRANGE
        tags = [self.test_property.property_tag]

        # Create 2 leads each from 4 different portals = 8 total
        for portal in ["MagicBricks", "99acres", "Housing.com", "OLX"]:
            for i in range(2):
                phone = f"{''.join([str(ord(p) % 10) for p in portal])}{i:04d}"
                self.create_portal_lead(
                    phone=phone,
                    portal_name=portal,
                    property_id=self.test_property.id,
                )

        # Get leads
        primary_leads = get_primary_leads_for_tags(self.env, tags)

        # ACT - Build breakdown
        portal_breakdown = {p: {"primary": 0, "recommended": 0} for p in KNOWN_PORTALS}
        portal_breakdown["Unknown"] = {"primary": 0, "recommended": 0}

        for lead in primary_leads:
            portal = (
                lead.portal_name if lead.portal_name in KNOWN_PORTALS else "Unknown"
            )
            portal_breakdown[portal]["primary"] += 1

        # ASSERT
        for portal in KNOWN_PORTALS:
            self.assertEqual(
                portal_breakdown[portal]["primary"],
                2,
                f"Portal {portal} should have 2 leads",
            )
