from odoo.tests import tagged
from odoo.tools import mute_logger
from psycopg2 import IntegrityError # Import DB Error
from .test_lead_scoring_common import LeadScoringTestCase

@tagged('post_install', '-at_install')
class TestLeadScoringCRUD(LeadScoringTestCase):
    """Test basic CRUD operations for lead.scoring.lead model."""

    def test_01_create_lead_with_required_fields(self):
        """Should create lead with minimum required fields."""
        lead = self.create_lead()
        self.assertTrue(lead.id)
        self.assertTrue(lead.lead_phone)

    def test_02_lead_phone_required(self):
        """Lead Phone field should be required (Database Constraint)."""
        # Mute the logger because the DB error will print a traceback even if caught
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.env['lead.scoring.lead'].create({
                'lead_name': 'Test Lead',
                # lead_phone is missing
                'property_tag': 'PROP-TEST-REQ'
            })

    def test_03_unique_phone_constraint(self):
        """Phone numbers should be unique across leads."""
        phone = '9876543210'

        # Create first lead
        self.create_lead(lead_phone=phone)

        # Attempt to create second lead with same phone
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
            self.create_lead(lead_phone=phone)
    
    def test_04_default_values(self):
        """Should set appropriate default values."""
        lead = self.create_lead()

        # Check computed fields default to False
        self.assertFalse(lead.is_delivered)
        self.assertFalse(lead.is_read)
        self.assertFalse(lead.has_replied)

    def test_05_workflow_stage_values(self):
        """Should accept all valid workflow stage values."""
        valid_stages = [
            'ringing',
            'detail_shared_of_property_message',
            'site_visit_schedule_reminder',
            'site_visit_schedule_after_visit',
            'other'
        ]

        for stage in valid_stages:
            # create_lead now handles unique phones automatically
            lead = self.create_lead(workflow_stage=stage)
            self.assertEqual(lead.workflow_stage, stage)

    def test_06_optional_fields_storage(self):
        """Should correctly store optional fields"""
        lead = self.create_lead(
            lead_name='John Doe',
            property_tag='PROP-12345',
            assigned_rm='RM Smith',
            predicted_score=0.92,
            current_status='interested'
        )

        self.assertEqual(lead.lead_name, 'John Doe')
        self.assertEqual(lead.property_tag, 'PROP-12345')
        self.assertEqual(lead.assigned_rm, 'RM Smith')
        self.assertEqual(lead.predicted_score, 0.92)
        self.assertEqual(lead.current_status, 'interested')

    def test_07_lead_ordering(self):
        """Leads should be ordered by last_activity descending."""
        from datetime import datetime, timedelta
        
        # Create leads (unique phones handled by helper)
        lead1 = self.create_lead()
        lead2 = self.create_lead()
        lead3 = self.create_lead()
        
        # Create events with different timestamps
        self.create_event(
            lead=lead1,
            event_timestamp=datetime.now() - timedelta(days=2)
        )
        self.create_event(
            lead=lead2,
            event_timestamp=datetime.now()
        )
        self.create_event(
            lead=lead3,
            event_timestamp=datetime.now() - timedelta(days=1)
        )
        
        # Force recompute/flush
        self.env.flush_all()
        for lead in [lead1, lead2, lead3]:
            lead.invalidate_recordset(['last_activity'])
        
        # Search and check order
        leads = self.env['lead.scoring.lead'].search([
            ('id', 'in', [lead1.id, lead2.id, lead3.id])
        ])
        
        # Expect order: lead2 (now), lead3 (yesterday), lead1 (2 days ago)
        self.assertEqual(leads[0], lead2)
        self.assertEqual(leads[1], lead3)
        self.assertEqual(leads[2], lead1)