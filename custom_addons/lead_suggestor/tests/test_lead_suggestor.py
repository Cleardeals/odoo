# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import ValidationError, AccessError
from odoo.tools import mute_logger
from unittest.mock import patch, MagicMock
from datetime import date, timedelta

@tagged('post_install', '-at_install')
class TestLeadSuggestor(TransactionCase):

    @classmethod
    def setUpClass(cls):
        """
        Global Setup: Create data reused across multiple tests.
        Executed once per class.
        """
        super().setUpClass()
        
        # 1. Create User
        cls.rm_user = cls.env['res.users'].create({
            'name': 'Test RM',
            'login': 'test_rm_user',
            'email': 'test_rm@example.com',
        })

        # 2. Assign Group using the Odoo 19 standard field name: 'user_ids'
        group_internal = cls.env.ref('base.group_user')
        group_internal.write({'user_ids': [(4, cls.rm_user.id)]})
        
        # Create a Property Inventory record
        cls.test_property = cls.env['property.inventory'].create({
            'property_tag': 'TEST-PROP-001',
            'rm_user_id': cls.rm_user.id,
            'is_active': True,
            'service_expiry_date': date(2026, 3, 14), # Fixed date for testing
            'welcome_call_date': date(2025, 12, 14),  # Fixed date for testing
        })

    def test_01_suggestion_counts_compute(self):
        """ Test Case: Verify that total and new suggestion counts calculate correctly. """
        Suggestion = self.env['property.lead.suggestion']
        
        Suggestion.create({
            'property_inventory_id': self.test_property.id,
            'suggested_lead_phone': '9876543210',
            'status': 'new',
        })
        
        Suggestion.create({
            'property_inventory_id': self.test_property.id,
            'suggested_lead_phone': '9876543211',
            'status': 'contacted',
        })

        # Force recompute
        self.test_property.invalidate_recordset()
        
        self.assertEqual(self.test_property.suggestion_count, 2, "Total suggestions should be 2")
        self.assertEqual(self.test_property.new_suggestion_count, 1, "New suggestions should be 1")

    def test_02_whatsapp_url_logic_indian(self):
        """ Test Case: Verify '91' is prepended correctly for 10-digit Indian numbers. """
        suggestion = self.env['property.lead.suggestion'].create({
            'property_inventory_id': self.test_property.id,
            'suggested_lead_phone': '9876543210', 
            'status': 'new',
        })
        url = suggestion.suggested_lead_phone_whatsapp_url
        self.assertTrue(url, "WhatsApp URL should be generated")
        self.assertIn('phone=919876543210', url, "URL should contain 91 prefix")

    def test_03_whatsapp_url_logic_garbage(self):
        """ Test Case: Verify URL is False for invalid phone numbers. """
        suggestion = self.env['property.lead.suggestion'].create({
            'property_inventory_id': self.test_property.id,
            'suggested_lead_phone': 'INVALID_NUMBER', 
            'status': 'new',
        })
        self.assertFalse(suggestion.suggested_lead_phone_whatsapp_url, "Invalid phone should result in False URL")

    def test_04_unique_constraint(self):
        """ Test Case: Verify that adding the same lead phone to the same property raises an error. """
        self.env['property.lead.suggestion'].create({
            'property_inventory_id': self.test_property.id,
            'suggested_lead_phone': '9999999999',
        })
        
        with self.assertRaises(Exception): 
            with mute_logger('odoo.sql_db'): 
                self.env['property.lead.suggestion'].create({
                    'property_inventory_id': self.test_property.id,
                    'suggested_lead_phone': '9999999999', # Duplicate
                })

    def test_05_client_action_context(self):
        """ Test Case: Verify the 'action_whatsapp_with_copy' returns the correct dictionary. """
        suggestion = self.env['property.lead.suggestion'].create({
            'property_inventory_id': self.test_property.id,
            'suggested_lead_phone': '9876543210',
            'lead_name': 'John Doe'
        })
        action = suggestion.action_whatsapp_with_copy()
        self.assertEqual(action['tag'], 'whatsapp_with_copy', "Action tag must match the JS registry name")
        self.assertIn('Hey John!', action['context']['message_text'], "Message text should contain lead name")

    @patch('google.cloud.bigquery.Client')
    def test_06_cron_sync_mocked(self, mock_bq_client):
        """ Test Case: Mock BigQuery to test the syncing logic without touching Google Cloud. """
        mock_instance = mock_bq_client.return_value
        mock_query_job = MagicMock()
        mock_instance.query.return_value = mock_query_job
        
        from collections import namedtuple
        BQRow = namedtuple('Row', ['active_property_tag', 'suggested_lead_phone', 'lead_name', 
                                   'original_property_tag', 'original_property_similarity', 
                                   'generation_date', 'current_status'])
        
        mock_rows = [
            BQRow(active_property_tag='TEST-PROP-001', suggested_lead_phone='1111111111', 
                  lead_name='Mock User', original_property_tag='OLD-PROP', 
                  original_property_similarity=0.85, generation_date=date.today(), 
                  current_status='New')
        ]
        mock_query_job.result.return_value = mock_rows

        self.env['property.lead.suggestion']._cron_sync_suggestions()

        new_suggestion = self.env['property.lead.suggestion'].search([
            ('suggested_lead_phone', '=', '1111111111'),
            ('property_inventory_id', '=', self.test_property.id)
        ])
        self.assertTrue(new_suggestion, "Cron job should have created a suggestion from the mock data")

    def test_07_date_display_formatting(self):
        """ 
        Test Case: Verify that the computed display fields strictly format dates as DD/MM/YYYY.
        This ensures UI consistency regardless of Odoo's locale settings.
        """
        # 1. Verify Property Inventory Dates
        prop = self.test_property
        self.assertEqual(prop.service_expiry_date_display, "14/03/2026", "Service Expiry should differ from system locale")
        self.assertEqual(prop.welcome_call_date_display, "14/12/2025", "Welcome Call should differ from system locale")

        # 2. Verify Suggestion Date
        suggestion = self.env['property.lead.suggestion'].create({
            'property_inventory_id': prop.id,
            'suggested_lead_phone': '5555555555',
            'generation_date': date(2024, 1, 1) 
        })
        self.assertEqual(suggestion.generation_date_display, "01/01/2024", "Generation Date should be DD/MM/YYYY")# -*- coding: utf-8 -*-