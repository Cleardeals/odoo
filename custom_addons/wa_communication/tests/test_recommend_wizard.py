"""Recommend Property wizard × WhatsApp segments — the binding hand-off.

Pure wizard behaviour (flattened hierarchy, duplicate guard) is covered in the
leads module (``leads/tests/test_recommend_wizard.py``). Here we test only the
cross-module contract: creating an inquiry through the wizard binds a pending
property-anchored segment on that phone's WhatsApp thread — closing the disconnect
where the wizard path used to strand the span.
"""

from odoo.tests import tagged

from .common import WaTransactionCase


@tagged('post_install', '-at_install', 'wa_communication')
class TestRecommendWizardBinding(WaTransactionCase):

    def setUp(self):
        super().setUp()
        self.Segment = self.env['wa.conversation.segment']
        self.env['ir.config_parameter'].sudo().set_param(
            'wa_communication.segments_enabled', '1')

    def _property(self, **vals):
        base = {'name': vals.pop('name', self._uniq('Prop '))}
        base.update(vals)
        return self.env['property.base'].sudo().create(base)

    def test_wizard_creation_binds_property_segment(self):
        """RM opens a 'New topic' span for propB, then creates propB's inquiry via
        the Recommend wizard — the span binds via the leads.new create hook."""
        propA = self._property()
        propB = self._property()
        primary = self.make_lead(phone='9000000105', property_base_id=propA.id,
                                 user_id=self.env.uid)
        conv = self.make_conversation(phone_number='919000000105')
        seg_id = self.env['wa.conversation'].start_property_topic(
            conv.id, propB.id)['segment_id']
        msg = self.make_message(conv, body='the 3BHK', segment_id=seg_id,
                                occurred_at='2026-01-02 10:00:00')

        wiz = self.env['lead.recommend.property.wizard'].create({
            'inquiry_id': primary.id,
            'property_base_id': propB.id,
            'assigned_rm_id': self.env.uid,
        })
        rec = self.env['leads.new'].browse(
            wiz.action_create_recommended_inquiry()['res_id'])

        seg = self.Segment.browse(seg_id)
        seg.invalidate_recordset()
        msg.invalidate_recordset()
        self.assertEqual(seg.inquiry_id, rec, "the wizard-created inquiry binds the span")
        self.assertEqual(msg.effective_inquiry_id, rec)
        self.assertEqual(msg.effective_property_id, propB)
