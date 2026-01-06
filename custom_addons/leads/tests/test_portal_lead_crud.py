from odoo.tests import tagged
from odoo.exceptions import ValidationError
from odoo.tools import mute_logger
import psycopg2
from .test_portal_common import PortalLeadTestCase

@tagged('post_install', '-at_install')
class TestPortalLeadCRUD(PortalLeadTestCase):
    """
    Test basic CRUD operations and field behaviors
    """
    
    def test_01_create_lead_with_required_fields(self):
        """Test creating a lead with minimum required fields."""
        lead = self.create_portal_lead()

        self.assertEqual(lead.name, 'Test Lead')
        self.assertEqual(lead.portal_name, 'MagicBricks')
        self.assertEqual(lead.state, 'new')
        self.assertEqual(lead.current_status, 'lead')
        self.assertFalse(lead.is_webhook_sent)

    
    def test_02_missing_required_fields(self):
        """Test that name field is required"""
        with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.IntegrityError):
            self.env['leads.new'].create({
                'phone': '9876543210',
                'portal_name': 'MagicBricks'
                # 'name' is missing -> Crash expected
            })

        vals = {
            'name': 'Default State Test',
            'phone': '9876543210',
            'portal_name': 'MagicBricks'
            # 'state' is omitted entirely
        }
        lead = self.env['leads.new'].create(vals)
        self.assertEqual(lead.state, 'new')

    def test_04_related_property_fields(self):
        """Test that related property fields populate correctly."""
        lead = self.create_portal_lead(property_id = self.test_property.id)

        self.assertEqual(lead.property_bhk, '3 BHK')
        self.assertEqual(lead.property_location, 'Test Location')
        self.assertEqual(lead.property_city, 'Test City')
        self.assertEqual(lead.property_link, self.test_property.property_link)

    
    def test_05_compute_create_date_only(self):
        """Test that create_date_only is computed correctly."""
        lead = self.create_portal_lead()
        
        self.assertIsNotNone(lead.create_date_only)
        self.assertIsInstance(lead.create_date_only,  type(lead.create_date.date()))
        self.assertEqual(lead.create_date_only, lead.create_date.date())

    
    def test_06_compute_site_visit_date_only(self):
        """Test site_visit_date_only computation."""
        from datetime import datetime
        visit_datetime = datetime(2025, 12, 25, 14, 40, 0)

        lead = self.create_portal_lead(current_status="site_visit_scheduled", site_visit_date=visit_datetime)
        
        self.assertEqual(lead.site_visit_date_only.day, 25)
        self.assertEqual(lead.site_visit_date_only.month, 12)
        self.assertEqual(lead.site_visit_date_only.year, 2025)

    def test_07_ops_sales_lead_flag(self):
        """
        Test that is_ops_sales_lead flag functions correctly.
        1. Verifies default is False.
        2. Verifies explicit assignment to True.
        """
        # Case 1: Default Behavior
        # We rely on your existing helper. Since we don't pass the flag, 
        # it should default to False (standard boolean behavior in Odoo).
        lead_default = self.create_portal_lead(name="Standard Lead")
        self.assertFalse(
            lead_default.is_ops_sale_lead, 
            "is_ops_sale_lead should default to False"
        )

        # Case 2: Explicit Creation
        # We pass the new field via **kwargs to your helper
        lead_ops = self.create_portal_lead(
            name="OPS Specialized Lead",
            is_ops_sale_lead=True
        )
        self.assertTrue(
            lead_ops.is_ops_sale_lead, 
            "is_ops_sale_lead should be True when explicitly set"
        )
    def test_08_feedback_general_field(self):
        """
        Test the feedback_general selection field.
        1. Verifies default is False (not set).
        2. Verifies all selection options can be set.
        """
        # Case 1: Default should be False/empty
        lead = self.create_portal_lead(name="Feedback Test Lead")
        self.assertFalse(
            lead.feedback_general,
            "feedback_general should default to False"
        )

        # Case 2: Test all valid selection values
        valid_feedback_options = [
            'buyer_did_not_visit_property',
            'buyer_not_interested',
            'buyer_not_picking_call',
            'visit_needs_to_be_rescheduled',
            'other',
        ]
        
        for feedback_value in valid_feedback_options:
            lead.write({'feedback_general': feedback_value})
            self.assertEqual(
                lead.feedback_general,
                feedback_value,
                f"feedback_general should be set to '{feedback_value}'"
            )

    def test_09_feedback_site_visit_done_field(self):
        """
        Test the feedback_site_visit_done selection field.
        1. Verifies default is False (not set).
        2. Verifies all selection options can be set.
        """
        # Case 1: Default should be False/empty
        lead = self.create_portal_lead(
            name="Site Visit Feedback Lead",
            current_status='site_visit_done'
        )
        self.assertFalse(
            lead.feedback_site_visit_done,
            "feedback_site_visit_done should default to False"
        )

        # Case 2: Test all valid selection values
        valid_feedback_options = [
            'buyer_liked_property',
            'buyer_requirement_closed',
            'buyer_visit_from_outside',
            'buyer_not_pickup_call',
            'planning_for_second_visit',
            'negotiation_stage',
            'visit_done_confirmed_by_owner',
            'looking_for_more_options',
            'price_is_high',
            'location_mismatch',
            'deal_closed',
            'other',
        ]
        
        for feedback_value in valid_feedback_options:
            lead.write({'feedback_site_visit_done': feedback_value})
            self.assertEqual(
                lead.feedback_site_visit_done,
                feedback_value,
                f"feedback_site_visit_done should be set to '{feedback_value}'"
            )

    def test_10_feedback_fields_independent(self):
        """
        Test that feedback_general and feedback_site_visit_done 
        are independent fields and can be set separately.
        """
        lead = self.create_portal_lead(name="Independent Feedback Lead")
        
        # Set only feedback_general
        lead.write({'feedback_general': 'buyer_not_interested'})
        self.assertEqual(lead.feedback_general, 'buyer_not_interested')
        self.assertFalse(lead.feedback_site_visit_done)
        
        # Set only feedback_site_visit_done (clear general first)
        lead.write({
            'feedback_general': False,
            'feedback_site_visit_done': 'buyer_liked_property'
        })
        self.assertFalse(lead.feedback_general)
        self.assertEqual(lead.feedback_site_visit_done, 'buyer_liked_property')
        
        # Set both simultaneously
        lead.write({
            'feedback_general': 'other',
            'feedback_site_visit_done': 'other'
        })
        self.assertEqual(lead.feedback_general, 'other')
        self.assertEqual(lead.feedback_site_visit_done, 'other')