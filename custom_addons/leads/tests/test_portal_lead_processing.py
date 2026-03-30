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

        self.assertEqual(lead.property_base_id, self.test_property)
        # [FIX] Changed assigned_rm_id to user_id to match model
        self.assertEqual(lead.user_id, self.rm_user) 
        self.assertEqual(lead.state, 'assigned')

    def test_08_process_lead_magicbricks_not_found_assigns_mayuri(self):
        """Should assign to Mayuri Malivad when property not found for MagicBricks portal."""
        lead = self.create_portal_lead(
            portal_name="MagicBricks",
            portal_property_id="NON_EXISTENT_ID",
            state='new'
        )

        lead._process_lead_logic()

        self.assertEqual(lead.user_id, self.mayuri_user)
        self.assertEqual(lead.state, 'assigned')
        self.assertFalse(lead.property_base_id)

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
        self.assertFalse(lead.property_base_id)
        self.assertEqual(lead.user_id, original_user)
        self.assertEqual(lead.state, 'assigned')

    def test_11_process_ops_lead_assignment(self):
        """
        Test that an OPS sales lead is processed and assigned correctly.
        Ensures the flag does not interfere with standard RM assignment.
        """
        # Create an OPS lead
        lead = self.create_portal_lead(
            name="OPS Processing Test",
            portal_name='MagicBricks',
            portal_property_id=self.mb_id, 
            is_ops_sale_lead=True  # Ensure this matches your singular field name
        )
        
        # Trigger processing
        lead._process_lead_logic()  # Using the internal logic method consistent with other tests
        
        # Verification 1: Flag remains True
        self.assertTrue(lead.is_ops_sale_lead, "Processing should not alter OPS flag")
        
        # Verification 2: RM was still assigned
        # Since we passed a valid 'portal_property_id' (self.mb_id) that links to 'self.test_property',
        # and 'self.test_property' has 'self.rm_user', the lead should be assigned to that RM.
        self.assertEqual(
            lead.user_id, 
            self.rm_user, 
            "OPS Leads should still be assigned an RM if property matches"
        )

    def test_12_process_lead_99acres_not_found_assigns_pratham(self):
        """Should assign to configured fallback user when property not found for 99acres."""
        lead = self.create_portal_lead(
            portal_name="99acres",
            portal_property_id="NON_EXISTENT_99ACRES_ID",
            state='new'
        )

        lead._process_lead_logic()

        self.assertEqual(lead.user_id, self.pratham_user)
        self.assertEqual(lead.state, 'assigned')
        self.assertFalse(lead.property_base_id)
        self.assertIn(self.pratham_user.name, lead.process_notes)

    def test_13_process_lead_housing_not_found_assigns_naresh(self):
        """Should assign to configured fallback user when property not found for Housing.com."""
        lead = self.create_portal_lead(
            portal_name="Housing.com",
            portal_property_id="NON_EXISTENT_HOUSING_ID",
            state='new'
        )

        lead._process_lead_logic()

        self.assertEqual(lead.user_id, self.naresh_user)
        self.assertEqual(lead.state, 'assigned')
        self.assertFalse(lead.property_base_id)
        self.assertIn(self.naresh_user.name, lead.process_notes)

    def test_14_process_lead_olx_not_found_assigns_naresh(self):
        """Should assign to configured fallback user when property not found for OLX."""
        lead = self.create_portal_lead(
            portal_name="OLX",
            portal_property_id="NON_EXISTENT_OLX_ID",
            state='new'
        )

        lead._process_lead_logic()

        self.assertEqual(lead.user_id, self.naresh_user)
        self.assertEqual(lead.state, 'assigned')
        self.assertFalse(lead.property_base_id)
        self.assertIn(self.naresh_user.name, lead.process_notes)

    def test_15_process_lead_unknown_portal_not_found_assigns_naresh(self):
        """Should assign to Naresh Rojiya (default) when property not found for unknown portal."""
        lead = self.create_portal_lead(
            portal_name="UnknownPortal",
            portal_property_id="NON_EXISTENT_ID",
            state='new'
        )

        lead._process_lead_logic()

        self.assertEqual(lead.user_id, self.naresh_user)
        self.assertEqual(lead.state, 'assigned')
        self.assertFalse(lead.property_base_id)