from odoo.tests import tagged
from .test_lead_scoring_common import LeadScoringTestCase

@tagged('post_install', '-at_install')
class TestLeadScoringEvents(LeadScoringTestCase):
    """Test lead-event relationship and event handling."""
    
    def test_01_event_one2many_relationship(self):
        """Lead should have access to events via one2many."""
        lead = self.create_lead()
        
        event1 = self.create_event(lead=lead)
        event2 = self.create_event(lead=lead)
        
        lead.invalidate_recordset(['event_ids'])
        
        self.assertEqual(len(lead.event_ids), 2)
        self.assertIn(event1, lead.event_ids)
        self.assertIn(event2, lead.event_ids)
    
    def test_02_events_isolated_per_lead(self):
        """Events should be isolated per lead."""
        lead1 = self.create_lead()
        lead2 = self.create_lead()
        
        event1 = self.create_event(lead=lead1)
        event2 = self.create_event(lead=lead2)
        
        lead1.invalidate_recordset(['event_ids'])
        lead2.invalidate_recordset(['event_ids'])
        
        self.assertEqual(len(lead1.event_ids), 1)
        self.assertEqual(len(lead2.event_ids), 1)
        self.assertNotIn(event2, lead1.event_ids)
        self.assertNotIn(event1, lead2.event_ids)
    
    def test_03_event_cascade_delete(self):
        """Deleting lead should cascade delete events."""
        lead = self.create_lead()
        event1 = self.create_event(lead=lead)
        event2 = self.create_event(lead=lead)
        
        event_ids = [event1.id, event2.id]
        
        # Delete lead
        lead.unlink()
        
        # Verify events are gone
        remaining = self.env['lead.scoring.event'].search([
            ('id', 'in', event_ids)
        ])
        
        self.assertEqual(len(remaining), 0)