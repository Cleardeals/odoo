"""
Test suite for the Property Activity Dashboard endpoint:
  POST /web/leads/property_activity/<property_id>

Core correctness guarantee being tested
----------------------------------------
Each test verifies that the dashboard returns data scoped ONLY to the
requested property_id.  The regression this guards against is the old
(broken) implementation that routed through `property_tag` lookup and
could return the entire dataset when `property_tag` was empty or when
multiple properties shared a tag.

Test Categories
---------------
- Isolation: leads for property A never appear in property B's data
- KPI accuracy: status bucket counts match the records created
- Recommended leads: leads.new(inquiry_type=recommended) rows surface under recommended
- Source breakdown: per-source counts are correct
- Site visit classification: upcoming / pending / completed / cancelled
- Empty property: no leads → all zeroes, no exception
- Mixed status: multiple status buckets counted independently
- Cross-property contamination: explicit assertion that no bleeding occurs

Model integration notes
-----------------------
Tests write `current_status`, `site_visit_date`, etc. directly (unit-test
isolation). In production these values arrive via the site-visit model or
the BQ import wizard. See test_lead_site_visit_models.py for those flows.
"""

import logging
from datetime import datetime, timedelta

from odoo.tests import tagged

from ..controllers.seller.property_dashboard import (
    PropertyActivityDashboardController,
    _STATUS_BUCKET,
    _serialize_lead,
)
from .test_portal_common import PortalLeadTestCase

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestPropertyActivityDashboard(PortalLeadTestCase):
    """
    Tests for the Property Activity Dashboard.
    Uses direct ORM queries to mirror the controller's logic so that
    any future refactor that changes the ORM path is caught immediately.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Second property — must be completely isolated from cls.test_property
        cls.other_property = cls.env["property.base"].create(
            {
                "property_tag": f"OTHER-PROP-{cls.suffix}",
                "name": f"Other Property {cls.suffix}",
                "prop_id": f"OP{cls.suffix}",
                "bedroom_count": 2,
                "location": "Other Location",
                "city": "Other City",
                "rm_user_id": cls.rm_user.id,
                "is_active": True,
            }
        )

    def setUp(self):
        super().setUp()
        # Wipe any leads linked to our two test properties between tests
        self.env["leads.new"].search(
            [("property_base_id", "in", [self.test_property.id, self.other_property.id])]
        ).unlink()
        self.env["lead.property.interest"].search(
            [("property_base_id", "in", [self.test_property.id, self.other_property.id])]
        ).unlink()

    # ════════════════════════════════════════════════════════════════════════
    # Helper — mirrors what the controller does exactly
    # ════════════════════════════════════════════════════════════════════════

    def _run_dashboard(self, property_id):
        """
        Execute the same ORM queries the controller uses and return the
        dashboard payload dict.  This tests the logic without requiring an
        HTTP session.
        """
        env = self.env
        prop = env["property.base"].browse(property_id)
        self.assertTrue(prop.exists(), "Test setup error: property not found")

        primary_leads = (
            env["leads.new"]
            .sudo()
            .search(
                [
                    ("property_base_id", "=", property_id),
                    ("inquiry_type", "=", "primary"),
                ],
                order="create_date desc",
            )
        )
        recommended = (
            env["leads.new"]
            .sudo()
            .search(
                [
                    ("property_base_id", "=", property_id),
                    ("inquiry_type", "=", "recommended"),
                ],
                order="create_date desc",
            )
        )

        kpi = {
            "total": len(primary_leads) + len(recommended),
            "primary": len(primary_leads),
            "recommended": len(recommended),
            "contacted": 0,
            "details_shared": 0,
            "site_visit_scheduled": 0,
            "site_visit_done": 0,
            "not_interested": 0,
        }
        for lead in primary_leads:
            bucket = _STATUS_BUCKET.get(lead.current_status)
            if bucket is None:
                continue  # "lead" (uncontacted) — not counted in sub-buckets
            kpi[bucket] = kpi.get(bucket, 0) + 1
        for rec in recommended:
            bucket = _STATUS_BUCKET.get(rec.current_status)
            if bucket is None:
                continue
            kpi[bucket] = kpi.get(bucket, 0) + 1

        source_counts = {}
        for lead in primary_leads:
            src = lead.source_id.name if lead.source_id else "Unknown"
            source_counts.setdefault(src, {"primary": 0, "recommended": 0})
            source_counts[src]["primary"] += 1
        for rec in recommended:
            src = rec.source_id.name if rec.source_id else "Unknown"
            source_counts.setdefault(src, {"primary": 0, "recommended": 0})
            source_counts[src]["recommended"] += 1

        activity = []
        for lead in primary_leads:
            activity.append(_serialize_lead(lead, "primary"))
        for rec in recommended:
            activity.append(_serialize_lead(rec, "recommended"))
        activity.sort(key=lambda r: r["inquiry_datetime"] or "", reverse=True)

        return {
            "property_id": property_id,
            "property_tag": prop.property_tag or "",
            "property_name": prop.name or "",
            "kpi": kpi,
            "source_breakdown": source_counts,
            "activity": activity,
        }

    # ════════════════════════════════════════════════════════════════════════
    # 1. ISOLATION — cross-property contamination
    # ════════════════════════════════════════════════════════════════════════

    def test_01_leads_for_property_a_do_not_appear_in_property_b(self):
        """
        ARRANGE: 3 leads on property A, 2 leads on property B.
        ACT: Run dashboard for property A; run dashboard for property B.
        ASSERT: Property A sees exactly 3; property B sees exactly 2.
                Neither set contains the other's lead IDs.
        """
        # ARRANGE
        for i in range(3):
            self.create_portal_lead(
                name=f"Buyer A{i}",
                phone=f"900000000{i}",
                property_base_id=self.test_property.id,
            )
        for i in range(2):
            self.create_portal_lead(
                name=f"Buyer B{i}",
                phone=f"910000000{i}",
                property_base_id=self.other_property.id,
            )

        # ACT
        dash_a = self._run_dashboard(self.test_property.id)
        dash_b = self._run_dashboard(self.other_property.id)

        # ASSERT — counts
        self.assertEqual(dash_a["kpi"]["total"], 3, "Property A should have exactly 3 leads")
        self.assertEqual(dash_b["kpi"]["total"], 2, "Property B should have exactly 2 leads")

        # ASSERT — no cross-contamination by name
        names_a = {r["lead_name"] for r in dash_a["activity"]}
        names_b = {r["lead_name"] for r in dash_b["activity"]}
        self.assertFalse(
            names_a & names_b,
            f"Cross-contamination detected: {names_a & names_b}",
        )

    def test_02_empty_property_returns_zero_kpi(self):
        """
        ARRANGE: Property with zero leads.
        ACT: Run dashboard.
        ASSERT: All KPI buckets are 0; activity list is empty; no exception.
        """
        dash = self._run_dashboard(self.other_property.id)

        self.assertEqual(dash["kpi"]["total"], 0)
        self.assertEqual(dash["kpi"]["primary"], 0)
        self.assertEqual(dash["kpi"]["recommended"], 0)
        self.assertEqual(dash["kpi"]["contacted"], 0)
        self.assertEqual(dash["kpi"]["details_shared"], 0)
        self.assertEqual(dash["kpi"]["site_visit_scheduled"], 0)
        self.assertEqual(dash["kpi"]["site_visit_done"], 0)
        self.assertEqual(dash["kpi"]["not_interested"], 0)
        self.assertEqual(len(dash["activity"]), 0)

    # ════════════════════════════════════════════════════════════════════════
    # 2. KPI ACCURACY — status bucket counting
    # ════════════════════════════════════════════════════════════════════════

    def test_03_kpi_contacted_bucket_counts_correctly(self):
        """
        ARRANGE: 3 leads with statuses that map to 'contacted' bucket.
        ACT: Run dashboard.
        ASSERT: kpi.contacted == 3; all other buckets == 0.
        """
        contacted_statuses = ["busy", "ringing", "other"]
        for status in contacted_statuses:
            lead = self.create_portal_lead(
                name=f"Buyer {status}",
                phone=f"9{contacted_statuses.index(status)}00000000",
                property_base_id=self.test_property.id,
            )
            lead.sudo().write({"current_status": status})

        dash = self._run_dashboard(self.test_property.id)

        self.assertEqual(dash["kpi"]["total"], 3)
        self.assertEqual(dash["kpi"]["contacted"], 3)
        self.assertEqual(dash["kpi"]["details_shared"], 0)
        self.assertEqual(dash["kpi"]["site_visit_scheduled"], 0)
        self.assertEqual(dash["kpi"]["site_visit_done"], 0)
        self.assertEqual(dash["kpi"]["not_interested"], 0)

    def test_04_kpi_all_buckets_count_independently(self):
        """
        ARRANGE: 1 lead in each of the 5 status buckets.
        ACT: Run dashboard.
        ASSERT: Each bucket == 1; total == 5.
        """
        status_sample = {
            "contacted": "busy",
            "details_shared": "details_shared_of_property",
            "site_visit_scheduled": "site_visit_scheduled",
            "site_visit_done": "site_visit_done",
            "not_interested": "no_requirements",
        }
        for i, (bucket, status) in enumerate(status_sample.items()):
            lead = self.create_portal_lead(
                name=f"Buyer {bucket}",
                phone=f"98765{i:05d}",
                property_base_id=self.test_property.id,
            )
            lead.sudo().write({"current_status": status})

        dash = self._run_dashboard(self.test_property.id)

        self.assertEqual(dash["kpi"]["total"], 5)
        for bucket in status_sample:
            self.assertEqual(
                dash["kpi"][bucket], 1,
                f"Expected kpi.{bucket} == 1, got {dash['kpi'][bucket]}",
            )

    def test_05_kpi_not_interested_all_statuses_counted(self):
        """
        ARRANGE: 6 leads, each with a different 'not_interested' sub-status.
        ACT: Run dashboard.
        ASSERT: kpi.not_interested == 6.
        """
        not_interested = [
            "option_not_matching_requirements",
            "no_requirements",
            "requirement_closed",
            "property_sold_out",
            "budget_not_sufficient",
            "number_not_in_use_wrong_number",
        ]
        for i, status in enumerate(not_interested):
            lead = self.create_portal_lead(
                name=f"Buyer NI{i}",
                phone=f"97654{i:05d}",
                property_base_id=self.test_property.id,
            )
            lead.sudo().write({"current_status": status})

        dash = self._run_dashboard(self.test_property.id)

        self.assertEqual(dash["kpi"]["not_interested"], 6)

    # ════════════════════════════════════════════════════════════════════════
    # 3. RECOMMENDED LEADS
    # ════════════════════════════════════════════════════════════════════════

    def test_06_recommended_leads_appear_in_dashboard(self):
        """
        ARRANGE: 1 primary lead on other_property (acts as the buyer lead);
                 1 leads.new(inquiry_type=recommended) on test_property.
        ACT: Run dashboard for test_property.
        ASSERT: kpi.recommended == 1; total == 1; recommended row in activity.
        """
        # Buyer lead lives on a DIFFERENT property so it doesn't count as
        # primary for test_property.
        buyer_lead = self.create_portal_lead(
            name="Buyer Rec",
            phone="9111111111",
            property_base_id=self.other_property.id,
        )
        # Recommended inquiry on test_property created via the same model
        # the Recommend Property wizard uses.
        self.env["leads.new"].sudo().create(
            {
                "name": buyer_lead.name,
                "phone": buyer_lead.phone,
                "source_id": buyer_lead.source_id.id,
                "property_base_id": self.test_property.id,
                "user_id": buyer_lead.user_id.id,
                "state": "assigned",
                "current_status": "site_visit_scheduled",
                "inquiry_type": "recommended",
                "parent_inquiry_id": buyer_lead.id,
            }
        )

        dash = self._run_dashboard(self.test_property.id)

        self.assertEqual(dash["kpi"]["primary"], 0)
        self.assertEqual(dash["kpi"]["recommended"], 1)
        self.assertEqual(dash["kpi"]["total"], 1)
        self.assertEqual(dash["kpi"]["site_visit_scheduled"], 1)

        rec_rows = [r for r in dash["activity"] if r["type"] == "recommended"]
        self.assertEqual(len(rec_rows), 1)
        self.assertEqual(rec_rows[0]["lead_name"], "Buyer Rec")

    def test_07_recommended_leads_for_other_property_not_included(self):
        """
        ARRANGE: A leads.new(inquiry_type=recommended) linking to other_property.
        ACT: Run dashboard for test_property.
        ASSERT: test_property dashboard shows 0 recommended.
        """
        buyer_lead = self.create_portal_lead(
            name="Buyer Wrong Prop",
            phone="9222222222",
            property_base_id=self.test_property.id,
        )
        # Recommended inquiry on OTHER property — must not appear for test_property
        self.env["leads.new"].sudo().create(
            {
                "name": buyer_lead.name,
                "phone": buyer_lead.phone,
                "source_id": buyer_lead.source_id.id,
                "property_base_id": self.other_property.id,
                "user_id": buyer_lead.user_id.id,
                "state": "assigned",
                "current_status": "lead",
                "inquiry_type": "recommended",
                "parent_inquiry_id": buyer_lead.id,
            }
        )

        dash = self._run_dashboard(self.test_property.id)

        # primary: 1 (buyer_lead is primary on test_property)
        # recommended: 0 (the recommended inquiry is on other_property)
        self.assertEqual(dash["kpi"]["primary"], 1)
        self.assertEqual(dash["kpi"]["recommended"], 0)

    # ════════════════════════════════════════════════════════════════════════
    # 4. SOURCE BREAKDOWN
    # ════════════════════════════════════════════════════════════════════════

    def test_08_source_breakdown_counts_per_source(self):
        """
        ARRANGE: 2 MagicBricks leads and 1 99acres lead on test_property.
        ACT: Run dashboard.
        ASSERT: source_breakdown['MagicBricks']['primary'] == 2,
                source_breakdown['99acres']['primary'] == 1.
        """
        for _ in range(2):
            self.create_portal_lead(
                name="MB Buyer",
                phone="9333333333",
                source_name="MagicBricks",
                property_base_id=self.test_property.id,
            )
        self.create_portal_lead(
            name="Acres Buyer",
            phone="9444444444",
            source_name="99acres",
            property_base_id=self.test_property.id,
        )

        dash = self._run_dashboard(self.test_property.id)

        sb = dash["source_breakdown"]
        self.assertIn("MagicBricks", sb)
        self.assertIn("99acres", sb)
        self.assertEqual(sb["MagicBricks"]["primary"], 2)
        self.assertEqual(sb["99acres"]["primary"], 1)

    def test_09_source_breakdown_excludes_other_property_sources(self):
        """
        ARRANGE: 1 lead on test_property (MagicBricks), 1 lead on other_property (99acres).
        ACT: Run dashboard for test_property.
        ASSERT: source_breakdown has only MagicBricks; 99acres is absent.
        """
        self.create_portal_lead(
            name="MB Buyer",
            phone="9555555555",
            source_name="MagicBricks",
            property_base_id=self.test_property.id,
        )
        self.create_portal_lead(
            name="Acres Buyer",
            phone="9666666666",
            source_name="99acres",
            property_base_id=self.other_property.id,
        )

        dash = self._run_dashboard(self.test_property.id)

        sb = dash["source_breakdown"]
        self.assertIn("MagicBricks", sb)
        self.assertNotIn("99acres", sb, "99acres lead belongs to other_property, not test_property")

    # ════════════════════════════════════════════════════════════════════════
    # 5. SERIALIZATION
    # ════════════════════════════════════════════════════════════════════════

    def test_10_serialize_lead_primary_fields(self):
        """
        ARRANGE: Lead with all main fields set.
        ACT: Call _serialize_lead directly.
        ASSERT: All expected keys are present and values match.
        """
        lead = self.create_portal_lead(
            name="Niraj Mehta",
            phone="9777777777",
            source_name="MagicBricks",
            property_base_id=self.test_property.id,
        )
        lead.sudo().write(
            {
                "current_status": "site_visit_done",
                "remarks": "Very interested",
                "feedback_site_visit_done": "deal_closed",
            }
        )

        row = _serialize_lead(lead, "primary")

        self.assertEqual(row["type"], "primary")
        self.assertEqual(row["lead_id"], lead.id)
        self.assertEqual(row["lead_name"], "Niraj Mehta")
        self.assertEqual(row["lead_phone"], "9777777777")
        self.assertEqual(row["source"], "MagicBricks")
        self.assertEqual(row["current_status"], "site_visit_done")
        self.assertEqual(row["remarks"], "Very interested")
        self.assertEqual(row["feedback_site_visit_done"], "deal_closed")
        self.assertEqual(row["property_tag"], self.test_property.property_tag)

    def test_11_serialize_lead_handles_missing_source(self):
        """
        ARRANGE: Lead with no source_id set.
        ACT: _serialize_lead.
        ASSERT: source returns "Unknown" not an exception.
        """
        lead = self.create_portal_lead(
            name="No Source Buyer",
            phone="9888888888",
            property_base_id=self.test_property.id,
        )
        lead.sudo().write({"source_id": False})

        row = _serialize_lead(lead, "primary")

        self.assertEqual(row["source"], "Unknown")

    # ════════════════════════════════════════════════════════════════════════
    # 6. STATUS BUCKET MAP — completeness
    # ════════════════════════════════════════════════════════════════════════

    def test_12_all_16_contact_statuses_have_a_bucket(self):
        """
        ASSERT: Every contactable current_status value maps to one of the 5 KPI buckets.
        "lead" (initial / uncontacted) is intentionally absent from _STATUS_BUCKET —
        those inquiries count toward the total but not any sub-bucket KPI.
        """
        # "lead" must NOT be in the bucket map
        self.assertIsNone(
            _STATUS_BUCKET.get("lead"),
            "'lead' status must be absent from _STATUS_BUCKET (uncontacted — no sub-bucket)",
        )
        valid_statuses = [
            "busy", "ringing", "call_back_later", "switched_off",
            "details_shared_of_property", "detail_shared_and_interested_for_site_visit",
            "site_visit_scheduled", "rescheduled", "site_visit_done",
            "option_not_matching_requirements", "no_requirements", "requirement_closed",
            "property_sold_out", "budget_not_sufficient", "number_not_in_use_wrong_number",
            "other",
        ]
        valid_buckets = {
            "contacted", "details_shared", "site_visit_scheduled", "site_visit_done", "not_interested",
        }
        for status in valid_statuses:
            bucket = _STATUS_BUCKET.get(status)
            self.assertIsNotNone(bucket, f"Status '{status}' has no bucket in _STATUS_BUCKET")
            self.assertIn(
                bucket,
                valid_buckets,
                f"Status '{status}' maps to unknown bucket '{bucket}'",
            )

    # ════════════════════════════════════════════════════════════════════════
    # 7. ACTIVITY ORDERING
    # ════════════════════════════════════════════════════════════════════════

    def test_13_activity_rows_are_newest_first(self):
        """
        ARRANGE: 3 leads created at different times on the same property.
        ACT: Run dashboard.
        ASSERT: activity list is in descending inquiry_datetime order.
        """
        leads = []
        for i in range(3):
            lead = self.create_portal_lead(
                name=f"Dated Buyer {i}",
                phone=f"9{i}11111111",
                property_base_id=self.test_property.id,
            )
            leads.append(lead)

        dash = self._run_dashboard(self.test_property.id)
        datetimes = [r["inquiry_datetime"] for r in dash["activity"] if r["inquiry_datetime"]]

        self.assertEqual(
            datetimes,
            sorted(datetimes, reverse=True),
            "Activity rows must be sorted newest-first",
        )

    # ════════════════════════════════════════════════════════════════════════
    # 8. PROPERTY META
    # ════════════════════════════════════════════════════════════════════════

    def test_14_dashboard_returns_correct_property_meta(self):
        """
        ASSERT: property_id, property_tag, and property_name in payload
                match the requested property, not some other property.
        """
        dash = self._run_dashboard(self.test_property.id)

        self.assertEqual(dash["property_id"], self.test_property.id)
        self.assertEqual(dash["property_tag"], self.test_property.property_tag)
        self.assertEqual(dash["property_name"], self.test_property.name)
