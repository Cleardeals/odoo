from odoo.tests import tagged
from .test_lead_scoring_common import LeadScoringTestCase

@tagged('post_install', '-at_install')
class TestLeadScoringFunnel(LeadScoringTestCase):
    """Test funnel metric: is_delivered, is_read, has_replied."""
    
    def test_01_initial_funnel_state(self):
        """New lead should have all funnel metrics False."""
        lead = self.create_lead()

        self.assertFalse(lead.is_delivered)
        self.assertFalse(lead.is_read)
        self.assertFalse(lead.has_replied)

    def test_02_is_delivered_on_delivered_event(self):
        """is_delivered should be True when status_delivered event exists"""
        lead = self.create_lead()
        corr_id = 'corr_123'

        # Send Message
        self.create_outbound_sent_event(lead, 'ringing', correlation_id=corr_id)
        # Delivery Event
        self.create_status_event(lead, 'status_delivered', correlation_id=corr_id)

        lead.invalidate_recordset()
        self.assertTrue(lead.is_delivered)

    def test_03_is_delivered_on_read_event(self):
        """is_delivered should be True when status_read event exists"""
        lead = self.create_lead()
        corr_id = 'corr_456'

        self.create_outbound_sent_event(lead, 'ringing', correlation_id=corr_id)
        self.create_status_event(lead, 'status_read', correlation_id=corr_id)

        lead.invalidate_recordset()
        self.assertTrue(lead.is_delivered)

    def test_04_is_read_on_read_event(self):
        """is_read should be True when status_read event exists"""

        lead = self.create_lead()
        corr_id = 'corr_789'

        self.create_outbound_sent_event(lead, 'ringing', correlation_id=corr_id)
        self.create_status_event(lead, 'status_read', correlation_id=corr_id)

        lead.invalidate_recordset()
        self.assertTrue(lead.is_read)
    
    def test_05_is_read_not_set_on_delivered_event(self):
        """is_read should be False if only delivered, not read."""
        lead = self.create_lead()
        corr_id = 'corr_111'

        self.create_outbound_sent_event(lead, 'ringing', correlation_id=corr_id)
        self.create_status_event(lead, 'status_delivered', correlation_id=corr_id)


        lead.invalidate_recordset()
        self.assertTrue(lead.is_delivered)
        self.assertFalse(lead.is_read)

    def test_06_has_replied_on_inbound_message(self):
        """has_replied should be Ture when inbound message exists"""
        lead = self.create_lead()

        self.create_inbound_event(lead, 'Yes, interested')

        lead.invalidate_recordset()
        self.assertTrue(lead.has_replied)

    def test_07_last_response_captures_inbound_content(self):
        """last_response should contain the most recent inbound message"""
        lead = self.create_lead()

        self.create_inbound_event(lead, 'First message')
        self.create_inbound_event(lead, 'Second message')

        lead.invalidate_recordset()
        self.assertEqual(lead.last_response, 'Second message')
    
    def test_08_last_response_false_when_no_replies(self):
        """last_response should be False when no inbound messages"""
        lead = self.create_lead()

        # Only outbound events
        self.create_outbound_sent_event(lead, 'ringing', 'corr_999')

        lead.invalidate_recordset()
        self.assertFalse(lead.last_response)

    