from odoo.tests import tagged
from odoo.exceptions import ValidationError
from odoo.tools import mute_logger
import psycopg2
from .test_portal_common import PortalLeadTestCase

@tagged('post_install', '-at_install')
class TestPortalLeadCRUD(PortalLeadTestCase):
    """
    Test basic CRUD operations and field behaviors for leads.new records.

    Model integration notes
    -----------------------
    Tests that pass current_status or site_visit_date directly to create_portal_lead()
    or call write() on the record do so for unit-test isolation. In production,
    current_status and site_visit_date are populated by
    lead.site.visit._sync_inquiry_snapshot when a visit is created or updated,
    not by direct writes on leads.new.
    """
    
    def test_01_create_lead_with_required_fields(self):
        """Test creating a lead with minimum required fields."""
        lead = self.create_portal_lead()

        self.assertEqual(lead.name, 'Test Lead')
        self.assertEqual(lead.source_id.name, 'MagicBricks')
        self.assertEqual(lead.state, 'new')
        self.assertEqual(lead.current_status, 'lead')
        self.assertFalse(lead.is_webhook_sent)

    
    def test_02_missing_required_fields(self):
        """Test that name field is required"""
        with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.IntegrityError):
            self.env['leads.new'].create({
                'phone': '9876543210',
                'source_id': self.source_magicbricks.id,
                # 'name' is missing -> Crash expected
            })

        vals = {
            'name': 'Default State Test',
            'phone': '9876543210',
            'source_id': self.source_magicbricks.id,
            # 'state' is omitted entirely
        }
        lead = self.env['leads.new'].with_context(automated_lead_creation=True).create(vals)
        self.assertEqual(lead.state, 'new')

    def test_04_related_property_fields(self):
        """Test that related property fields populate correctly."""
        lead = self.create_portal_lead(property_base_id=self.test_property.id)

        self.assertEqual(lead.base_property_bhk, '3 BHK')
        self.assertEqual(lead.base_property_location, 'Test Location')
        self.assertEqual(lead.base_property_city, 'Test City')
        self.assertEqual(lead.base_property_link, self.test_property.property_link)

    
    def test_05_compute_create_date_only(self):
        """Test that create_date_only is computed correctly."""
        lead = self.create_portal_lead()
        
        self.assertIsNotNone(lead.create_date_only)
        self.assertIsInstance(lead.create_date_only,  type(lead.create_date.date()))
        self.assertEqual(lead.create_date_only, lead.create_date.date())

    
    def test_06_compute_site_visit_date_only(self):
        """
        Verify that site_visit_date_only (Date) is computed from site_visit_date (Datetime).

        current_status and site_visit_date are set directly here for isolation.
        In production both fields are written by lead.site.visit._sync_inquiry_snapshot
        when a visit is created; site_visit_date_only is then computed automatically.
        """
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

        # Case 2: Explicit Creation — bde_id is required when is_ops_sale_lead is True
        bde = self.env["leads.bde"].create({"name": "Test BDE"})
        lead_ops = self.create_portal_lead(
            name="OPS Specialized Lead",
            is_ops_sale_lead=True,
            bde_id=bde.id,
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

        Note: current_status is set directly here for field isolation. In
        production the "site_visit_done" status arrives via
        lead.site.visit._sync_inquiry_snapshot when a visit is marked completed.
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

    def test_11_bde_ops_sale_required(self):
        """
        BDE is mandatory when is_ops_sale_lead is True.
        Setting the flag without a BDE must raise a ValidationError.
        """
        with self.assertRaises(ValidationError):
            self.create_portal_lead(name="Ops Lead No BDE", is_ops_sale_lead=True)

    def test_12_bde_rm_restriction_enforced(self):
        """
        A BDE with allowed_rm_ids set blocks any RM not on the list.
        """
        with self.assertRaises(ValidationError):
            self.create_portal_lead(
                name="Blocked Ops Lead",
                is_ops_sale_lead=True,
                bde_id=self.test_bde_restricted.id,
                user_id=self.test_rm_a.id,  # not in test_bde_restricted.allowed_rm_ids
            )

    def test_13_bde_rm_restriction_allowed(self):
        """
        An RM in a BDE's allowed_rm_ids can be assigned that BDE successfully.
        """
        lead = self.create_portal_lead(
            name="Allowed Ops Lead",
            is_ops_sale_lead=True,
            bde_id=self.test_bde_restricted.id,
            user_id=self.test_rm_b.id,  # IS in test_bde_restricted.allowed_rm_ids
        )
        self.assertEqual(lead.bde_id, self.test_bde_restricted)

    def test_14_bde_open_allows_any_rm(self):
        """
        A BDE with no allowed_rm_ids is open — any RM can be assigned to it.
        """
        lead = self.create_portal_lead(
            name="Open BDE Lead",
            is_ops_sale_lead=True,
            bde_id=self.test_bde_open.id,
            user_id=self.test_rm_a.id,  # not in any restriction list, but BDE is open
        )
        self.assertEqual(lead.bde_id, self.test_bde_open)