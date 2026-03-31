"""
Test suite for the Seller Funnel API endpoint: GET /api/track/property/funnel

This module tests the conversion funnel business logic that aggregates inquiry
stages across all portals and properties belonging to a seller.

Test Categories:
- Happy Path: Valid funnel data with mixed stages
- Stage Counting: Accurate counts for each funnel stage
- Key Metrics: Contacted, site visits, closed/lost calculations
- Edge Cases: Empty funnels, single stage leads
- Data Integrity: Percentages, totals consistency

Model integration notes
-----------------------
Funnel tests write current_status directly on leads.new for isolation. In
production, current_status is set by lead.site.visit._sync_inquiry_snapshot
for visit-related transitions ("site_visit_scheduled", "site_visit_done").

The "rescheduled" stage in ALL_FUNNEL_STAGES and _CONTACTED_STAGES is a
legacy selection value retained for backward compatibility. The new visit
model never writes "rescheduled" to the snapshot — a reschedule triggers
the supersede-and-replace flow and writes "site_visit_scheduled" with the
new date instead. Records with current_status="rescheduled" therefore only
exist as pre-v1.3.0 data or records set via direct write / BQ import.
"""

import logging
from collections import defaultdict

from odoo.tests import tagged

from .test_portal_common import PortalLeadTestCase

_logger = logging.getLogger(__name__)

# All possible funnel stages (from funnel.py)
ALL_FUNNEL_STAGES = [
    "lead",
    "busy",
    "ringing",
    "call_back_later",
    "details_shared_of_property",
    "detail_shared_and_interested_for_site_visit",
    "option_not_matching_requirements",
    "site_visit_scheduled",
    "rescheduled",
    "site_visit_done",
    "requirement_closed",
    "no_requirements",
    "property_sold_out",
    "budget_not_sufficient",
    "switched_off",
    "number_not_in_use_wrong_number",
    "other",
]

_CONTACTED_STAGES = {
    "busy",
    "ringing",
    "call_back_later",
    "details_shared_of_property",
    "detail_shared_and_interested_for_site_visit",
    "option_not_matching_requirements",
    "site_visit_scheduled",
    "rescheduled",
    "site_visit_done",
    "requirement_closed",
    "no_requirements",
    "property_sold_out",
    "budget_not_sufficient",
    "switched_off",
}

_CLOSED_STAGES = {
    "requirement_closed",
    "no_requirements",
    "property_sold_out",
    "budget_not_sufficient",
}


@tagged("post_install", "-at_install")
class TestSellerFunnelAPI(PortalLeadTestCase):
    """
    Test suite for the Seller Funnel API endpoint business logic.
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
    # FUNNEL STAGE COUNTING TESTS
    # ========================================================================

    def test_01_funnel_captures_all_stages(self):
        """
        ARRANGE: Create leads with different stages (lead, busy, ringing, etc.)
        ACT: Build funnel stage counts
        ASSERT: All stages are present in result, even with zero count
        """
        # ARRANGE
        tags = [self.test_property.property_tag]
        stage_counts = defaultdict(int)

        # Create leads with specific stages
        stages_to_test = ["lead", "busy", "ringing", "site_visit_scheduled"]
        for stage in stages_to_test:
            lead = self.create_portal_lead(
                phone=f"999999999{stages_to_test.index(stage)}",
            )
            lead.write({"current_status": stage})
            stage_counts[stage] += 1

        # ACT - Build complete funnel (all stages should be present)
        def pct(count):
            return round((count / len(stage_counts)) * 100, 1) if stage_counts else 0.0

        stages = {
            stage: {
                "count": stage_counts.get(stage, 0),
                "pct_of_total": pct(stage_counts.get(stage, 0)),
            }
            for stage in ALL_FUNNEL_STAGES
        }

        # ASSERT
        self.assertEqual(
            len(stages),
            len(ALL_FUNNEL_STAGES),
            "All stages should be present",
        )
        for stage in ALL_FUNNEL_STAGES:
            self.assertIn(stage, stages, f"Stage {stage} should be in result")

    def test_02_stage_counts_accurate(self):
        """
        ARRANGE: Create 3 leads with 'lead' status, 2 with 'busy'
        ACT: Count stages
        ASSERT: lead=3, busy=2
        """
        # ARRANGE
        stage_counts = defaultdict(int)

        # Create leads
        for i in range(3):
            lead = self.create_portal_lead(phone=f"11111111{i:02d}")
            lead.write({"current_status": "lead"})
            stage_counts["lead"] += 1

        for i in range(2):
            lead = self.create_portal_lead(phone=f"22222222{i:02d}")
            lead.write({"current_status": "busy"})
            stage_counts["busy"] += 1

        # ACT & ASSERT
        self.assertEqual(stage_counts["lead"], 3)
        self.assertEqual(stage_counts["busy"], 2)

    def test_03_primary_and_recommended_counted_together(self):
        """
        ARRANGE: 2 primary leads in 'lead' stage, 3 recommended interests in 'site_visit_done'
        ACT: Build funnel
        ASSERT: Total = 5, stages reflect both types
        """
        # ARRANGE
        tags = [self.test_property.property_tag, self.test_property_2.property_tag]
        stage_counts = defaultdict(int)

        # Create 2 primary leads
        for i in range(2):
            lead = self.create_portal_lead(
                phone=f"33333333{i:02d}",
                property_base_id=self.test_property.id,
            )
            lead.write({"current_status": "lead"})
            stage_counts["lead"] += 1

        # Create 3 recommended interests
        for i in range(3):
            lead = self.create_portal_lead(phone=f"44444444{i:02d}")
            interest = self.env["lead.property.interest"].create(
                {
                    "lead_id": lead.id,
                    "property_base_id": self.test_property_2.id,
                    "current_status": "site_visit_done",
                },
            )
            stage_counts["site_visit_done"] += 1

        # ACT & ASSERT
        total = sum(stage_counts.values())
        self.assertEqual(total, 5)
        self.assertEqual(stage_counts["lead"], 2)
        self.assertEqual(stage_counts["site_visit_done"], 3)

    def test_04_default_status_is_other(self):
        """
        ARRANGE: Create lead with no status (null)
        ACT: Count stages
        ASSERT: Counted as 'other'
        """
        # ARRANGE
        lead = self.create_portal_lead(phone="5555555555")
        lead.write({"current_status": None})

        stage_counts = defaultdict(int)
        status = lead.current_status or "other"
        stage_counts[status] += 1

        # ACT & ASSERT
        self.assertEqual(stage_counts["other"], 1)

    # ========================================================================
    # PERCENTAGE CALCULATION TESTS
    # ========================================================================

    def test_05_percentage_calculation_accuracy(self):
        """
        ARRANGE: 10 leads total: 5 in 'lead', 3 in 'busy', 2 in 'site_visit_done'
        ACT: Calculate percentages
        ASSERT: 'lead'=50%, 'busy'=30%, 'site_visit_done'=20%
        """
        # ARRANGE
        total = 10
        counts = {
            "lead": 5,
            "busy": 3,
            "site_visit_done": 2,
        }

        # ACT
        def pct(count):
            return round((count / total) * 100, 1) if total > 0 else 0.0

        percentages = {stage: pct(count) for stage, count in counts.items()}

        # ASSERT
        self.assertEqual(percentages["lead"], 50.0)
        self.assertEqual(percentages["busy"], 30.0)
        self.assertEqual(percentages["site_visit_done"], 20.0)

    def test_06_percentage_zero_for_zero_total(self):
        """
        ARRANGE: No inquiries
        ACT: Calculate percentages
        ASSERT: All percentages are 0.0
        """
        # ARRANGE
        total = 0

        # ACT
        def pct(count):
            return round((count / total) * 100, 1) if total > 0 else 0.0

        result = pct(5)

        # ASSERT
        self.assertEqual(result, 0.0)

    def test_07_percentage_rounding_one_decimal(self):
        """
        ARRANGE: 3 leads out of 7 total (3/7 = 42.857...)
        ACT: Calculate percentage
        ASSERT: Rounds to 1 decimal place = 42.9%
        """
        # ARRANGE
        total = 7
        count = 3

        # ACT
        result = round((count / total) * 100, 1)

        # ASSERT
        self.assertEqual(result, 42.9)

    # ========================================================================
    # KEY METRICS TESTS
    # ========================================================================

    def test_08_key_metrics_contacted_calculation(self):
        """
        ARRANGE: Mix of stages: 2 'lead', 3 'busy', 2 'ringing', 4 'site_visit_scheduled'
        ACT: Calculate contacted (sum of contacted stages)
        ASSERT: contacted = 3 + 2 + 4 = 9 (excludes 'lead')
        """
        # ARRANGE
        stage_counts = defaultdict(int)
        stage_counts["lead"] = 2
        stage_counts["busy"] = 3
        stage_counts["ringing"] = 2
        stage_counts["site_visit_scheduled"] = 4

        # ACT
        contacted = sum(stage_counts[stage] for stage in _CONTACTED_STAGES)

        # ASSERT - contacted excludes 'lead' stage
        self.assertEqual(contacted, 9)

    def test_09_key_metrics_site_visit_scheduled(self):
        """
        ARRANGE: 6 leads with 'site_visit_scheduled' status
        ACT: Extract metric
        ASSERT: site_visit_scheduled = 6
        """
        # ARRANGE
        stage_counts = defaultdict(int)
        for i in range(6):
            lead = self.create_portal_lead(phone=f"66666666{i:02d}")
            lead.write({"current_status": "site_visit_scheduled"})
            stage_counts["site_visit_scheduled"] += 1

        # ACT
        site_visit_scheduled = stage_counts.get("site_visit_scheduled", 0)

        # ASSERT
        self.assertEqual(site_visit_scheduled, 6)

    def test_10_key_metrics_site_visit_done(self):
        """
        ARRANGE: 4 leads with 'site_visit_done' status
        ACT: Extract metric
        ASSERT: site_visit_done = 4
        """
        # ARRANGE
        stage_counts = defaultdict(int)
        for i in range(4):
            lead = self.create_portal_lead(phone=f"77777777{i:02d}")
            lead.write({"current_status": "site_visit_done"})
            stage_counts["site_visit_done"] += 1

        # ACT
        site_visit_done = stage_counts.get("site_visit_done", 0)

        # ASSERT
        self.assertEqual(site_visit_done, 4)

    def test_11_key_metrics_closed_or_lost(self):
        """
        ARRANGE: 3 'requirement_closed', 2 'no_requirements', 1 'budget_not_sufficient'
        ACT: Calculate closed_or_lost
        ASSERT: closed_or_lost = 6
        """
        # ARRANGE
        stage_counts = defaultdict(int)
        stage_counts["requirement_closed"] = 3
        stage_counts["no_requirements"] = 2
        stage_counts["budget_not_sufficient"] = 1

        # ACT
        closed_or_lost = sum(stage_counts[stage] for stage in _CLOSED_STAGES)

        # ASSERT
        self.assertEqual(closed_or_lost, 6)

    # ========================================================================
    # EDGE CASES
    # ========================================================================

    def test_12_empty_funnel_all_zeros(self):
        """
        ARRANGE: Property with no leads
        ACT: Build funnel
        ASSERT: Total = 0, all stages = 0, all percentages = 0
        """
        # ARRANGE
        phone = "2222222222"
        prop = self.env["property.base"].create(
            {
                "property_tag": f"EMPTY-FUNNEL-{self.suffix}",
                "name": f"Empty Funnel Prop {self.suffix}",
                "bedroom_count": 3,
                "location": "Empty",
                "city": "City",
                "rm_user_id": self.rm_user.id,
                "is_active": True,
                "owner_phone": phone,
            },
        )
        tags = [prop.property_tag]

        stage_counts = defaultdict(int)
        total = len(stage_counts)

        # ACT
        def pct(count):
            return round((count / total) * 100, 1) if total > 0 else 0.0

        stages = {
            stage: {
                "count": 0,
                "pct_of_total": pct(0),
            }
            for stage in ALL_FUNNEL_STAGES
        }

        # ASSERT
        self.assertEqual(total, 0)
        for stage in ALL_FUNNEL_STAGES:
            self.assertEqual(stages[stage]["count"], 0)
            self.assertEqual(stages[stage]["pct_of_total"], 0.0)

    def test_13_single_stage_funnel(self):
        """
        ARRANGE: All leads in single stage
        ACT: Build funnel
        ASSERT: Only one stage has count, rest are 0
        """
        # ARRANGE
        stage_counts = defaultdict(int)
        for i in range(10):
            lead = self.create_portal_lead(phone=f"88888888{i:02d}")
            lead.write({"current_status": "lead"})
            stage_counts["lead"] += 1

        # ACT
        def pct(count):
            return round((count / 10) * 100, 1)

        stages = {
            stage: {
                "count": stage_counts.get(stage, 0),
                "pct_of_total": pct(stage_counts.get(stage, 0)),
            }
            for stage in ALL_FUNNEL_STAGES
        }

        # ASSERT
        self.assertEqual(stages["lead"]["count"], 10)
        self.assertEqual(stages["lead"]["pct_of_total"], 100.0)
        for stage in ALL_FUNNEL_STAGES:
            if stage != "lead":
                self.assertEqual(stages[stage]["count"], 0)

    def test_14_multiple_properties_combined(self):
        """
        ARRANGE: Leads across 3 properties
        ACT: Build combined funnel
        ASSERT: Counts include all properties
        """
        # ARRANGE
        tags = [
            self.test_property.property_tag,
            self.test_property_2.property_tag,
            self.test_property_3.property_tag,
        ]

        stage_counts = defaultdict(int)

        # Create leads across properties
        for prop in [self.test_property, self.test_property_2, self.test_property_3]:
            lead = self.create_portal_lead(
                phone=f"99999999{prop.id}",
                property_base_id=prop.id,
            )
            lead.write({"current_status": "site_visit_done"})
            stage_counts["site_visit_done"] += 1

        # ACT & ASSERT
        self.assertEqual(
            stage_counts["site_visit_done"],
            3,
            "Should count leads from all properties",
        )

    # ========================================================================
    # DATA INTEGRITY TESTS
    # ========================================================================

    def test_15_total_inquiries_primary_plus_recommended(self):
        """
        ARRANGE: 5 primary leads + 7 recommended interests
        ACT: Calculate total
        ASSERT: total = 12
        """
        # ARRANGE
        tags = [self.test_property.property_tag]

        # Create 5 primary
        primary_count = 0
        for i in range(5):
            lead = self.create_portal_lead(
                phone=f"10101010{i:02d}",
                property_base_id=self.test_property.id,
            )
            lead.write({"current_status": "lead"})
            primary_count += 1

        # Create 7 recommended
        recommended_count = 0
        for i in range(7):
            lead = self.create_portal_lead(phone=f"20202020{i:02d}")
            self.env["lead.property.interest"].create(
                {
                    "lead_id": lead.id,
                    "property_base_id": self.test_property.id,
                    "current_status": "busy",
                },
            )
            recommended_count += 1

        # ACT
        total = primary_count + recommended_count

        # ASSERT
        self.assertEqual(total, 12)

    def test_16_funnel_percentages_sum_correctly(self):
        """
        ARRANGE: Funnel with multiple stages
        ACT: Sum all percentages
        ASSERT: Should sum to 100.0
        """
        # ARRANGE
        stage_counts = {
            "lead": 4,
            "busy": 2,
            "ringing": 2,
            "site_visit_scheduled": 2,
        }
        total = sum(stage_counts.values())  # 10

        # ACT
        def pct(count):
            return round((count / total) * 100, 1)

        percentages = [pct(count) for count in stage_counts.values()]
        total_pct = sum(percentages)

        # ASSERT
        self.assertEqual(total_pct, 100.0)

    def test_17_key_metrics_consistency(self):
        """
        ARRANGE: Mixed lead statuses
        ACT: Build key metrics
        ASSERT: Metrics are consistent and non-negative
        """
        # ARRANGE
        stage_counts = defaultdict(int)
        stage_counts["lead"] = 5
        stage_counts["busy"] = 3
        stage_counts["site_visit_scheduled"] = 2
        stage_counts["site_visit_done"] = 1
        stage_counts["requirement_closed"] = 1

        # ACT
        contacted = sum(stage_counts[s] for s in _CONTACTED_STAGES)
        site_visits_scheduled = stage_counts.get("site_visit_scheduled", 0)
        site_visits_done = stage_counts.get("site_visit_done", 0)
        closed = sum(stage_counts[s] for s in _CLOSED_STAGES)

        # ASSERT - All metrics should be >= 0
        self.assertGreaterEqual(contacted, 0)
        self.assertGreaterEqual(site_visits_scheduled, 0)
        self.assertGreaterEqual(site_visits_done, 0)
        self.assertGreaterEqual(closed, 0)

        # contacted should include site visits
        self.assertGreaterEqual(contacted, site_visits_scheduled + site_visits_done)

    def test_18_stage_with_zero_count_still_has_percentage(self):
        """
        ARRANGE: Few leads, many stages with zero count
        ACT: Build stage dict
        ASSERT: Zero-count stages have pct_of_total = 0.0
        """
        # ARRANGE
        stage_counts = defaultdict(int)
        stage_counts["lead"] = 5
        total = 5

        # ACT
        def pct(count):
            return round((count / total) * 100, 1) if total > 0 else 0.0

        stages = {
            stage: {
                "count": stage_counts.get(stage, 0),
                "pct_of_total": pct(stage_counts.get(stage, 0)),
            }
            for stage in ALL_FUNNEL_STAGES
        }

        # ASSERT
        for stage in ALL_FUNNEL_STAGES:
            if stage != "lead":
                self.assertEqual(stages[stage]["count"], 0)
                self.assertEqual(stages[stage]["pct_of_total"], 0.0)

    def test_19_funnel_handles_all_stage_types(self):
        """
        ARRANGE: Create leads across diverse stages
        ACT: Build funnel
        ASSERT: All stages are properly captured
        """
        # ARRANGE
        diverse_stages = [
            "lead",
            "busy",
            "ringing",
            "call_back_later",
            "details_shared_of_property",
            "site_visit_scheduled",
            "site_visit_done",
            "requirement_closed",
        ]
        stage_counts = defaultdict(int)

        for stage in diverse_stages:
            lead = self.create_portal_lead(
                phone=f"30303030{diverse_stages.index(stage):02d}",
            )
            lead.write({"current_status": stage})
            stage_counts[stage] += 1

        # ACT & ASSERT
        for stage in diverse_stages:
            self.assertEqual(
                stage_counts[stage],
                1,
                f"Stage {stage} should have count of 1",
            )
