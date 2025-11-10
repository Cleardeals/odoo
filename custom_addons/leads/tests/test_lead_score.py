# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError, ValidationError
from datetime import date, timedelta
import logging

_logger = logging.getLogger(__name__)

class TestLeadScore(TransactionCase):
    """
    Test suite for the custom 'lead.score' model.
    """

    def setUp(self):
        """
        Set up common records for all test methods.
        """
        super(TestLeadScore, self).setUp()

        # Get today's date for comparisons
        self.today = date.today()
        self.yesterday = self.today - timedelta(days=1)
        self.tomorrow = self.today + timedelta(days=1)

        # Create a test User (RM)
        self.rm_user = self.env['res.users'].create({
            'name': 'Test RM',
            'login': 'testrm@example.com',
        })

        # Create a base lead.score record for testing
        self.lead = self.env['lead.score'].create({
            'name': 'Test Lead',
            'assigned_rm_id': self.rm_user.id,
            'standardized_phone': '1234567890',
            'predicted_score': 0.75,
        })
        self.WhatsappResponse = None
        try:
            # Use self.env['model.name'] - this is a more direct lookup.
            # If this fails, the model is definitely not in the registry.
            self.WhatsappResponse = self.env['whatsapp.response']
        except KeyError:
            _logger.warning("Model 'whatsapp.response' not found during test setup.")
            # We'll keep self.WhatsappResponse as None, and the test will skip.

    # --- Test Compute Methods ---

    def test_01_compute_next_follow_up_date_visit_scheduled(self):
        """
        Test next_follow_up_date is +1 day from site_visit_scheduled_date
        when status is 'site_visit_scheduled'.
        """
        self.lead.write({
            'current_status': 'site_visit_scheduled',
            'site_visit_scheduled_date': self.tomorrow
        })
        # Note: The compute is @api.depends, so it triggers on write.
        # We call invalidate_recordset() to be 100% sure we have the computed value.
        self.lead.invalidate_recordset()

        expected_follow_up = self.tomorrow + timedelta(days=1)
        self.assertEqual(
            self.lead.next_follow_up_date,
            expected_follow_up,
            "Follow-up date should be 1 day after site visit date."
        )

    def test_02_compute_next_follow_up_date_rescheduled(self):
        """
        Test next_follow_up_date is +1 day from site_visit_scheduled_date
        when status is 'rescheduled'.
        """
        self.lead.write({
            'current_status': 'rescheduled',
            'site_visit_scheduled_date': self.tomorrow
        })
        self.lead.invalidate_recordset()

        expected_follow_up = self.tomorrow + timedelta(days=1)
        self.assertEqual(
            self.lead.next_follow_up_date,
            expected_follow_up,
            "Follow-up date should be 1 day after rescheduled visit date."
        )

    def test_03_compute_next_follow_up_date_default_today(self):
        """
        Test that a new lead with no follow-up date defaults to today.
        """
        # The lead created in setUp() should have triggered this.
        # The compute method sets it to today if it's not set.
        self.lead.invalidate_recordset()
        self.assertEqual(
            self.lead.next_follow_up_date,
            self.today,
            "New lead's follow-up date should default to today."
        )

    def test_04_compute_is_actionable_today_true_yesterday(self):
        """Test is_actionable_today is True if follow-up date was yesterday."""
        self.lead.write({'next_follow_up_date': self.yesterday})
        self.lead.invalidate_recordset()
        self.assertTrue(
            self.lead.is_actionable_today,
            "Should be actionable if follow-up date is in the past."
        )

    def test_05_compute_is_actionable_today_true_today(self):
        """Test is_actionable_today is True if follow-up date is today."""
        self.lead.write({'next_follow_up_date': self.today})
        self.lead.invalidate_recordset()
        self.assertTrue(
            self.lead.is_actionable_today,
            "Should be actionable if follow-up date is today."
        )

    def test_06_compute_is_actionable_today_false_tomorrow(self):
        """Test is_actionable_today is False if follow-up date is tomorrow."""
        self.lead.write({'next_follow_up_date': self.tomorrow})
        self.lead.invalidate_recordset()
        self.assertFalse(
            self.lead.is_actionable_today,
            "Should not be actionable if follow-up date is in the future."
        )

    def test_07_compute_whatsapp_response_count(self):
        """Test the _compute_whatsapp_response_count method."""
        # and has a 'lead_id' field (Many2one to 'lead.score')
        if not self.WhatsappResponse:
            self.skipTest("Model 'whatsapp.response' not found (checked in setUp).")

        # 1. Initial state: count should be 0
        self.lead.invalidate_recordset()
        self.assertEqual(
            self.lead.whatsapp_response_count, 0,
            "Initial response count should be 0."
        )

        # 2. Add one response
        self.WhatsappResponse.create({
            'lead_id': self.lead.id,
            'number': self.lead.standardized_phone,
            'response': 'generic_response', # Provide a valid selection
        })
        self.lead.invalidate_recordset()
        self.assertEqual(
            self.lead.whatsapp_response_count, 1,
            "Response count should be 1 after adding a response."
        )

        # 3. Add a second response
        self.WhatsappResponse.create({
            'lead_id': self.lead.id,
            'number': self.lead.standardized_phone,
            'response': 'call_me_back', # Provide a valid selection
        })
        self.lead.invalidate_recordset()
        self.assertEqual(
            self.lead.whatsapp_response_count, 2,
            "Response count should be 2 after adding a second response."
        )

    # --- Test Onchange Methods ---

    def test_20_onchange_state_set_follow_up(self):
        """Test the _onchange_state_set_follow_up method."""
        # Onchange methods are tested on in-memory 'new' records
        lead_form = self.env['lead.score'].new({
            'name': 'Onchange Test Lead',
            'next_follow_up_date': self.today, # Start with today
        })

        # 1. Change status to one that triggers the onchange
        lead_form.current_status = 'call_back_later'
        lead_form._onchange_state_set_follow_up()

        # Check that the follow-up date was set to tomorrow
        expected_date = self.today + timedelta(days=1)
        self.assertEqual(
            lead_form.next_follow_up_date, expected_date,
            "Follow-up date should be set to tomorrow for 'call_back_later'."
        )

        # 2. Change status to one that does *not* trigger the logic
        lead_form.current_status = 'site_visit_scheduled'
        lead_form.next_follow_up_date = self.today # Reset
        lead_form._onchange_state_set_follow_up()

        # Check that the follow-up date was *not* changed
        self.assertEqual(
            lead_form.next_follow_up_date, self.today,
            "Follow-up date should not change for 'site_visit_scheduled'."
        )

    # --- Test Scheduled Actions ---

    def test_30_recompute_actionable_flag(self):
        """Test the _recompute_actionable_flag scheduled action."""
        # 1. Create a lead that *should* be actionable but isn't
        lead_to_fix = self.env['lead.score'].create({
            'name': 'Lead to Fix',
            'next_follow_up_date': self.yesterday,
            # Manually force is_actionable_today to False
            # We use 'with_context' to bypass compute for this one write
        })
        # We must use SQL to bypass the compute/write triggers
        self.env.cr.execute(
            "UPDATE lead_score SET is_actionable_today = False WHERE id = %s",
            (lead_to_fix.id,)
        )
        # DO NOT invalidate here. Invalidation may trigger a recompute
        # which defeats the purpose of the SQL update.
        # lead_to_fix.invalidate_recordset()

        # We must re-read from the DB with SQL to bypass the compute method
        self.env.cr.execute(
            "SELECT is_actionable_today FROM lead_score WHERE id = %s",
            (lead_to_fix.id,)
        )
        is_actionable = self.env.cr.fetchone()[0]
        self.assertFalse(
            is_actionable,
            "Pre-condition: is_actionable_today must be False in the database."
        )

        self.assertEqual(
            lead_to_fix.next_follow_up_date, self.yesterday,
            "Pre-condition: Follow-up date must be in the past."
        )

        # 2. Create a lead that should *not* be updated
        lead_to_ignore = self.env['lead.score'].create({
            'name': 'Lead to Ignore',
            'next_follow_up_date': self.tomorrow,
            'is_actionable_today': False, # This is correct
        })
        lead_to_ignore.invalidate_recordset()
        self.assertFalse(lead_to_ignore.is_actionable_today)

        # 3. Run the scheduled action method on all leads
        self.env['lead.score']._recompute_actionable_flag()

        # 4. Check the results
        lead_to_fix.invalidate_recordset()
        self.assertTrue(
            lead_to_fix.is_actionable_today,
            "Scheduled action should have fixed this lead."
        )

        lead_to_ignore.invalidate_recordset()
        self.assertFalse(
            lead_to_ignore.is_actionable_today,
            "Scheduled action should not have touched this lead."
        )