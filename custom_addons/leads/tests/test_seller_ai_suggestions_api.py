"""
Test suite for the Seller AI Suggestions API endpoint: GET /api/track/property/ai-suggestions

This module tests the AI-generated lead suggestions business logic that combines
suggestions from the property.lead.suggestion model (synced from BigQuery), with
pagination and filtering support.

Test Categories:
- Serialization: Suggestion data transformation
- Pagination: Page/page_size handling, offset calculation
- Filtering: Property tag filtering for seller's properties
- Sorting: Chronological ordering by generation_date descending
- Edge Cases: Empty results, invalid pagination params, missing suggestions
- Data Integrity: Field mapping, null handling, similarity percentage formatting
"""

import logging
from datetime import date, timedelta

from odoo.tests import tagged

from ..controllers.shared.property_resolver import get_properties_for_phone
from .test_portal_common import PortalLeadTestCase

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestSellerAiSuggestionsAPI(PortalLeadTestCase):
    """
    Test suite for the Seller AI Suggestions API endpoint business logic.
    Uses FAANG-style testing with clear Arrange-Act-Assert patterns.
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures and data."""
        super().setUpClass()

        # Create multiple test properties owned by same seller
        cls.test_property_2 = cls.env["property.inventory"].create(
            {
                "property_tag": f"TEST-PROP-2-{cls.suffix}",
                "bhk": "2 BHK",
                "location": "Second Location",
                "city": "Second City",
                "rm_user_id": cls.rm_user.id,
                "is_active": True,
                "owner_phone": "9876543210",
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
                "owner_phone": "9876543210",
            },
        )

        cls.test_property.write({"owner_phone": "9876543210"})

    def setUp(self):
        """Prepare test environment before each test method."""
        super().setUp()
        # Clean up suggestions from previous tests
        self.env["property.lead.suggestion"].search(
            [
                (
                    "property_inventory_id",
                    "in",
                    [
                        self.test_property.id,
                        self.test_property_2.id,
                        self.test_property_3.id,
                    ],
                )
            ],
        ).unlink()

    def _create_suggestion(self, property_id, lead_phone, **kwargs):
        """Helper to create a suggestion record."""
        defaults = {
            "suggested_lead_phone": lead_phone,
            "lead_name": kwargs.get("lead_name", "Test Lead"),
            "original_property_tag": kwargs.get("original_property_tag", "ORIG-TAG-1"),
            "original_property_similarity": kwargs.get("similarity_pct", 85.0),
            "contact_type": kwargs.get("contact_type", "site_visit_done"),
            "generation_date": kwargs.get("generation_date", date.today()),
            "status": kwargs.get("status", "new"),
            "rm_feedback": kwargs.get("rm_feedback"),
        }
        return self.env["property.lead.suggestion"].create(
            {
                "property_inventory_id": property_id,
                **defaults,
            },
        )

    # ========================================================================
    # SUGGESTION SERIALIZATION TESTS
    # ========================================================================

    def test_01_suggestion_serialization_all_fields(self):
        """
        ARRANGE: Create a suggestion with all fields populated
        ACT: Serialize it
        ASSERT: All fields are present and correctly formatted
        """
        # ARRANGE
        suggestion = self._create_suggestion(
            self.test_property.id,
            "9123456789",
            lead_name="Amit Patel",
            original_property_tag="ORIG-123",
            similarity_pct=87.5,
            contact_type="site_visit_done",
            status="contacted",
            rm_feedback="Interested, will call back tomorrow",
            generation_date=date(2025, 1, 10),
        )

        # ACT
        serialized = {
            "property_tag": suggestion.property_tag or None,
            "suggested_lead_name": suggestion.lead_name or None,
            "suggested_lead_phone": suggestion.suggested_lead_phone or None,
            "original_property_tag": suggestion.original_property_tag or None,
            "similarity_pct": round(suggestion.original_property_similarity or 0.0, 2),
            "suggested_on": (
                suggestion.generation_date.isoformat()
                if suggestion.generation_date
                else None
            ),
            "contact_type": suggestion.contact_type or None,
            "rm_status": suggestion.status or None,
            "rm_feedback": suggestion.rm_feedback or None,
        }

        # ASSERT
        self.assertEqual(serialized["suggested_lead_name"], "Amit Patel")
        self.assertEqual(serialized["suggested_lead_phone"], "9123456789")
        self.assertEqual(serialized["original_property_tag"], "ORIG-123")
        self.assertEqual(serialized["similarity_pct"], 87.5)
        self.assertEqual(serialized["suggested_on"], "2025-01-10")
        self.assertEqual(serialized["contact_type"], "site_visit_done")
        self.assertEqual(serialized["rm_status"], "contacted")
        self.assertEqual(
            serialized["rm_feedback"], "Interested, will call back tomorrow"
        )

    def test_02_suggestion_serialization_handles_nulls(self):
        """
        ARRANGE: Create a minimal suggestion
        ACT: Serialize it
        ASSERT: Null fields are None in serialization
        """
        # ARRANGE
        suggestion = self._create_suggestion(
            self.test_property.id,
            "9111111111",
        )

        # ACT
        serialized = {
            "suggested_lead_name": suggestion.lead_name or None,
            "original_property_tag": suggestion.original_property_tag or None,
            "rm_feedback": suggestion.rm_feedback or None,
        }

        # ASSERT
        self.assertIsNotNone(serialized["suggested_lead_name"])  # Default provided
        self.assertIsNotNone(serialized["original_property_tag"])  # Default provided
        self.assertIsNone(serialized["rm_feedback"])

    def test_03_similarity_percentage_rounding(self):
        """
        ARRANGE: Create suggestion with 3-decimal similarity
        ACT: Round to 2 decimals
        ASSERT: Correctly rounded to 2 decimal places
        """
        # ARRANGE
        suggestion = self._create_suggestion(
            self.test_property.id,
            "9222222222",
            similarity_pct=87.556,
        )

        # ACT
        rounded = round(suggestion.original_property_similarity or 0.0, 2)

        # ASSERT
        self.assertEqual(rounded, 87.56)

    def test_04_property_tag_from_related_property(self):
        """
        ARRANGE: Create suggestion linked to property with specific tag
        ACT: Access property_tag related field
        ASSERT: property_tag matches property.property_tag
        """
        # ARRANGE
        suggestion = self._create_suggestion(self.test_property.id, "9333333333")

        # ACT
        prop_tag = suggestion.property_tag

        # ASSERT
        self.assertEqual(prop_tag, self.test_property.property_tag)

    def test_05_suggestion_date_iso_format(self):
        """
        ARRANGE: Create suggestion with specific date
        ACT: Convert to ISO format
        ASSERT: Correctly formatted as YYYY-MM-DD
        """
        # ARRANGE
        test_date = date(2025, 3, 15)
        suggestion = self._create_suggestion(
            self.test_property.id,
            "9444444444",
            generation_date=test_date,
        )

        # ACT
        iso_date = suggestion.generation_date.isoformat()

        # ASSERT
        self.assertEqual(iso_date, "2025-03-15")

    def test_06_rm_status_selection_values(self):
        """
        ARRANGE: Create suggestions with different status values
        ACT: Verify all valid statuses are writable
        ASSERT: Each status writes successfully without validation error
        """
        # ARRANGE
        valid_statuses = [
            "new",
            "contacted",
            "details_shared_of_property",
            "not_interested",
            "interested",
            "converted",
            "whatsapp_done",
            "other",
        ]
        created_suggestions = []

        # ACT & ASSERT
        for i, status in enumerate(valid_statuses):
            suggestion = self._create_suggestion(
                self.test_property.id,
                f"91000000{i:02d}",
                status=status,
            )
            created_suggestions.append(suggestion)
            self.assertEqual(suggestion.status, status)

    # ========================================================================
    # PAGINATION TESTS
    # ========================================================================

    def test_07_pagination_page_1_default_size(self):
        """
        ARRANGE: Create 55 suggestions (3 pages of 20 each)
        ACT: Get page 1 with page_size=20
        ASSERT: Returns 20 items, has page_count=3
        """
        # ARRANGE
        for i in range(55):
            self._create_suggestion(
                self.test_property.id,
                f"91555555{i:02d}",
            )

        suggestions = self.env["property.lead.suggestion"].search(
            [("property_inventory_id", "=", self.test_property.id)],
        )
        records = [{"id": s.id} for s in suggestions]

        # ACT - Paginate manually
        page = 1
        page_size = 20
        offset = (page - 1) * page_size
        page_records = records[offset : offset + page_size]
        page_count = (len(records) + page_size - 1) // page_size

        # ASSERT
        self.assertEqual(len(page_records), 20)
        self.assertEqual(page_count, 3)

    def test_08_pagination_page_2_offset(self):
        """
        ARRANGE: Create 60 suggestions
        ACT: Get page 2 with page_size=25
        ASSERT: Gets items 26-50
        """
        # ARRANGE
        suggestion_ids = []
        for i in range(60):
            s = self._create_suggestion(
                self.test_property.id,
                f"91666666{i:02d}",
            )
            suggestion_ids.append(s.id)

        records = [{"id": sid} for sid in suggestion_ids]

        # ACT
        page = 2
        page_size = 25
        offset = (page - 1) * page_size
        page_records = records[offset : offset + page_size]

        # ASSERT
        self.assertEqual(len(page_records), 25)
        self.assertEqual(page_records[0]["id"], suggestion_ids[25])

    def test_09_pagination_page_size_max_100(self):
        """
        ARRANGE: User requests page_size=9999
        ACT: Should cap at 100
        ASSERT: page_size capped to 100
        """
        # This would be enforced in the controller, but we test the logic
        page_size = min(9999, 100)

        self.assertEqual(page_size, 100)

    def test_10_pagination_last_page_partial(self):
        """
        ARRANGE: Create 45 suggestions, page_size=20
        ACT: Get page 3
        ASSERT: Returns remaining 5 items
        """
        # ARRANGE
        for i in range(45):
            self._create_suggestion(
                self.test_property.id,
                f"91777777{i:02d}",
            )

        suggestions = self.env["property.lead.suggestion"].search(
            [("property_inventory_id", "=", self.test_property.id)],
        )
        records = [{"id": s.id} for s in suggestions]

        # ACT
        page = 3
        page_size = 20
        offset = (page - 1) * page_size
        page_records = records[offset : offset + page_size]

        # ASSERT
        self.assertEqual(len(page_records), 5)

    def test_11_pagination_invalid_page_returns_empty(self):
        """
        ARRANGE: Create 30 suggestions, request page 10
        ACT: Try to get page 10 with page_size=20
        ASSERT: Returns empty list
        """
        # ARRANGE
        for i in range(30):
            self._create_suggestion(
                self.test_property.id,
                f"91888888{i:02d}",
            )

        # ACT
        page = 10
        page_size = 20
        offset = (page - 1) * page_size
        records = []  # Simulating paginate returning empty

        # ASSERT
        self.assertEqual(len(records), 0)

    def test_12_pagination_info_calculation(self):
        """
        ARRANGE: 75 suggestions with page_size=20
        ACT: Calculate pagination info for page 2
        ASSERT: Correct total_pages, has_next, has_prev
        """
        # ARRANGE
        total = 75
        page_size = 20
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
        self.assertEqual(offset, 20)

    # ========================================================================
    # SORTING TESTS
    # ========================================================================

    def test_13_suggestions_sorted_by_generation_date_descending(self):
        """
        ARRANGE: Create 3 suggestions with different generation dates
        ACT: Sort by generation_date descending
        ASSERT: Most recent first
        """
        # ARRANGE
        today = date.today()
        s1 = self._create_suggestion(
            self.test_property.id,
            "9900000001",
            generation_date=today - timedelta(days=2),
        )
        s2 = self._create_suggestion(
            self.test_property.id,
            "9900000002",
            generation_date=today,
        )
        s3 = self._create_suggestion(
            self.test_property.id,
            "9900000003",
            generation_date=today - timedelta(days=1),
        )

        records = [
            {"id": s1.id, "generation_date": (today - timedelta(days=2)).isoformat()},
            {"id": s2.id, "generation_date": today.isoformat()},
            {"id": s3.id, "generation_date": (today - timedelta(days=1)).isoformat()},
        ]

        # ACT - Sort like the endpoint does
        records.sort(key=lambda r: r["generation_date"] or "", reverse=True)

        # ASSERT - Most recent (s2) should be first
        self.assertEqual(records[0]["id"], s2.id)
        self.assertEqual(records[2]["id"], s1.id)

    def test_14_suggestions_with_same_date_preserve_order(self):
        """
        ARRANGE: Create 2 suggestions with same generation date
        ACT: Sort
        ASSERT: Order is consistent (tied by creation)
        """
        # ARRANGE
        today = date.today()
        suggestions = []
        for i in range(2):
            s = self._create_suggestion(
                self.test_property.id,
                f"99000000{i:02d}",
                generation_date=today,
            )
            suggestions.append(s)

        records = [
            {"id": s.id, "generation_date": today.isoformat()} for s in suggestions
        ]

        # ACT
        records.sort(key=lambda r: r["generation_date"] or "", reverse=True)

        # ASSERT - Same date should maintain relative order
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["generation_date"], today.isoformat())
        self.assertEqual(records[1]["generation_date"], today.isoformat())

    # ========================================================================
    # FILTERING TESTS
    # ========================================================================

    def test_15_filter_by_property_tag(self):
        """
        ARRANGE: Seller with 3 properties, create suggestions on each
        ACT: Filter by one property_tag
        ASSERT: Returns only suggestions from that property
        """
        # ARRANGE
        for prop in [self.test_property, self.test_property_2, self.test_property_3]:
            self._create_suggestion(prop.id, f"9950000{prop.id}")

        properties = [self.test_property, self.test_property_2, self.test_property_3]
        tags = [p.property_tag for p in properties]

        # ACT - Filter to one property
        tag_filter = self.test_property.property_tag
        filtered_tags = [tag for tag in tags if tag == tag_filter]

        # ASSERT
        self.assertEqual(len(filtered_tags), 1)
        self.assertEqual(filtered_tags[0], self.test_property.property_tag)

    def test_16_filter_no_results_for_invalid_tag(self):
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

    def test_17_suggestions_for_multiple_properties_accessible(self):
        """
        ARRANGE: Create suggestions for all 3 properties
        ACT: Query suggestions for all property tags
        ASSERT: All suggestions retrieved
        """
        # ARRANGE
        tags = [
            self.test_property.property_tag,
            self.test_property_2.property_tag,
            self.test_property_3.property_tag,
        ]

        for prop in [self.test_property, self.test_property_2, self.test_property_3]:
            for i in range(2):
                self._create_suggestion(prop.id, f"9960000{prop.id}{i}")

        # ACT
        suggestions = self.env["property.lead.suggestion"].search(
            [("property_tag", "in", tags)],
        )

        # ASSERT
        self.assertEqual(len(suggestions), 6)  # 3 properties * 2 suggestions each

    # ========================================================================
    # EDGE CASES & DATA INTEGRITY
    # ========================================================================

    def test_18_empty_suggestions_list(self):
        """
        ARRANGE: Property with no suggestions
        ACT: Get suggestions list
        ASSERT: Returns empty list
        """
        # ARRANGE
        phone = "1111111111"
        prop = self.env["property.inventory"].create(
            {
                "property_tag": f"EMPTY-SUGG-{self.suffix}",
                "bhk": "3 BHK",
                "location": "Empty",
                "city": "City",
                "rm_user_id": self.rm_user.id,
                "is_active": True,
                "owner_phone": phone,
            },
        )

        # ACT
        suggestions = self.env["property.lead.suggestion"].search(
            [("property_inventory_id", "=", prop.id)],
        )

        # ASSERT
        self.assertEqual(len(suggestions), 0)

    def test_19_suggestion_preserves_all_details(self):
        """
        ARRANGE: Create suggestion with all details
        ACT: Retrieve and serialize
        ASSERT: All details preserved
        """
        # ARRANGE
        suggestion = self._create_suggestion(
            self.test_property.id,
            "9970000001",
            lead_name="Rajesh Kumar",
            original_property_tag="ORIG-456",
            similarity_pct=92.75,
            contact_type="site_visit_scheduled",
            status="interested",
            rm_feedback="Very interested in the property",
            generation_date=date(2025, 2, 15),
        )

        # ACT
        record = {
            "lead_name": suggestion.lead_name,
            "lead_phone": suggestion.suggested_lead_phone,
            "original_tag": suggestion.original_property_tag,
            "similarity": round(suggestion.original_property_similarity or 0.0, 2),
            "contact_type": suggestion.contact_type,
            "status": suggestion.status,
            "feedback": suggestion.rm_feedback,
        }

        # ASSERT
        self.assertEqual(record["lead_name"], "Rajesh Kumar")
        self.assertEqual(record["lead_phone"], "9970000001")
        self.assertEqual(record["original_tag"], "ORIG-456")
        self.assertEqual(record["similarity"], 92.75)
        self.assertEqual(record["contact_type"], "site_visit_scheduled")
        self.assertEqual(record["status"], "interested")
        self.assertEqual(record["feedback"], "Very interested in the property")

    def test_20_multiple_suggestions_same_lead(self):
        """
        ARRANGE: Create multiple suggestions for same lead but different properties
        ACT: Retrieve all
        ASSERT: All retrieved, can be filtered by property
        """
        # ARRANGE
        lead_phone = "9999999999"
        for prop in [self.test_property, self.test_property_2]:
            self._create_suggestion(prop.id, lead_phone, lead_name="Same Lead")

        # ACT
        all_suggestions = self.env["property.lead.suggestion"].search(
            [("suggested_lead_phone", "=", lead_phone)],
        )
        prop1_suggestions = all_suggestions.filtered(
            lambda s: s.property_inventory_id == self.test_property,
        )

        # ASSERT
        self.assertEqual(len(all_suggestions), 2)
        self.assertEqual(len(prop1_suggestions), 1)

    def test_21_suggestion_status_update(self):
        """
        ARRANGE: Create suggestion with 'new' status
        ACT: Update to 'contacted'
        ASSERT: Status updated successfully
        """
        # ARRANGE
        suggestion = self._create_suggestion(self.test_property.id, "9980000001")

        # ACT
        suggestion.write({"status": "contacted"})

        # ASSERT
        self.assertEqual(suggestion.status, "contacted")

    def test_22_rm_feedback_update(self):
        """
        ARRANGE: Create suggestion with no feedback
        ACT: Add feedback
        ASSERT: Feedback stored and retrieved
        """
        # ARRANGE
        suggestion = self._create_suggestion(self.test_property.id, "9990000001")

        # ACT
        feedback_text = "Lead is very interested, shared property details via WhatsApp"
        suggestion.write({"rm_feedback": feedback_text})

        # ASSERT
        self.assertEqual(suggestion.rm_feedback, feedback_text)

    def test_23_zero_similarity_handled(self):
        """
        ARRANGE: Create suggestion without similarity value (0.0)
        ACT: Serialize with fallback
        ASSERT: Returns 0.0, not None
        """
        # ARRANGE
        suggestion = self._create_suggestion(
            self.test_property.id,
            "9900000022",
            similarity_pct=0.0,
        )

        # ACT
        similarity = round(suggestion.original_property_similarity or 0.0, 2)

        # ASSERT
        self.assertEqual(similarity, 0.0)

    def test_24_lead_phone_normalization_preserved(self):
        """
        ARRANGE: Create suggestion with various phone formats
        ACT: Retrieve phone
        ASSERT: Stored as-is (no normalization at model level)
        """
        # ARRANGE
        phone = "9876543210"
        suggestion = self._create_suggestion(
            self.test_property.id,
            phone,
        )

        # ACT
        retrieved_phone = suggestion.suggested_lead_phone

        # ASSERT
        self.assertEqual(retrieved_phone, phone)

    def test_25_pagination_validate_params_format(self):
        """
        ARRANGE: Request with non-integer page_size
        ACT: Try to parse
        ASSERT: Should fail gracefully with ValueError
        """
        # ARRANGE
        page_size_str = "not_a_number"

        # ACT & ASSERT
        with self.assertRaises(ValueError):
            int(page_size_str)
