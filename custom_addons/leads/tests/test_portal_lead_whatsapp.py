from odoo.tests import tagged
from .test_portal_common import PortalLeadTestCase

@tagged('post_install', '-at_install')
class TestPortalLeadWhatsapp(PortalLeadTestCase):
    """Test Whatsapp URL generation and functionality"""

    def test_01_whatsapp_url_10_digit_phone(self):
        """Should generate URL generation and functionality"""
        lead = self.create_portal_lead(phone='9876543210')

        self.assertEqual(
            lead.phone_whatsapp_url,
            'whatsapp://send?phone=919876543210'
        )
    

    def test_02_whatsapp_url_with_91_prefix(self):
        """Should handle phone already with 91 prefix"""

        lead = self.create_portal_lead(phone='919876543210')

        self.assertEqual(
            lead.phone_whatsapp_url,
            'whatsapp://send?phone=919876543210'
        )

    
    def test_03_whatsapp_url_no_phone(self):
        """Should return false when no phone"""
        lead = self.create_portal_lead(phone='')

        self.assertFalse(lead.phone_whatsapp_url)


    def test_04_whatsapp_html_includes_icon(self):
        """Should generate proper message for Whatsapp action."""
        lead = self.create_portal_lead(
            phone='9876543210'
        )

        self.assertIn('fa-whatsapp', lead.phone_whatsapp_html)
        self.assertIn('href=', lead.phone_whatsapp_html)

    def test_05_action_whatsapp_generates_message(self):
        """Should generate proper message for WhatsApp action."""
        lead = self.create_portal_lead(
            name='John Doe',
            property_base_id=self.test_property.id,
            portal_name='MagicBricks'
        )
        
        result = lead.action_whatsapp_with_copy()
        
        self.assertEqual(result['type'], 'ir.actions.client')
        self.assertEqual(result['tag'], 'whatsapp_with_copy')
        self.assertIn('whatsapp_url', result['context'])
        self.assertIn('message_text', result['context'])
        
        message = result['context']['message_text']
        self.assertIn('John Doe', message)
        self.assertIn('3 BHK', message)
        self.assertIn('Test Location', message)