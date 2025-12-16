# -*- coding: utf-8 -*-
from odoo.tests import tagged
from .test_portal_common import PortalLeadTestCase

@tagged('post_install', '-at_install')
class TestPortalLeadProcessing(PortalLeadTestCase):
    
    def test_01_find_property_by_magicbricks_id(self):
        lead = self.create_portal_lead(
            portal_name='MagicBricks',
            portal_property_id=self.mb_id
        )
        self.assertEqual(lead._find_property(), self.test_property)

    def test_02_find_property_by_housing_id(self):
        # Ensure 'Housing' matches your model's expected string
        lead = self.create_portal_lead(
            portal_name='Housing.com', 
            portal_property_id=self.hsg_id
        )
        self.assertEqual(lead._find_property(), self.test_property)

    def test_03_find_property_by_99acres_id(self):
        # Ensure '99Acres' matches your model
        lead = self.create_portal_lead(
            portal_name='99acres',
            portal_property_id=self.acres_id
        )
        self.assertEqual(lead._find_property(), self.test_property)

    def test_04_find_property_by_olx_id(self):
        lead = self.create_portal_lead(
            portal_name='OLX',
            portal_property_id=self.olx_id
        )
        self.assertEqual(lead._find_property(), self.test_property)

    def test_05_property_not_found_returns_empty(self):
        """Should return empty recordset if property not found."""
        lead = self.create_portal_lead(
            portal_name='MagicBricks',
            portal_property_id='NON_EXISTENT_ID'
        )
        property_rec = lead._find_property()
        self.assertFalse(property_rec)

    def test_06_find_rm_from_property(self):
        """Should find RM from property record."""
        lead = self.create_portal_lead()
        
        # Assuming the method is named _find_rm or similar. 
        # If specific method logic exists, test it. 
        # Otherwise, relying on test_07 is safer.
        # We'll use the one defined in your logic:
        rm = lead._find_rm(self.test_property)
        self.assertEqual(rm, self.rm_user)

    def test_07_process_lead_assigns_property_and_rm(self):
        """Processing should assign property and RM to lead."""
        lead = self.create_portal_lead(
            portal_name="MagicBricks",
            portal_property_id=self.mb_id,
            state='new'
        )

        lead._process_lead_logic()

        self.assertEqual(lead.property_id, self.test_property)
        # [FIX] Changed assigned_rm_id to user_id to match model
        self.assertEqual(lead.user_id, self.rm_user) 
        self.assertEqual(lead.state, 'assigned')

    def test_08_process_lead_property_not_found_assigns_naresh(self):
        """Should assign to Naresh when property not found."""
        lead = self.create_portal_lead(
            portal_name="MagicBricks",
            portal_property_id="NON_EXISTENT_ID",
            state='new'
        )

        lead._process_lead_logic()

        self.assertEqual(lead.user_id, self.naresh_user)
        self.assertEqual(lead.state, 'assigned')
        self.assertFalse(lead.property_id)

    def test_09_process_lead_adds_notes(self):
        """Processing should add notes."""
        lead = self.create_portal_lead(
            portal_name="MagicBricks",
            portal_property_id=self.mb_id,
            state='new'
        )
        
        lead._process_lead_logic()

        self.assertTrue(lead.process_notes)
        self.assertIn("Successfully assigned", lead.process_notes)

    def test_10_process_lead_skips_non_new_leads(self):
        """Should skip leads that are not in 'new' state"""
        lead = self.create_portal_lead(
            state='assigned',  # Not 'new'
            user_id = self.rm_user.id
        )
        
        original_user = lead.user_id
        lead._process_lead_logic()

        # Should NOT change
        self.assertFalse(lead.property_id)
        self.assertEqual(lead.user_id, original_user)
        self.assertEqual(lead.state, 'assigned')