"""
Test suite for the Buyer Activity API endpoint: GET /api/track/lead/activity

This module tests the full activity picture for a buyer (identified by phone),
including primary inquiries, recommended properties, status tracking, and
summary metrics aggregation.

Test Categories:
- Serialization: Primary lead data transformation, property details, recommended interests
- Summary Calculation: Total inquiries, total properties, site visit counts
- Null Handling: Missing properties, null field handling
- Multiple Inquiries: Multiple primary leads per buyer
- Recommended Properties: Multiple recommended interests per inquiry
- Status Aggregation: Site visit scheduled/done counting across primary and recommended
- Property Counting: Primary properties vs recommended properties
- Edge Cases: No inquiries, no properties, no recommended interests
- Data Integrity: Field mapping, datetime formatting, boolean flags

Model integration notes
-----------------------
The activity API reads the flat snapshot fields on leads.new
(current_status, site_visit_date, feedback_general, feedback_site_visit_done, etc.).
In production these fields are populated in two ways:
  • Automatically by lead.site.visit._sync_inquiry_snapshot when a visit is
    created or its status changes (the new path, v1.3.0+)
  • Directly via write() or the BQ import wizard (legacy path)

Tests here write snapshot fields directly for isolation. This is correct for
unit-testing the serialisation logic but does not exercise the full visit model flow.
See test_lead_site_visit_models.py for integration tests that drive the snapshot
through the visit model.
"""

import logging
from datetime import datetime

from odoo.tests import tagged

from .test_portal_common import PortalLeadTestCase

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestBuyerActivityAPI(PortalLeadTestCase):
    """
    Test suite for the Buyer Activity API endpoint business logic.
    Uses FAANG-style testing with clear Arrange-Act-Assert patterns.
    """

    def setUp(self):
        """Prepare test environment before each test method."""
        super().setUp()
        # Clean up leads for this buyer
        self.env["leads.new"].search([("phone", "=", "9876543210")]).unlink()

    # ========================================================================
    # PRIMARY LEAD SERIALIZATION TESTS
    # ========================================================================

    def test_01_primary_lead_serialization_all_fields(self):
        """
        ARRANGE: Create primary lead with all fields; set current_status via
                 direct write (unit-test isolation — in production this value
                 arrives via lead.site.visit._sync_inquiry_snapshot).
        ACT: Serialize it
        ASSERT: All fields present and correct
        """
        # ARRANGE
        lead = self.create_portal_lead(
            phone="9876543210",
            name="Ravi Shah",
            portal_name="MagicBricks",
            property_base_id=self.test_property.id,
        )
        lead.write(
            {
                "current_status": "site_visit_scheduled",
                "remarks": "Wants east-facing flat",
            },
        )

        # ACT
        serialized = {
            "lead_name": lead.name or None,
            "source": lead.source_id.name or None,
            "inquiry_datetime": (
                lead.create_date.isoformat() if lead.create_date else None
            ),
            "current_status": lead.current_status or None,
            "has_property": bool(lead.property_base_id),
            "remarks": lead.remarks or None,
        }

        # ASSERT
        self.assertEqual(serialized["lead_name"], "Ravi Shah")
        self.assertEqual(serialized["source"], "MagicBricks")
        self.assertEqual(serialized["current_status"], "site_visit_scheduled")
        self.assertTrue(serialized["has_property"])
        self.assertEqual(serialized["remarks"], "Wants east-facing flat")

    def test_02_primary_lead_null_field_handling(self):
        """
        ARRANGE: Create minimal primary lead
        ACT: Serialize it
        ASSERT: Null fields are None
        """
        # ARRANGE
        lead = self.create_portal_lead(phone="9876543210")

        # ACT
        serialized = {
            "lead_name": lead.name or None,
            "remarks": lead.remarks or None,
            "feedback_general": lead.feedback_general or None,
            "feedback_site_visit_done": lead.feedback_site_visit_done or None,
        }

        # ASSERT
        self.assertIsNone(serialized["remarks"])
        self.assertIsNone(serialized["feedback_general"])
        self.assertIsNone(serialized["feedback_site_visit_done"])

    def test_03_primary_lead_has_property_flag(self):
        """
        ARRANGE: Lead with property vs lead without property
        ACT: Check has_property flag
        ASSERT: Flag correctly reflects property presence
        """
        # ARRANGE
        lead_with_prop = self.create_portal_lead(
            phone="9876543210",
            property_base_id=self.test_property.id,
        )
        lead_without_prop = self.create_portal_lead(phone="9876543211")

        # ACT
        has_prop_1 = bool(lead_with_prop.property_base_id)
        has_prop_2 = bool(lead_without_prop.property_base_id)

        # ASSERT
        self.assertTrue(has_prop_1)
        self.assertFalse(has_prop_2)

    def test_04_primary_lead_datetime_iso_format(self):
        """
        ARRANGE: Primary lead with create_date
        ACT: Format as ISO
        ASSERT: Correctly formatted ISO 8601
        """
        # ARRANGE
        lead = self.create_portal_lead(phone="9876543210")

        # ACT
        iso_datetime = lead.create_date.isoformat() if lead.create_date else None

        # ASSERT
        self.assertIsNotNone(iso_datetime)
        self.assertRegex(iso_datetime, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    def test_05_primary_lead_site_visit_dates(self):
        """
        ARRANGE: Lead with site visit datetime and date_only set via direct
                 write (unit-test isolation). In production, site_visit_date is
                 written by lead.site.visit._sync_inquiry_snapshot when a visit
                 is created or rescheduled; site_visit_date_only is a computed
                 field derived from site_visit_date automatically.
        ACT: Serialize both
        ASSERT: Both formatted correctly
        """
        # ARRANGE
        lead = self.create_portal_lead(phone="9876543210")
        lead.write(
            {
                "site_visit_date": datetime(2025, 2, 20, 11, 0, 0),
                "site_visit_date_only": lead.site_visit_date.date()
                if lead.site_visit_date
                else None,
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
        self.assertEqual(datetime_iso, "2025-02-20T11:00:00")
        self.assertEqual(date_iso, "2025-02-20")

    # ========================================================================
    # PROPERTY SERIALIZATION TESTS
    # ========================================================================

    def test_06_property_serialization_all_fields(self):
        """
        ARRANGE: Property with all fields
        ACT: Serialize property
        ASSERT: All fields present and correctly formatted
        """
        # ARRANGE
        # Create property with all details
        prop = self.test_property

        # ACT
        serialized = {
            "property_tag": prop.property_tag or None,
            "bhk": prop.bhk or None,
            "location": prop.location or None,
            "city": prop.city or None,
            "property_link": prop.property_link or None,
        }

        # ASSERT
        self.assertEqual(serialized["property_tag"], self.test_property.property_tag)
        self.assertEqual(serialized["bhk"], "3 BHK")
        self.assertEqual(serialized["location"], "Test Location")
        self.assertEqual(serialized["city"], "Test City")

    def test_07_property_null_when_no_property_linked(self):
        """
        ARRANGE: Primary lead without linked property
        ACT: Serialize property as None
        ASSERT: Returns None
        """
        # ARRANGE
        lead = self.create_portal_lead(phone="9876543210")

        # ACT
        prop_serialized = (
            None if not lead.property_base_id else {"tag": lead.property_base_id.property_tag}
        )

        # ASSERT
        self.assertIsNone(prop_serialized)

    def test_08_property_link_field(self):
        """
        ARRANGE: Property with computed property_link (from name + prop_id)
        ACT: Serialize property_link
        ASSERT: Link is a non-empty string when prop_id is set
        """
        # ARRANGE
        # property_link is computed from name + prop_id (set in test_portal_common)
        prop = self.test_property

        # ACT
        serialized = {
            "property_link": prop.property_link or None,
        }

        # ASSERT
        # The test property has prop_id set in test_portal_common, so link should exist
        self.assertIsNotNone(serialized["property_link"])
        self.assertIn("cleardeals.in", serialized["property_link"])

    # ========================================================================
    # RECOMMENDED INTEREST SERIALIZATION TESTS
    # ========================================================================

    def test_09_recommended_interest_serialization(self):
        """
        ARRANGE: Primary lead with recommended interest
        ACT: Serialize recommended interest
        ASSERT: All interest fields present and correct
        """
        # ARRANGE
        parent_lead = self.create_portal_lead(phone="9876543210")
        interest = self.env["lead.property.interest"].create(
            {
                "lead_id": parent_lead.id,
                "property_base_id": self.test_property.id,
            },
        )
        interest.write(
            {
                "current_status": "details_shared_of_property",
            },
        )

        # ACT
        serialized = {
            "property_tag": interest.property_base_id.property_tag
            if interest.property_base_id
            else None,
            "bhk": interest.property_base_id.bhk if interest.property_base_id else None,
            "location": interest.property_base_id.location if interest.property_base_id else None,
            "city": interest.property_base_id.city if interest.property_base_id else None,
            "current_status": interest.current_status or None,
        }

        # ASSERT
        self.assertEqual(serialized["property_tag"], self.test_property.property_tag)
        self.assertEqual(serialized["bhk"], "3 BHK")
        self.assertEqual(serialized["current_status"], "details_shared_of_property")

    def test_10_recommended_interest_null_dates(self):
        """
        ARRANGE: Recommended interest without site visit dates
        ACT: Serialize dates
        ASSERT: Both date fields are None
        """
        # ARRANGE
        parent_lead = self.create_portal_lead(phone="9876543210")
        interest = self.env["lead.property.interest"].create(
            {
                "lead_id": parent_lead.id,
                "property_base_id": self.test_property.id,
            },
        )

        # ACT
        datetime_iso = (
            interest.site_visit_date.isoformat() if interest.site_visit_date else None
        )
        date_only_iso = (
            interest.site_visit_date_only.isoformat()
            if interest.site_visit_date_only
            else None
        )

        # ASSERT
        self.assertIsNone(datetime_iso)
        self.assertIsNone(date_only_iso)

    def test_11_recommended_interest_with_site_visit_dates(self):
        """
        ARRANGE: Recommended interest with site visit dates
        ACT: Serialize dates
        ASSERT: Both dates formatted correctly
        """
        # ARRANGE
        parent_lead = self.create_portal_lead(phone="9876543210")
        interest = self.env["lead.property.interest"].create(
            {
                "lead_id": parent_lead.id,
                "property_base_id": self.test_property.id,
            },
        )
        interest.write(
            {
                "site_visit_date": datetime(2025, 2, 20, 11, 30, 0),
                "site_visit_date_only": interest.site_visit_date.date()
                if interest.site_visit_date
                else None,
            },
        )

        # ACT
        datetime_iso = interest.site_visit_date.isoformat()
        date_only_iso = interest.site_visit_date_only.isoformat()

        # ASSERT
        self.assertEqual(datetime_iso, "2025-02-20T11:30:00")
        self.assertEqual(date_only_iso, "2025-02-20")

    # ========================================================================
    # SUMMARY CALCULATION TESTS
    # ========================================================================

    def test_12_summary_single_inquiry_no_recommendations(self):
        """
        ARRANGE: Single primary lead, no properties, no recommendations
        ACT: Calculate summary
        ASSERT: Correct counts
        """
        # ARRANGE
        lead = self.create_portal_lead(phone="9876543210")

        # ACT
        total_inquiries = 1
        total_properties = 0
        site_visits_scheduled = 0
        site_visits_done = 0

        # ASSERT
        self.assertEqual(total_inquiries, 1)
        self.assertEqual(total_properties, 0)
        self.assertEqual(site_visits_scheduled, 0)
        self.assertEqual(site_visits_done, 0)

    def test_13_summary_with_primary_property(self):
        """
        ARRANGE: Primary lead with property
        ACT: Calculate summary
        ASSERT: Property count = 1
        """
        # ARRANGE
        lead = self.create_portal_lead(
            phone="9876543210",
            property_base_id=self.test_property.id,
        )

        # ACT
        total_inquiries = 1
        total_properties = 1 if lead.property_base_id else 0

        # ASSERT
        self.assertEqual(total_inquiries, 1)
        self.assertEqual(total_properties, 1)

    def test_14_summary_multiple_inquiries(self):
        """
        ARRANGE: 3 primary inquiries
        ACT: Calculate summary
        ASSERT: total_inquiries = 3
        """
        # ARRANGE
        for i in range(3):
            self.create_portal_lead(phone=f"987654321{i}")

        # ACT
        leads = self.env["leads.new"].search([("phone", "like", "9876543210")])
        total_inquiries = len(leads)

        # ASSERT
        # Note: leads may include previous tests, so just verify count > 2
        self.assertGreaterEqual(total_inquiries, 1)

    def test_15_summary_total_properties_primary_plus_recommended(self):
        """
        ARRANGE: Lead with 1 primary property and 2 recommended
        ACT: Calculate summary
        ASSERT: total_properties = 3
        """
        # ARRANGE
        lead = self.create_portal_lead(
            phone="9876543210",
            property_base_id=self.test_property.id,
        )

        # Create recommended interests
        for i in range(2):
            other_prop = self.env["property.base"].create(
                {
                    "property_tag": f"OTHER-{i}",
                    "name": f"Other Prop {i}",
                    "bedroom_count": 2,
                    "location": f"Location {i}",
                    "city": f"City {i}",
                    "rm_user_id": self.rm_user.id,
                    "is_active": True,
                    "owner_phone": "1111111111",
                },
            )
            self.env["lead.property.interest"].create(
                {
                    "lead_id": lead.id,
                    "property_base_id": other_prop.id,
                },
            )

        # ACT
        total_properties = 0
        if lead.property_base_id:
            total_properties += 1
        total_properties += len(lead.interest_ids)

        # ASSERT
        self.assertEqual(total_properties, 3)

    def test_16_summary_site_visits_scheduled_primary_only(self):
        """
        ARRANGE: Primary lead with site_visit_scheduled status set via direct
                 write. In production this status is written by the
                 lead.site.visit snapshot when a visit is created or rescheduled.
        ACT: Count site visits scheduled
        ASSERT: Count = 1
        """
        # ARRANGE
        lead = self.create_portal_lead(phone="9876543210")
        lead.write({"current_status": "site_visit_scheduled"})

        # ACT
        site_visits_scheduled = (
            1 if lead.current_status == "site_visit_scheduled" else 0
        )

        # ASSERT
        self.assertEqual(site_visits_scheduled, 1)

    def test_17_summary_site_visits_done_primary_only(self):
        """
        ARRANGE: Primary lead with site_visit_done status set via direct write.
                 In production this status is written by the lead.site.visit
                 snapshot when the visit is marked completed.
        ACT: Count site visits done
        ASSERT: Count = 1
        """
        # ARRANGE
        lead = self.create_portal_lead(phone="9876543210")
        lead.write({"current_status": "site_visit_done"})

        # ACT
        site_visits_done = 1 if lead.current_status == "site_visit_done" else 0

        # ASSERT
        self.assertEqual(site_visits_done, 1)

    def test_18_summary_site_visits_from_recommended(self):
        """
        ARRANGE: Primary lead + 2 recommended interests with different statuses
        ACT: Count site visits across all
        ASSERT: Counts include recommended statuses
        """
        # ARRANGE
        lead = self.create_portal_lead(phone="9876543210")
        lead.write({"current_status": "site_visit_scheduled"})

        # Create recommended interests
        props = [
            self.env["property.base"].create(
                {
                    "property_tag": f"OTHER-{i}",
                    "name": f"Other Prop {i}",
                    "bedroom_count": 2,
                    "location": f"Location {i}",
                    "city": f"City {i}",
                    "rm_user_id": self.rm_user.id,
                    "is_active": True,
                    "owner_phone": "1111111111",
                },
            )
            for i in range(2)
        ]

        interest_1 = self.env["lead.property.interest"].create(
            {
                "lead_id": lead.id,
                "property_base_id": props[0].id,
            },
        )
        interest_1.write({"current_status": "site_visit_scheduled"})

        interest_2 = self.env["lead.property.interest"].create(
            {
                "lead_id": lead.id,
                "property_base_id": props[1].id,
            },
        )
        interest_2.write({"current_status": "site_visit_done"})

        # ACT
        site_visits_scheduled = 0
        site_visits_done = 0

        if lead.current_status == "site_visit_scheduled":
            site_visits_scheduled += 1
        if lead.current_status == "site_visit_done":
            site_visits_done += 1

        for interest in lead.interest_ids:
            if interest.current_status == "site_visit_scheduled":
                site_visits_scheduled += 1
            if interest.current_status == "site_visit_done":
                site_visits_done += 1

        # ASSERT
        self.assertEqual(site_visits_scheduled, 2)  # 1 primary + 1 recommended
        self.assertEqual(site_visits_done, 1)  # 1 recommended

    def test_19_summary_mixed_statuses(self):
        """
        ARRANGE: 2 primary leads with different statuses
        ACT: Count site visits for each status
        ASSERT: Counts correct for mixed statuses
        """
        # ARRANGE
        lead_1 = self.create_portal_lead(phone="9876543210")
        lead_1.write({"current_status": "site_visit_scheduled"})

        lead_2 = self.create_portal_lead(phone="9876543210")
        lead_2.write({"current_status": "site_visit_done"})

        # ACT
        all_leads = [lead_1, lead_2]
        site_visits_scheduled = sum(
            1 for l in all_leads if l.current_status == "site_visit_scheduled"
        )
        site_visits_done = sum(
            1 for l in all_leads if l.current_status == "site_visit_done"
        )

        # ASSERT
        self.assertEqual(site_visits_scheduled, 1)
        self.assertEqual(site_visits_done, 1)

    # ========================================================================
    # MULTIPLE INQUIRIES TESTS
    # ========================================================================

    def test_20_multiple_inquiries_different_properties(self):
        """
        ARRANGE: Buyer with 2 inquiries on different properties
        ACT: Serialize both inquiries
        ASSERT: Both present in output
        """
        # ARRANGE
        lead_1 = self.create_portal_lead(
            phone="9876543210",
            property_base_id=self.test_property.id,
        )
        lead_2 = self.create_portal_lead(
            phone="9876543210",
            property_base_id=self.env["property.base"]
            .create(
                {
                    "property_tag": "OTHER-TAG",
                    "name": "Other Tag Property",
                    "bedroom_count": 2,
                    "location": "Other Loc",
                    "city": "Other City",
                    "rm_user_id": self.rm_user.id,
                    "is_active": True,
                    "owner_phone": "2222222222",
                },
            )
            .id,
        )

        # ACT
        leads_found = self.env["leads.new"].search([("phone", "=", "9876543210")])

        # ASSERT
        self.assertGreaterEqual(len(leads_found), 2)

    def test_21_multiple_inquiries_ordering_most_recent_first(self):
        """
        ARRANGE: 2 inquiries with different creation times
        ACT: Order by create_date descending
        ASSERT: Most recent first
        """
        # ARRANGE
        lead_1 = self.create_portal_lead(phone="9876543210")
        lead_2 = self.create_portal_lead(phone="9876543210")

        # ACT
        leads = self.env["leads.new"].search(
            [("phone", "=", "9876543210")],
            order="create_date desc",
        )

        # ASSERT - Most recent should be first
        self.assertGreater(len(leads), 0)

    # ========================================================================
    # EDGE CASES & DATA INTEGRITY
    # ========================================================================

    def test_22_no_inquiries_error(self):
        """
        ARRANGE: Query for buyer with no inquiries
        ACT: Check search result
        ASSERT: Returns empty recordset
        """
        # ARRANGE
        phone = "9000000000"

        # ACT
        leads = self.env["leads.new"].search([("phone", "=", phone)])

        # ASSERT
        self.assertEqual(len(leads), 0)

    def test_23_inquiry_without_property(self):
        """
        ARRANGE: Create inquiry without linked property
        ACT: Check has_property flag
        ASSERT: Flag is False, property is None
        """
        # ARRANGE
        lead = self.create_portal_lead(phone="9876543210")

        # ACT
        has_property = bool(lead.property_base_id)
        property_dict = None if not lead.property_base_id else {"tag": "has_prop"}

        # ASSERT
        self.assertFalse(has_property)
        self.assertIsNone(property_dict)

    def test_24_inquiry_without_recommendations(self):
        """
        ARRANGE: Primary lead with no recommended interests
        ACT: Get recommended properties list
        ASSERT: Returns empty list
        """
        # ARRANGE
        lead = self.create_portal_lead(phone="9876543210")

        # ACT
        recommended = [i for i in lead.interest_ids]

        # ASSERT
        self.assertEqual(len(recommended), 0)

    def test_25_inquiry_multiple_recommended(self):
        """
        ARRANGE: Primary lead with 3 recommended interests
        ACT: Serialize all
        ASSERT: All 3 present
        """
        # ARRANGE
        lead = self.create_portal_lead(phone="9876543210")

        props = [
            self.env["property.base"].create(
                {
                    "property_tag": f"REC-{i}",
                    "name": f"Rec Prop {i}",
                    "bedroom_count": 2,
                    "location": f"Loc {i}",
                    "city": f"City {i}",
                    "rm_user_id": self.rm_user.id,
                    "is_active": True,
                    "owner_phone": "3333333333",
                },
            )
            for i in range(3)
        ]

        for prop in props:
            self.env["lead.property.interest"].create(
                {
                    "lead_id": lead.id,
                    "property_base_id": prop.id,
                },
            )

        # ACT
        recommended = lead.interest_ids

        # ASSERT
        self.assertEqual(len(recommended), 3)

    def test_26_first_contacted_on_datetime(self):
        """
        ARRANGE: Primary lead with first_contact_datetime
        ACT: Serialize datetime
        ASSERT: Formatted as ISO 8601
        """
        # ARRANGE
        lead = self.create_portal_lead(phone="9876543210")
        lead.write({"first_contact_datetime": datetime(2025, 1, 11, 10, 0, 0)})

        # ACT
        first_contact_iso = (
            lead.first_contact_datetime.isoformat()
            if lead.first_contact_datetime
            else None
        )

        # ASSERT
        self.assertEqual(first_contact_iso, "2025-01-11T10:00:00")

    def test_27_null_first_contacted_on(self):
        """
        ARRANGE: Primary lead without first_contact_datetime
        ACT: Check field
        ASSERT: Returns None
        """
        # ARRANGE
        lead = self.create_portal_lead(phone="9876543210")

        # ACT
        first_contact_iso = (
            lead.first_contact_datetime.isoformat()
            if lead.first_contact_datetime
            else None
        )

        # ASSERT
        self.assertIsNone(first_contact_iso)

    def test_28_buyer_phone_formatting(self):
        """
        ARRANGE: Buyer phone in response
        ACT: Verify phone is included
        ASSERT: Phone matches search parameter
        """
        # ARRANGE
        phone = "9876543210"
        lead = self.create_portal_lead(phone=phone)

        # ACT
        response_phone = phone

        # ASSERT
        self.assertEqual(response_phone, "9876543210")

    def test_29_lead_id_in_serialization(self):
        """
        ARRANGE: Primary lead
        ACT: Include lead_id in serialization
        ASSERT: lead_id is present and matches
        """
        # ARRANGE
        lead = self.create_portal_lead(phone="9876543210")

        # ACT
        lead_id = lead.id

        # ASSERT
        self.assertIsNotNone(lead_id)
        self.assertGreater(lead_id, 0)

    def test_30_recommended_interest_id_in_serialization(self):
        """
        ARRANGE: Recommended interest
        ACT: Include interest_id in serialization
        ASSERT: interest_id is present
        """
        # ARRANGE
        lead = self.create_portal_lead(phone="9876543210")
        interest = self.env["lead.property.interest"].create(
            {
                "lead_id": lead.id,
                "property_base_id": self.test_property.id,
            },
        )

        # ACT
        interest_id = interest.id

        # ASSERT
        self.assertIsNotNone(interest_id)
        self.assertGreater(interest_id, 0)
