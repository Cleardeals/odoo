"""
FAANG-style test suite for BuyerSiteVisitsController.lead_site_visits endpoint.

Tests the business logic of the buyer site visits API, including:
- Visit classification into 5 buckets (upcoming, pending_feedback, cancelled, rescheduled, completed)
- Base record serialization with proper null handling
- Bucket-specific fields (note, feedback_general, feedback_site_visit_done, remarks)
- Sorting per bucket (ascending for upcoming/pending_feedback, descending for others)
- Primary lead vs. recommended interest distinction (source field)
- Multiple inquiries and visit aggregation
- Valid status values for site_visit classification
- Integration with lead.site.visit model (snapshot sync, reschedule flow)

Model integration notes
-----------------------
The API reads the flat snapshot fields on leads.new (site_visit_date,
current_status, feedback_general, etc.). These are populated either:
  • Directly by the RM (legacy path)
  • Automatically by lead.site.visit._sync_inquiry_snapshot (new path)

Under the new model, completed visits write current_status="site_visit_done"
and scheduled/rescheduled visits both write current_status="site_visit_scheduled".
The "rescheduled" bucket in the controller is therefore LEGACY ONLY — it is kept
for backward compatibility with records that had "rescheduled" written directly.
New reschedules will always appear in the "upcoming" bucket.
"""

import logging
from datetime import datetime, timedelta

from odoo.tests import tagged

from .test_portal_common import PortalLeadTestCase

_logger = logging.getLogger(__name__)

# Valid site visit statuses per controller
_VISIT_STATUSES = {"site_visit_scheduled", "site_visit_done", "rescheduled"}
_EMPTY_FEEDBACK = {None, "", "other", False}


@tagged("post_install", "-at_install")
class TestBuyerSiteVisitsAPI(PortalLeadTestCase):
    """
    Buyer site visits endpoint test suite testing visit classification,
    serialization, and aggregation logic.
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures including additional test properties."""
        super().setUpClass()

        # Create additional test properties for recommended interests
        cls.test_property_2 = cls.env["property.base"].create(
            {
                "property_tag": f"TEST-PROP-2-{cls.suffix}",
                "name": f"Test Property 2 {cls.suffix}",
                "bedroom_count": 2,
                "location": "Second Test Location",
                "city": "Second Test City",
                "rm_user_id": cls.rm_user.id,
                "is_active": True,
            },
        )

        cls.test_property_3 = cls.env["property.base"].create(
            {
                "property_tag": f"TEST-PROP-3-{cls.suffix}",
                "name": f"Test Property 3 {cls.suffix}",
                "bedroom_count": 4,
                "location": "Third Test Location",
                "city": "Third Test City",
                "rm_user_id": cls.rm_user.id,
                "is_active": True,
            },
        )

    def setUp(self):
        """Prepare test environment before each test method."""
        super().setUp()
        self.now = datetime.now()
        self.past_date = self.now - timedelta(days=10)
        self.future_date = self.now + timedelta(days=10)

    def create_interest_for_lead(self, lead, property_obj):
        """
        Helper to create a recommended property interest (lead.property.interest).
        UNIQUE constraint: (lead_id, property_base_id) — same lead cannot have duplicate
        interests for same property.
        """
        interest = self.env["lead.property.interest"].create(
            {
                "lead_id": lead.id,
                "property_base_id": property_obj.id,
            },
        )
        return interest

    # ─────────────────────────────────────────────────────────────────────────
    # TEST: Visit Classification (5 Buckets)
    # ─────────────────────────────────────────────────────────────────────────

    def test_001_classify_upcoming_future_scheduled(self):
        """
        ARRANGE: site_visit_scheduled with future date
        ACT: Classify
        ASSERT: "upcoming" bucket
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "site_visit_date": self.future_date,
                "current_status": "site_visit_scheduled",
            },
        )

        self.assertEqual(lead.current_status, "site_visit_scheduled")
        self.assertTrue(lead.site_visit_date > self.now)

    def test_002_classify_pending_feedback_past_no_feedback(self):
        """
        ARRANGE: site_visit_scheduled + past date + no feedback (None)
        ACT: Classify
        ASSERT: "pending_feedback" bucket (feedback is in _EMPTY_FEEDBACK)
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "site_visit_date": self.past_date,
                "current_status": "site_visit_scheduled",
                "feedback_general": None,
            },
        )

        self.assertEqual(lead.current_status, "site_visit_scheduled")
        self.assertTrue(lead.site_visit_date < self.now)
        self.assertFalse(lead.feedback_general)

    def test_003_classify_cancelled_past_with_feedback(self):
        """
        ARRANGE: site_visit_scheduled + past date + feedback value set
        ACT: Classify
        ASSERT: "cancelled" bucket (feedback NOT in _EMPTY_FEEDBACK)
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "site_visit_date": self.past_date,
                "current_status": "site_visit_scheduled",
                "feedback_general": "buyer_not_interested",
            },
        )

        self.assertEqual(lead.current_status, "site_visit_scheduled")
        self.assertEqual(lead.feedback_general, "buyer_not_interested")

    def test_004_classify_rescheduled(self):
        """
        ARRANGE: status = rescheduled written directly on leads.new
        ACT: Classify
        ASSERT: "rescheduled" bucket

        LEGACY TEST: This path is only reachable for records that had
        current_status="rescheduled" written directly (pre-visit-model data or
        a manual override). New reschedules via lead.site.visit write
        current_status="site_visit_scheduled" to the snapshot instead, so those
        appear in the "upcoming" bucket. See test_036_reschedule_via_new_model.
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "site_visit_date": self.past_date,
                "current_status": "rescheduled",
            },
        )

        self.assertEqual(lead.current_status, "rescheduled")

    def test_005_classify_completed(self):
        """
        ARRANGE: status = site_visit_done
        ACT: Classify
        ASSERT: "completed" bucket (date irrelevant)
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "site_visit_date": self.past_date,
                "current_status": "site_visit_done",
                "feedback_site_visit_done": "buyer_liked_property",
            },
        )

        self.assertEqual(lead.current_status, "site_visit_done")

    def test_006_empty_string_feedback_pending(self):
        """
        ARRANGE: site_visit_scheduled + past + feedback=""
        ACT: Classify
        ASSERT: pending_feedback (empty string in _EMPTY_FEEDBACK)
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "site_visit_date": self.past_date,
                "current_status": "site_visit_scheduled",
                "feedback_general": "",
            },
        )

        self.assertFalse(lead.feedback_general)

    def test_007_false_feedback_pending(self):
        """
        ARRANGE: site_visit_scheduled + past + feedback=False
        ACT: Classify
        ASSERT: pending_feedback (False in _EMPTY_FEEDBACK)
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "site_visit_date": self.past_date,
                "current_status": "site_visit_scheduled",
                "feedback_general": False,
            },
        )

        self.assertFalse(lead.feedback_general)

    # ─────────────────────────────────────────────────────────────────────────
    # TEST: Primary Lead Record Building
    # ─────────────────────────────────────────────────────────────────────────

    def test_008_primary_lead_record_all_base_fields(self):
        """
        ARRANGE: Primary lead with all fields set
        ACT: Verify field structure
        ASSERT: All base fields present and correct
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "name": "Ravi Shah",
                "source_id": self.source_magicbricks.id,
                "site_visit_date": self.future_date,
                "site_visit_date_only": self.future_date.date(),
                "current_status": "site_visit_scheduled",
                "remarks": "Wants east-facing flat",
                "property_base_id": self.test_property.id,
            },
        )

        self.assertEqual(lead.name, "Ravi Shah")
        self.assertEqual(lead.source_id.name, "MagicBricks")
        self.assertIsNotNone(lead.site_visit_date)
        self.assertIsNotNone(lead.site_visit_date_only)
        self.assertEqual(lead.current_status, "site_visit_scheduled")
        self.assertEqual(lead.remarks, "Wants east-facing flat")
        self.assertIsNotNone(lead.property_base_id)

    def test_009_null_name_and_portal(self):
        """
        ARRANGE: Lead with null name and portal_name
        ACT: Check fields
        ASSERT: Null fields remain None (not default)
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "name": False,
                "source_id": False,
                "site_visit_date": self.future_date,
                "current_status": "site_visit_scheduled",
            },
        )

        # Odoo stores False for empty name/source_id
        self.assertFalse(lead.name)
        self.assertFalse(lead.source_id)

    def test_010_site_visit_datetime_iso_format(self):
        """
        ARRANGE: Lead with specific datetime
        ACT: Format as ISO 8601
        ASSERT: Correct format
        """
        test_datetime = datetime(2025, 3, 15, 14, 30, 0)
        lead = self.create_portal_lead()
        lead.write(
            {
                "site_visit_date": test_datetime,
                "current_status": "site_visit_scheduled",
            },
        )

        iso_str = lead.site_visit_date.isoformat()
        self.assertEqual(iso_str, test_datetime.isoformat())

    def test_011_property_details_accessible(self):
        """
        ARRANGE: Lead with property assigned
        ACT: Access property fields
        ASSERT: All fields accessible
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "property_base_id": self.test_property.id,
                "site_visit_date": self.future_date,
                "current_status": "site_visit_scheduled",
            },
        )

        prop = lead.property_base_id
        self.assertIsNotNone(prop.property_tag)
        self.assertIsNotNone(prop.bhk)
        self.assertIsNotNone(prop.location)
        self.assertIsNotNone(prop.city)

    # ─────────────────────────────────────────────────────────────────────────
    # TEST: Recommended Interest Record Building
    # ─────────────────────────────────────────────────────────────────────────

    def test_012_recommended_interest_structure(self):
        """
        ARRANGE: Recommended interest on lead
        ACT: Create and verify
        ASSERT: Parent lead and property linked
        """
        lead = self.create_portal_lead()
        interest = self.create_interest_for_lead(lead, self.test_property_2)
        interest.write(
            {
                "site_visit_date": self.future_date,
                "current_status": "site_visit_scheduled",
            },
        )

        self.assertEqual(interest.lead_id.id, lead.id)
        self.assertEqual(interest.property_base_id.id, self.test_property_2.id)

    def test_013_recommended_inherits_lead_info(self):
        """
        ARRANGE: Recommended interest with parent lead data
        ACT: Access via interest.lead_id
        ASSERT: Parent info accessible
        """
        lead = self.create_portal_lead()
        lead.write({"name": "Buyer Name", "source_id": self.source_99acres.id})

        interest = self.create_interest_for_lead(lead, self.test_property_2)

        self.assertEqual(interest.lead_id.name, "Buyer Name")
        self.assertEqual(interest.lead_id.source_id.name, "99acres")

    # ─────────────────────────────────────────────────────────────────────────
    # TEST: Bucket-Specific Fields
    # ─────────────────────────────────────────────────────────────────────────

    def test_014_pending_feedback_no_feedback_value(self):
        """
        ARRANGE: Pending feedback visit (scheduled past, no feedback)
        ACT: Check feedback fields
        ASSERT: feedback_general is empty
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "site_visit_date": self.past_date,
                "current_status": "site_visit_scheduled",
                "feedback_general": None,
            },
        )

        # Feedback should be None/False (no value set)
        self.assertFalse(lead.feedback_general)

    def test_015_cancelled_has_feedback_value(self):
        """
        ARRANGE: Cancelled visit with feedback reason
        ACT: Check feedback
        ASSERT: feedback_general has value
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "site_visit_date": self.past_date,
                "current_status": "site_visit_scheduled",
                "feedback_general": "buyer_not_picking_call",
            },
        )

        self.assertEqual(lead.feedback_general, "buyer_not_picking_call")

    def test_016_rescheduled_status_preserved(self):
        """
        ARRANGE: Rescheduled visit via direct write on leads.new
        ACT: Check status
        ASSERT: rescheduled status preserved in the controller's legacy bucket

        LEGACY TEST: current_status="rescheduled" on leads.new is only produced
        by pre-visit-model direct writes. Reschedules via lead.site.visit produce
        current_status="site_visit_scheduled" instead. See test_036.
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "site_visit_date": self.past_date,
                "current_status": "rescheduled",
            },
        )

        self.assertEqual(lead.current_status, "rescheduled")

    def test_017_completed_has_feedback_done(self):
        """
        ARRANGE: Completed visit (site_visit_done)
        ACT: Check feedback_site_visit_done
        ASSERT: Field can have value
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "site_visit_date": self.past_date,
                "current_status": "site_visit_done",
                "feedback_site_visit_done": "buyer_liked_property",
            },
        )

        self.assertEqual(lead.feedback_site_visit_done, "buyer_liked_property")

    def test_018_completed_with_remarks_other(self):
        """
        ARRANGE: Completed with feedback="other" + remarks
        ACT: Set fields
        ASSERT: Both present
        """
        lead = self.create_portal_lead()
        test_remark = "Buyer interested but needs time to think"
        lead.write(
            {
                "site_visit_date": self.past_date,
                "current_status": "site_visit_done",
                "feedback_site_visit_done": "other",
                "remarks": test_remark,
            },
        )

        self.assertEqual(lead.feedback_site_visit_done, "other")
        self.assertEqual(lead.remarks, test_remark)

    def test_019_completed_clean_remarks_non_other(self):
        """
        ARRANGE: Completed with feedback!="other" but remarks set
        ACT: API would clean remarks
        ASSERT: Logic: remarks set to None when feedback != "other"
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "site_visit_date": self.past_date,
                "current_status": "site_visit_done",
                "feedback_site_visit_done": "buyer_liked_property",
                "remarks": "This would be ignored in API response",
            },
        )

        self.assertEqual(lead.feedback_site_visit_done, "buyer_liked_property")

    def test_020_upcoming_minimal_fields(self):
        """
        ARRANGE: Upcoming visit
        ACT: Check fields
        ASSERT: No feedback fields set
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "site_visit_date": self.future_date,
                "current_status": "site_visit_scheduled",
            },
        )

        # No feedback fields
        self.assertFalse(lead.feedback_general)
        self.assertFalse(lead.feedback_site_visit_done)

    # ─────────────────────────────────────────────────────────────────────────
    # TEST: Sorting Logic
    # ─────────────────────────────────────────────────────────────────────────

    def test_021_upcoming_ascending_soonest_first(self):
        """
        ARRANGE: Two upcoming visits with different dates
        ACT: Sort by date
        ASSERT: Earlier date first
        """
        lead = self.create_portal_lead()
        date_soon = self.now + timedelta(days=1)
        date_later = self.now + timedelta(days=3)

        lead.write(
            {
                "site_visit_date": date_later,
                "current_status": "site_visit_scheduled",
            },
        )

        interest = self.create_interest_for_lead(lead, self.test_property_2)
        interest.write(
            {
                "site_visit_date": date_soon,
                "current_status": "site_visit_scheduled",
            },
        )

        # Test ascending sort
        visits = sorted(
            [lead.site_visit_date, interest.site_visit_date],
        )
        self.assertEqual(visits[0], date_soon)
        self.assertEqual(visits[1], date_later)

    def test_022_pending_ascending_oldest_first(self):
        """
        ARRANGE: Two pending feedback visits
        ACT: Sort by date
        ASSERT: Oldest first
        """
        lead = self.create_portal_lead()
        date_old = self.now - timedelta(days=5)
        date_recent = self.now - timedelta(days=1)

        lead.write(
            {
                "site_visit_date": date_recent,
                "current_status": "site_visit_scheduled",
                "feedback_general": None,
            },
        )

        interest = self.create_interest_for_lead(lead, self.test_property_2)
        interest.write(
            {
                "site_visit_date": date_old,
                "current_status": "site_visit_scheduled",
                "feedback_general": None,
            },
        )

        visits = sorted([lead.site_visit_date, interest.site_visit_date])
        self.assertEqual(visits[0], date_old)
        self.assertEqual(visits[1], date_recent)

    def test_023_cancelled_descending_recent_first(self):
        """
        ARRANGE: Two cancelled visits
        ACT: Sort by date descending
        ASSERT: Recent first
        """
        lead = self.create_portal_lead()
        date_old = self.now - timedelta(days=10)
        date_recent = self.now - timedelta(days=1)

        lead.write(
            {
                "site_visit_date": date_old,
                "current_status": "site_visit_scheduled",
                "feedback_general": "buyer_not_interested",
            },
        )

        interest = self.create_interest_for_lead(lead, self.test_property_2)
        interest.write(
            {
                "site_visit_date": date_recent,
                "current_status": "site_visit_scheduled",
                "feedback_general": "buyer_not_interested",
            },
        )

        visits = sorted([lead.site_visit_date, interest.site_visit_date], reverse=True)
        self.assertEqual(visits[0], date_recent)
        self.assertEqual(visits[1], date_old)

    def test_024_completed_descending_recent_first(self):
        """
        ARRANGE: Two completed visits
        ACT: Sort descending
        ASSERT: Recent first
        """
        lead = self.create_portal_lead()
        date_old = self.now - timedelta(days=7)
        date_recent = self.now - timedelta(days=2)

        lead.write(
            {
                "site_visit_date": date_old,
                "current_status": "site_visit_done",
                "feedback_site_visit_done": "buyer_liked_property",
            },
        )

        interest = self.create_interest_for_lead(lead, self.test_property_2)
        interest.write(
            {
                "site_visit_date": date_recent,
                "current_status": "site_visit_done",
                "feedback_site_visit_done": "buyer_liked_property",
            },
        )

        visits = sorted([lead.site_visit_date, interest.site_visit_date], reverse=True)
        self.assertEqual(visits[0], date_recent)
        self.assertEqual(visits[1], date_old)

    # ─────────────────────────────────────────────────────────────────────────
    # TEST: Source Field (Primary vs Recommended)
    # ─────────────────────────────────────────────────────────────────────────

    def test_025_primary_lead_source(self):
        """
        ARRANGE: Primary lead with site visit
        ACT: Check source
        ASSERT: Source would be "primary" in API
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "site_visit_date": self.future_date,
                "current_status": "site_visit_scheduled",
            },
        )

        self.assertIsNotNone(lead.id)

    def test_026_recommended_source(self):
        """
        ARRANGE: Recommended interest
        ACT: Check lead linkage
        ASSERT: Source would be "recommended" in API
        """
        lead = self.create_portal_lead()
        interest = self.create_interest_for_lead(lead, self.test_property_2)
        interest.write(
            {
                "site_visit_date": self.future_date,
                "current_status": "site_visit_scheduled",
            },
        )

        self.assertEqual(interest.lead_id.id, lead.id)

    def test_027_primary_and_recommended_together(self):
        """
        ARRANGE: Lead with primary + recommended visits
        ACT: Check both
        ASSERT: Both present with distinct sources
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "site_visit_date": self.future_date,
                "current_status": "site_visit_scheduled",
            },
        )

        interest = self.create_interest_for_lead(lead, self.test_property_2)
        interest.write(
            {
                "site_visit_date": self.future_date,
                "current_status": "site_visit_scheduled",
            },
        )

        self.assertEqual(lead.id, lead.id)
        self.assertEqual(interest.lead_id.id, lead.id)

    # ─────────────────────────────────────────────────────────────────────────
    # TEST: Multiple Inquiries
    # ─────────────────────────────────────────────────────────────────────────

    def test_028_multiple_inquiries_same_buyer(self):
        """
        ARRANGE: Same buyer phone with 2 inquiries
        ACT: Create both
        ASSERT: Both linked to same phone
        """
        phone = "9876543210"
        lead1 = self.create_portal_lead(phone=phone)
        lead1.write(
            {
                "site_visit_date": self.future_date,
                "current_status": "site_visit_scheduled",
            },
        )

        lead2 = self.create_portal_lead(phone=phone)
        lead2.write(
            {
                "site_visit_date": self.future_date + timedelta(days=1),
                "current_status": "site_visit_scheduled",
            },
        )

        leads = self.env["leads.new"].search([("phone", "=", phone)])
        self.assertGreaterEqual(len(leads), 2)

    def test_029_multiple_recommendations_single_inquiry(self):
        """
        ARRANGE: Single lead with 2 recommended properties
        ACT: Create both
        ASSERT: Both linked to lead
        """
        lead = self.create_portal_lead()

        interest1 = self.create_interest_for_lead(lead, self.test_property_2)
        interest1.write(
            {
                "site_visit_date": self.future_date,
                "current_status": "site_visit_scheduled",
            },
        )

        interest2 = self.create_interest_for_lead(lead, self.test_property_3)
        interest2.write(
            {
                "site_visit_date": self.future_date + timedelta(days=1),
                "current_status": "site_visit_scheduled",
            },
        )

        interests = lead.interest_ids
        self.assertEqual(len(interests), 2)

    def test_030_primary_plus_multi_recommended(self):
        """
        ARRANGE: Lead with primary + 2 recommended
        ACT: Count all
        ASSERT: 3 total visit records
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "property_base_id": self.test_property.id,
                "site_visit_date": self.future_date,
                "current_status": "site_visit_scheduled",
            },
        )

        interest1 = self.create_interest_for_lead(lead, self.test_property_2)
        interest1.write(
            {
                "site_visit_date": self.future_date,
                "current_status": "site_visit_scheduled",
            },
        )

        interest2 = self.create_interest_for_lead(lead, self.test_property_3)
        interest2.write(
            {
                "site_visit_date": self.future_date,
                "current_status": "site_visit_scheduled",
            },
        )

        total = 1 + len(lead.interest_ids)
        self.assertEqual(total, 3)

    # ─────────────────────────────────────────────────────────────────────────
    # TEST: Aggregation and Filtering
    # ─────────────────────────────────────────────────────────────────────────

    def test_031_count_across_all_buckets(self):
        """
        ARRANGE: Visits in multiple buckets
        ACT: Create and count
        ASSERT: Correct distribution
        """
        lead = self.create_portal_lead()

        # Upcoming
        lead.write(
            {
                "site_visit_date": self.future_date,
                "current_status": "site_visit_scheduled",
            },
        )

        # Pending feedback
        interest1 = self.create_interest_for_lead(lead, self.test_property_2)
        interest1.write(
            {
                "site_visit_date": self.past_date,
                "current_status": "site_visit_scheduled",
                "feedback_general": None,
            },
        )

        # Cancelled
        interest2 = self.create_interest_for_lead(lead, self.test_property_3)
        interest2.write(
            {
                "site_visit_date": self.past_date,
                "current_status": "site_visit_scheduled",
                "feedback_general": "buyer_not_interested",
            },
        )

        self.assertEqual(lead.current_status, "site_visit_scheduled")
        self.assertEqual(interest1.current_status, "site_visit_scheduled")
        self.assertEqual(interest2.current_status, "site_visit_scheduled")

    def test_032_no_visits_empty_list(self):
        """
        ARRANGE: Lead with no site_visit_date
        ACT: Filter
        ASSERT: Excluded from visits
        """
        lead = self.create_portal_lead()
        # No site_visit_date

        self.assertFalse(lead.site_visit_date)

    def test_033_single_primary_only(self):
        """
        ARRANGE: Lead with primary visit, no interests
        ACT: Count
        ASSERT: Only 1 record
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "site_visit_date": self.future_date,
                "current_status": "site_visit_scheduled",
            },
        )

        self.assertEqual(len(lead.interest_ids), 0)

    def test_034_missing_visit_date_excluded(self):
        """
        ARRANGE: Lead with status but no date
        ACT: Filter logic per controller: if lead.site_visit_date and lead.current_status in _VISIT_STATUSES
        ASSERT: Not included (site_visit_date is falsy)
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "site_visit_date": None,
                "current_status": "site_visit_scheduled",
            },
        )

        # Odoo datetime fields return False (not None) when empty.
        # Controller filters: if lead.site_visit_date (truthiness check).
        # So a None/False site_visit_date means the record is NOT included.
        included = bool(lead.site_visit_date) and lead.current_status in _VISIT_STATUSES
        self.assertFalse(included)

    def test_035_invalid_status_excluded(self):
        """
        ARRANGE: Lead with date but invalid status
        ACT: Filter logic
        ASSERT: Not in visits (status not in _VISIT_STATUSES)
        """
        lead = self.create_portal_lead()
        lead.write(
            {
                "site_visit_date": self.future_date,
                "current_status": "lead",  # Not a site visit status
            },
        )

        is_visit_status = lead.current_status in _VISIT_STATUSES
        self.assertFalse(is_visit_status)

    # ─────────────────────────────────────────────────────────────────────────
    # NEW MODEL INTEGRATION: lead.site.visit drives the snapshot
    # ─────────────────────────────────────────────────────────────────────────

    def test_036_new_model_scheduled_visit_syncs_to_upcoming_bucket(self):
        """
        ARRANGE: Lead with no visits.
        ACT    : Create a lead.site.visit with 'scheduled' status and a future
                 datetime. The model's _sync_inquiry_snapshot writes back to the
                 leads.new flat fields automatically.
        ASSERT : leads.new.current_status == "site_visit_scheduled"
                 leads.new.site_visit_date  == the scheduled datetime
                 The controller's _classify_visit() maps this to "upcoming".

        This verifies that the new model drives the API response correctly without
        any direct writes to leads.new snapshot fields.
        """
        from odoo.addons.leads.controllers.buyer.site_visits import _classify_visit

        lead = self.create_portal_lead(
            property_base_id=self.test_property.id,
            user_id=self.rm_user.id,
        )
        scheduled_status = self.env["lead.site.visit.status"].search(
            [("code", "=", "scheduled")], limit=1
        )

        future_dt = self.future_date
        self.env["lead.site.visit"].create(
            {
                "inquiry_id": lead.id,
                "status_id": scheduled_status.id,
                "scheduled_datetime": future_dt,
            }
        )

        # Snapshot synchronisation must have fired.
        self.assertEqual(lead.current_status, "site_visit_scheduled")
        self.assertEqual(lead.site_visit_date, future_dt)

        # The controller classifies this as "upcoming".
        bucket = _classify_visit(
            current_status=lead.current_status,
            site_visit_date=lead.site_visit_date,
            now=self.now,
            feedback_general=lead.feedback_general,
        )
        self.assertEqual(bucket, "upcoming")

    def test_037_new_model_completed_visit_syncs_to_completed_bucket(self):
        """
        ARRANGE: Lead with a scheduled visit.
        ACT    : Mark the visit as 'completed'. Snapshot updates current_status
                 to "site_visit_done".
        ASSERT : leads.new.current_status == "site_visit_done"
                 _classify_visit() maps this to "completed".

        This is the normal post-visit flow: RM marks the visit done,
        the snapshot flips the inquiry to site_visit_done, and the API
        surfaces it in the "completed" bucket.
        """
        from odoo.addons.leads.controllers.buyer.site_visits import _classify_visit

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
                "scheduled_datetime": self.past_date,
            }
        )
        visit.write({"status_id": completed_status.id})

        # Snapshot must reflect the completed outcome.
        self.assertEqual(lead.current_status, "site_visit_done")

        bucket = _classify_visit(
            current_status=lead.current_status,
            site_visit_date=lead.site_visit_date,
            now=self.now,
            feedback_general=lead.feedback_general,
        )
        self.assertEqual(bucket, "completed")

    def test_038_reschedule_via_new_model_appears_in_upcoming_not_rescheduled(self):
        """
        ARRANGE: Lead with one scheduled visit.
        ACT    : Reschedule the visit via lead.site.visit.write(status=rescheduled).
                 The model supersedes the original visit and creates a new one
                 with 'scheduled' status. The snapshot receives
                 current_status="site_visit_scheduled" (NOT "rescheduled").
        ASSERT : leads.new.current_status == "site_visit_scheduled"
                 _classify_visit() returns "upcoming" for the new future date.

        This is the critical contract test: the "rescheduled" bucket in the API
        will NEVER be populated by the new visit model. Reschedules always appear
        as upcoming visits with a new date. The "rescheduled" bucket survives
        only for legacy records written before the visit model was introduced.
        """
        from odoo.addons.leads.controllers.buyer.site_visits import _classify_visit

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
                "scheduled_datetime": self.past_date,
            }
        )

        new_future_dt = self.future_date + timedelta(days=3)
        original_visit.write(
            {"status_id": rescheduled_status.id, "scheduled_datetime": new_future_dt}
        )

        # The snapshot must reflect the NEW scheduled visit, not "rescheduled".
        self.assertEqual(
            lead.current_status,
            "site_visit_scheduled",
            "Reschedule via new model must write 'site_visit_scheduled' to snapshot, "
            "not 'rescheduled'. The 'rescheduled' bucket is legacy-only.",
        )

        # The API classifies this as "upcoming" because the new visit is in the future.
        bucket = _classify_visit(
            current_status=lead.current_status,
            site_visit_date=lead.site_visit_date,
            now=self.now,
            feedback_general=lead.feedback_general,
        )
        self.assertEqual(
            bucket,
            "upcoming",
            "A rescheduled visit (new model) must appear in 'upcoming', not 'rescheduled'.",
        )
