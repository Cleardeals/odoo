from odoo.tests import tagged
from .test_portal_common import PortalLeadTestCase

@tagged('post_install', '-at_install')
class TestPortalLeadPhoneStandardization(PortalLeadTestCase):
    """Test phone number standardization logic."""
    
    def test_01_standardize_10_digit_phone(self):
        """10-digit phone should remain as-is."""
        result = self.env['leads.new']._standardize_phone('9876543210')
        self.assertEqual(result, '9876543210')
    
    def test_02_standardize_with_country_code(self):
        """12-digit phone starting with 91 should remove prefix."""
        result = self.env['leads.new']._standardize_phone('919876543210')
        self.assertEqual(result, '9876543210')
    
    def test_03_standardize_with_spaces(self):
        """Phone with spaces should be cleaned."""
        result = self.env['leads.new']._standardize_phone('98765 43210')
        self.assertEqual(result, '9876543210')
    
    def test_04_standardize_with_dashes(self):
        """Phone with dashes should be cleaned."""
        result = self.env['leads.new']._standardize_phone('98765-43210')
        self.assertEqual(result, '9876543210')
    
    def test_05_standardize_with_plus_sign(self):
        """Phone with +91 should be cleaned."""
        result = self.env['leads.new']._standardize_phone('+919876543210')
        self.assertEqual(result, '9876543210')
    
    def test_06_standardize_with_parentheses(self):
        """Phone with parentheses should be cleaned."""
        result = self.env['leads.new']._standardize_phone('(987) 654-3210')
        self.assertEqual(result, '9876543210')
    
    def test_07_standardize_empty_phone(self):
        """Empty phone should return empty string."""
        result = self.env['leads.new']._standardize_phone('')
        self.assertEqual(result, '')
    
    def test_08_standardize_none_phone(self):
        """None phone should return empty string."""
        result = self.env['leads.new']._standardize_phone(None)
        self.assertEqual(result, '')
    
    def test_09_lead_creation_standardizes_phone(self):
        """Creating a lead should standardize the phone number."""
        lead_vals = {
            'name': 'Test',
            'phone': '+91 98765-43210',
            'portal_name': 'Test',
            'portal_property_id': 'TEST123'
        }
        
        lead = self.env['leads.new'].create_lead_if_not_duplicate(lead_vals)
        self.assertEqual(lead.phone, '9876543210')