"""Inbox "Create inquiry" on an orphan chat — cross-RM ownership.

An RM working an unknown-number conversation clicks "Create inquiry", names the
contact and picks the property being discussed. ``create_lead_from_chat`` runs
and used to fail for any RM, in two places:

1. ``leads.new`` carries an RM record rule of ``[('user_id', '=', user.id)]``
   that applies to **create** as well as read. The canonical creation runs
   under ``automated_lead_creation=True``, which deliberately skips the
   "manual leads are owned by their creator" branch that sets ``user_id`` — so
   the new row matched no rule and creation was refused outright.
2. Even once created, picking a property routes the lead to **that property's**
   RM (``property.base.rm_user_id``), usually somebody else. Every later touch
   of the un-elevated ``lead`` recordset — the segment bind, the system-event
   log, and the ``leads.new`` form the inbox opens on success — then raised on
   read.

Ownership here is a business decision, not a reflection of the caller's rights,
so the resolution is elevated and ``user_id`` is set before the row is written.

Regression for the staging report of 2026-08-03 (Pratham Bhandari, id=29).
"""

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import WaTransactionCase


@tagged('post_install', '-at_install', 'wa_communication')
class TestInboxCreateInquiryAccess(WaTransactionCase):
    """Triage must succeed even when the property belongs to another RM."""

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            'wa_communication.segments_enabled', '1')

        # The RM doing the triage: owns the chat, not the property.
        self.working_rm = self.make_user(login=self._uniq('wa_rm_'))
        self.working_rm.sudo().write({
            'group_ids': [
                (4, self.env.ref('leads.group_lead_score_rm').id),
                (4, self.env.ref('properties.group_property_rm').id),
            ],
        })
        # The RM who owns the property, and will end up owning the lead.
        self.property_rm = self.make_user(login=self._uniq('wa_prop_rm_'))

    def _property(self, **vals):
        base = {'name': vals.pop('name', self._uniq('Prop '))}
        base.update(vals)
        return self.env['property.base'].sudo().create(base)

    def _orphan_chat(self):
        """A phone-only conversation the working RM is handling."""
        return self.make_conversation(
            phone_number=self._uniq_phone(),
            assigned_user_id=self.working_rm.id,
        )

    # ── The reported failure ─────────────────────────────────────────────────

    def test_triage_with_another_rms_property_does_not_raise(self):
        """The exact click that failed: pick a property owned by another RM."""
        prop = self._property(rm_user_id=self.property_rm.id)
        conv = self._orphan_chat()

        lead_id = self.env['wa.conversation'].with_user(
            self.working_rm).create_lead_from_chat(
                conversation_id=conv.id,
                name='Walk-in Buyer',
                property_base_id=prop.id,
            )

        self.assertTrue(lead_id)
        lead = self.env['leads.new'].sudo().browse(lead_id)
        self.assertEqual(lead.user_id, self.property_rm,
                         "the lead routes to the property's RM, not the triager")
        self.assertEqual(lead.property_base_id, prop)

    def test_triage_links_the_conversation_to_the_new_lead(self):
        """The whole point of triage — the chat stops being an orphan."""
        prop = self._property(rm_user_id=self.property_rm.id)
        conv = self._orphan_chat()

        lead_id = self.env['wa.conversation'].with_user(
            self.working_rm).create_lead_from_chat(
                conversation_id=conv.id, name='Walk-in Buyer',
                property_base_id=prop.id,
            )

        conv.invalidate_recordset()
        self.assertEqual(conv.sudo().lead_id.id, lead_id)

    def test_triage_binds_a_segment_for_the_new_lead(self):
        """The segment bind reads the lead — it must survive the reassignment."""
        prop = self._property(rm_user_id=self.property_rm.id)
        conv = self._orphan_chat()

        lead_id = self.env['wa.conversation'].with_user(
            self.working_rm).create_lead_from_chat(
                conversation_id=conv.id, name='Walk-in Buyer',
                property_base_id=prop.id,
            )

        segs = self.env['wa.conversation.segment'].sudo().search(
            [('conversation_id', '=', conv.id)])
        self.assertTrue(
            segs.filtered(lambda s: s.inquiry_id.id == lead_id),
            "a segment is bound to the freshly created inquiry")

    def test_triage_logs_the_system_event(self):
        """The log line interpolates lead.name — the last read that failed."""
        prop = self._property(rm_user_id=self.property_rm.id)
        conv = self._orphan_chat()

        self.env['wa.conversation'].with_user(
            self.working_rm).create_lead_from_chat(
                conversation_id=conv.id, name='Walk-in Buyer',
                property_base_id=prop.id,
            )

        logs = self.env['wa.message'].sudo().search([
            ('conversation_id', '=', conv.id), ('kind', '=', 'system'),
        ])
        self.assertTrue(
            logs.filtered(lambda m: 'Lead created from chat' in (m.body or '')),
            "the system event is logged")

    # ── The same flow when nothing changes hands ─────────────────────────────

    def test_triage_without_property_still_assigns_to_the_triager(self):
        """No property picked → the triaging RM keeps the lead. Must not regress."""
        conv = self._orphan_chat()

        lead_id = self.env['wa.conversation'].with_user(
            self.working_rm).create_lead_from_chat(
                conversation_id=conv.id, name='Walk-in Buyer',
            )

        lead = self.env['leads.new'].sudo().browse(lead_id)
        self.assertEqual(lead.user_id, self.working_rm)

    def test_triage_with_own_property_keeps_the_lead(self):
        """Property owned by the triager → no hand-off, no elevation needed."""
        prop = self._property(rm_user_id=self.working_rm.id)
        conv = self._orphan_chat()

        lead_id = self.env['wa.conversation'].with_user(
            self.working_rm).create_lead_from_chat(
                conversation_id=conv.id, name='Walk-in Buyer',
                property_base_id=prop.id,
            )

        lead = self.env['leads.new'].sudo().browse(lead_id)
        self.assertEqual(lead.user_id, self.working_rm)

    # ── Guard rail: elevation must stay narrow ───────────────────────────────

    def test_triage_does_not_grant_the_rm_read_on_the_handed_off_lead(self):
        """Triaging is not a general grant on leads.new.

        The RM hands the lead over; they must not retain read access to it
        afterwards, or the record rule would be porous.
        """
        prop = self._property(rm_user_id=self.property_rm.id)
        conv = self._orphan_chat()

        lead_id = self.env['wa.conversation'].with_user(
            self.working_rm).create_lead_from_chat(
                conversation_id=conv.id, name='Walk-in Buyer',
                property_base_id=prop.id,
            )

        with self.assertRaises(AccessError):
            self.env['leads.new'].with_user(self.working_rm).browse(
                lead_id).read(['name'])


@tagged('post_install', '-at_install', 'wa_communication')
class TestInboxRecommendWizardAccess(WaTransactionCase):
    """The other branch of the CTA: the chat already has an anchor lead.

    ``createInquiryForActive`` seeds the Recommend Property wizard with
    ``conv.lead_id``. Conversations get reassigned freely while the originating
    inquiry keeps its owner, so that anchor lead is often another RM's.
    """

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            'wa_communication.segments_enabled', '1')
        self.working_rm = self.make_user(login=self._uniq('wz_rm_'))
        self.working_rm.sudo().write({
            'group_ids': [
                (4, self.env.ref('leads.group_lead_score_rm').id),
                (4, self.env.ref('properties.group_property_rm').id),
            ],
        })
        self.other_rm = self.make_user(login=self._uniq('wz_other_'))

    def _property(self, **vals):
        base = {'name': vals.pop('name', self._uniq('Prop '))}
        base.update(vals)
        return self.env['property.base'].sudo().create(base)

    def _cross_rm_anchor(self):
        prop_anchor = self._property()
        prop_new = self._property()
        phone = self._uniq_phone()
        anchor = self.make_lead(phone=phone[2:],
                                property_base_id=prop_anchor.id,
                                user_id=self.other_rm.id)
        conv = self.make_conversation(phone_number=phone, lead_id=anchor.id,
                                      assigned_user_id=self.working_rm.id)
        seg_id = self.env['wa.conversation'].start_property_topic(
            conv.id, prop_new.id)['segment_id']
        return anchor, prop_new, conv, seg_id

    def test_wizard_defaults_seed_from_an_unreadable_anchor(self):
        anchor, prop_new, _conv, _seg = self._cross_rm_anchor()
        vals = self.env['lead.recommend.property.wizard'].with_user(
            self.working_rm).with_context(
                default_inquiry_id=anchor.id,
                default_property_base_id=prop_new.id,
                active_id=anchor.id, active_model='leads.new',
            ).default_get(['inquiry_id', 'assigned_rm_id', 'source_id'])
        self.assertEqual(vals.get('inquiry_id'), anchor.id)
        self.assertEqual(vals.get('source_id'), anchor.source_id.id)

    def test_wizard_creates_from_an_unreadable_anchor(self):
        anchor, prop_new, _conv, seg_id = self._cross_rm_anchor()
        wiz = self.env['lead.recommend.property.wizard'].with_user(
            self.working_rm).create({
                'inquiry_id': anchor.id,
                'property_base_id': prop_new.id,
                'assigned_rm_id': self.working_rm.id,
            })
        rec_id = wiz.action_create_recommended_inquiry()['res_id']
        rec = self.env['leads.new'].sudo().browse(rec_id)
        self.assertEqual(rec.parent_inquiry_id, anchor)
        self.assertEqual(rec.user_id, self.working_rm)
        seg = self.env['wa.conversation.segment'].sudo().browse(seg_id)
        seg.invalidate_recordset()
        self.assertEqual(seg.inquiry_id.id, rec_id)
