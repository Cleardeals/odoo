from odoo.tests import tagged
from .test_lead_scoring_common import LeadScoringTestCase

@tagged('post_install', '-at_install')
class TestLeadScoringMetrics(LeadScoringTestCase):
    """Test smart button metrics: total_outbound, total_inbound, total_failed."""
    
    def test_01_initial_counts_zero(self):
        """New lead should have zero counts."""
        lead = self.create_lead()
        
        self.assertEqual(lead.total_outbound, 0)
        self.assertEqual(lead.total_inbound, 0)
        self.assertEqual(lead.total_failed, 0)
    
    def test_02_total_outbound_counts_unique_messages(self):
        """total_outbound should count unique sent messages by correlation_id."""
        lead = self.create_lead()
        
        # Send 2 unique messages
        self.create_outbound_sent_event(lead, 'ringing', 'corr_001')
        self.create_outbound_sent_event(lead, 'detail_shared_of_property_message', 'corr_002')
        
        lead.invalidate_recordset()
        self.assertEqual(lead.total_outbound, 2)
    
    def test_03_total_outbound_ignores_status_events(self):
        """total_outbound should NOT count status events."""
        lead = self.create_lead()
        corr_id = 'corr_003'
        
        # Send message
        self.create_outbound_sent_event(lead, 'ringing', corr_id)
        
        # Status events for same correlation_id
        self.create_status_event(lead, 'status_delivered', corr_id)
        self.create_status_event(lead, 'status_read', corr_id)
        
        lead.invalidate_recordset()
        # Should only count the initial send, not status updates
        self.assertEqual(lead.total_outbound, 1)
    
    def test_04_total_outbound_deduplicates_same_correlation(self):
        """total_outbound should count each correlation_id only once."""
        lead = self.create_lead()
        corr_id = 'corr_dup'
        
        # Multiple events with same correlation_id
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
        self.assertEqual(lead.total_outbound, 1)
    
    def test_05_total_inbound_counts_all_replies(self):
        """total_inbound should count all inbound messages."""
        lead = self.create_lead()
        
        self.create_inbound_event(lead, 'Reply 1')
        self.create_inbound_event(lead, 'Reply 2')
        self.create_inbound_event(lead, 'Reply 3')
        
        lead.invalidate_recordset()
        self.assertEqual(lead.total_inbound, 3)
    
    def test_06_total_failed_counts_unique_failures(self):
        """total_failed should count unique failed messages."""
        lead = self.create_lead()
        
        self.create_event(
            lead=lead,
            event_type='status_failed',
            correlation_id='fail_001'
        )
        self.create_event(
            lead=lead,
            event_type='status_failed',
            correlation_id='fail_002'
        )
        
        lead.invalidate_recordset()
        self.assertEqual(lead.total_failed, 2)
    
    def test_07_total_failed_deduplicates_same_correlation(self):
        """total_failed should count each correlation_id only once."""
        lead = self.create_lead()
        corr_id = 'fail_dup'
        
        self.create_event(
            lead=lead,
            event_type='status_failed',
            correlation_id=corr_id
        )
        self.create_event(
            lead=lead,
            event_type='status_failed',
            correlation_id=corr_id
        )
        
        lead.invalidate_recordset()
        self.assertEqual(lead.total_failed, 1)
    
    def test_08_last_activity_tracks_most_recent_event(self):
        """last_activity should be the timestamp of most recent event."""
        from datetime import datetime, timedelta
        lead = self.create_lead()
        
        old_time = datetime.now() - timedelta(hours=2)
        new_time = datetime.now()
        
        self.create_event(lead=lead, event_timestamp=old_time)
        self.create_event(lead=lead, event_timestamp=new_time)
        
        lead.invalidate_recordset()
        
        # Should be close to new_time (within 1 second tolerance)
        time_diff = abs((lead.last_activity - new_time).total_seconds())
        self.assertLess(time_diff, 1)