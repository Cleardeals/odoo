# -*- coding: utf-8 -*-
"""Phone validation on manually entered leads.

RMs were able to save leads from the form with no phone number at all, or with
something that could never be dialled — ``_standardize_phone`` only logged a
warning and stored whatever digits it was given.

The guard is scoped to manual entry on purpose. Every automated creator
(portal webhooks, the CSV import wizard, the SquareYards/OLX pulls, WhatsApp
triage, the recommend wizard) passes ``automated_lead_creation``; the lead form
is the only one that does not. A portal sending a malformed number must still
land the lead — losing a real inbound enquiry is worse than storing a number an
RM has to correct.
"""

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .test_portal_common import PortalLeadTestCase


@tagged('post_install', '-at_install')
class TestLeadPhoneValidation(PortalLeadTestCase):

    def _source(self):
        return self.env['leads.new']._get_or_create_source('PhoneTest')

    def _manual_vals(self, phone, **extra):
        vals = {
            'name': 'Phone Test %s' % self.suffix,
            'phone': phone,
            'source_id': self._source().id,
        }
        vals.update(extra)
        return vals

    def _create_manual(self, phone, **extra):
        """Create the way the lead form does — no automated context."""
        return self.env['leads.new'].create(self._manual_vals(phone, **extra))

    # ── Rejected ─────────────────────────────────────────────────────────────

    def test_missing_phone_is_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            self._create_manual('')
        self.assertIn('phone number is required', str(ctx.exception).lower())

    def test_none_phone_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._create_manual(None)

    def test_whitespace_only_phone_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._create_manual('   ')

    def test_too_short_phone_is_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            self._create_manual('98765')
        self.assertIn('10-digit', str(ctx.exception))

    def test_too_long_phone_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._create_manual('98765432101234')

    def test_letters_only_phone_is_rejected(self):
        """Strips to nothing, so it reads as missing rather than malformed."""
        with self.assertRaises(ValidationError):
            self._create_manual('not a number')

    def test_landline_style_number_is_rejected(self):
        """Indian mobiles start 6-9; the whole system reaches people on WhatsApp."""
        with self.assertRaises(ValidationError) as ctx:
            self._create_manual('2234567890')
        self.assertIn('6, 7, 8 or 9', str(ctx.exception))

    def test_all_zeroes_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._create_manual('0000000000')

    def test_trunk_prefixed_number_is_rejected(self):
        """'08012345678' is a Bangalore landline, not a mobile.

        Trimming the leading zero would yield '8012345678', which merely looks
        like a mobile — ``_standardize_phone`` deliberately leaves 11-digit
        numbers whole (see test_portal_lead_phone.test_16), so accepting this
        would store an 11-digit value nobody can dial. Make the RM retype it.
        """
        with self.assertRaises(ValidationError):
            self._create_manual('08012345678')

    # ── Accepted, and normalised on the way in ───────────────────────────────

    def test_plain_ten_digits_is_accepted(self):
        lead = self._create_manual('9876543210')
        self.assertEqual(lead.phone, '9876543210')

    def test_country_code_is_accepted_and_stripped(self):
        lead = self._create_manual('+91 98765 43210')
        self.assertEqual(lead.phone, '9876543210')

    def test_punctuation_is_accepted(self):
        lead = self._create_manual('(98765)-43210')
        self.assertEqual(lead.phone, '9876543210')

    def test_each_valid_leading_digit_is_accepted(self):
        for first in '6789':
            with self.subTest(first=first):
                lead = self._create_manual('%s87654321%s' % (first, first))
                self.assertTrue(lead.id)

    # ── Editing ──────────────────────────────────────────────────────────────

    def test_writing_a_bad_phone_is_rejected(self):
        lead = self._create_manual('9876543210')
        with self.assertRaises(ValidationError):
            lead.write({'phone': '123'})

    def test_writing_a_good_phone_is_accepted(self):
        lead = self._create_manual('9876543210')
        lead.write({'phone': '8123456789'})
        self.assertEqual(lead.phone, '8123456789')

    def test_editing_other_fields_on_a_legacy_bad_row_still_works(self):
        """Existing rows with bad numbers must not become uneditable.

        Odoo only runs a constraint when one of its trigger fields is written,
        so touching an unrelated field must not trip the phone check. Without
        this, every legacy row with a bad number would be frozen.
        """
        lead = self.env['leads.new'].with_context(
            automated_lead_creation=True).create(self._manual_vals('123'))
        self.assertEqual(lead.phone, '123')

        lead.write({'name': 'Renamed, phone untouched'})
        self.assertEqual(lead.name, 'Renamed, phone untouched')

    # ── Automated paths are deliberately exempt ──────────────────────────────

    def test_automated_creation_allows_a_bad_number(self):
        """A portal sending junk must still land the lead, not lose it."""
        lead = self.env['leads.new'].with_context(
            automated_lead_creation=True).create(self._manual_vals('123'))
        self.assertTrue(lead.id)

    def test_automated_creation_allows_a_missing_number(self):
        lead = self.env['leads.new'].with_context(
            automated_lead_creation=True).create(self._manual_vals(''))
        self.assertTrue(lead.id)

    # ── The rule itself ──────────────────────────────────────────────────────

    def test_validation_helper_returns_empty_for_valid(self):
        self.assertEqual(
            self.env['leads.new']._phone_validation_error('9876543210'), '')

    def test_validation_helper_explains_the_problem(self):
        msg = self.env['leads.new']._phone_validation_error('12345')
        self.assertTrue(msg)
        self.assertIn('12345', msg, "the rejected value is quoted back")
