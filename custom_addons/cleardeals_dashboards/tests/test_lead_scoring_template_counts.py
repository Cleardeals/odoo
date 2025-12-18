from odoo.tests import tagged
from .test_lead_scoring_common import LeadScoringTestCase

@tagged('post_install', '-at_install')
class TestLeadScoringTemplateCounts(LeadScoringTestCase):
    """Test granular template counting fields."""

    def test_01_all_template_counts_initially_zero(self):
        """New lead should have all template counts at zero."""
        lead = self.create_lead()

        # Trigger templates
        self.assertEqual(lead.cnt_ringing, 0)
        self.assertEqual(lead.cnt_details, 0)
        self.assertEqual(lead.cnt_visit_reminder, 0)
        self.assertEqual(lead.cnt_visit_feedback, 0)
        
        # Response templates
        self.assertEqual(lead.cnt_resp_going_visit, 0)
        self.assertEqual(lead.cnt_resp_need_help, 0)
        self.assertEqual(lead.cnt_resp_visit_done, 0)

    def test_02_cnt_ringing_counts_ringing_template(self):
        """cnt_ringing should count 'ringing' template sends."""
        lead = self.create_lead()

        self.create_outbound_sent_event(lead, 'ringing', 'corr_r1')
        self.create_outbound_sent_event(lead, 'ringing', 'corr_r2')

        lead.invalidate_recordset()
        self.assertEqual(lead.cnt_ringing, 2)

    def test_03_cnt_details_counts_detail_shared_template(self):
        """cnt_details should count 'detail_shared_of_property_message' template."""
        lead = self.create_lead()
        
        self.create_outbound_sent_event(
            lead, 
            'detail_shared_of_property_message', 
            'corr_d1'
        )
        
        lead.invalidate_recordset()
        self.assertEqual(lead.cnt_details, 1)

    def test_04_cnt_visit_reminder_counts_reminder_template(self):
        """cnt_visit_reminder should count site visit reminder template."""
        lead = self.create_lead()
        
        self.create_outbound_sent_event(
            lead,
            'site_visit_schedule_reminder',
            'corr_vr1'
        )
        
        lead.invalidate_recordset()
        self.assertEqual(lead.cnt_visit_reminder, 1)

    def test_05_cnt_visit_feedback_counts_feedback_template(self):
        """cnt_visit_feedback should count after visit template."""
        lead = self.create_lead()
        
        self.create_outbound_sent_event(
            lead,
            'site_visit_schedule_after_visit',
            'corr_vf1'
        )
        
        lead.invalidate_recordset()
        self.assertEqual(lead.cnt_visit_feedback, 1)

    def test_06_response_templates_counted_separately(self):
        """Response templates should be counted in their own fields."""
        lead = self.create_lead()
        
        # Different response templates
        self.create_outbound_sent_event(lead, 'going_for_visit_today', 'r1')
        self.create_outbound_sent_event(lead, 'need_help_for_site_visit_today', 'r2')
        self.create_outbound_sent_event(lead, 'ringing_abhi_call_kare', 'r3')
        
        lead.invalidate_recordset()
        
        self.assertEqual(lead.cnt_resp_going_visit, 1)
        self.assertEqual(lead.cnt_resp_need_help, 1)
        self.assertEqual(lead.cnt_resp_abhi_call, 1)

    def test_07_template_counts_deduplicate_by_correlation(self):
        """Template counts should deduplicate by correlation_id."""
        lead = self.create_lead()
        corr_id = 'corr_dup'
        
        # Same correlation_id, multiple events
        self.create_event(
            lead=lead,
            event_type='message_sent',
            message_direction='outbound',
            template_name='ringing',
            correlation_id=corr_id
        )
        self.create_event(
            lead=lead,
            event_type='status_sent',
            message_direction='outbound',
            template_name='ringing',
            correlation_id=corr_id
        )
        
        lead.invalidate_recordset()
        self.assertEqual(lead.cnt_ringing, 1)

    def test_08_template_counts_ignore_non_template_events(self):
        """Template counts should ignore events without template_name."""
        lead = self.create_lead()
        
        # Event without template
        self.create_event(
            lead=lead,
            event_type='message_sent',
            message_direction='outbound',
            template_name=False,
            correlation_id='corr_no_template'
        )
        
        lead.invalidate_recordset()
        self.assertEqual(lead.cnt_ringing, 0)

    def test_09_template_counts_only_outbound(self):
        """Template counts should only count outbound messages."""
        lead = self.create_lead()
        
        # Inbound event (shouldn't be counted)
        self.create_event(
            lead=lead,
            event_type='message_received',
            message_direction='inbound',
            template_name='ringing',  # Shouldn't have template, but testing logic
            correlation_id='corr_inbound'
        )
        
        lead.invalidate_recordset()
        self.assertEqual(lead.cnt_ringing, 0)

    def test_10_multiple_templates_counted_independently(self):
        """Multiple different templates should be counted in their fields."""
        lead = self.create_lead()
        
        self.create_outbound_sent_event(lead, 'ringing', 'c1')
        self.create_outbound_sent_event(lead, 'ringing', 'c2')
        self.create_outbound_sent_event(lead, 'detail_shared_of_property_message', 'c3')
        self.create_outbound_sent_event(lead, 'site_visit_schedule_reminder', 'c4')
        
        lead.invalidate_recordset()
        
        self.assertEqual(lead.cnt_ringing, 2)
        self.assertEqual(lead.cnt_details, 1)
        self.assertEqual(lead.cnt_visit_reminder, 1)
        self.assertEqual(lead.cnt_visit_feedback, 0)