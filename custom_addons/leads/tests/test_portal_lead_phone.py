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

    # ------------------------------------------------------------------ #
    # Malformed input — `_standardize_phone` never raises; anything that  #
    # isn't 10 digits (or 12 digits starting "91") is logged and returned #
    # as-is (digits-only). These tests pin that fallback behaviour so a   #
    # future change to it is a deliberate decision, not a silent drift.   #
    # ------------------------------------------------------------------ #

    def test_10_standardize_too_short_returns_raw_digits(self):
        """A 5-digit number is not rejected — it's returned unchanged."""
        result = self.env['leads.new']._standardize_phone('98765')
        self.assertEqual(result, '98765')

    def test_11_standardize_too_long_returns_raw_digits(self):
        """A 15-digit number is not truncated — it's returned unchanged."""
        result = self.env['leads.new']._standardize_phone('123456789012345')
        self.assertEqual(result, '123456789012345')

    def test_12_standardize_letters_mixed_with_digits(self):
        """Letters are stripped; if the remaining digits don't fit 10/12, they pass through as-is."""
        result = self.env['leads.new']._standardize_phone('abc98765xyz')
        self.assertEqual(result, '98765')

    def test_13_standardize_letters_only_returns_empty(self):
        """No digits at all -> empty string, not an error."""
        result = self.env['leads.new']._standardize_phone('abcdef')
        self.assertEqual(result, '')

    def test_14_standardize_symbols_only_returns_empty(self):
        """Symbol-only input strips to zero digits -> empty string."""
        result = self.env['leads.new']._standardize_phone('----')
        self.assertEqual(result, '')

    def test_15_standardize_whitespace_only_returns_empty(self):
        result = self.env['leads.new']._standardize_phone('   ')
        self.assertEqual(result, '')

    def test_16_standardize_landline_11_digits_no_country_code(self):
        """An 11-digit landline-style number is not massaged down to 10 digits."""
        result = self.env['leads.new']._standardize_phone('08012345678')
        self.assertEqual(result, '08012345678')

    def test_17_standardize_us_number_11_digits_with_country_code(self):
        """A +1 (US) number that strips to 11 digits is not confused for a +91 Indian one."""
        result = self.env['leads.new']._standardize_phone('+12025551234')
        self.assertEqual(result, '12025551234')

    def test_18_standardize_twelve_digits_not_91_prefixed(self):
        """Only a 12-digit number starting with '91' is unwrapped; other 12-digit inputs pass through."""
        result = self.env['leads.new']._standardize_phone('123456789012')
        self.assertEqual(result, '123456789012')

    def test_19_standardize_eleven_digits_leading_zero_not_stripped(self):
        """No leading-zero handling exists — an 11-digit '0'-prefixed number is kept whole."""
        result = self.env['leads.new']._standardize_phone('09876543210')
        self.assertEqual(result, '09876543210')

    def test_20_standardize_us_number_coincidentally_ten_digits_misclassified(self):
        """
        KNOWN GAP: `_standardize_phone` only checks digit COUNT, not country
        validity. A +1 US number whose national number is 9 digits strips to
        exactly 10 digits total and is silently accepted as if it were a
        valid 10-digit Indian mobile number. This test documents the gap so
        a future fix is a deliberate, tested change rather than a surprise.
        """
        result = self.env['leads.new']._standardize_phone('+1202555123')
        self.assertEqual(result, '1202555123')
        self.assertEqual(len(result), 10)

    # ------------------------------------------------------------------ #
    # Malformed input & de-duplication interaction                        #
    # ------------------------------------------------------------------ #

    def test_21_malformed_nonempty_phone_still_dedupes_within_window(self):
        """A garbage-but-non-empty phone still dedupes identically against itself."""
        vals = {
            'name': 'Malformed Dedup 1',
            'phone': '98765',
            'source_id': self.source_magicbricks.id,
            'portal_property_id': self.mb_id,
            'state': 'new',
        }
        lead1 = self.env['leads.new'].create_lead_if_not_duplicate(dict(vals))
        self.assertTrue(lead1)
        self.assertEqual(lead1.phone, '98765')

        lead2 = self.env['leads.new'].create_lead_if_not_duplicate(dict(vals, name='Malformed Dedup 2'))
        self.assertFalse(lead2, "Identical malformed phone + same property must still be de-duped")

    def test_22_symbol_only_phone_bypasses_dedup_creates_duplicates(self):
        """
        KNOWN GAP: when a phone strips to an empty string, `_compute_duplicate_domain`
        cannot build a dedup key, and `create_lead_if_not_duplicate` explicitly
        creates the lead anyway rather than blocking it. Two pushes with the
        same symbol-only phone therefore create two separate leads.
        """
        vals = {
            'name': 'Empty Phone Dedup',
            'phone': '----',
            'source_id': self.source_magicbricks.id,
            'portal_property_id': self.mb_id,
            'state': 'new',
        }
        lead1 = self.env['leads.new'].create_lead_if_not_duplicate(dict(vals))
        lead2 = self.env['leads.new'].create_lead_if_not_duplicate(dict(vals))

        self.assertTrue(lead1)
        self.assertTrue(lead2, "Empty-normalised phone cannot be deduped; both pushes create leads")
        self.assertNotEqual(lead1.id, lead2.id)
        self.assertEqual(lead1.phone, '')
        self.assertEqual(lead2.phone, '')