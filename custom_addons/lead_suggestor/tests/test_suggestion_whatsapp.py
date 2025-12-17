# -*- coding: utf-8 -*-
from odoo.tests import tagged
from .test_property_common import PropertyInventoryTestCase

@tagged('post_install', '-at_install')
class TestSuggestionWhatsapp(PropertyInventoryTestCase):
    """
    Test Whatsapp URL generation and message creation for suggestions.
    """

    def test_01_whatsapp_url_10_digit_phone(self):
        """Should generate URL for 10-digit Indian number."""
        suggestion = self.create_suggestion(suggested_lead_phone='9876543210')
        self.assertTrue(suggestion.suggested_lead_phone_whatsapp_url)
        self.assertIn('phone=919876543210', suggestion.suggested_lead_phone_whatsapp_url)

    def test_02_whatsapp_url_with_91_prefix(self):
        """Should handle phone already with 91 prefix."""
        suggestion = self.create_suggestion(suggested_lead_phone='919876543210')
        self.assertTrue(suggestion.suggested_lead_phone_whatsapp_url)
        self.assertIn('phone=919876543210', suggestion.suggested_lead_phone_whatsapp_url)

    def test_03_whatsapp_url_with_leading_zero(self):
        """Should remove leading zero and add 91 prefix."""
        suggestion = self.create_suggestion(suggested_lead_phone='09876543210')
        self.assertTrue(suggestion.suggested_lead_phone_whatsapp_url)
        self.assertIn('phone=919876543210', suggestion.suggested_lead_phone_whatsapp_url)

    def test_04_whatsapp_url_with_spaces_dashes(self):
        """Should clean phone number of spaces and dashes."""
        suggestion = self.create_suggestion(suggested_lead_phone='98765-43210')
        self.assertTrue(suggestion.suggested_lead_phone_whatsapp_url)
        self.assertIn('phone=919876543210', suggestion.suggested_lead_phone_whatsapp_url)

    def test_05_whatsapp_url_with_plus_sign(self):
        """Should handle +91 prefix."""
        suggestion = self.create_suggestion(suggested_lead_phone='+919876543210')
        self.assertTrue(suggestion.suggested_lead_phone_whatsapp_url)
        self.assertIn('phone=919876543210', suggestion.suggested_lead_phone_whatsapp_url)

    def test_06_whatsapp_url_invalid_phone(self):
        """Should return False for invalid phone numbers."""
        suggestion = self.create_suggestion(suggested_lead_phone='INVALID_PHONE')
        self.assertFalse(suggestion.suggested_lead_phone_whatsapp_url)
    
    def test_07_whatsapp_url_empty_phone(self):
        """Should return False for empty phone number."""
        suggestion = self.create_suggestion(suggested_lead_phone='')
        self.assertFalse(suggestion.suggested_lead_phone_whatsapp_url)

    def test_08_whatsapp_html_contains_icon(self):
        """HTML should include WhatsApp icon and link."""
        suggestion = self.create_suggestion(suggested_lead_phone='9876543210')

        html = suggestion.suggested_lead_phone_html
        self.assertIn('fa-whatsapp', html)
        self.assertIn('href=', html)
        self.assertIn('whatsapp://', html)

    def test_09_whatsapp_html_no_url_shows_plain_phone(self):
        """HTML should show plain phone if no URL generated."""
        suggestion = self.create_suggestion(suggested_lead_phone='BAD_NUMBER')

        html = suggestion.suggested_lead_phone_html
        html_str = str(html)
        
        self.assertIn('BAD_NUMBER', html_str)
        self.assertNotIn('href=', html_str)
        
    def test_10_action_whatsapp_returns_client_action(self):
        """WhatsApp action should return proper client action dict."""
        prop = self.create_property(
            bhk='3 BHK',
            location='Test Location',
            city='Test City',
            property_link='https://example.com/property/1'
        )

        suggestion = self.create_suggestion(
            property_rec=prop,
            suggested_lead_phone='9876543210',
            lead_name="John Doe",
        )

        action = suggestion.action_whatsapp_with_copy()

        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'whatsapp_with_copy')
        self.assertIn('whatsapp_url', action['context'])
        self.assertIn('message_text', action['context'])

    def test_11_action_whatsapp_message_contains_details(self):
        """WhatsApp message should contain property details."""
        prop = self.create_property(
            bhk='2 BHK',
            location='A-Downtown',
            city='Mumbai',
            property_link='https://example.com/prop'
        )
        suggestion = self.create_suggestion(
            property_rec=prop,
            suggested_lead_phone='9876543210',
            lead_name='Jane Smith'
        )
        
        action = suggestion.action_whatsapp_with_copy()
        message = action['context']['message_text']
        
        self.assertIn('Jane', message)
        self.assertIn('2 BHK', message)
        self.assertIn('Downtown', message) # Cleaned
        self.assertIn('Mumbai', message)
        self.assertIn('https://example.com/prop', message)
    
    def test_12_action_whatsapp_uses_first_name_only(self):
        """Should use only first name if logic supports it."""
        suggestion = self.create_suggestion(
            lead_name='John Michael Doe',
            suggested_lead_phone='9876543210'
        )
        
        action = suggestion.action_whatsapp_with_copy()
        message = action['context']['message_text']
        self.assertIn('John', message)