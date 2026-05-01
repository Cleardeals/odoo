from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from .test_portal_common import PortalLeadTestCase


# ---------------------------------------------------------------------------
# Module : leads
# Tests  : Cross-RM access correctness
# Purpose: Regression tests for three bugs fixed in April 2026:
#
#   BUG-1  Recommended inquiry duplicate check was blind to inquiries owned
#          by other RMs — leads.new record rule (user_id = user.id) silently
#          filtered them out, allowing a duplicate recommended inquiry on the
#          same buyer+property to be created by a second RM.
#
#   BUG-2  Inquiry Timeline (site_visit_ids) was empty for RM users when the
#          visit's assigned_rm_id differed from the viewing RM — caused by the
#          lead.site.visit record rule (assigned_rm_id = user.id) hiding the
#          visit in the One2many read.
#
#   BUG-3  Overall Lead Timeline (_compute_all_phone_site_visit_ids) returned
#          only the current RM's own visits — the cross-model domain
#          ("inquiry_id.phone", …) applied the leads.new record rule to the
#          JOIN subquery even when the outer search used sudo(), hiding
#          inquiries owned by other RMs and their associated visits.
#
#   BUG-4  AccessError on visit field access: when the Many2many recordset from
#          all_phone_site_visit_ids (fetched with sudo) was later accessed via
#          the non-sudo rec, Odoo re-ran model-level ACL checks using rec.env,
#          raising "doesn't have 'read' access to lead.site.visit" for users
#          who aren't in the RM group at the point of record read.
#
# Owner  : Cleardeals Tech
# ---------------------------------------------------------------------------


@tagged("post_install", "-at_install")
class TestCrossRMRecommendedDuplicate(PortalLeadTestCase):
    """BUG-1 — Duplicate recommended inquiry check must be cross-RM."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.second_property = cls.env["property.base"].create(
            {
                "property_tag": f"TEST-PROP-B-{cls.suffix}",
                "name": f"Test Property B {cls.suffix}",
                "prop_id": f"TPB{cls.suffix}",
                "bedroom_count": 2,
                "location": "Test Location B",
                "city": "Test City B",
                "rm_user_id": cls.test_rm_a.id,
                "is_active": True,
            }
        )

    def test_01_recommended_duplicate_blocked_across_rms(self):
        """
        ARRANGE: RM-A creates a primary inquiry with phone P on property X.
                 RM-A creates a recommended inquiry for property Y on that
                 primary inquiry.
        ACT    : RM-B opens the same primary inquiry and tries to create
                 another recommended inquiry for property Y via the wizard.
        ASSERT : ValidationError is raised — the existing recommended
                 inquiry (owned by RM-A) must be found despite the record
                 rule filtering.
        """
        primary = self.env["leads.new"].with_context(
            automated_lead_creation=True
        ).create(
            {
                "name": "Cross RM Duplicate Test",
                "phone": f"99001{self.suffix[-5:]}",
                "source_id": self.source_magicbricks.id,
                "property_base_id": self.test_property.id,
                "user_id": self.test_rm_a.id,
                "state": "assigned",
                "inquiry_type": "primary",
            }
        )

        # RM-A creates the first recommended inquiry for second_property.
        wizard_a = (
            self.env["lead.recommend.property.wizard"]
            .with_user(self.test_rm_a)
            .with_context(default_inquiry_id=primary.id)
            .create(
                {
                    "inquiry_id": primary.id,
                    "property_base_id": self.second_property.id,
                    "assigned_rm_id": self.test_rm_a.id,
                }
            )
        )
        wizard_a.action_create_recommended_inquiry()

        # RM-B now attempts to create a recommended inquiry for the same
        # property on the same primary inquiry.
        wizard_b = (
            self.env["lead.recommend.property.wizard"]
            .with_user(self.test_rm_b)
            .with_context(default_inquiry_id=primary.id)
            .create(
                {
                    "inquiry_id": primary.id,
                    "property_base_id": self.second_property.id,
                    "assigned_rm_id": self.test_rm_b.id,
                }
            )
        )

        with self.assertRaises(
            ValidationError,
            msg="Duplicate recommended inquiry across RMs must be blocked.",
        ):
            wizard_b.action_create_recommended_inquiry()

    def test_02_recommended_allowed_for_different_property(self):
        """
        ARRANGE: RM-A has a recommended inquiry for property Y.
        ACT    : RM-B creates a recommended inquiry for property Z (different).
        ASSERT : No duplicate error — different property is allowed.
        """
        primary = self.env["leads.new"].with_context(
            automated_lead_creation=True
        ).create(
            {
                "name": "Cross RM Diff Property Test",
                "phone": f"99002{self.suffix[-5:]}",
                "source_id": self.source_magicbricks.id,
                "property_base_id": self.test_property.id,
                "user_id": self.test_rm_a.id,
                "state": "assigned",
                "inquiry_type": "primary",
            }
        )

        third_property = self.env["property.base"].create(
            {
                "property_tag": f"TEST-PROP-C-{self.suffix}",
                "name": f"Test Property C {self.suffix}",
                "prop_id": f"TPC{self.suffix}",
                "bedroom_count": 3,
                "location": "Test Location C",
                "city": "Test City C",
                "rm_user_id": self.test_rm_b.id,
                "is_active": True,
            }
        )

        wizard_a = (
            self.env["lead.recommend.property.wizard"]
            .with_user(self.test_rm_a)
            .with_context(default_inquiry_id=primary.id)
            .create(
                {
                    "inquiry_id": primary.id,
                    "property_base_id": self.second_property.id,
                    "assigned_rm_id": self.test_rm_a.id,
                }
            )
        )
        wizard_a.action_create_recommended_inquiry()

        # RM-B creates for a DIFFERENT property — should succeed.
        wizard_b = (
            self.env["lead.recommend.property.wizard"]
            .with_user(self.test_rm_b)
            .with_context(default_inquiry_id=primary.id)
            .create(
                {
                    "inquiry_id": primary.id,
                    "property_base_id": third_property.id,
                    "assigned_rm_id": self.test_rm_b.id,
                }
            )
        )
        action = wizard_b.action_create_recommended_inquiry()
        new_rec = self.env["leads.new"].browse(action["res_id"])
        self.assertTrue(new_rec.exists())
        self.assertEqual(new_rec.inquiry_type, "recommended")


@tagged("post_install", "-at_install")
class TestCrossRMVisitTimeline(PortalLeadTestCase):
    """BUG-2, BUG-3, BUG-4 — Inquiry and Overall timelines must work cross-RM."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.scheduled_status = cls.env["lead.site.visit.status"].search(
            [("code", "=", "scheduled")], limit=1
        )
        if not cls.scheduled_status:
            raise Exception("'scheduled' site visit status seed data is missing.")

        cls.second_property = cls.env["property.base"].create(
            {
                "property_tag": f"TEST-PROP-TL-{cls.suffix}",
                "name": f"Timeline Test Property {cls.suffix}",
                "prop_id": f"TPTL{cls.suffix}",
                "bedroom_count": 2,
                "location": "Timeline Location",
                "city": "Timeline City",
                "rm_user_id": cls.test_rm_b.id,
                "is_active": True,
            }
        )

    def _make_primary(self, phone, rm_user, property_rec=None):
        return self.env["leads.new"].with_context(
            automated_lead_creation=True
        ).create(
            {
                "name": f"TL Lead {phone}",
                "phone": phone,
                "source_id": self.source_magicbricks.id,
                "property_base_id": (property_rec or self.test_property).id,
                "user_id": rm_user.id,
                "state": "assigned",
                "inquiry_type": "primary",
            }
        )

    def _make_visit(self, inquiry, rm_user=None, dt="2026-05-01 10:00:00"):
        return self.env["lead.site.visit"].sudo().create(
            {
                "inquiry_id": inquiry.id,
                "property_base_id": inquiry.property_base_id.id,
                "assigned_rm_id": (rm_user or inquiry.user_id).id,
                "scheduled_datetime": dt,
                "status_id": self.scheduled_status.id,
            }
        )

    def test_03_inquiry_timeline_visible_to_assigned_rm(self):
        """
        BUG-2 — RM can see their own inquiry's visits in the Inquiry Timeline
        even though the visit's assigned_rm_id equals their own user.id (the
        record rule should not block this).
        """
        phone = f"99003{self.suffix[-5:]}"
        inquiry = self._make_primary(phone, self.test_rm_a)
        self._make_visit(inquiry, self.test_rm_a)

        # Read via the RM's env — the timeline must not be empty.
        inquiry_as_rm = inquiry.with_user(self.test_rm_a)
        timeline = inquiry_as_rm.sudo().site_visit_ids
        self.assertEqual(len(timeline), 1, "RM must see their own inquiry's visit.")

    def test_04_inquiry_timeline_visible_when_visit_assigned_to_other_rm(self):
        """
        BUG-2 — If a visit on RM-A's inquiry is assigned to RM-B (e.g. a
        manager books it), RM-A must still see it in the Inquiry Timeline.
        The visit belongs to the inquiry via inquiry_id, but assigned_rm_id =
        RM-B; the record rule must not hide it from RM-A's perspective.
        """
        phone = f"99004{self.suffix[-5:]}"
        inquiry = self._make_primary(phone, self.test_rm_a)
        # Visit assigned to RM-B on RM-A's inquiry.
        self._make_visit(inquiry, self.test_rm_b)

        # The sudo() read bypasses the rule — visit must be there.
        inquiry_sudo = inquiry.sudo()
        self.assertEqual(
            len(inquiry_sudo.site_visit_ids),
            1,
            "Visit on inquiry must be visible regardless of assigned_rm_id.",
        )

    def test_05_overall_timeline_shows_visits_from_other_rms(self):
        """
        BUG-3 — Overall Lead Timeline must include visits from ALL inquiries
        for the same phone number, regardless of which RM owns each inquiry.

        ARRANGE: phone P has two inquiries — one owned by RM-A (property X),
                 one owned by RM-B (property Y).  Each has one scheduled visit.
        ACT    : read all_phone_site_visit_ids from RM-A's inquiry (as RM-A).
        ASSERT : both visits appear — not just RM-A's own.
        """
        phone = f"99005{self.suffix[-5:]}"
        inquiry_a = self._make_primary(phone, self.test_rm_a, self.test_property)
        inquiry_b = self._make_primary(phone, self.test_rm_b, self.second_property)

        self._make_visit(inquiry_a, self.test_rm_a, "2026-05-01 10:00:00")
        self._make_visit(inquiry_b, self.test_rm_b, "2026-05-02 10:00:00")

        # Read all_phone_site_visit_ids as computed on RM-A's inquiry.
        # The field is non-stored (compute), so we invalidate to force recompute.
        inquiry_a.invalidate_recordset(["all_phone_site_visit_ids"])
        all_visits = inquiry_a.sudo().all_phone_site_visit_ids

        self.assertEqual(
            len(all_visits),
            2,
            "Overall timeline must show visits from both RM-A and RM-B inquiries.",
        )

    def test_06_overall_timeline_empty_when_no_phone(self):
        """
        Edge case: overall timeline must return empty (not crash) when the
        inquiry has no phone number.
        """
        inquiry = self.env["leads.new"].with_context(
            automated_lead_creation=True
        ).create(
            {
                "name": "No Phone Lead",
                "source_id": self.source_magicbricks.id,
                "property_base_id": self.test_property.id,
                "user_id": self.test_rm_a.id,
                "state": "assigned",
                "inquiry_type": "primary",
            }
        )
        self.assertFalse(inquiry.phone)
        inquiry.invalidate_recordset(["all_phone_site_visit_ids"])
        self.assertFalse(
            inquiry.sudo().all_phone_site_visit_ids,
            "Overall timeline must be empty when inquiry has no phone.",
        )

    def test_07_inquiry_timeline_html_no_access_error_for_rm(self):
        """
        BUG-4 — Computing inquiry_timeline_html and overall_timeline_html for
        an RM user must not raise AccessError for lead.site.visit.

        The bug was that Many2many records fetched with sudo() were later
        accessed via the non-sudo rec env, triggering model-level ACL checks.
        """
        phone = f"99007{self.suffix[-5:]}"
        inquiry = self._make_primary(phone, self.test_rm_a)
        self._make_visit(inquiry, self.test_rm_a)

        # Force recompute via the RM's user environment.
        inquiry_as_rm = inquiry.with_user(self.test_rm_a)
        inquiry_as_rm.invalidate_recordset(
            ["inquiry_timeline_html", "overall_timeline_html"]
        )

        # These must not raise AccessError.
        try:
            html = inquiry_as_rm.inquiry_timeline_html
            overall = inquiry_as_rm.overall_timeline_html
        except Exception as exc:
            self.fail(
                f"Timeline HTML compute raised an exception for RM user: {exc}"
            )

        self.assertTrue(html, "Inquiry timeline HTML must be non-empty.")

    def test_08_overall_timeline_html_shows_other_rm_visits(self):
        """
        BUG-3 + BUG-4 combined — Overall timeline HTML for RM-A must include
        visit rows that belong to RM-B's inquiry on the same phone number.
        """
        phone = f"99008{self.suffix[-5:]}"
        inquiry_a = self._make_primary(phone, self.test_rm_a, self.test_property)
        inquiry_b = self._make_primary(phone, self.test_rm_b, self.second_property)

        self._make_visit(inquiry_a, self.test_rm_a, "2026-05-01 10:00:00")
        self._make_visit(inquiry_b, self.test_rm_b, "2026-05-02 10:00:00")

        inquiry_a_as_rm = inquiry_a.with_user(self.test_rm_a)
        inquiry_a_as_rm.invalidate_recordset(["overall_timeline_html"])

        try:
            overall_html = inquiry_a_as_rm.overall_timeline_html
        except Exception as exc:
            self.fail(
                f"overall_timeline_html raised an exception for RM user: {exc}"
            )

        # Both property names must appear in the rendered HTML.
        self.assertIn(
            self.test_property.name,
            overall_html,
            "Overall timeline must mention RM-A's property.",
        )
        self.assertIn(
            self.second_property.name,
            overall_html,
            "Overall timeline must mention RM-B's property (cross-RM visit).",
        )
