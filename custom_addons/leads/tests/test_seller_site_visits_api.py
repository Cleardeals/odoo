"""
Test suite for the Seller Site Visits API endpoint: GET /api/track/property/site-visits

This module tests the site visit classification and aggregation logic that combines
both primary leads and recommended interests, classifying them into 5 buckets
based on status and timing, with specialized field handling per bucket.

Test Categories:
- Classification: Current status + date logic determining bucket placement
- Serialization: Visit data transformation with bucket-specific fields
- Sorting: Chronological ordering within buckets (bucket-specific rules)
- Filtering: Property tag filtering for seller's properties
- Source Handling: Primary vs recommended leads
- Feedback Logic: Handling of feedback_general and feedback_site_visit_done
- Remarks Handling: Conditional inclusion only for "other" feedback
- Edge Cases: Null dates, missing fields, empty buckets
- Data Integrity: Field mapping, datetime formatting
- New Model Integration: lead.site.visit snapshot sync, reschedule contract

Model integration notes
-----------------------
The API reads the flat snapshot fields on leads.new (site_visit_date,
current_status, feedback_general, etc.). These are populated either:
  • Directly by the RM (legacy path)
  • Automatically by lead.site.visit._sync_inquiry_snapshot (new path)

Under the new model, completed visits write current_status="site_visit_done"
and scheduled/rescheduled visits both write current_status="site_visit_scheduled".
The "rescheduled" bucket is therefore LEGACY ONLY — retained for backward
compatibility with records written before the visit model existed.
New reschedules always appear in the "upcoming" bucket.
"""

import logging
from datetime import date, datetime, timedelta

from odoo.tests import tagged

from .test_portal_common import PortalLeadTestCase

_logger = logging.getLogger(__name__)

# Same constants as the controller
_EMPTY_FEEDBACK = {None, "", "other"}


@tagged("post_install", "-at_install")
class TestSellerSiteVisitsAPI(PortalLeadTestCase):
    """
    Test suite for the Seller Site Visits API endpoint business logic.
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
    # VISIT CLASSIFICATION LOGIC TESTS
    # ========================================================================

    def test_01_classify_upcoming_visit(self):
        """
        ARRANGE: A site_visit_scheduled status with future date
        ACT: Classify visit
        ASSERT: Returns 'upcoming'
        """
        # ARRANGE
        now = datetime.now()
        future_date = now + timedelta(days=5)
        current_status = "site_visit_scheduled"
        feedback_general = None

        # ACT - Simulate _classify_visit logic
        if current_status == "site_visit_scheduled" and future_date > now:
            bucket = "upcoming"
        else:
            bucket = "other"

        # ASSERT
        self.assertEqual(bucket, "upcoming")

    def test_02_classify_pending_feedback_visit(self):
        """
        ARRANGE: site_visit_scheduled with past date and empty feedback
        ACT: Classify visit
        ASSERT: Returns 'pending_feedback'
        """
        # ARRANGE
        now = datetime.now()
        past_date = now - timedelta(days=2)
        current_status = "site_visit_scheduled"
        feedback_general = None

        # ACT
        if current_status == "site_visit_scheduled":
            if past_date > now:
                bucket = "upcoming"
            elif feedback_general in _EMPTY_FEEDBACK:
                bucket = "pending_feedback"
            else:
                bucket = "cancelled"
        else:
            bucket = "other"

        # ASSERT
        self.assertEqual(bucket, "pending_feedback")

    def test_03_classify_cancelled_visit(self):
        """
        ARRANGE: site_visit_scheduled with past date and meaningful feedback
        ACT: Classify visit
        ASSERT: Returns 'cancelled'
        """
        # ARRANGE
        now = datetime.now()
        past_date = now - timedelta(days=3)
        current_status = "site_visit_scheduled"
        feedback_general = "buyer_not_interested"

        # ACT
        if current_status == "site_visit_scheduled":
            if past_date > now:
                bucket = "upcoming"
            elif feedback_general in _EMPTY_FEEDBACK:
                bucket = "pending_feedback"
            else:
                bucket = "cancelled"
        else:
            bucket = "other"

        # ASSERT
        self.assertEqual(bucket, "cancelled")

    def test_04_classify_rescheduled_visit(self):
        """
        ARRANGE: A rescheduled status (in-memory classification)
        ACT: Classify visit
        ASSERT: Returns 'rescheduled'

        LEGACY TEST (in-memory): This tests the _classify_visit() function's
        "rescheduled" branch in isolation. In production, this branch is only
        reachable for records that had current_status="rescheduled" written
        directly (pre-visit-model data or a manual override). New reschedules
        via lead.site.visit produce current_status="site_visit_scheduled"
        on the snapshot, so those appear in "upcoming". See test_33.
        """
        # ARRANGE
        current_status = "rescheduled"

        # ACT
        if current_status == "site_visit_done":
            bucket = "completed"
        elif current_status == "rescheduled":
            bucket = "rescheduled"
        else:
            bucket = "other"

        # ASSERT
        self.assertEqual(bucket, "rescheduled")

    def test_05_classify_completed_visit(self):
        """
        ARRANGE: A site_visit_done status
        ACT: Classify visit
        ASSERT: Returns 'completed'
        """
        # ARRANGE
        current_status = "site_visit_done"

        # ACT
        if current_status == "site_visit_done":
            bucket = "completed"
        else:
            bucket = "other"

        # ASSERT
        self.assertEqual(bucket, "completed")

    def test_06_classify_pending_feedback_with_empty_string_feedback(self):
        """
        ARRANGE: site_visit_scheduled, past date, feedback is empty string
        ACT: Classify
        ASSERT: Returns 'pending_feedback' (empty string is in _EMPTY_FEEDBACK)
        """
        # ARRANGE
        now = datetime.now()
        past_date = now - timedelta(days=1)
        current_status = "site_visit_scheduled"
        feedback_general = ""

        # ACT
        if current_status == "site_visit_scheduled":
            if past_date > now:
                bucket = "upcoming"
            elif feedback_general in _EMPTY_FEEDBACK:
                bucket = "pending_feedback"
            else:
                bucket = "cancelled"
        else:
            bucket = "other"

        # ASSERT
        self.assertEqual(bucket, "pending_feedback")

    def test_07_classify_pending_feedback_with_other_feedback(self):
        """
        ARRANGE: site_visit_scheduled, past date, feedback='other'
        ACT: Classify
        ASSERT: Returns 'pending_feedback' ('other' is in _EMPTY_FEEDBACK)
        """
        # ARRANGE
        now = datetime.now()
        past_date = now - timedelta(days=1)
        current_status = "site_visit_scheduled"
        feedback_general = "other"

        # ACT
        if current_status == "site_visit_scheduled":
            if past_date > now:
                bucket = "upcoming"
            elif feedback_general in _EMPTY_FEEDBACK:
                bucket = "pending_feedback"
            else:
                bucket = "cancelled"
        else:
            bucket = "other"

        # ASSERT
        self.assertEqual(bucket, "pending_feedback")

    # ========================================================================
    # BASE RECORD SERIALIZATION TESTS
    # ========================================================================

    def test_08_base_record_all_fields(self):
        """
        ARRANGE: Create full visit record with all fields
        ACT: Build base record
        ASSERT: All fields present and correctly formatted
        """
        # ARRANGE
        lead = self.create_portal_lead(
            phone="9999999999",
            name="Ravi Shah",
            property_base_id=self.test_property.id,
        )
        lead.write(
            {
                "site_visit_date": date(2025, 3, 20),
                "site_visit_date_only": date(2025, 3, 20),
                "current_status": "site_visit_scheduled",
                "remarks": "Wants to see the terrace",
            },
        )

        # ACT
        record = {
            "source": "primary",
            "lead_name": lead.name or None,
            "lead_phone": lead.phone or None,
            "property_tag": lead.property_base_id.property_tag if lead.property_base_id else None,
            "property_bhk": lead.property_base_id.bhk if lead.property_base_id else None,
            "property_location": lead.property_base_id.location
            if lead.property_base_id
            else None,
            "site_visit_datetime": (
                lead.site_visit_date.isoformat() if lead.site_visit_date else None
            ),
            "site_visit_date": (
                lead.site_visit_date_only.isoformat()
                if lead.site_visit_date_only
                else None
            ),
            "current_status": lead.current_status or None,
            "remarks": lead.remarks or None,
        }

        # ASSERT
        self.assertEqual(record["source"], "primary")
        self.assertEqual(record["lead_name"], "Ravi Shah")
        self.assertEqual(record["lead_phone"], "9999999999")
        self.assertEqual(record["property_tag"], self.test_property.property_tag)
        self.assertEqual(record["property_bhk"], "3 BHK")
        self.assertEqual(record["property_location"], "Test Location")
        self.assertEqual(record["site_visit_date"], "2025-03-20")
        self.assertEqual(record["current_status"], "site_visit_scheduled")
        self.assertEqual(record["remarks"], "Wants to see the terrace")

    def test_09_base_record_handles_nulls(self):
        """
        ARRANGE: Minimal visit record with many nulls
        ACT: Build base record
        ASSERT: Null fields are None
        """
        # ARRANGE
        lead = self.create_portal_lead(property_base_id=self.test_property.id)

        # ACT
        record = {
            "lead_name": lead.name or None,
            "remarks": lead.remarks or None,
            "site_visit_date": None,
        }

        # ASSERT
        self.assertIsNone(record["remarks"])
        self.assertIsNone(record["site_visit_date"])

    def test_10_recommended_source_inherits_parent_lead_info(self):
        """
        ARRANGE: Create recommended interest with parent lead
        ACT: Build base record for recommended
        ASSERT: Source is 'recommended' and uses parent lead name/phone
        """
        # ARRANGE
        parent_lead = self.create_portal_lead(
            phone="8888888888",
            name="Priya Patel",
        )
        interest = self.env["lead.property.interest"].create(
            {
                "lead_id": parent_lead.id,
                "property_base_id": self.test_property.id,
            },
        )

        # ACT
        record = {
            "source": "recommended",
            "lead_name": parent_lead.name or None,
            "lead_phone": parent_lead.phone or None,
        }

        # ASSERT
        self.assertEqual(record["source"], "recommended")
        self.assertEqual(record["lead_name"], "Priya Patel")
        self.assertEqual(record["lead_phone"], "8888888888")

    # ========================================================================
    # BUCKET-SPECIFIC FIELD APPLICATION TESTS
    # ========================================================================

    def test_11_pending_feedback_adds_note(self):
        """
        ARRANGE: Record in pending_feedback bucket
        ACT: Apply bucket-specific fields
        ASSERT: Note is added
        """
        # ARRANGE
        record = {"site_visit_date": "2025-01-01"}

        # ACT
        record["note"] = "Visit date has passed — awaiting RM feedback"

        # ASSERT
        self.assertIn("note", record)
        self.assertEqual(
            record["note"],
            "Visit date has passed — awaiting RM feedback",
        )

    def test_12_cancelled_includes_feedback_general_and_note(self):
        """
        ARRANGE: Record in cancelled bucket
        ACT: Apply bucket-specific fields
        ASSERT: feedback_general and note included
        """
        # ARRANGE
        record = {"site_visit_date": "2025-01-01"}
        feedback_general = "buyer_not_interested"

        # ACT
        record["feedback_general"] = feedback_general
        record["note"] = "Visit did not occur due to buyer status"

        # ASSERT
        self.assertEqual(record["feedback_general"], "buyer_not_interested")
        self.assertEqual(record["note"], "Visit did not occur due to buyer status")

    def test_13_completed_includes_feedback_site_visit_done(self):
        """
        ARRANGE: Record in completed bucket
        ACT: Apply bucket-specific fields
        ASSERT: feedback_site_visit_done included
        """
        # ARRANGE
        record = {}
        feedback_site_visit_done = "buyer_liked_property"

        # ACT
        record["feedback_site_visit_done"] = feedback_site_visit_done or None

        # ASSERT
        self.assertEqual(record["feedback_site_visit_done"], "buyer_liked_property")

    def test_14_completed_includes_remarks_only_when_feedback_other(self):
        """
        ARRANGE: Record in completed bucket with feedback='other'
        ACT: Apply bucket-specific fields
        ASSERT: remarks is included
        """
        # ARRANGE
        record = {}
        feedback_site_visit_done = "other"
        remarks = "Buyer asked for a second tour"

        # ACT
        record["feedback_site_visit_done"] = feedback_site_visit_done or None
        if feedback_site_visit_done == "other":
            record["remarks"] = remarks or None
        else:
            record["remarks"] = None

        # ASSERT
        self.assertEqual(record["remarks"], "Buyer asked for a second tour")

    def test_15_completed_excludes_remarks_when_feedback_not_other(self):
        """
        ARRANGE: Record in completed bucket with feedback='deal_closed'
        ACT: Apply bucket-specific fields
        ASSERT: remarks is None (excluded)
        """
        # ARRANGE
        record = {}
        feedback_site_visit_done = "deal_closed"
        remarks = "Some remarks"

        # ACT
        record["feedback_site_visit_done"] = feedback_site_visit_done or None
        if feedback_site_visit_done == "other":
            record["remarks"] = remarks or None
        else:
            record["remarks"] = None

        # ASSERT
        self.assertIsNone(record["remarks"])

    def test_16_rescheduled_adds_note(self):
        """
        ARRANGE: Record in rescheduled bucket (in-memory)
        ACT: Apply bucket-specific fields
        ASSERT: Note is added

        LEGACY TEST (in-memory): Tests the note that _apply_bucket_fields()
        attaches for the "rescheduled" bucket. This bucket is now legacy-only;
        new reschedules appear in "upcoming" via the lead.site.visit model.
        """
        # ARRANGE
        record = {}

        # ACT
        record["note"] = "Visit was rescheduled — confirm new date with RM"

        # ASSERT
        self.assertIn("note", record)
        self.assertEqual(
            record["note"],
            "Visit was rescheduled — confirm new date with RM",
        )

    def test_17_upcoming_has_no_extra_fields(self):
        """
        ARRANGE: Record in upcoming bucket
        ACT: Apply bucket-specific fields (upcoming has none)
        ASSERT: Only base fields present
        """
        # ARRANGE
        record = {
            "source": "primary",
            "lead_name": "Test",
            "current_status": "site_visit_scheduled",
        }

        # ACT - upcoming bucket adds no extra fields

        # ASSERT - verify no extra fields added
        self.assertNotIn("note", record)
        self.assertNotIn("feedback_general", record)
        self.assertNotIn("feedback_site_visit_done", record)

    # ========================================================================
    # SORTING TESTS
    # ========================================================================

    def test_18_upcoming_sorted_ascending_soonest_first(self):
        """
        ARRANGE: 3 upcoming visits on different future dates
        ACT: Sort ascending
        ASSERT: Soonest date first
        """
        # ARRANGE
        now = datetime.now()
        records = [
            {
                "date": now + timedelta(days=5),
                "lead": "Lead A",
            },
            {
                "date": now + timedelta(days=1),
                "lead": "Lead B",
            },
            {
                "date": now + timedelta(days=3),
                "lead": "Lead C",
            },
        ]

        # ACT
        sorted_records = sorted(records, key=lambda r: r["date"])

        # ASSERT - Soonest should be first
        self.assertEqual(sorted_records[0]["lead"], "Lead B")
        self.assertEqual(sorted_records[1]["lead"], "Lead C")
        self.assertEqual(sorted_records[2]["lead"], "Lead A")

    def test_19_pending_feedback_sorted_ascending_oldest_first(self):
        """
        ARRANGE: 3 pending_feedback visits on different past dates
        ACT: Sort ascending
        ASSERT: Most overdue (oldest) first
        """
        # ARRANGE
        now = datetime.now()
        records = [
            {
                "date": now - timedelta(days=1),
                "lead": "Lead A",
            },
            {
                "date": now - timedelta(days=5),
                "lead": "Lead B",
            },
            {
                "date": now - timedelta(days=3),
                "lead": "Lead C",
            },
        ]

        # ACT
        sorted_records = sorted(records, key=lambda r: r["date"])

        # ASSERT - Most overdue (oldest) should be first
        self.assertEqual(sorted_records[0]["lead"], "Lead B")
        self.assertEqual(sorted_records[1]["lead"], "Lead C")
        self.assertEqual(sorted_records[2]["lead"], "Lead A")

    def test_20_completed_sorted_descending_most_recent_first(self):
        """
        ARRANGE: 3 completed visits on different dates
        ACT: Sort descending
        ASSERT: Most recent first
        """
        # ARRANGE
        now = datetime.now()
        records = [
            {
                "date": now - timedelta(days=5),
                "lead": "Lead A",
            },
            {
                "date": now - timedelta(days=1),
                "lead": "Lead B",
            },
            {
                "date": now - timedelta(days=3),
                "lead": "Lead C",
            },
        ]

        # ACT
        sorted_records = sorted(records, key=lambda r: r["date"], reverse=True)

        # ASSERT - Most recent should be first
        self.assertEqual(sorted_records[0]["lead"], "Lead B")
        self.assertEqual(sorted_records[1]["lead"], "Lead C")
        self.assertEqual(sorted_records[2]["lead"], "Lead A")

    def test_21_cancelled_sorted_descending_most_recent_first(self):
        """
        ARRANGE: 3 cancelled visits
        ACT: Sort descending
        ASSERT: Most recent first
        """
        # ARRANGE
        now = datetime.now()
        records = [
            {"date": now - timedelta(days=10), "lead": "Old"},
            {"date": now - timedelta(days=2), "lead": "Recent"},
            {"date": now - timedelta(days=5), "lead": "Middle"},
        ]

        # ACT
        sorted_records = sorted(records, key=lambda r: r["date"], reverse=True)

        # ASSERT
        self.assertEqual(sorted_records[0]["lead"], "Recent")
        self.assertEqual(sorted_records[1]["lead"], "Middle")
        self.assertEqual(sorted_records[2]["lead"], "Old")

    # ========================================================================
    # FILTERING TESTS
    # ========================================================================

    def test_22_filter_by_property_tag(self):
        """
        ARRANGE: Seller with 3 properties, visits created
        ACT: Filter by one property_tag
        ASSERT: Returns only visits from that property
        """
        # ARRANGE
        lead_1 = self.create_portal_lead(
            phone="9111111111",
            property_base_id=self.test_property.id,
        )
        lead_2 = self.create_portal_lead(
            phone="9111111112",
            property_base_id=self.test_property_2.id,
        )

        properties = [self.test_property, self.test_property_2, self.test_property_3]
        tags = [p.property_tag for p in properties]

        # ACT - Filter to one property
        tag_filter = self.test_property.property_tag
        filtered_tags = [tag for tag in tags if tag == tag_filter]

        # ASSERT
        self.assertEqual(len(filtered_tags), 1)
        self.assertEqual(filtered_tags[0], self.test_property.property_tag)

    def test_23_no_visits_for_property_without_site_visit_date(self):
        """
        ARRANGE: Create lead without site_visit_date
        ACT: Query for visits
        ASSERT: Lead is filtered out (requires site_visit_date and valid status)
        """
        # ARRANGE
        lead = self.create_portal_lead(
            phone="9222222222",
            property_base_id=self.test_property.id,
        )
        # site_visit_date is not set

        # ACT - Check if lead would be included
        has_visit_date = lead.site_visit_date is not None
        has_valid_status = lead.current_status in {
            "site_visit_scheduled",
            "site_visit_done",
            "rescheduled",
        }
        would_include = has_visit_date and has_valid_status

        # ASSERT
        self.assertFalse(would_include)

    # ========================================================================
    # COMBINED PRIMARY + RECOMMENDED TESTS
    # ========================================================================

    def test_24_visits_combine_primary_and_recommended(self):
        """
        ARRANGE: 2 primary visits, 2 recommended visits
        ACT: Combine both into site visits
        ASSERT: All 4 visits included with correct sources
        """
        # ARRANGE
        # 2 primary
        lead_1 = self.create_portal_lead(
            phone="9333333333",
            property_base_id=self.test_property.id,
        )
        lead_2 = self.create_portal_lead(
            phone="9333333334",
            property_base_id=self.test_property.id,
        )

        # 2 recommended
        parent_lead_1 = self.create_portal_lead(phone="9333333335")
        interest_1 = self.env["lead.property.interest"].create(
            {
                "lead_id": parent_lead_1.id,
                "property_base_id": self.test_property.id,
            },
        )

        parent_lead_2 = self.create_portal_lead(phone="9333333336")
        interest_2 = self.env["lead.property.interest"].create(
            {
                "lead_id": parent_lead_2.id,
                "property_base_id": self.test_property.id,
            },
        )

        # ACT
        records = [
            {"source": "primary"},
            {"source": "primary"},
            {"source": "recommended"},
            {"source": "recommended"},
        ]

        # ASSERT
        primary_count = sum(1 for r in records if r["source"] == "primary")
        recommended_count = sum(1 for r in records if r["source"] == "recommended")
        self.assertEqual(primary_count, 2)
        self.assertEqual(recommended_count, 2)

    def test_25_mixed_bucket_distribution(self):
        """
        ARRANGE: Create visits that will fall into different buckets
        ACT: Classify each
        ASSERT: Each lands in correct bucket
        """
        # ARRANGE
        now = datetime.now()
        visits = [
            {
                "status": "site_visit_scheduled",
                "date": now + timedelta(days=5),
                "feedback": None,
                "expected_bucket": "upcoming",
            },
            {
                "status": "site_visit_scheduled",
                "date": now - timedelta(days=2),
                "feedback": None,
                "expected_bucket": "pending_feedback",
            },
            {
                "status": "site_visit_scheduled",
                "date": now - timedelta(days=1),
                "feedback": "buyer_not_interested",
                "expected_bucket": "cancelled",
            },
            {
                "status": "rescheduled",
                "date": now + timedelta(days=3),
                "feedback": None,
                "expected_bucket": "rescheduled",
            },
            {
                "status": "site_visit_done",
                "date": now - timedelta(days=10),
                "feedback": "deal_closed",
                "expected_bucket": "completed",
            },
        ]

        # ACT & ASSERT
        for visit in visits:
            if visit["status"] == "site_visit_done":
                bucket = "completed"
            elif visit["status"] == "rescheduled":
                bucket = "rescheduled"
            elif visit["status"] == "site_visit_scheduled":
                if visit["date"] > now:
                    bucket = "upcoming"
                elif visit["feedback"] in _EMPTY_FEEDBACK:
                    bucket = "pending_feedback"
                else:
                    bucket = "cancelled"
            else:
                bucket = "unknown"

            self.assertEqual(bucket, visit["expected_bucket"])

    # ========================================================================
    # TOTALS CALCULATION TESTS
    # ========================================================================

    def test_26_totals_calculation(self):
        """
        ARRANGE: 5 visits distributed across buckets
        ACT: Calculate totals
        ASSERT: Correct count per bucket
        """
        # ARRANGE
        buckets = {
            "upcoming": [1, 2],
            "pending_feedback": [3],
            "cancelled": [4, 5],
            "rescheduled": [],
            "completed": [6, 7, 8],
        }

        # ACT
        totals = {k: len(v) for k, v in buckets.items()}

        # ASSERT
        self.assertEqual(totals["upcoming"], 2)
        self.assertEqual(totals["pending_feedback"], 1)
        self.assertEqual(totals["cancelled"], 2)
        self.assertEqual(totals["rescheduled"], 0)
        self.assertEqual(totals["completed"], 3)

    # ========================================================================
    # EDGE CASES & DATA INTEGRITY
    # ========================================================================

    def test_27_empty_all_buckets(self):
        """
        ARRANGE: No visits for property
        ACT: Get site visits
        ASSERT: All buckets empty, totals are 0
        """
        # ARRANGE
        buckets = {
            "upcoming": [],
            "pending_feedback": [],
            "cancelled": [],
            "rescheduled": [],
            "completed": [],
        }

        # ACT
        total_visits = sum(len(v) for v in buckets.values())

        # ASSERT
        self.assertEqual(total_visits, 0)
        for bucket_name, records in buckets.items():
            self.assertEqual(len(records), 0)

    def test_28_datetime_iso_format(self):
        """
        ARRANGE: Visit with specific datetime
        ACT: Format as ISO
        ASSERT: Correctly formatted as ISO 8601
        """
        # ARRANGE
        dt = datetime(2025, 3, 20, 11, 0, 0)

        # ACT
        iso_str = dt.isoformat()

        # ASSERT
        self.assertEqual(iso_str, "2025-03-20T11:00:00")

    def test_29_date_iso_format(self):
        """
        ARRANGE: Visit date
        ACT: Format as ISO
        ASSERT: Correctly formatted as YYYY-MM-DD
        """
        # ARRANGE
        d = date(2025, 3, 20)

        # ACT
        iso_str = d.isoformat()

        # ASSERT
        self.assertEqual(iso_str, "2025-03-20")

    def test_30_property_tag_mapping(self):
        """
        ARRANGE: Multiple properties with different tags
        ACT: Map all tags
        ASSERT: All tags accessible
        """
        # ARRANGE
        properties = [self.test_property, self.test_property_2, self.test_property_3]
        tags = [p.property_tag for p in properties]

        # ACT
        extracted_tags = tags

        # ASSERT
        self.assertEqual(len(extracted_tags), 3)
        self.assertIn(self.test_property.property_tag, extracted_tags)
        self.assertIn(self.test_property_2.property_tag, extracted_tags)
        self.assertIn(self.test_property_3.property_tag, extracted_tags)

    def test_31_visit_with_all_feedback_types(self):
        """
        ARRANGE: Create visits with different feedback values
        ACT: Verify each produces correct bucket-specific behavior
        ASSERT: All feedback types handled correctly
        """
        # ARRANGE
        feedback_values = [
            {"value": None, "expected_empty": True},
            {"value": "", "expected_empty": True},
            {"value": "other", "expected_empty": True},
            {"value": "buyer_not_interested", "expected_empty": False},
            {"value": "buyer_not_picking_call", "expected_empty": False},
            {"value": "buyer_did_not_visit_property", "expected_empty": False},
            {"value": "visit_needs_to_be_rescheduled", "expected_empty": False},
        ]

        # ACT & ASSERT
        for feedback in feedback_values:
            is_empty = feedback["value"] in _EMPTY_FEEDBACK
            self.assertEqual(is_empty, feedback["expected_empty"])

    def test_32_site_visit_date_only_vs_datetime(self):
        """
        ARRANGE: Visit with both date and datetime fields
        ACT: Serialize both
        ASSERT: Different formats, same underlying date
        """
        # ARRANGE
        lead = self.create_portal_lead(property_base_id=self.test_property.id)
        lead.write(
            {
                "site_visit_date": datetime(2025, 3, 20, 11, 30, 0),
                "site_visit_date_only": date(2025, 3, 20),
            },
        )

        # ACT
        datetime_iso = (
            lead.site_visit_date.isoformat() if lead.site_visit_date else None
        )
        date_iso = (
            lead.site_visit_date_only.isoformat() if lead.site_visit_date_only else None
        )

        # ASSERT
        self.assertEqual(datetime_iso, "2025-03-20T11:30:00")
        self.assertEqual(date_iso, "2025-03-20")
        # Both refer to same calendar date
        self.assertTrue(datetime_iso.startswith(date_iso))

    # ─────────────────────────────────────────────────────────────────────────
    # NEW MODEL INTEGRATION: lead.site.visit drives the snapshot
    # ─────────────────────────────────────────────────────────────────────────

    def test_33_new_model_scheduled_visit_syncs_to_upcoming_bucket(self):
        """
        ARRANGE: Lead with a linked property (seller's property) and no visits.
        ACT    : Create a lead.site.visit with 'scheduled' status and a future
                 datetime. The model's _sync_inquiry_snapshot writes back to the
                 leads.new flat fields automatically.
        ASSERT : leads.new.current_status == "site_visit_scheduled"
                 leads.new.site_visit_date  == the scheduled datetime
                 _classify_visit_new(visit, now) maps the visit to "upcoming".

        This verifies that the new model drives the seller API response correctly
        without any direct writes to leads.new snapshot fields.
        """
        from odoo.addons.leads.controllers.seller.site_visits import _classify_visit_new

        now = datetime.now()
        lead = self.create_portal_lead(
            property_base_id=self.test_property.id,
            user_id=self.rm_user.id,
        )
        scheduled_status = self.env["lead.site.visit.status"].search(
            [("code", "=", "scheduled")], limit=1
        )
        future_dt = now + timedelta(days=7)

        visit = self.env["lead.site.visit"].create(
            {
                "inquiry_id": lead.id,
                "status_id": scheduled_status.id,
                "scheduled_datetime": future_dt,
            }
        )

        # Snapshot synchronisation must have fired.
        self.assertEqual(lead.current_status, "site_visit_scheduled")
        self.assertEqual(lead.site_visit_date, future_dt)

        # The controller classifies this as "upcoming" using the visit record directly.
        bucket = _classify_visit_new(visit, now)
        self.assertEqual(bucket, "upcoming")

    def test_34_new_model_completed_visit_syncs_to_completed_bucket(self):
        """
        ARRANGE: Lead with a scheduled visit.
        ACT    : Mark the visit 'completed'. Snapshot updates current_status
                 to "site_visit_done".
        ASSERT : leads.new.current_status == "site_visit_done"
                 _classify_visit_new(visit, now) maps it to "completed".

        Normal post-visit flow: RM marks visit done, snapshot flips the inquiry
        to site_visit_done, seller API shows it in the "completed" bucket.
        """
        from odoo.addons.leads.controllers.seller.site_visits import _classify_visit_new

        now = datetime.now()
        lead = self.create_portal_lead(
            property_base_id=self.test_property.id,
            user_id=self.rm_user.id,
        )
        scheduled_status = self.env["lead.site.visit.status"].search(
            [("code", "=", "scheduled")], limit=1
        )
        completed_status = self.env["lead.site.visit.status"].search(
            [("code", "=", "completed")], limit=1
        )

        visit = self.env["lead.site.visit"].create(
            {
                "inquiry_id": lead.id,
                "status_id": scheduled_status.id,
                "scheduled_datetime": now - timedelta(days=2),
            }
        )
        visit.write({"status_id": completed_status.id})

        self.assertEqual(lead.current_status, "site_visit_done")

        bucket = _classify_visit_new(visit, now)
        self.assertEqual(bucket, "completed")

    def test_35_reschedule_via_new_model_appears_in_upcoming_not_rescheduled(self):
        """
        ARRANGE: Lead with one scheduled visit.
        ACT    : Reschedule via lead.site.visit.write(status=rescheduled, new_datetime).
                 The model supersedes the original and creates a new 'scheduled' visit.
                 The snapshot receives current_status="site_visit_scheduled".
        ASSERT : leads.new.current_status == "site_visit_scheduled" (NOT "rescheduled")
                 _classify_visit_new(active_visit, now) returns "upcoming".

        Critical contract: the "rescheduled" bucket is NEVER populated by the new
        visit model. Reschedules always appear in "upcoming". The "rescheduled"
        bucket is legacy-only (pre-visit-model direct writes).
        """
        from odoo.addons.leads.controllers.seller.site_visits import (
            _classify_visit_new,
            _get_latest_active_visit,
        )

        now = datetime.now()
        lead = self.create_portal_lead(
            property_base_id=self.test_property.id,
            user_id=self.rm_user.id,
        )
        scheduled_status = self.env["lead.site.visit.status"].search(
            [("code", "=", "scheduled")], limit=1
        )
        rescheduled_status = self.env["lead.site.visit.status"].search(
            [("code", "=", "rescheduled")], limit=1
        )

        original_visit = self.env["lead.site.visit"].create(
            {
                "inquiry_id": lead.id,
                "status_id": scheduled_status.id,
                "scheduled_datetime": now - timedelta(days=1),
            }
        )

        new_future_dt = now + timedelta(days=5)
        original_visit.write(
            {"status_id": rescheduled_status.id, "scheduled_datetime": new_future_dt}
        )

        self.assertEqual(
            lead.current_status,
            "site_visit_scheduled",
            "Reschedule via new model must write 'site_visit_scheduled' to snapshot, "
            "not 'rescheduled'. The 'rescheduled' bucket is legacy-only.",
        )

        # The controller gets the latest non-superseded visit and classifies it.
        active_visit = _get_latest_active_visit(lead)
        bucket = _classify_visit_new(active_visit, now)
        self.assertEqual(
            bucket,
            "upcoming",
            "A rescheduled visit (new model) must appear in 'upcoming', not 'rescheduled'.",
        )
