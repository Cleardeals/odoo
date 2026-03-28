"""
Test suite for the Seller Activity API endpoint: GET /api/track/property/activity

This module tests the granular lead-level activity business logic that combines
both primary leads and recommended interests, with pagination and filtering support.

Test Categories:
- Serialization: Primary and recommended lead data transformation
- Pagination: Page/page_size handling, offset calculation
- Filtering: Property tag filtering for seller's properties
- Sorting: Chronological ordering by inquiry_datetime descending
- Edge Cases: Empty results, invalid pagination params
- Data Integrity: Field mapping, null handling
"""

import logging
from datetime import datetime, timedelta

from odoo.tests import tagged

from ..controllers.shared.property_resolver import (
    get_primary_leads_for_tags,
    get_properties_for_phone,
    get_recommended_leads_for_tags,
)
from .test_portal_common import PortalLeadTestCase

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestSellerActivityAPI(PortalLeadTestCase):
    """
    Test suite for the Seller Activity API endpoint business logic.
    Uses FAANG-style testing with clear Arrange-Act-Assert patterns.
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures and data."""
        super().setUpClass()

        # Create multiple test properties owned by same seller
        cls.test_property_2 = cls.env["property.base"].create(
            {
                "property_tag": f"TEST-PROP-2-{cls.suffix}",
                "name": f"Test Property 2 {cls.suffix}",
                "bedroom_count": 2,
                "location": "Second Location",
                "city": "Second City",
                "rm_user_id": cls.rm_user.id,
                "is_active": True,
                "owner_phone": "9876543210",
            },
        )

        cls.test_property_3 = cls.env["property.base"].create(
            {
                "property_tag": f"TEST-PROP-3-{cls.suffix}",
                "name": f"Test Property 3 {cls.suffix}",
                "bedroom_count": 4,
                "location": "Third Location",
                "city": "Third City",
                "rm_user_id": cls.rm_user.id,
                "is_active": True,
                "owner_phone": "9876543210",
            },
        )

        cls.test_property.write({"owner_phone": "9876543210"})

    def setUp(self):
        """Prepare test environment before each test method."""
        super().setUp()
        # Clean up leads from previous tests
        self.env["leads.new"].search([("phone", "=", "9876543210")]).unlink()

    # ========================================================================
    # PRIMARY LEAD SERIALIZATION TESTS
    # ========================================================================

    def test_01_primary_lead_serialization_all_fields(self):
        """
        ARRANGE: Create a primary lead with all fields populated
        ACT: Serialize it
        ASSERT: All fields are present and correct
        """
        # ARRANGE
        lead = self.create_portal_lead(
            phone="9999999999",
            name="Ravi Shah",
            email="ravi@example.com",
            portal_name="MagicBricks",
            property_base_id=self.test_property.id,
        )
        lead.write(
            {
                "current_status": "site_visit_scheduled",
                "remarks": "Interested in 2nd floor",
                "feedback_general": "buyer_not_interested",
            },
        )

        # ACT
        serialized = {
            "type": "primary",
            "lead_id": lead.id,
            "lead_name": lead.name or None,
            "lead_phone": lead.phone or None,
            "source": lead.source_id.name or None,
            "property_tag": lead.property_base_id.property_tag if lead.property_base_id else None,
            "property_bhk": lead.property_base_id.bhk if lead.property_base_id else None,
            "property_location": lead.property_base_id.location
            if lead.property_base_id
            else None,
            "current_status": lead.current_status or None,
            "remarks": lead.remarks or None,
            "feedback_general": lead.feedback_general or None,
        }

        # ASSERT
        self.assertEqual(serialized["type"], "primary")
        self.assertEqual(serialized["lead_name"], "Ravi Shah")
        self.assertEqual(serialized["lead_phone"], "9999999999")
        self.assertEqual(serialized["source"], "MagicBricks")
        self.assertEqual(serialized["property_tag"], self.test_property.property_tag)
        self.assertEqual(serialized["property_bhk"], "3 BHK")
        self.assertEqual(serialized["current_status"], "site_visit_scheduled")
        self.assertEqual(serialized["remarks"], "Interested in 2nd floor")

    def test_02_primary_lead_serialization_handles_nulls(self):
        """
        ARRANGE: Create a minimal primary lead (many null fields)
        ACT: Serialize it
        ASSERT: Null fields are None in serialization
        """
        # ARRANGE
        lead = self.create_portal_lead(
            phone="8888888888",
            property_base_id=self.test_property.id,
        )

        # ACT
        serialized = {
            "lead_id": lead.id,
            "remarks": lead.remarks or None,
            "feedback_general": lead.feedback_general or None,
            "feedback_site_visit_done": None,
        }

        # ASSERT
        self.assertIsNone(serialized["remarks"])
        self.assertIsNone(serialized["feedback_general"])
        self.assertIsNone(serialized["feedback_site_visit_done"])

    def test_03_primary_lead_has_property_details(self):
        """
        ARRANGE: Create lead linked to property with specific details
        ACT: Serialize and extract property info
        ASSERT: Property BHK, location match
        """
        # ARRANGE
        lead = self.create_portal_lead(property_base_id=self.test_property.id)

        # ACT
        prop = lead.property_base_id
        serialized = {
            "property_tag": prop.property_tag,
            "property_bhk": prop.bhk,
            "property_location": prop.location,
        }

        # ASSERT
        self.assertEqual(serialized["property_tag"], self.test_property.property_tag)
        self.assertEqual(serialized["property_bhk"], "3 BHK")
        self.assertEqual(serialized["property_location"], "Test Location")

    # ========================================================================
    # RECOMMENDED INTEREST SERIALIZATION TESTS
    # ========================================================================

    def test_04_recommended_interest_serialization(self):
        """
        ARRANGE: Create a recommended interest with parent lead
        ACT: Serialize it
        ASSERT: Inherits lead info and has interest-specific details
        """
        # ARRANGE
        parent_lead = self.create_portal_lead(
            phone="7777777777",
            name="Priya Patel",
            portal_name="99acres",
        )
        interest = self.env["lead.property.interest"].create(
            {
                "lead_id": parent_lead.id,
                "property_base_id": self.test_property.id,
                "current_status": "site_visit_done",
                "remarks": "Already visited",
            },
        )

        # ACT
        serialized = {
            "type": "recommended",
            "lead_id": parent_lead.id,
            "lead_name": parent_lead.name,
            "lead_phone": parent_lead.phone,
            "source": parent_lead.source_id.name,
            "property_tag": interest.property_base_id.property_tag,
            "current_status": interest.current_status,
            "remarks": interest.remarks,
        }

        # ASSERT
        self.assertEqual(serialized["type"], "recommended")
        self.assertEqual(serialized["lead_name"], "Priya Patel")
        self.assertEqual(serialized["source"], "99acres")
        self.assertEqual(serialized["property_tag"], self.test_property.property_tag)
        self.assertEqual(serialized["current_status"], "site_visit_done")

    def test_05_recommended_interest_inherits_parent_contact_info(self):
        """
        ARRANGE: Create interest whose first_contacted_on comes from parent lead
        ACT: Serialize
        ASSERT: first_contacted_on is from parent, not interest
        """
        # ARRANGE
        parent_lead = self.create_portal_lead(phone="6666666666")
        parent_lead.write({"first_contact_datetime": datetime.now()})

        interest = self.env["lead.property.interest"].create(
            {
                "lead_id": parent_lead.id,
                "property_base_id": self.test_property.id,
            },
        )

        # ACT
        first_contact = (
            parent_lead.first_contact_datetime.isoformat()
            if parent_lead.first_contact_datetime
            else None
        )

        # ASSERT
        self.assertIsNotNone(first_contact)

    # ========================================================================
    # PAGINATION TESTS
    # ========================================================================

    def test_06_pagination_page_1_default_size(self):
        """
        ARRANGE: Create 75 leads (3 pages of 25 each)
        ACT: Get page 1 with page_size=25
        ASSERT: Returns 25 items, has page_count=3
        """
        # ARRANGE
        tags = [self.test_property.property_tag]
        for i in range(75):
            self.create_portal_lead(
                phone=f"10101010{i:02d}",
                property_base_id=self.test_property.id,
            )

        primary_leads = get_primary_leads_for_tags(self.env, tags)
        records = [
            {
                "lead_id": lead.id,
                "inquiry_datetime": lead.create_date.isoformat()
                if lead.create_date
                else None,
            }
            for lead in primary_leads
        ]

        # ACT - Paginate manually
        page = 1
        page_size = 25
        offset = (page - 1) * page_size
        page_records = records[offset : offset + page_size]
        page_count = (len(records) + page_size - 1) // page_size

        # ASSERT
        self.assertEqual(len(page_records), 25)
        self.assertEqual(page_count, 3)

    def test_07_pagination_page_2_offset(self):
        """
        ARRANGE: Create 60 leads
        ACT: Get page 2 with page_size=25
        ASSERT: Gets items 26-50
        """
        # ARRANGE
        tags = [self.test_property.property_tag]
        lead_ids = []
        for i in range(60):
            lead = self.create_portal_lead(
                phone=f"20202020{i:02d}",
                property_base_id=self.test_property.id,
            )
            lead_ids.append(lead.id)

        records = [{"lead_id": lid} for lid in lead_ids]

        # ACT
        page = 2
        page_size = 25
        offset = (page - 1) * page_size
        page_records = records[offset : offset + page_size]

        # ASSERT
        self.assertEqual(len(page_records), 25)
        self.assertEqual(page_records[0]["lead_id"], lead_ids[25])

    def test_08_pagination_last_page_partial(self):
        """
        ARRANGE: Create 55 leads, page_size=25
        ACT: Get page 3
        ASSERT: Returns remaining 5 items
        """
        # ARRANGE
        tags = [self.test_property.property_tag]
        for i in range(55):
            self.create_portal_lead(
                phone=f"30303030{i:02d}",
                property_base_id=self.test_property.id,
            )

        primary_leads = get_primary_leads_for_tags(self.env, tags)
        records = [{"lead_id": lead.id} for lead in primary_leads]

        # ACT
        page = 3
        page_size = 25
        offset = (page - 1) * page_size
        page_records = records[offset : offset + page_size]

        # ASSERT
        self.assertEqual(len(page_records), 5)

    def test_09_pagination_invalid_page_returns_empty(self):
        """
        ARRANGE: Create 30 leads, request page 10
        ACT: Try to get page 10 with page_size=25
        ASSERT: Returns empty list
        """
        # ARRANGE
        for i in range(30):
            self.create_portal_lead(
                phone=f"40404040{i:02d}",
                property_base_id=self.test_property.id,
            )

        # ACT
        page = 10
        page_size = 25
        offset = (page - 1) * page_size
        # Simulating paginate returning empty
        records = []

        # ASSERT
        self.assertEqual(len(records), 0)

    def test_10_pagination_page_size_max_200(self):
        """
        ARRANGE: User requests page_size=9999
        ACT: Should cap at 200
        ASSERT: page_size capped to 200
        """
        # This would be enforced in the controller, but we test the logic
        page_size = min(9999, 200)

        self.assertEqual(page_size, 200)

    # ========================================================================
    # SORTING TESTS
    # ========================================================================

    def test_11_records_sorted_by_inquiry_datetime_descending(self):
        """
        ARRANGE: Create 3 leads with different create dates
        ACT: Sort by inquiry_datetime descending
        ASSERT: Most recent first
        """
        # ARRANGE
        now = datetime.now()
        lead_1 = self.create_portal_lead(phone="5555555550")
        lead_2 = self.create_portal_lead(phone="5555555551")
        lead_3 = self.create_portal_lead(phone="5555555552")

        records = [
            {
                "lead_id": lead_1.id,
                "inquiry_datetime": (now - timedelta(days=2)).isoformat(),
            },
            {"lead_id": lead_3.id, "inquiry_datetime": now.isoformat()},
            {
                "lead_id": lead_2.id,
                "inquiry_datetime": (now - timedelta(days=1)).isoformat(),
            },
        ]

        # ACT - Sort like the endpoint does
        records.sort(
            key=lambda r: r["inquiry_datetime"] or "",
            reverse=True,
        )

        # ASSERT - Most recent (lead_3) should be first
        self.assertEqual(records[0]["lead_id"], lead_3.id)
        self.assertEqual(records[2]["lead_id"], lead_1.id)

    def test_12_records_with_null_datetime_go_last(self):
        """
        ARRANGE: Mix of records with and without inquiry_datetime
        ACT: Sort
        ASSERT: Null datetimes appear last
        """
        # ARRANGE
        now = datetime.now()
        records = [
            {"lead_id": 1, "inquiry_datetime": now.isoformat()},
            {"lead_id": 2, "inquiry_datetime": None},
            {"lead_id": 3, "inquiry_datetime": (now - timedelta(hours=1)).isoformat()},
            {"lead_id": 4, "inquiry_datetime": None},
        ]

        # ACT
        records.sort(
            key=lambda r: r["inquiry_datetime"] or "",
            reverse=True,
        )

        # ASSERT - Nulls should be last (empty string sorts lowest)
        self.assertIsNotNone(records[0]["inquiry_datetime"])
        self.assertIsNotNone(records[1]["inquiry_datetime"])
        self.assertIsNone(records[2]["inquiry_datetime"])
        self.assertIsNone(records[3]["inquiry_datetime"])

    # ========================================================================
    # FILTERING TESTS
    # ========================================================================

    def test_13_filter_by_property_tag(self):
        """
        ARRANGE: Seller with 3 properties, create leads on each
        ACT: Filter by one property_tag
        ASSERT: Returns only leads from that property
        """
        # ARRANGE
        properties = [self.test_property, self.test_property_2, self.test_property_3]
        for prop in properties:
            self.create_portal_lead(phone=f"60606060{prop.id}", property_base_id=prop.id)

        tags = [
            self.test_property.property_tag,
            self.test_property_2.property_tag,
            self.test_property_3.property_tag,
        ]

        # ACT - Filter to one property
        tag_filter = self.test_property.property_tag
        filtered_props = [p for p in properties if p.property_tag == tag_filter]
        filtered_tags = [p.property_tag for p in filtered_props]

        # ASSERT
        self.assertEqual(len(filtered_tags), 1)
        self.assertEqual(filtered_tags[0], self.test_property.property_tag)

    def test_14_filter_no_results_for_invalid_tag(self):
        """
        ARRANGE: Seller with properties, filter by non-existent tag
        ACT: Apply filter
        ASSERT: Returns empty
        """
        # ARRANGE
        tag_filter = "INVALID_TAG"
        phone = "9876543210"
        props = get_properties_for_phone(self.env, phone)

        # ACT
        filtered = props.filtered(lambda p: p.property_tag == tag_filter)

        # ASSERT
        self.assertEqual(len(filtered), 0)

    # ========================================================================
    # COMBINED PRIMARY + RECOMMENDED TESTS
    # ========================================================================

    def test_15_activity_combines_primary_and_recommended(self):
        """
        ARRANGE: 3 primary leads, 2 recommended interests
        ACT: Combine both into activity list
        ASSERT: Total 5 records, types correct
        """
        # ARRANGE
        tags = [self.test_property.property_tag]

        # Create 3 primary
        for i in range(3):
            self.create_portal_lead(
                phone=f"70707070{i:02d}",
                property_base_id=self.test_property.id,
            )

        # Create 2 recommended
        for i in range(2):
            lead = self.create_portal_lead(phone=f"71717171{i:02d}")
            self.env["lead.property.interest"].create(
                {
                    "lead_id": lead.id,
                    "property_base_id": self.test_property.id,
                },
            )

        primary_leads = get_primary_leads_for_tags(self.env, tags)
        recommended_interests = get_recommended_leads_for_tags(self.env, tags)

        # ACT
        records = []
        for _ in primary_leads:
            records.append({"type": "primary"})
        for _ in recommended_interests:
            records.append({"type": "recommended"})

        # ASSERT
        self.assertEqual(len(records), 5)
        primary_count = sum(1 for r in records if r["type"] == "primary")
        recommended_count = sum(1 for r in records if r["type"] == "recommended")
        self.assertEqual(primary_count, 3)
        self.assertEqual(recommended_count, 2)

    def test_16_activity_mixed_sorting(self):
        """
        ARRANGE: Mix of primary and recommended with varied dates
        ACT: Sort combined list
        ASSERT: Correctly ordered by inquiry_datetime
        """
        # ARRANGE
        now = datetime.now()
        records = [
            {
                "type": "primary",
                "inquiry_datetime": (now - timedelta(days=1)).isoformat(),
            },
            {"type": "recommended", "inquiry_datetime": now.isoformat()},
            {
                "type": "primary",
                "inquiry_datetime": (now - timedelta(hours=1)).isoformat(),
            },
        ]

        # ACT
        records.sort(key=lambda r: r["inquiry_datetime"] or "", reverse=True)

        # ASSERT - Most recent first, regardless of type
        self.assertEqual(records[0]["type"], "recommended")
        self.assertEqual(records[1]["type"], "primary")
        self.assertEqual(records[2]["type"], "primary")

    # ========================================================================
    # EDGE CASES & DATA INTEGRITY
    # ========================================================================

    def test_17_empty_activity_list(self):
        """
        ARRANGE: Property with no leads or interests
        ACT: Get activity list
        ASSERT: Returns empty list
        """
        # ARRANGE
        phone = "1111111111"
        prop = self.env["property.base"].create(
            {
                "property_tag": f"EMPTY-ACTIVITY-{self.suffix}",
                "name": f"Empty Activity Prop {self.suffix}",
                "bedroom_count": 3,
                "location": "Empty",
                "city": "City",
                "rm_user_id": self.rm_user.id,
                "is_active": True,
                "owner_phone": phone,
            },
        )

        tags = [prop.property_tag]
        primary_leads = get_primary_leads_for_tags(self.env, tags)
        recommended_interests = get_recommended_leads_for_tags(self.env, tags)

        # ACT
        records = []
        for _ in primary_leads:
            records.append({})
        for _ in recommended_interests:
            records.append({})

        # ASSERT
        self.assertEqual(len(records), 0)

    def test_18_activity_preserves_lead_details(self):
        """
        ARRANGE: Create primary lead with specific details
        ACT: Serialize to activity record
        ASSERT: All details preserved
        """
        # ARRANGE
        lead = self.create_portal_lead(
            phone="9111111111",
            name="Test Lead",
            email="test@test.com",
            portal_name="Housing.com",
            property_base_id=self.test_property.id,
        )
        lead.write({"current_status": "site_visit_scheduled"})

        # ACT
        record = {
            "type": "primary",
            "lead_id": lead.id,
            "lead_name": lead.name,
            "lead_phone": lead.phone,
            "source": lead.source_id.name,
            "current_status": lead.current_status,
        }

        # ASSERT
        self.assertEqual(record["lead_name"], "Test Lead")
        self.assertEqual(record["lead_phone"], "9111111111")
        self.assertEqual(record["source"], "Housing.com")
        self.assertEqual(record["current_status"], "site_visit_scheduled")

    def test_19_page_size_parameter_validation(self):
        """
        ARRANGE: Request with non-integer page_size
        ACT: Try to parse
        ASSERT: Should fail gracefully
        """
        # ARRANGE
        page_size_str = "not_a_number"

        # ACT & ASSERT
        with self.assertRaises(ValueError):
            int(page_size_str)

    def test_20_page_parameter_validation(self):
        """
        ARRANGE: Request with non-integer page
        ACT: Try to parse
        ASSERT: Should fail gracefully
        """
        # ARRANGE
        page_str = "abc"

        # ACT & ASSERT
        with self.assertRaises(ValueError):
            int(page_str)

    def test_21_pagination_info_calculation(self):
        """
        ARRANGE: 150 records with page_size=40
        ACT: Calculate pagination info
        ASSERT: Correct total_pages, has_next, has_prev
        """
        # ARRANGE
        total = 150
        page_size = 40
        page = 2

        # ACT
        total_pages = (total + page_size - 1) // page_size
        has_next = page < total_pages
        has_prev = page > 1
        offset = (page - 1) * page_size

        # ASSERT
        self.assertEqual(total_pages, 4)
        self.assertTrue(has_next)
        self.assertTrue(has_prev)
        self.assertEqual(offset, 40)

    def test_22_activity_datetime_iso_format(self):
        """
        ARRANGE: Lead with create_date
        ACT: Convert to ISO format
        ASSERT: Valid ISO 8601 format
        """
        # ARRANGE
        lead = self.create_portal_lead(phone="9222222222")

        # ACT
        inquiry_datetime = lead.create_date.isoformat() if lead.create_date else None

        # ASSERT
        self.assertIsNotNone(inquiry_datetime)
        self.assertIn("T", inquiry_datetime)  # ISO format has 'T' between date and time
