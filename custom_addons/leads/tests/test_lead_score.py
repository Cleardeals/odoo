from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.tools import mute_logger
import psycopg2
from odoo.exceptions import ValidationError
from datetime import date, timedelta

@tagged('post_install', '-at_install')
class TestLeadScore(TransactionCase):
    """
    Enhanced Test Suite for 'lead.score' model.
    Covers:
    - Basic CRUD and Defaults
    - Actionable Flag Logic (_compute_is_actionable_today)
    - Follow-up Date Logic (_compute_next_follow_up_date)
    - UI Onchange logic (_onchange_state_set_follow_up)
    - Integration with WhatsApp Response Count
    - Edge cases and error conditions
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user_rm = cls.env.ref('base.user_admin')

    def setUp(self):
        """Create a fresh lead for each test to ensure independence."""
        super().setUp()
        self.lead = self.env['lead.score'].create({
            'name': 'Test Lead',
            'standardized_phone': '9876543210',
            'assigned_rm_id': self.user_rm.id,
            'predicted_score': 0.85
        })

    def test_01_default_values(self):
        """Verify default values are set correctly upon creation."""
        self.assertEqual(self.lead.current_status, 'lead', 
                        "Default current_status should be 'lead'.")
        self.assertEqual(self.lead.state, 'lead', 
                        "Default state should be 'lead'.")
        self.assertTrue(self.lead.is_actionable_today, 
                       "New leads without follow-up date should be actionable by default.")
        # Additional default checks
        self.assertEqual(self.lead.next_follow_up_date, date.today(),
                        "next_follow_up_date should be today's date initially")
        self.assertEqual(self.lead.whatsapp_response_count, 0,
                        "Initial WhatsApp response count should be 0")

    def test_02_required_fields(self):
        """Verify that required fields are enforced."""
        # 1. We expect an IntegrityError (Validation Success)
        # 2. We mute 'odoo.sql_db' so the expected error doesn't spam the logs
        with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.IntegrityError):
            self.env['lead.score'].create({
                'standardized_phone': '1234567890',
                # Missing 'name' triggers the crash we WANT to see
            })


    def test_03_actionable_flag_logic(self):
        """
        Verify 'is_actionable_today' computes correctly based on dates.
        Logic: True if date is Today or Past, False if future, True if None.
        """
        today = date.today()

        # Case 1: No date set -> Actionable
        self.lead.next_follow_up_date = False
        self.assertTrue(self.lead.is_actionable_today, 
                       "Lead should be actionable when no follow-up date is set")

        # Case 2: Future Date -> Not Actionable
        self.lead.next_follow_up_date = today + timedelta(days=5)
        self.assertFalse(self.lead.is_actionable_today, 
                        "Lead should NOT be actionable for future date")

        # Case 3: Today -> Actionable
        self.lead.next_follow_up_date = today
        self.assertTrue(self.lead.is_actionable_today, 
                       "Lead should be actionable for today's date")

        # Case 4: Past Date -> Actionable (Overdue)
        self.lead.next_follow_up_date = today - timedelta(days=2)
        self.assertTrue(self.lead.is_actionable_today, 
                       "Lead should be actionable for past date (overdue)")

        # Case 5: Boundary - Yesterday
        self.lead.next_follow_up_date = today - timedelta(days=1)
        self.assertTrue(self.lead.is_actionable_today,
                       "Lead should be actionable for yesterday (overdue)")

        # Case 6: Boundary - Tomorrow
        self.lead.next_follow_up_date = today + timedelta(days=1)
        self.assertFalse(self.lead.is_actionable_today,
                        "Lead should NOT be actionable for tomorrow")

    def test_04_site_visit_follow_up_logic(self):
        """
        Verify 'next_follow_up_date' is automatically set to (Site Visit Date + 1 day)
        when status is 'site_visit_scheduled'.
        """
        visit_date = date.today() + timedelta(days=3)

        # Set Site Visit Date first
        self.lead.site_visit_scheduled_date = visit_date

        # Change status to trigger compute logic
        self.lead.current_status = 'site_visit_scheduled'

        expected_date = visit_date + timedelta(days=1)
        self.assertEqual(
            self.lead.next_follow_up_date,
            expected_date,
            f"Follow-up date should be 1 day after site visit. "
            f"Got {self.lead.next_follow_up_date}, expected {expected_date}."
        )

    def test_05_rescheduled_follow_up_logic(self):
        """
        Verify that 'rescheduled' status also triggers follow-up date computation
        similar to 'site_visit_scheduled'.
        """
        visit_date = date.today() + timedelta(days=7)
        
        self.lead.site_visit_scheduled_date = visit_date
        self.lead.current_status = 'rescheduled'

        expected_date = visit_date + timedelta(days=1)
        self.assertEqual(
            self.lead.next_follow_up_date,
            expected_date,
            "Rescheduled status should set follow-up to 1 day after visit date"
        )

    def test_06_site_visit_without_date(self):
        """
        Verify behavior when site_visit_scheduled status is set but no date is provided.
        """
        today = date.today()
        
        # Don't set site_visit_scheduled_date
        self.lead.site_visit_scheduled_date = False
        self.lead.current_status = 'site_visit_scheduled'

        # Should fall back to default behavior (today if not set)
        self.assertTrue(
            self.lead.next_follow_up_date == today or self.lead.next_follow_up_date is False,
            "Should handle missing site visit date gracefully"
        )

    def test_07_onchange_status_behavior(self):
        """
        Verify UI Onchange behavior: Changing status (non-site-visit)
        should push follow-up to Tomorrow.
        
        NOTE: onchange methods don't automatically trigger in tests,
        must be called explicitly.
        """
        today = date.today()

        # Simulate Onchange: User changes status to 'ringing'
        self.lead.current_status = 'ringing'
        self.lead._onchange_state_set_follow_up()  # Fixed: added underscore prefix

        expected_date = today + timedelta(days=1)
        self.assertEqual(
            self.lead.next_follow_up_date,
            expected_date,
            "Changing status to 'ringing' should set follow-up to tomorrow."
        )

    def test_08_onchange_does_not_affect_site_visit(self):
        """
        Verify onchange doesn't override site visit logic.
        """
        visit_date = date.today() + timedelta(days=5)
        
        self.lead.site_visit_scheduled_date = visit_date
        self.lead.current_status = 'site_visit_scheduled'
        
        # Store the computed date
        expected_date = self.lead.next_follow_up_date
        
        # Trigger onchange - it should NOT change the date
        self.lead._onchange_state_set_follow_up()
        
        self.assertEqual(
            self.lead.next_follow_up_date,
            expected_date,
            "Onchange should not override site visit scheduled date"
        )

    def test_09_whatsapp_integration_count(self):
        """
        Verify 'whatsapp_response_count' increments when linked records are created.
        """
        # Initially 0
        self.assertEqual(self.lead.whatsapp_response_count, 0)

        # Create first response
        self.env['whatsapp.response'].create({
            'lead_id': self.lead.id,
            'number': '9876543210',
            'response': 'yes_going_for_visit',
            'response_type': 'positive'
        })

        # Invalidate cache to force recompute
        self.lead.invalidate_recordset(['whatsapp_response_count'])
        self.assertEqual(self.lead.whatsapp_response_count, 1, 
                        "Count should be 1 after adding a response.")

        # Create second response
        self.env['whatsapp.response'].create({
            'lead_id': self.lead.id,
            'number': '9876543210',
            'response': 'need_help',
            'response_type': 'neutral'
        })

        self.lead.invalidate_recordset(['whatsapp_response_count'])
        self.assertEqual(self.lead.whatsapp_response_count, 2,
                        "Count should be 2 after adding second response.")

    def test_10_whatsapp_one2many_relationship(self):
        """
        Verify the one2many relationship works correctly.
        """
        # Create responses
        response1 = self.env['whatsapp.response'].create({
            'lead_id': self.lead.id,
            'number': '9876543210',
            'response': 'yes_going_for_visit',
            'response_type': 'positive'
        })

        self.lead.invalidate_recordset(['whatsapp_response_ids'])
        
        self.assertIn(response1, self.lead.whatsapp_response_ids,
                     "Response should be in lead's response_ids")
        self.assertEqual(response1.lead_id, self.lead,
                        "Response should link back to lead")

    def test_11_cron_job_recomputation(self):
        """Verify Cron Job logic."""
        today = date.today()
        self.lead.next_follow_up_date = today
        
        # Flush ORM writes BEFORE running raw SQL
        self.env.flush_all()

        # Force incorrect state via SQL
        self.env.cr.execute(
            "UPDATE lead_score SET is_actionable_today = false WHERE id = %s",
            (self.lead.id,)
        )
        self.lead.invalidate_recordset()

        self.assertFalse(self.lead.is_actionable_today, "Setup failed: SQL didn't stick")

        # Run Cron
        self.env['lead.score']._recompute_actionable_flag()

        self.lead.invalidate_recordset()
        self.assertTrue(self.lead.is_actionable_today, "Cron failed to fix flag")

    def test_12_cron_job_with_overdue_leads(self):
        """
        Verify cron job handles multiple overdue leads correctly.
        """
        today = date.today()
        
        # Create multiple leads with past dates but marked as not actionable
        leads = self.env['lead.score']
        for i in range(3):
            lead = self.env['lead.score'].create({
                'name': f'Overdue Lead {i}',
                'standardized_phone': f'987654321{i}',
                'assigned_rm_id': self.user_rm.id,
                'next_follow_up_date': today - timedelta(days=i+1)
            })
            # Force to false
            self.env.cr.execute(
                "UPDATE lead_score SET is_actionable_today = false WHERE id = %s",
                (lead.id,)
            )
            leads |= lead

        leads.invalidate_recordset()
        
        # Run cron
        self.env['lead.score']._recompute_actionable_flag()
        
        # Verify all are now actionable
        leads.invalidate_recordset()
        for lead in leads:
            self.assertTrue(lead.is_actionable_today,
                          f"Lead {lead.name} should be actionable after cron")

    def test_13_multiple_status_changes(self):
        """
        Test that follow-up date updates correctly through multiple status changes.
        """
        today = date.today()
        
        # First change
        self.lead.current_status = 'ringing'
        self.lead._onchange_state_set_follow_up()
        first_date = self.lead.next_follow_up_date
        self.assertEqual(first_date, today + timedelta(days=1))
        
        # Second change
        self.lead.current_status = 'call_back_later'
        self.lead._onchange_state_set_follow_up()
        second_date = self.lead.next_follow_up_date
        self.assertEqual(second_date, today + timedelta(days=1))

    def test_14_state_and_current_status_independence(self):
        """
        Verify that 'state' and 'current_status' are separate fields
        that can have different values.
        """
        self.lead.current_status = 'ringing'
        self.lead.state = 'site_visit_scheduled'
        
        self.assertEqual(self.lead.current_status, 'ringing')
        self.assertEqual(self.lead.state, 'site_visit_scheduled')
        self.assertNotEqual(self.lead.current_status, self.lead.state,
                          "current_status and state should be independent")

    def test_15_lead_ordering(self):
        """
        Verify leads are ordered by predicted_score descending.
        """
        lead1 = self.env['lead.score'].create({
            'name': 'Low Score Lead',
            'standardized_phone': '1111111111',
            'predicted_score': 0.3
        })
        
        lead2 = self.env['lead.score'].create({
            'name': 'High Score Lead',
            'standardized_phone': '2222222222',
            'predicted_score': 0.9
        })
        
        leads = self.env['lead.score'].search([
            ('id', 'in', [lead1.id, lead2.id])
        ])
        
        self.assertEqual(leads[0], lead2,
                        "Higher scored lead should come first")
        self.assertEqual(leads[1], lead1,
                        "Lower scored lead should come second")

    def test_16_feedback_fields_set_correctly(self):
        """
        Test that feedback fields can be set properly.
        """
        self.lead.feedback_general = 'buyer_not_interested'
        self.assertEqual(self.lead.feedback_general, 'buyer_not_interested')
        
        self.lead.feedback_site_visit_done = 'buyer_liked_property'
        self.assertEqual(self.lead.feedback_site_visit_done, 'buyer_liked_property')

    def test_17_edge_case_far_future_date(self):
        """
        Test with a follow-up date far in the future.
        """
        far_future = date.today() + timedelta(days=365)
        self.lead.next_follow_up_date = far_future
        
        self.assertFalse(self.lead.is_actionable_today,
                        "Lead with far future date should not be actionable")

    def test_18_edge_case_far_past_date(self):
        """
        Test with a follow-up date far in the past.
        """
        far_past = date.today() - timedelta(days=365)
        self.lead.next_follow_up_date = far_past
        
        self.assertTrue(self.lead.is_actionable_today,
                       "Lead with far past date should be actionable (very overdue)")

    def test_19_property_fields_storage(self):
        """
        Verify property-related fields store data correctly.
        """
        property_data = {
            'project_name': 'Luxury Towers',
            'property_type': 'Apartment',
            'bhk': '3 BHK',
            'price_range': '50-75',
            'location': 'Downtown'
        }
        
        self.lead.write(property_data)
        
        for field, value in property_data.items():
            self.assertEqual(getattr(self.lead, field), value,
                           f"Field {field} should store value correctly")

    def test_20_notes_field(self):
        """
        Test that notes field accepts and stores text.
        """
        test_note = "This is a test note with some details about the lead."
        self.lead.notes = test_note
        
        self.assertEqual(self.lead.notes, test_note,
                        "Notes field should store text correctly")