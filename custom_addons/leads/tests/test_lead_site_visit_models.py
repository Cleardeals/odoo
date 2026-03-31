from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .test_portal_common import PortalLeadTestCase


@tagged("post_install", "-at_install")
class TestLeadSiteVisitModels(PortalLeadTestCase):
    def test_01_create_site_visit_with_defaults(self):
        lead = self.create_portal_lead(
            property_base_id=self.test_property.id,
            user_id=self.rm_user.id,
        )
        scheduled = self.env["lead.site.visit.status"].search(
            [("code", "=", "scheduled")],
            limit=1,
        )

        visit = self.env["lead.site.visit"].create(
            {
                "inquiry_id": lead.id,
                "status_id": scheduled.id,
                "scheduled_datetime": "2026-04-01 10:00:00",
            },
        )

        self.assertEqual(visit.inquiry_id, lead)
        self.assertEqual(visit.property_base_id, lead.property_base_id)
        self.assertEqual(visit.assigned_rm_id, lead.user_id)
        self.assertEqual(lead.current_status, "site_visit_scheduled")

    def test_02_rescheduled_requires_previous_visit(self):
        lead = self.create_portal_lead(
            property_base_id=self.test_property.id,
            user_id=self.rm_user.id,
        )
        rescheduled = self.env["lead.site.visit.status"].search(
            [("code", "=", "rescheduled")],
            limit=1,
        )

        with self.assertRaises(ValidationError):
            self.env["lead.site.visit"].create(
                {
                    "inquiry_id": lead.id,
                    "status_id": rescheduled.id,
                    "scheduled_datetime": "2026-04-01 10:00:00",
                },
            )

    def test_03_feedback_option_must_match_status(self):
        lead = self.create_portal_lead(
            property_base_id=self.test_property.id,
            user_id=self.rm_user.id,
        )
        scheduled = self.env["lead.site.visit.status"].search(
            [("code", "=", "scheduled")],
            limit=1,
        )
        completed = self.env["lead.site.visit.status"].search(
            [("code", "=", "completed")],
            limit=1,
        )
        completed_feedback = self.env["lead.site.visit.feedback.option"].search(
            [
                ("status_id", "=", completed.id),
            ],
            limit=1,
        )

        with self.assertRaises(ValidationError):
            self.env["lead.site.visit"].create(
                {
                    "inquiry_id": lead.id,
                    "status_id": scheduled.id,
                    "feedback_option_id": completed_feedback.id,
                    "scheduled_datetime": "2026-04-01 10:00:00",
                },
            )

    def test_04_write_reschedule_creates_new_visit(self):
        """
        ARRANGE: a lead with one scheduled visit.
        ACT    : write rescheduled status + a new datetime onto that visit.
        ASSERT : the original visit is closed as 'superseded'; a new visit is
                 created with 'scheduled' status and back-links to the original.

        This verifies the core reschedule contract: writing a rescheduled status
        triggers the supersede-and-replace flow rather than mutating the original
        record in place, preserving audit history.
        """
        lead = self.create_portal_lead(
            property_base_id=self.test_property.id,
            user_id=self.rm_user.id,
        )
        scheduled = self.env["lead.site.visit.status"].search(
            [("code", "=", "scheduled")],
            limit=1,
        )
        rescheduled = self.env["lead.site.visit.status"].search(
            [("code", "=", "rescheduled")],
            limit=1,
        )
        superseded = self.env["lead.site.visit.status"].search(
            [("code", "=", "superseded")],
            limit=1,
        )

        first_visit = self.env["lead.site.visit"].create(
            {
                "inquiry_id": lead.id,
                "status_id": scheduled.id,
                "scheduled_datetime": "2026-04-01 10:00:00",
            },
        )

        first_visit.write(
            {
                "status_id": rescheduled.id,
                "scheduled_datetime": "2026-04-02 12:00:00",
            }
        )

        visits = self.env["lead.site.visit"].search(
            [("inquiry_id", "=", lead.id)],
            order="id asc",
        )
        # Reschedule creates a second visit record — two in total.
        self.assertEqual(len(visits), 2)
        # New visit links back to the original so the chain is traceable.
        self.assertEqual(visits[-1].previous_visit_id, first_visit)
        # New visit is 'scheduled' (not 'rescheduled') — a fresh open slot.
        self.assertEqual(visits[-1].status_id, scheduled)
        # Original visit is closed as 'superseded' — it no longer represents
        # an active appointment.
        self.assertEqual(first_visit.status_id, superseded)
        # The inquiry snapshot still reflects an upcoming scheduled visit.
        self.assertEqual(lead.current_status, "site_visit_scheduled")

    def test_05_recommend_wizard_uses_original_source(self):
        lead = self.create_portal_lead(
            property_base_id=self.test_property.id,
            user_id=self.rm_user.id,
        )

        secondary_property = self.env["property.base"].create(
            {
                "property_tag": "TEST-PROP-REC",
                "name": "Recommended Test Property",
                "prop_id": "TP-REC-1",
                "bedroom_count": 2,
                "location": "Recommended Location",
                "city": "Recommended City",
                "rm_user_id": self.rm_user.id,
                "is_active": True,
            }
        )

        wizard = self.env["lead.recommend.property.wizard"].with_context(
            default_inquiry_id=lead.id,
            active_model="leads.new",
            active_id=lead.id,
        ).create(
            {
                "inquiry_id": lead.id,
                "property_base_id": secondary_property.id,
                "assigned_rm_id": self.rm_user.id,
            }
        )

        action = wizard.action_create_recommended_inquiry()
        recommended = self.env["leads.new"].browse(action["res_id"])

        self.assertEqual(recommended.inquiry_type, "recommended")
        self.assertEqual(recommended.source_id, lead.source_id)

    # ─────────────────────────────────────────────────────────────────────────
    # Reschedule flow — supersede behaviour
    # ─────────────────────────────────────────────────────────────────────────

    def test_06_reschedule_closes_original_as_superseded(self):
        """
        ARRANGE: a lead with one scheduled visit.
        ACT    : write rescheduled status onto that visit.
        ASSERT : original visit's status changes to 'superseded'.

        Isolation: this test focuses only on the original visit's terminal
        state transition and does not assert on the new visit.
        """
        lead = self.create_portal_lead(
            property_base_id=self.test_property.id,
            user_id=self.rm_user.id,
        )
        scheduled = self.env["lead.site.visit.status"].search(
            [("code", "=", "scheduled")], limit=1
        )
        rescheduled = self.env["lead.site.visit.status"].search(
            [("code", "=", "rescheduled")], limit=1
        )
        superseded = self.env["lead.site.visit.status"].search(
            [("code", "=", "superseded")], limit=1
        )

        visit = self.env["lead.site.visit"].create(
            {
                "inquiry_id": lead.id,
                "status_id": scheduled.id,
                "scheduled_datetime": "2026-05-01 09:00:00",
            }
        )
        visit.write(
            {"status_id": rescheduled.id, "scheduled_datetime": "2026-05-02 09:00:00"}
        )

        self.assertEqual(
            visit.status_id,
            superseded,
            "Original visit must be superseded after a reschedule, not left as scheduled.",
        )

    def test_07_reschedule_new_visit_has_scheduled_status(self):
        """
        ARRANGE: a lead with one scheduled visit.
        ACT    : trigger reschedule flow.
        ASSERT : the newly created replacement visit has 'scheduled' status,
                 not 'rescheduled' — it represents a fresh active appointment.

        The 'rescheduled' status on the write() call is the trigger signal;
        the replacement visit itself starts life as 'scheduled'.
        """
        lead = self.create_portal_lead(
            property_base_id=self.test_property.id,
            user_id=self.rm_user.id,
        )
        scheduled = self.env["lead.site.visit.status"].search(
            [("code", "=", "scheduled")], limit=1
        )
        rescheduled = self.env["lead.site.visit.status"].search(
            [("code", "=", "rescheduled")], limit=1
        )

        original = self.env["lead.site.visit"].create(
            {
                "inquiry_id": lead.id,
                "status_id": scheduled.id,
                "scheduled_datetime": "2026-05-01 09:00:00",
            }
        )
        original.write(
            {"status_id": rescheduled.id, "scheduled_datetime": "2026-05-03 09:00:00"}
        )

        new_visit = self.env["lead.site.visit"].search(
            [("inquiry_id", "=", lead.id), ("previous_visit_id", "=", original.id)],
            limit=1,
        )
        self.assertTrue(new_visit, "A replacement visit must be created on reschedule.")
        self.assertEqual(
            new_visit.status_id,
            scheduled,
            "Replacement visit must start with 'scheduled' status.",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Computed fields
    # ─────────────────────────────────────────────────────────────────────────

    def test_08_is_overdue_open_flags_past_open_visits(self):
        """
        ARRANGE: a scheduled visit with a datetime in the past.
        ASSERT : is_overdue_open is True.
        ARRANGE: mark that visit completed.
        ASSERT : is_overdue_open becomes False — only open visits are flagged.
        """
        lead = self.create_portal_lead(
            property_base_id=self.test_property.id,
            user_id=self.rm_user.id,
        )
        scheduled = self.env["lead.site.visit.status"].search(
            [("code", "=", "scheduled")], limit=1
        )
        completed = self.env["lead.site.visit.status"].search(
            [("code", "=", "completed")], limit=1
        )

        # Past datetime → should be overdue.
        past_visit = self.env["lead.site.visit"].create(
            {
                "inquiry_id": lead.id,
                "status_id": scheduled.id,
                "scheduled_datetime": "2020-01-01 10:00:00",
            }
        )
        self.assertTrue(
            past_visit.is_overdue_open,
            "A scheduled visit in the past must be flagged as overdue.",
        )

        # Closing the visit (completed) must clear the overdue flag.
        past_visit.write({"status_id": completed.id})
        self.assertFalse(
            past_visit.is_overdue_open,
            "A completed visit must not be flagged as overdue.",
        )

    def test_09_total_inquiry_visit_count(self):
        """
        ARRANGE: a lead with no visits.
        ASSERT : total_inquiry_visit_count == 0.
        ACT    : add two visits.
        ASSERT : total_inquiry_visit_count == 2.

        This count drives the stat button on the forms view so accuracy is
        important for RM context awareness.
        """
        lead = self.create_portal_lead(
            property_base_id=self.test_property.id,
            user_id=self.rm_user.id,
        )
        scheduled = self.env["lead.site.visit.status"].search(
            [("code", "=", "scheduled")], limit=1
        )

        self.assertEqual(lead.site_visit_count, 0)

        self.env["lead.site.visit"].create(
            {
                "inquiry_id": lead.id,
                "status_id": scheduled.id,
                "scheduled_datetime": "2026-06-01 10:00:00",
            }
        )
        self.env["lead.site.visit"].create(
            {
                "inquiry_id": lead.id,
                "status_id": scheduled.id,
                "scheduled_datetime": "2026-06-08 10:00:00",
            }
        )

        self.assertEqual(lead.site_visit_count, 2)

    # ─────────────────────────────────────────────────────────────────────────
    # Wizard defaults
    # ─────────────────────────────────────────────────────────────────────────

    def test_10_add_site_visit_wizard_defaults_to_scheduled(self):
        """
        ARRANGE: an inquiry lead.
        ACT    : instantiate LeadAddSiteVisitWizard via default_get (simulating
                 the RM clicking the "Add Site Visit" button on the form view).
        ASSERT : status_id defaults to the 'scheduled' status so the RM does
                 not need to touch the status dropdown for the common case.
        """
        lead = self.create_portal_lead(
            property_base_id=self.test_property.id,
            user_id=self.rm_user.id,
        )
        scheduled = self.env["lead.site.visit.status"].search(
            [("code", "=", "scheduled")], limit=1
        )

        wizard_vals = (
            self.env["lead.add.site.visit.wizard"]
            .with_context(
                active_model="leads.new",
                active_id=lead.id,
            )
            .default_get(["inquiry_id", "status_id"])
        )

        self.assertEqual(
            wizard_vals.get("status_id"),
            scheduled.id,
            "Wizard must pre-select 'scheduled' so RMs skip the status dropdown.",
        )
