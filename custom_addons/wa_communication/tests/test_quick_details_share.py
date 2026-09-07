"""Quick property-details share — the "Share Property Details" button.

The contract that matters most here is the **variable order**, pinned by
:meth:`test_body_values_match_the_template_slot_order`.  ``details_shared_v4``
takes two body variables — "<project name>, <locality>" and the website link —
and if the composition or the order drifts, the buyer is sent a card with the
wrong text in the wrong slot and nothing else in the system would notice.
"""

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.wa_communication.models.wa_conversation_outbound import (
    QUICK_SHARE_BODY_VARS,
    QUICK_SHARE_IMAGE_FALLBACK,
    QUICK_SHARE_VAR_SEPARATOR,
)

from .common import WaTransactionCase


@tagged('post_install', '-at_install', 'wa_communication')
class TestQuickDetailsShare(WaTransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Param = cls.env['ir.config_parameter'].sudo()

    def _property(self, **vals):
        # bhk and property_link are computed (from bedroom_count and
        # name + prop_id), so they are driven rather than set.
        base = {
            'name': 'Sunrise Heights',
            'prop_id': self._uniq('SH'),
            'location': 'Bopal',
            'bedroom_count': 3,
            'prop_sub_type': 'Apartment',
            'property_size': '1450 sqft',
            'furnishing_type': 'Semi Furnished',
            'primary_image_url': 'https://img.example.com/sunrise.jpg',
            'tour_360_url': 'https://tour.example.com/sunrise',
        }
        base.update(vals)
        return self.env['property.base'].sudo().create(base)

    def _lead_with_property(self, **prop_vals):
        prop = self._property(**prop_vals)
        return self.make_lead(
            phone=self._uniq_phone()[2:], property_base_id=prop.id), prop

    # ── Variable contract ────────────────────────────────────────────────────

    def test_body_values_match_the_template_slot_order(self):
        """Slot order and composition must mirror details_shared_v4 exactly."""
        lead, prop = self._lead_with_property()
        body, header = self.Conv._quick_share_values(lead)

        self.assertEqual(len(body), 2)
        # {{1}} — project name (tag stripped) and locality, in one variable.
        self.assertEqual(body[0], 'Sunrise Heights, Bopal')
        # {{2}} — the property's page on the website.
        self.assertEqual(body[1], prop.property_link)
        self.assertEqual(header, ['https://img.example.com/sunrise.jpg'])

    def test_values_come_from_the_same_snapshot_the_workflow_uses(self):
        """Reusing _wa_actor_snapshot is what keeps the wording rules in one place."""
        lead, _prop = self._lead_with_property()
        snapshot = lead._wa_actor_snapshot()['property']
        body, header = self.Conv._quick_share_values(lead)

        expected = [
            QUICK_SHARE_VAR_SEPARATOR.join(
                snapshot[key] for key, _label, _fb in parts)
            for parts in QUICK_SHARE_BODY_VARS
        ]
        self.assertEqual(body, expected)
        self.assertEqual(header, [snapshot['image_url']])

    def test_missing_image_uses_the_shared_fallback(self):
        """Same GCS asset the workflow falls back to, so both look alike."""
        lead, _prop = self._lead_with_property(primary_image_url=False)
        _body, header = self.Conv._quick_share_values(lead)
        self.assertEqual(header, [QUICK_SHARE_IMAGE_FALLBACK])

    def test_fields_the_template_no_longer_uses_do_not_block_the_send(self):
        """v4 dropped type/size/furnishing/360 — a blank one must not refuse."""
        lead, prop = self._lead_with_property(
            tour_360_url=False, property_size=False, furnishing_type=False)
        body, _header = self.Conv._quick_share_values(lead)
        self.assertEqual(body, ['Sunrise Heights, Bopal', prop.property_link])

    # ── Guards ───────────────────────────────────────────────────────────────

    def test_blank_required_field_is_refused_with_the_field_named(self):
        """Interakt rejects blank variables, so catch it while it's fixable."""
        lead, _prop = self._lead_with_property(location=False)
        with self.assertRaises(UserError) as ctx:
            self.Conv._quick_share_values(lead)
        self.assertIn('Locality', str(ctx.exception))

    def test_blank_link_is_refused(self):
        """The website link is the whole point of the card's second variable."""
        lead, prop = self._lead_with_property()
        prop.sudo().write({'property_link': False})
        with self.assertRaises(UserError) as ctx:
            self.Conv._quick_share_values(lead)
        self.assertIn('Property link', str(ctx.exception))

    def test_lead_without_property_is_refused(self):
        lead = self.make_lead(phone=self._uniq_phone()[2:])
        with self.assertRaises(UserError) as ctx:
            self.Conv._quick_share_values(lead)
        self.assertIn('no property linked', str(ctx.exception))

    def test_missing_lead_is_refused(self):
        with self.assertRaises(UserError):
            self.Conv._quick_share_values(self.env['leads.new'])

    def test_absent_lead_id_gives_a_readable_error(self):
        """A null id must not surface as a raw int() TypeError.

        The UI reads the lead id off the form record, so a stale or unsaved
        form sends nothing — the RM should be told to save, not shown a
        Python type error.
        """
        for missing in (None, False, 0, ''):
            with self.assertRaises(UserError) as ctx:
                self.Conv.send_property_details_for_lead(missing)
            self.assertIn('Save this inquiry', str(ctx.exception))

    # ── Template configuration ───────────────────────────────────────────────

    def test_template_name_comes_from_config(self):
        """Meta keeps reclassifying the copy, so the name must be swappable."""
        self.Param.set_param(
            'wa_communication.quick_share_template', 'some_other_template_v9')
        self.Param.set_param(
            'wa_communication.quick_share_template_language', 'en')
        name, lang = self.Conv._quick_share_template()
        self.assertEqual(name, 'some_other_template_v9')
        self.assertEqual(lang, 'en')

    def test_blank_template_config_is_refused(self):
        """Whitespace, not '': set_param('') deletes the key, restoring the
        default.  A whitespace value is the blank that can actually be stored,
        and it would otherwise be sent to Interakt as a template name."""
        self.Param.set_param('wa_communication.quick_share_template', '   ')
        with self.assertRaises(UserError) as ctx:
            self.Conv._quick_share_template()
        self.assertIn('quick_share_template', str(ctx.exception))

    def test_deleting_the_config_falls_back_to_the_shipped_default(self):
        self.Param.set_param('wa_communication.quick_share_template', '')
        name, lang = self.Conv._quick_share_template()
        self.assertEqual(name, 'details_shared_v4')
        self.assertEqual(lang, 'hi')

    # ── The send ─────────────────────────────────────────────────────────────

    def test_send_publishes_a_template_request_with_header_values(self):
        lead, _prop = self._lead_with_property()
        conv = self.make_conversation(
            phone_number='91%s' % lead.phone, lead_id=lead.id)

        with self.mock_pubsub() as published:
            msg = conv.send_property_details()

        self.assertEqual(msg.kind, 'template')
        self.assertEqual(msg.status, 'queued')
        self.assertEqual(msg.initiator, 'rm')

        payload = published[-1].payload
        self.assertEqual(payload['request_type'], 'send')
        self.assertEqual(payload['kind'], 'template')
        self.assertEqual(len(payload['body_values']), 2)
        self.assertEqual(
            payload['header_values'], ['https://img.example.com/sunrise.jpg'])

    def test_send_uses_the_configured_template(self):
        self.Param.set_param(
            'wa_communication.quick_share_template', 'details_shared_v4')
        lead, _prop = self._lead_with_property()
        conv = self.make_conversation(
            phone_number='91%s' % lead.phone, lead_id=lead.id)
        with self.mock_pubsub() as published:
            conv.send_property_details()
        self.assertEqual(
            published[-1].payload['template_name'], 'details_shared_v4')

    def test_send_for_lead_creates_the_conversation_when_there_is_none(self):
        """First outreach: no conversation exists yet, so make one and claim it."""
        lead, _prop = self._lead_with_property()
        with self.mock_pubsub() as published:
            conv_id = self.Conv.send_property_details_for_lead(lead.id)

        conv = self.Conv.browse(conv_id)
        self.assertTrue(conv.exists())
        self.assertEqual(conv.lead_id, lead)
        self.assertEqual(conv.assigned_user_id.id, self.env.uid)
        self.assertEqual(published[-1].payload['kind'], 'template')

    def test_send_for_lead_reuses_an_existing_conversation(self):
        lead, _prop = self._lead_with_property()
        conv = self.make_conversation(
            phone_number='91%s' % lead.phone, lead_id=lead.id)
        with self.mock_pubsub():
            returned = self.Conv.send_property_details_for_lead(lead.id)
        self.assertEqual(returned, conv.id)

    def test_send_files_under_the_shared_inquiry_not_the_active_span(self):
        """The card must be attributed to the lead the RM is acting on.

        A buyer with several inquiries has one thread, and the active span is
        whichever property was last discussed.  Inheriting it tagged the card
        with the wrong property and attributed the send to the wrong inquiry.
        """
        shared, _prop = self._lead_with_property()
        other, other_prop = self._lead_with_property()
        other.write({'phone': shared.phone})

        conv = self.make_conversation(
            phone_number='91%s' % shared.phone, lead_id=other.id)
        # The thread is mid-discussion about the OTHER property.
        conv._owa_ensure_segment(inquiry=other, started_by='rm')
        self.assertEqual(conv.active_segment_id.inquiry_id, other)

        with self.mock_pubsub():
            self.Conv.send_property_details_for_lead(shared.id)

        msg = self.Msg.sudo().search(
            [('conversation_id', '=', conv.id), ('direction', '=', 'outbound')],
            order='id desc', limit=1)
        self.assertEqual(msg.segment_id.inquiry_id, shared)
        self.assertEqual(msg.effective_inquiry_id, shared)

    def test_send_finds_the_thread_when_the_lead_is_not_its_anchor(self):
        """Second inquiry on a number: the thread is anchored to the first."""
        anchor, _p1 = self._lead_with_property()
        second, _p2 = self._lead_with_property()
        second.write({'phone': anchor.phone})
        conv = self.make_conversation(
            phone_number='91%s' % anchor.phone, lead_id=anchor.id)

        with self.mock_pubsub():
            returned = self.Conv.send_property_details_for_lead(second.id)

        self.assertEqual(returned, conv.id,
                         "must reuse the number's thread, not start a second one")

    def test_bad_property_leaves_no_orphan_conversation_behind(self):
        """Validate before creating anything, or a failed click litters the DB."""
        lead, _prop = self._lead_with_property(location=False)
        before = self.Conv.sudo().search_count([])
        with self.assertRaises(UserError):
            self.Conv.send_property_details_for_lead(lead.id)
        self.assertEqual(self.Conv.sudo().search_count([]), before)

    def test_send_counts_as_an_attempt_for_the_status_gate(self):
        """The two features meet here: sharing details unlocks the status."""
        lead, _prop = self._lead_with_property()
        conv = self.make_conversation(
            phone_number='91%s' % lead.phone, lead_id=lead.id)
        with self.mock_pubsub():
            conv.send_property_details()
        lead.invalidate_recordset()
        self.assertTrue(lead._wa_has_send_attempt())
