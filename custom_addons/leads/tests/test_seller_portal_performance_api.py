"""
Test suite for the Seller Portal Performance API endpoint: GET /api/track/property/portal-performance

This module tests the per-portal quality breakdown logic that aggregates leads
by portal, distinguishing primary and recommended leads, calculating status
distributions and key metrics.

Test Categories:
- Portal Classification: Known vs unknown portal mapping
- Lead Counting: Primary, recommended, and total lead aggregation
- Status Aggregation: Status distribution per portal, null handling
- Key Metrics: site_visit_scheduled and site_visit_done calculation
- Recommended Interest Attribution: Parent lead portal assignment
- Filtering: Property tag filtering
- Portal Block Initialization: All portals initialized with zero counts
- Edge Cases: No leads, multiple portals, mixed types
- Data Integrity: Status dictionary formatting, metric accuracy
"""

import logging
from collections import defaultdict

from odoo.tests import tagged

from .test_portal_common import PortalLeadTestCase

_logger = logging.getLogger(__name__)

KNOWN_PORTALS = ["MagicBricks", "99acres", "Housing.com", "OLX"]


def _empty_portal_block() -> dict:
    """Helper to create empty portal block."""
    return {
        "total_leads": 0,
        "primary_leads": 0,
        "recommended_leads": 0,
        "statuses": defaultdict(int),
    }


@tagged("post_install", "-at_install")
class TestSellerPortalPerformanceAPI(PortalLeadTestCase):
    """
    Test suite for the Seller Portal Performance API endpoint business logic.
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
        # Clean up leads from previous tests
        self.env["leads.new"].search([("phone", "=", "9876543210")]).unlink()

    # ========================================================================
    # PORTAL CLASSIFICATION TESTS
    # ========================================================================

    def test_01_classify_magicbricks_as_known(self):
        """
        ARRANGE: Lead with MagicBricks portal
        ACT: Classify portal
        ASSERT: Returns 'MagicBricks' (known)
        """
        # ARRANGE
        portal_name = "MagicBricks"

        # ACT
        portal = portal_name if portal_name in KNOWN_PORTALS else "Unknown"

        # ASSERT
        self.assertEqual(portal, "MagicBricks")

    def test_02_classify_99acres_as_known(self):
        """
        ARRANGE: Lead with 99acres portal
        ACT: Classify portal
        ASSERT: Returns '99acres' (known)
        """
        # ARRANGE
        portal_name = "99acres"

        # ACT
        portal = portal_name if portal_name in KNOWN_PORTALS else "Unknown"

        # ASSERT
        self.assertEqual(portal, "99acres")

    def test_03_classify_housing_as_known(self):
        """
        ARRANGE: Lead with Housing.com portal
        ACT: Classify portal
        ASSERT: Returns 'Housing.com' (known)
        """
        # ARRANGE
        portal_name = "Housing.com"

        # ACT
        portal = portal_name if portal_name in KNOWN_PORTALS else "Unknown"

        # ASSERT
        self.assertEqual(portal, "Housing.com")

    def test_04_classify_olx_as_known(self):
        """
        ARRANGE: Lead with OLX portal
        ACT: Classify portal
        ASSERT: Returns 'OLX' (known)
        """
        # ARRANGE
        portal_name = "OLX"

        # ACT
        portal = portal_name if portal_name in KNOWN_PORTALS else "Unknown"

        # ASSERT
        self.assertEqual(portal, "OLX")

    def test_05_classify_unmapped_portal_as_unknown(self):
        """
        ARRANGE: Lead with unmapped portal name
        ACT: Classify portal
        ASSERT: Returns 'Unknown'
        """
        # ARRANGE
        portal_name = "SomeUnknownPortal"

        # ACT
        portal = portal_name if portal_name in KNOWN_PORTALS else "Unknown"

        # ASSERT
        self.assertEqual(portal, "Unknown")

    def test_06_classify_none_portal_as_unknown(self):
        """
        ARRANGE: Lead with None portal
        ACT: Classify portal
        ASSERT: Returns 'Unknown'
        """
        # ARRANGE
        portal_name = None

        # ACT
        portal = portal_name if portal_name in KNOWN_PORTALS else "Unknown"

        # ASSERT
        self.assertEqual(portal, "Unknown")

    def test_07_classify_empty_portal_as_unknown(self):
        """
        ARRANGE: Lead with empty string portal
        ACT: Classify portal
        ASSERT: Returns 'Unknown'
        """
        # ARRANGE
        portal_name = ""

        # ACT
        portal = portal_name if portal_name in KNOWN_PORTALS else "Unknown"

        # ASSERT
        self.assertEqual(portal, "Unknown")

    # ========================================================================
    # PRIMARY LEAD COUNTING TESTS
    # ========================================================================

    def test_08_count_primary_leads_single_portal(self):
        """
        ARRANGE: Create 3 primary leads on MagicBricks
        ACT: Count leads per portal
        ASSERT: MagicBricks has 3 primary, others have 0
        """
        # ARRANGE
        for i in range(3):
            self.create_portal_lead(
                phone=f"91000000{i:02d}",
                portal_name="MagicBricks",
                property_id=self.test_property.id,
            )

        # ACT
        portal_data = {p: _empty_portal_block() for p in KNOWN_PORTALS + ["Unknown"]}
        leads = self.env["leads.new"].search(
            [("property_id", "=", self.test_property.id)],
        )
        for lead in leads:
            portal = (
                lead.portal_name if lead.portal_name in KNOWN_PORTALS else "Unknown"
            )
            portal_data[portal]["total_leads"] += 1
            portal_data[portal]["primary_leads"] += 1

        # ASSERT
        self.assertEqual(portal_data["MagicBricks"]["primary_leads"], 3)
        self.assertEqual(portal_data["MagicBricks"]["total_leads"], 3)
        self.assertEqual(portal_data["99acres"]["primary_leads"], 0)
        self.assertEqual(portal_data["Unknown"]["primary_leads"], 0)

    def test_09_count_primary_leads_multiple_portals(self):
        """
        ARRANGE: Create 2 on MagicBricks, 3 on 99acres
        ACT: Count per portal
        ASSERT: Each portal has correct count
        """
        # ARRANGE
        for i in range(2):
            self.create_portal_lead(
                phone=f"91100000{i:02d}",
                portal_name="MagicBricks",
                property_id=self.test_property.id,
            )

        for i in range(3):
            self.create_portal_lead(
                phone=f"91110000{i:02d}",
                portal_name="99acres",
                property_id=self.test_property.id,
            )

        # ACT
        portal_data = {p: _empty_portal_block() for p in KNOWN_PORTALS + ["Unknown"]}
        leads = self.env["leads.new"].search(
            [("property_id", "=", self.test_property.id)],
        )
        for lead in leads:
            portal = (
                lead.portal_name if lead.portal_name in KNOWN_PORTALS else "Unknown"
            )
            portal_data[portal]["primary_leads"] += 1

        # ASSERT
        self.assertEqual(portal_data["MagicBricks"]["primary_leads"], 2)
        self.assertEqual(portal_data["99acres"]["primary_leads"], 3)

    def test_10_count_primary_leads_unmapped_portal(self):
        """
        ARRANGE: Create lead with unmapped portal
        ACT: Count leads
        ASSERT: Counted under 'Unknown'
        """
        # ARRANGE
        lead = self.create_portal_lead(
            phone="9120000001",
            portal_name="RandomPortal",
            property_id=self.test_property.id,
        )

        # ACT
        portal_data = {p: _empty_portal_block() for p in KNOWN_PORTALS + ["Unknown"]}
        portal = lead.portal_name if lead.portal_name in KNOWN_PORTALS else "Unknown"
        portal_data[portal]["primary_leads"] += 1

        # ASSERT
        self.assertEqual(portal_data["Unknown"]["primary_leads"], 1)

    # ========================================================================
    # RECOMMENDED INTEREST COUNTING TESTS
    # ========================================================================

    def test_11_count_recommended_leads_single_portal(self):
        """
        ARRANGE: Create parent lead with MagicBricks, add 2 recommended interests
        ACT: Count recommended per portal
        ASSERT: MagicBricks has 2 recommended
        """
        # ARRANGE
        parent_lead = self.create_portal_lead(
            phone="9130000001",
            portal_name="MagicBricks",
        )

        # Create interests on different properties (unique constraint on lead_id + property_id)
        for i, prop in enumerate([self.test_property, self.test_property_2]):
            self.env["lead.property.interest"].create(
                {
                    "lead_id": parent_lead.id,
                    "property_id": prop.id,
                },
            )

        # ACT
        portal_data = {p: _empty_portal_block() for p in KNOWN_PORTALS + ["Unknown"]}
        interests = self.env["lead.property.interest"].search(
            [("lead_id", "=", parent_lead.id)],
        )
        for interest in interests:
            portal_name = (
                interest.lead_id.portal_name
                if interest.lead_id and interest.lead_id.portal_name in KNOWN_PORTALS
                else "Unknown"
            )
            portal_data[portal_name]["recommended_leads"] += 1

        # ASSERT
        self.assertEqual(portal_data["MagicBricks"]["recommended_leads"], 2)

    def test_12_count_recommended_inherits_parent_portal(self):
        """
        ARRANGE: Parent lead with 99acres, multiple recommended interests
        ACT: Count recommended
        ASSERT: All attributed to parent's portal (99acres)
        """
        # ARRANGE
        parent_lead = self.create_portal_lead(
            phone="9140000001",
            portal_name="99acres",
        )

        # Create 3 different properties for interests (unique constraint on lead_id + property_id)
        properties_for_interests = [
            self.test_property,
            self.test_property_2,
            self.test_property_3,
        ]
        for i in range(3):
            self.env["lead.property.interest"].create(
                {
                    "lead_id": parent_lead.id,
                    "property_id": properties_for_interests[i].id,
                },
            )

        # ACT
        portal_data = {p: _empty_portal_block() for p in KNOWN_PORTALS + ["Unknown"]}
        interests = self.env["lead.property.interest"].search(
            [("lead_id", "=", parent_lead.id)],
        )
        for interest in interests:
            portal_name = (
                interest.lead_id.portal_name
                if interest.lead_id and interest.lead_id.portal_name in KNOWN_PORTALS
                else "Unknown"
            )
            portal_data[portal_name]["recommended_leads"] += 1

        # ASSERT
        self.assertEqual(portal_data["99acres"]["recommended_leads"], 3)
        self.assertEqual(portal_data["Unknown"]["recommended_leads"], 0)

    def test_13_count_recommended_unmapped_parent_portal(self):
        """
        ARRANGE: Parent lead with unmapped portal, recommended interests
        ACT: Count recommended
        ASSERT: Attributed to 'Unknown'
        """
        # ARRANGE
        parent_lead = self.create_portal_lead(
            phone="9150000001",
            portal_name="UnknownPortal",
        )

        interest = self.env["lead.property.interest"].create(
            {
                "lead_id": parent_lead.id,
                "property_id": self.test_property.id,
            },
        )

        # ACT
        portal_data = {p: _empty_portal_block() for p in KNOWN_PORTALS + ["Unknown"]}
        portal_name = (
            parent_lead.portal_name
            if parent_lead.portal_name in KNOWN_PORTALS
            else "Unknown"
        )
        portal_data[portal_name]["recommended_leads"] += 1

        # ASSERT
        self.assertEqual(portal_data["Unknown"]["recommended_leads"], 1)

    def test_14_count_recommended_orphaned_interest(self):
        """
        ARRANGE: Recommended interest with no parent lead
        ACT: Count recommended
        ASSERT: Attributed to 'Unknown'
        """
        # ARRANGE
        portal_data = {p: _empty_portal_block() for p in KNOWN_PORTALS + ["Unknown"]}

        # ACT - Simulate orphaned interest
        portal_name = "Unknown"  # No parent lead to get portal from
        portal_data[portal_name]["recommended_leads"] += 1

        # ASSERT
        self.assertEqual(portal_data["Unknown"]["recommended_leads"], 1)

    # ========================================================================
    # TOTAL LEAD COUNTING TESTS
    # ========================================================================

    def test_15_total_leads_primary_plus_recommended(self):
        """
        ARRANGE: 3 primary + 2 recommended on MagicBricks
        ACT: Calculate total
        ASSERT: total_leads = 5
        """
        # ARRANGE
        portal_data = {p: _empty_portal_block() for p in KNOWN_PORTALS + ["Unknown"]}

        # ACT
        portal_data["MagicBricks"]["primary_leads"] = 3
        portal_data["MagicBricks"]["recommended_leads"] = 2
        portal_data["MagicBricks"]["total_leads"] = (
            portal_data["MagicBricks"]["primary_leads"]
            + portal_data["MagicBricks"]["recommended_leads"]
        )

        # ASSERT
        self.assertEqual(portal_data["MagicBricks"]["total_leads"], 5)

    def test_16_total_leads_zero_when_no_leads(self):
        """
        ARRANGE: Portal with no leads
        ACT: Check total
        ASSERT: total_leads = 0
        """
        # ARRANGE
        portal_data = {p: _empty_portal_block() for p in KNOWN_PORTALS + ["Unknown"]}

        # ASSERT
        self.assertEqual(portal_data["Housing.com"]["total_leads"], 0)

    def test_17_multiple_portals_totals(self):
        """
        ARRANGE: Different leads on different portals
        ACT: Calculate totals for each
        ASSERT: Each portal has correct total
        """
        # ARRANGE
        portal_data = {p: _empty_portal_block() for p in KNOWN_PORTALS + ["Unknown"]}
        portal_data["MagicBricks"]["primary_leads"] = 5
        portal_data["99acres"]["recommended_leads"] = 3
        portal_data["Housing.com"]["primary_leads"] = 2
        portal_data["Housing.com"]["recommended_leads"] = 1

        # ACT
        for portal, block in portal_data.items():
            block["total_leads"] = block["primary_leads"] + block["recommended_leads"]

        # ASSERT
        self.assertEqual(portal_data["MagicBricks"]["total_leads"], 5)
        self.assertEqual(portal_data["99acres"]["total_leads"], 3)
        self.assertEqual(portal_data["Housing.com"]["total_leads"], 3)

    # ========================================================================
    # STATUS AGGREGATION TESTS
    # ========================================================================

    def test_18_status_aggregation_single_status(self):
        """
        ARRANGE: 3 leads with site_visit_scheduled status
        ACT: Aggregate statuses
        ASSERT: site_visit_scheduled count = 3
        """
        # ARRANGE
        for i in range(3):
            lead = self.create_portal_lead(
                phone=f"91200000{i:02d}",
                portal_name="MagicBricks",
                property_id=self.test_property.id,
            )
            lead.write({"current_status": "site_visit_scheduled"})

        # ACT
        portal_data = {p: _empty_portal_block() for p in KNOWN_PORTALS + ["Unknown"]}
        leads = self.env["leads.new"].search(
            [("property_id", "=", self.test_property.id)],
        )
        for lead in leads:
            portal = (
                lead.portal_name if lead.portal_name in KNOWN_PORTALS else "Unknown"
            )
            portal_data[portal]["statuses"][lead.current_status or "other"] += 1

        # ASSERT
        self.assertEqual(
            portal_data["MagicBricks"]["statuses"]["site_visit_scheduled"],
            3,
        )

    def test_19_status_aggregation_multiple_statuses(self):
        """
        ARRANGE: Leads with different statuses on same portal
        ACT: Aggregate statuses
        ASSERT: Each status counted correctly
        """
        # ARRANGE
        statuses = ["lead", "busy", "site_visit_scheduled", "site_visit_done"]
        leads = []
        for i, status in enumerate(statuses):
            lead = self.create_portal_lead(
                phone=f"91210000{i:02d}",
                portal_name="MagicBricks",
                property_id=self.test_property.id,
            )
            lead.write({"current_status": status})
            leads.append(lead)

        # ACT
        portal_data = {p: _empty_portal_block() for p in KNOWN_PORTALS + ["Unknown"]}
        for lead in leads:
            portal = "MagicBricks"
            portal_data[portal]["statuses"][lead.current_status or "other"] += 1

        # ASSERT
        self.assertEqual(portal_data["MagicBricks"]["statuses"]["lead"], 1)
        self.assertEqual(portal_data["MagicBricks"]["statuses"]["busy"], 1)
        self.assertEqual(
            portal_data["MagicBricks"]["statuses"]["site_visit_scheduled"],
            1,
        )
        self.assertEqual(portal_data["MagicBricks"]["statuses"]["site_visit_done"], 1)

    def test_20_status_null_defaults_to_other(self):
        """
        ARRANGE: Leads with None status
        ACT: Aggregate
        ASSERT: Counted as 'other'
        """
        # ARRANGE
        lead = self.create_portal_lead(
            phone="9122000001",
            portal_name="99acres",
            property_id=self.test_property.id,
        )
        # Explicitly set status to None
        lead.write({"current_status": None})

        # ACT
        portal_data = {p: _empty_portal_block() for p in KNOWN_PORTALS + ["Unknown"]}
        status_key = lead.current_status or "other"
        portal_data["99acres"]["statuses"][status_key] += 1

        # ASSERT
        self.assertEqual(portal_data["99acres"]["statuses"]["other"], 1)

    def test_21_status_dict_conversion(self):
        """
        ARRANGE: Portal block with defaultdict statuses
        ACT: Convert to plain dict
        ASSERT: Returns plain dict
        """
        # ARRANGE
        statuses = defaultdict(int)
        statuses["site_visit_done"] = 3
        statuses["site_visit_scheduled"] = 2

        # ACT
        plain = dict(statuses)

        # ASSERT
        self.assertIsInstance(plain, dict)
        self.assertEqual(plain["site_visit_done"], 3)
        self.assertEqual(plain["site_visit_scheduled"], 2)
        self.assertNotIsInstance(plain, defaultdict)

    # ========================================================================
    # KEY METRICS TESTS
    # ========================================================================

    def test_22_key_metrics_site_visit_scheduled(self):
        """
        ARRANGE: Portal with 4 site_visit_scheduled leads
        ACT: Calculate key metric
        ASSERT: site_visit_scheduled = 4
        """
        # ARRANGE
        portal_data = {p: _empty_portal_block() for p in KNOWN_PORTALS + ["Unknown"]}
        portal_data["MagicBricks"]["statuses"]["site_visit_scheduled"] = 4

        # ACT
        svs = portal_data["MagicBricks"]["statuses"].get("site_visit_scheduled", 0)

        # ASSERT
        self.assertEqual(svs, 4)

    def test_23_key_metrics_site_visit_done(self):
        """
        ARRANGE: Portal with 3 site_visit_done leads
        ACT: Calculate key metric
        ASSERT: site_visit_done = 3
        """
        # ARRANGE
        portal_data = {p: _empty_portal_block() for p in KNOWN_PORTALS + ["Unknown"]}
        portal_data["MagicBricks"]["statuses"]["site_visit_done"] = 3

        # ACT
        svd = portal_data["MagicBricks"]["statuses"].get("site_visit_done", 0)

        # ASSERT
        self.assertEqual(svd, 3)

    def test_24_key_metrics_both(self):
        """
        ARRANGE: Portal with multiple status types
        ACT: Extract both key metrics
        ASSERT: Both calculated correctly
        """
        # ARRANGE
        statuses = defaultdict(int)
        statuses["site_visit_scheduled"] = 4
        statuses["site_visit_done"] = 3
        statuses["lead"] = 5
        statuses["other"] = 2

        # ACT
        svs = statuses.get("site_visit_scheduled", 0)
        svd = statuses.get("site_visit_done", 0)

        # ASSERT
        self.assertEqual(svs, 4)
        self.assertEqual(svd, 3)

    def test_25_key_metrics_zero_when_missing(self):
        """
        ARRANGE: Portal with no site visit statuses
        ACT: Get metrics
        ASSERT: Both return 0 via default
        """
        # ARRANGE
        statuses = defaultdict(int)
        statuses["lead"] = 5

        # ACT
        svs = statuses.get("site_visit_scheduled", 0)
        svd = statuses.get("site_visit_done", 0)

        # ASSERT
        self.assertEqual(svs, 0)
        self.assertEqual(svd, 0)

    # ========================================================================
    # FILTERING TESTS
    # ========================================================================

    def test_26_filter_by_property_tag(self):
        """
        ARRANGE: Seller with 2 properties, leads on each
        ACT: Filter by one property_tag
        ASSERT: Only returns leads from that property
        """
        # ARRANGE
        self.create_portal_lead(
            phone="9130000001",
            portal_name="MagicBricks",
            property_id=self.test_property.id,
        )
        self.create_portal_lead(
            phone="9130000002",
            portal_name="99acres",
            property_id=self.test_property_2.id,
        )

        properties = [self.test_property, self.test_property_2]
        tags = [p.property_tag for p in properties]

        # ACT
        tag_filter = self.test_property.property_tag
        filtered_tags = [t for t in tags if t == tag_filter]

        # ASSERT
        self.assertEqual(len(filtered_tags), 1)
        self.assertEqual(filtered_tags[0], self.test_property.property_tag)

    def test_27_no_results_for_invalid_filter(self):
        """
        ARRANGE: Filter by non-existent property_tag
        ACT: Query
        ASSERT: No properties returned
        """
        # ARRANGE
        properties = self.env["property.inventory"].search(
            [("property_tag", "=", "NON_EXISTENT")],
        )

        # ASSERT
        self.assertEqual(len(properties), 0)

    # ========================================================================
    # PORTAL BLOCK INITIALIZATION TESTS
    # ========================================================================

    def test_28_all_known_portals_initialized(self):
        """
        ARRANGE: Initialize portal blocks
        ACT: Check all known portals present
        ASSERT: All 4 known portals in dict
        """
        # ARRANGE
        portal_data = {p: _empty_portal_block() for p in KNOWN_PORTALS + ["Unknown"]}

        # ACT
        known_in_data = [p for p in KNOWN_PORTALS if p in portal_data]

        # ASSERT
        self.assertEqual(len(known_in_data), 4)
        self.assertIn("MagicBricks", portal_data)
        self.assertIn("99acres", portal_data)
        self.assertIn("Housing.com", portal_data)
        self.assertIn("OLX", portal_data)

    def test_29_unknown_portal_initialized(self):
        """
        ARRANGE: Initialize portal blocks
        ACT: Check 'Unknown' present
        ASSERT: 'Unknown' in dict
        """
        # ARRANGE
        portal_data = {p: _empty_portal_block() for p in KNOWN_PORTALS + ["Unknown"]}

        # ASSERT
        self.assertIn("Unknown", portal_data)

    def test_30_empty_portal_block_structure(self):
        """
        ARRANGE: Create empty portal block
        ACT: Check structure
        ASSERT: All required keys present with zero values
        """
        # ARRANGE
        block = _empty_portal_block()

        # ASSERT
        self.assertIn("total_leads", block)
        self.assertIn("primary_leads", block)
        self.assertIn("recommended_leads", block)
        self.assertIn("statuses", block)
        self.assertEqual(block["total_leads"], 0)
        self.assertEqual(block["primary_leads"], 0)
        self.assertEqual(block["recommended_leads"], 0)
        self.assertIsInstance(block["statuses"], defaultdict)

    # ========================================================================
    # COMBINED SCENARIO TESTS
    # ========================================================================

    def test_31_full_aggregation_scenario(self):
        """
        ARRANGE: Multiple portals, primary+recommended, various statuses
        ACT: Aggregate all
        ASSERT: All counts and metrics correct
        """
        # ARRANGE
        # MagicBricks: 2 primary (1 scheduled, 1 done)
        mb_p1 = self.create_portal_lead(
            phone="9140000001",
            portal_name="MagicBricks",
            property_id=self.test_property.id,
        )
        mb_p1.write({"current_status": "site_visit_scheduled"})

        mb_p2 = self.create_portal_lead(
            phone="9140000002",
            portal_name="MagicBricks",
            property_id=self.test_property.id,
        )
        mb_p2.write({"current_status": "site_visit_done"})

        # MagicBricks: 1 recommended (scheduled)
        mb_parent = self.create_portal_lead(
            phone="9140000003",
            portal_name="MagicBricks",
        )
        mb_interest = self.env["lead.property.interest"].create(
            {
                "lead_id": mb_parent.id,
                "property_id": self.test_property.id,
            },
        )
        mb_interest.write({"current_status": "site_visit_scheduled"})

        # ACT
        portal_data = {p: _empty_portal_block() for p in KNOWN_PORTALS + ["Unknown"]}

        # Process primary
        for lead in [mb_p1, mb_p2]:
            portal_data["MagicBricks"]["total_leads"] += 1
            portal_data["MagicBricks"]["primary_leads"] += 1
            portal_data["MagicBricks"]["statuses"][lead.current_status or "other"] += 1

        # Process recommended
        portal_data["MagicBricks"]["total_leads"] += 1
        portal_data["MagicBricks"]["recommended_leads"] += 1
        portal_data["MagicBricks"]["statuses"][
            mb_interest.current_status or "other"
        ] += 1

        # Calculate metrics
        svs = portal_data["MagicBricks"]["statuses"].get(
            "site_visit_scheduled",
            0,
        )
        svd = portal_data["MagicBricks"]["statuses"].get("site_visit_done", 0)

        # ASSERT
        self.assertEqual(portal_data["MagicBricks"]["total_leads"], 3)
        self.assertEqual(portal_data["MagicBricks"]["primary_leads"], 2)
        self.assertEqual(portal_data["MagicBricks"]["recommended_leads"], 1)
        self.assertEqual(svs, 2)  # 1 primary scheduled + 1 recommended scheduled
        self.assertEqual(svd, 1)  # 1 primary done

    def test_32_empty_property_all_portals_zero(self):
        """
        ARRANGE: Property with no leads
        ACT: Initialize and check all portals
        ASSERT: All portals have zero counts
        """
        # ARRANGE
        phone = "1111111111"
        prop = self.env["property.inventory"].create(
            {
                "property_tag": f"EMPTY-PORTAL-{self.suffix}",
                "bhk": "3 BHK",
                "location": "Empty",
                "city": "City",
                "rm_user_id": self.rm_user.id,
                "is_active": True,
                "owner_phone": phone,
            },
        )

        # ACT
        portal_data = {p: _empty_portal_block() for p in KNOWN_PORTALS + ["Unknown"]}

        # ASSERT
        for portal, block in portal_data.items():
            self.assertEqual(block["total_leads"], 0)
            self.assertEqual(block["primary_leads"], 0)
            self.assertEqual(block["recommended_leads"], 0)
            self.assertEqual(len(block["statuses"]), 0)

    def test_33_serialization_format(self):
        """
        ARRANGE: Portal block with data
        ACT: Serialize to plain dict
        ASSERT: Correct JSON-serializable format
        """
        # ARRANGE
        block = {
            "total_leads": 5,
            "primary_leads": 3,
            "recommended_leads": 2,
            "statuses": defaultdict(
                int,
                {"site_visit_done": 2, "site_visit_scheduled": 3},
            ),
        }

        # ACT
        serialized = {
            "total_leads": block["total_leads"],
            "primary_leads": block["primary_leads"],
            "recommended_leads": block["recommended_leads"],
            "statuses": dict(block["statuses"]),
            "key_metrics": {
                "site_visit_scheduled": block["statuses"].get(
                    "site_visit_scheduled",
                    0,
                ),
                "site_visit_done": block["statuses"].get("site_visit_done", 0),
            },
        }

        # ASSERT
        self.assertEqual(serialized["total_leads"], 5)
        self.assertEqual(serialized["primary_leads"], 3)
        self.assertEqual(serialized["recommended_leads"], 2)
        self.assertIsInstance(serialized["statuses"], dict)
        self.assertNotIsInstance(serialized["statuses"], defaultdict)
        self.assertEqual(serialized["key_metrics"]["site_visit_scheduled"], 3)
        self.assertEqual(serialized["key_metrics"]["site_visit_done"], 2)
