from odoo.tests import tagged
from .test_lead_scoring_common import LeadScoringTestCase

@tagged('post_install', '-at_install')
class TestLeadScoringSmartButtons(LeadScoringTestCase):
    """Test smart button action methods."""
    
    def test_01_action_view_events_returns_outbound_domain(self):
        """action_view_events should return action with outbound filter."""
        lead = self.create_lead()
        
        action = lead.action_view_events()
        
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'lead.scoring.event')
        self.assertEqual(action['view_mode'], 'list,form')
        self.assertIn(('lead_id', '=', lead.id), action['domain'])
        self.assertIn(('message_direction', '=', 'outbound'), action['domain'])
    
    def test_02_action_view_replies_returns_inbound_domain(self):
        """action_view_replies should return action with inbound filter."""
        lead = self.create_lead()
        
        action = lead.action_view_replies()
        
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'lead.scoring.event')
        self.assertIn(('lead_id', '=', lead.id), action['domain'])
        self.assertIn(('message_direction', '=', 'inbound'), action['domain'])
    
    def test_03_action_view_failures_returns_failed_domain(self):
        """action_view_failures should return action with failed filter."""
        lead = self.create_lead()
        
        action = lead.action_view_failures()
        
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'lead.scoring.event')
        self.assertIn(('lead_id', '=', lead.id), action['domain'])
        self.assertIn(('event_type', '=', 'status_failed'), action['domain'])
    
    def test_04_smart_button_actions_have_default_context(self):
        """Smart button actions should set default lead_id in context."""
        lead = self.create_lead()
        
        events_action = lead.action_view_events()
        replies_action = lead.action_view_replies()
        failures_action = lead.action_view_failures()
        
        self.assertEqual(events_action['context']['default_lead_id'], lead.id)
        self.assertEqual(replies_action['context']['default_lead_id'], lead.id)
        self.assertEqual(failures_action['context']['default_lead_id'], lead.id)