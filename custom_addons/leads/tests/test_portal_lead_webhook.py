# -*- coding: utf-8 -*-
from odoo.tests import tagged
from unittest.mock import patch, MagicMock
import json
from .test_portal_common import PortalLeadTestCase

@tagged('post_install', '-at_install')
class TestPortalLeadWebhook(PortalLeadTestCase):
    """
    Test webhook functionality (sending leads to n8n).
    """

    @patch('requests.post')
    def test_01_webhook_sends_unsent_leads(self, mock_post):
        """Webhook cron should send unsent leads."""
        mock_post.return_value.raise_for_status = lambda: None
        
        self.env['ir.config_parameter'].sudo().set_param(
            'n8n.new_lead_webhook_url',
            'https://test.webhook.com'
        )
        
        lead = self.create_portal_lead(
            property_base_id=self.test_property.id,
            user_id=self.rm_user.id,
            is_webhook_sent=False
        )
        self.assertFalse(lead.is_webhook_sent)
        
        self.env['leads.new']._cron_send_new_lead_webhooks()
        
        self.assertTrue(mock_post.called, "requests.post should have been called")
        
        lead.invalidate_recordset()
        self.assertTrue(lead.is_webhook_sent, "Lead should be marked as sent")

    @patch('requests.post')
    def test_02_webhook_includes_property_details(self, mock_post):
        """Webhook payload should include specific property details."""
        mock_post.return_value.raise_for_status = lambda: None
        
        self.env['ir.config_parameter'].sudo().set_param(
            'n8n.new_lead_webhook_url',
            'https://test.webhook.com'
        )
        
        # Create a Unique Lead for this test
        unique_name = f"Webhook Test Lead {self.suffix}"
        lead = self.create_portal_lead(
            name=unique_name,
            property_base_id=self.test_property.id,
            user_id=self.rm_user.id,
            is_webhook_sent=False
        )
        
        self.env['leads.new']._cron_send_new_lead_webhooks()
        
        # Extract Payload
        call_args = mock_post.call_args
        payload = json.loads(call_args[1]['data'])
        
        target_lead_data = next((item for item in payload if item['name'] == unique_name), None)
        
        self.assertIsNotNone(target_lead_data, "Created lead not found in webhook payload")
        
        # Verify Details
        self.assertEqual(target_lead_data['property_bhk'], '3 BHK')
        self.assertIn(self.rm_user.name, target_lead_data['rm_name'])
        self.assertEqual(target_lead_data['property_tag'], self.test_property.property_tag)

    def test_03_webhook_skips_if_url_not_configured(self):
        """Should skip webhook if URL not configured."""
        self.env['ir.config_parameter'].sudo().set_param(
            'n8n.new_lead_webhook_url', ''
        )
        
        lead = self.create_portal_lead(is_webhook_sent=False)
        
        self.env['leads.new']._cron_send_new_lead_webhooks()
        
        lead.invalidate_recordset()
        self.assertFalse(lead.is_webhook_sent)