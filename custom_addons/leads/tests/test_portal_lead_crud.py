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
