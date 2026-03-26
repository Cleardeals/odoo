# -*- coding: utf-8 -*-
import requests

from odoo.tests import tagged
from unittest.mock import patch, MagicMock
from .test_portal_common import PortalLeadTestCase

@tagged('post_install', '-at_install')
class TestPortalLeadAPI(PortalLeadTestCase):
    """
    Test external API integrations (Housing.com) with mocking.
    """

    def setUp(self):
        super().setUp()
        # Setup System Parameters for Housing API
        self.env['ir.config_parameter'].sudo().set_param('housing.api.key', 'test_key')
        self.env['ir.config_parameter'].sudo().set_param('housing.api.id', 'test_id')

    @patch('requests.get')
    def test_01_housing_api_fetch_success(self, mock_get):
        """Should successfully fetch and parse leads from Housing.com API."""
        # 1. Mock API Response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'data': [
                {
                    'lead_name': 'API Tester',
                    'lead_phone': '9876543210',
                    'lead_email': 'api@test.com',
                    'flat_id': 'HSG123',
                    'apartment_names': 'Test Apt',
                    'locality_name': 'Test Loc'
                }
            ]
        }
        mock_get.return_value = mock_response
        
        # 2. Call Method
        leads = self.env['leads.new']._api_fetch_housing()
        
        # 3. Verify Parsing
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]['lead_name'], 'API Tester')
        self.assertEqual(leads[0]['property_code'], 'HSG123')

    @patch('requests.get')
    def test_02_housing_api_no_leads(self, mock_get):
        """Should handle empty data gracefully."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'data': []}
        mock_get.return_value = mock_response
        
        leads = self.env['leads.new']._api_fetch_housing()
        self.assertEqual(len(leads), 0)

    @patch('requests.get')
    def test_03_housing_api_error(self, mock_get):
        """Should handle HTTP/Connection errors gracefully (return empty list)."""
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection Refused")
        
        leads = self.env['leads.new']._api_fetch_housing()
        self.assertEqual(len(leads), 0)

    @patch('odoo.addons.leads.models.new_portal_leads.NewPortalLead._api_fetch_housing')
    def test_04_cron_full_flow(self, mock_fetch):
        """
        INTEGRATION TEST: 
        Simulate the Cron Job (_cron_pull_external_leads).
        1. Mock the fetch method to return 1 valid lead pointing to our Test Property.
        2. Run the Cron.
        3. Verify Lead is Created, Linked to Property, and Assigned to RM.
        """
        # 1. Mock Return Data (Use self.hsg_id to match existing property)
        mock_fetch.return_value = [{
            'lead_name': 'Cron Job Lead',
            'lead_phone': '9998887776',
            'lead_email': 'cron@test.com',
            'property_code': self.hsg_id, # [IMPORTANT] Dynamic ID matches Test Property
            'project': 'Test Project',
            'raw_json': {'id': 1}
        }]

        # 2. Run the Cron Method
        self.env['leads.new']._cron_pull_external_leads()

        # 3. Verify Creation
        lead = self.env['leads.new'].search([('name', '=', 'Cron Job Lead')], limit=1)
        self.assertTrue(lead, "Cron should have created the lead")
        
        # 4. Verify Processing Logic (Property Linking)
        self.assertEqual(lead.portal_name, 'Housing.com')
        self.assertEqual(lead.property_base_id, self.test_property, "Lead should link to Test Property")
        self.assertEqual(lead.user_id, self.rm_user, "Lead should be assigned to RM")
        self.assertEqual(lead.state, 'assigned')