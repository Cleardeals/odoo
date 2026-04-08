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
        ASSERT : the original visit is closed as terminal 'Rescheduled'
                 (code='superseded'); a new visit is created with 'scheduled'
                 status and back-links to the original.

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
        rescheduled_terminal = self.env["lead.site.visit.status"].with_context(
            active_test=False
        ).search(
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
        # Original visit is closed as terminal 'Rescheduled' — it no longer
        # represents an active appointment but shows the reason it was closed.
        self.assertEqual(first_visit.status_id, rescheduled_terminal)
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

    def test_06_reschedule_closes_original_as_rescheduled(self):
        """
        ARRANGE: a lead with one scheduled visit.
        ACT    : write rescheduled status onto that visit.
        ASSERT : original visit's status changes to the terminal 'Rescheduled'
                 status (code='superseded', active=False).

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
        rescheduled_terminal = self.env["lead.site.visit.status"].with_context(
            active_test=False
        ).search(
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
            rescheduled_terminal,
            "Original visit must be closed as terminal 'Rescheduled' after a reschedule.",
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

    def test_08b_terminal_visit_rejects_status_change(self):
        """
        ARRANGE: a completed (terminal) visit.
        ACT    : attempt to write a new status_id onto it.
        ASSERT : ValidationError is raised — terminal visits are immutable.

        This covers US-08: the model-level guard is the last line of defence
        when the UI buttons are bypassed (e.g. direct API write).
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

        visit = self.env["lead.site.visit"].create(
            {
                "inquiry_id": lead.id,
                "status_id": scheduled.id,
                "scheduled_datetime": "2026-05-10 10:00:00",
            }
        )
        visit.write({"status_id": completed.id})

        with self.assertRaises(
            ValidationError,
            msg="Changing status on a terminal visit must be blocked.",
        ):
            visit.write({"status_id": scheduled.id})

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
        completed = self.env["lead.site.visit.status"].search(
            [("code", "=", "completed")], limit=1
        )

        self.assertEqual(lead.site_visit_count, 0)

        first_visit = self.env["lead.site.visit"].create(
            {
                "inquiry_id": lead.id,
                "status_id": scheduled.id,
                "scheduled_datetime": "2026-06-01 10:00:00",
            }
        )
        # Close the first visit — cannot have two active visits for the same inquiry.
        first_visit.write({"status_id": completed.id})

        self.env["lead.site.visit"].create(
            {
                "inquiry_id": lead.id,
                "status_id": scheduled.id,
                "scheduled_datetime": "2026-06-08 10:00:00",
            }
        )

        self.assertEqual(lead.site_visit_count, 2)

    # ─────────────────────────────────────────────────────────────────────────
    # Concurrent visit enforcement
    # ─────────────────────────────────────────────────────────────────────────

    def test_10a_cannot_create_second_active_visit_for_same_inquiry(self):
        """
        ARRANGE: an inquiry with one active (non-terminal) scheduled visit.
        ACT    : attempt to create a second active visit directly for the same inquiry.
        ASSERT : ValidationError is raised — only one active visit per inquiry allowed.

        The concurrent guard ensures RMs must close or reschedule an existing
        visit rather than silently stacking conflicting appointments.
        """
        lead = self.create_portal_lead(
            property_base_id=self.test_property.id,
            user_id=self.rm_user.id,
        )
        scheduled = self.env["lead.site.visit.status"].search(
            [("code", "=", "scheduled")], limit=1
        )
        self.env["lead.site.visit"].create(
            {
                "inquiry_id": lead.id,
                "status_id": scheduled.id,
                "scheduled_datetime": "2026-07-01 10:00:00",
            }
        )

        with self.assertRaises(
            Exception,
            msg="Creating a second active visit when one is already open must be blocked.",
        ):
            self.env["lead.site.visit"].create(
                {
                    "inquiry_id": lead.id,
                    "status_id": scheduled.id,
                    "scheduled_datetime": "2026-07-08 10:00:00",
                }
            )

    def test_10b_new_visit_allowed_after_terminal_close(self):
        """
        ARRANGE: an inquiry with one completed (terminal) visit.
        ACT    : create a second scheduled visit for the same inquiry.
        ASSERT : creation succeeds — terminal visits do not block new visits.
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
        first = self.env["lead.site.visit"].create(
            {
                "inquiry_id": lead.id,
                "status_id": scheduled.id,
                "scheduled_datetime": "2026-07-01 10:00:00",
            }
        )
        first.write({"status_id": completed.id})

        second = self.env["lead.site.visit"].create(
            {
                "inquiry_id": lead.id,
                "status_id": scheduled.id,
                "scheduled_datetime": "2026-07-10 10:00:00",
            }
        )
        self.assertTrue(second.id, "Second visit should be created after first is completed.")

    def test_10c_reschedule_flow_bypasses_concurrent_guard(self):
        """
        ARRANGE: an inquiry with one scheduled visit.
        ACT    : reschedule it via write(status=rescheduled, scheduled_datetime=...).
        ASSERT : no error raised; reschedule creates a new scheduled visit and closes
                 the old one as terminal 'Rescheduled' — even though the old visit is
                 still non-terminal at the moment the new one is inserted.

        This ensures the skip_active_visit_check context flag works correctly.
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

        visit = self.env["lead.site.visit"].create(
            {
                "inquiry_id": lead.id,
                "status_id": scheduled.id,
                "scheduled_datetime": "2026-07-01 10:00:00",
            }
        )
        # Must not raise even though the old visit is still open at insert time.
        visit.write(
            {"status_id": rescheduled.id, "scheduled_datetime": "2026-07-08 10:00:00"}
        )
        # After reschedule: exactly one non-terminal visit remains (the new one).
        active_visits = self.env["lead.site.visit"].search(
            [
                ("inquiry_id", "=", lead.id),
                ("status_id.is_terminal", "=", False),
            ]
        )
        self.assertEqual(len(active_visits), 1, "Exactly one active visit after reschedule.")
        self.assertEqual(active_visits.status_id, scheduled)

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
