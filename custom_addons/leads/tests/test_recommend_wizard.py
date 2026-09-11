# -*- coding: utf-8 -*-
"""Recommend Property wizard — flattened hierarchy and duplicate guard.

Pure leads-module behaviour: a recommended inquiry may be created from a primary
OR another recommended inquiry, but the hierarchy stays flat (a
recommendation-of-a-recommendation parents to the SAME primary, never nests), and
the (phone, property) duplicate guard blocks a second inquiry for the same buyer +
property.
"""

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .test_portal_common import PortalLeadTestCase


@tagged('post_install', '-at_install')
class TestRecommendWizard(PortalLeadTestCase):

    def _prop(self, tag):
        return self.env['property.base'].create({
            'name': f'Prop {tag} {self.suffix}',
            'property_tag': f'PROP-{tag}-{self.suffix}',
            'prop_id': f'P{tag}{self.suffix}',
            'rm_user_id': self.rm_user.id,
        })

    def _inquiry(self, phone, prop, inquiry_type='primary', parent=None):
        return self.env['leads.new'].with_context(
            automated_lead_creation=True,
        ).create({
            'name': 'Buyer',
            'phone': phone,
            'source_id': self.source_magicbricks.id,
            'property_base_id': prop.id,
            'user_id': self.rm_user.id,
            'inquiry_type': inquiry_type,
            'parent_inquiry_id': parent.id if parent else False,
            'state': 'assigned',
        })

    def _recommend(self, source, prop):
        wiz = self.env['lead.recommend.property.wizard'].create({
            'inquiry_id': source.id,
            'property_base_id': prop.id,
            'assigned_rm_id': self.rm_user.id,
        })
        action = wiz.action_create_recommended_inquiry()
        return self.env['leads.new'].browse(action['res_id'])

    # ── Flattened hierarchy ───────────────────────────────────────────────────

    def test_recommended_from_primary_parents_to_primary(self):
        primary = self._inquiry('9000000101', self._prop('A'))
        rec = self._recommend(primary, self._prop('B'))
        self.assertEqual(rec.inquiry_type, 'recommended')
        self.assertEqual(rec.parent_inquiry_id, primary)

    def test_recommended_from_recommended_parents_to_primary(self):
        """A recommendation created from another recommendation inherits the SAME
        primary parent — the hierarchy never nests deeper than one level."""
        primary = self._inquiry('9000000102', self._prop('A'))
        rec1 = self._recommend(primary, self._prop('B'))
        rec2 = self._recommend(rec1, self._prop('C'))
        self.assertEqual(rec2.parent_inquiry_id, primary,
                         "grandchild flattens to the primary, not the recommendation")

    def test_recommended_from_orphan_recommended_raises(self):
        """A recommended inquiry with no parent can't seed another — surfaced as a
        clear error rather than creating a dangling record."""
        orphan = self._inquiry('9000000103', self._prop('A'),
                               inquiry_type='recommended')
        wiz = self.env['lead.recommend.property.wizard'].create({
            'inquiry_id': orphan.id, 'property_base_id': self._prop('B').id,
            'assigned_rm_id': self.rm_user.id})
        with self.assertRaises(ValidationError):
            wiz.action_create_recommended_inquiry()

    # ── Duplicate guard ───────────────────────────────────────────────────────

    def test_wizard_dedup_existing_phone_property_raises(self):
        propA = self._prop('A')
        primary = self._inquiry('9000000104', propA)
        wiz = self.env['lead.recommend.property.wizard'].create({
            'inquiry_id': primary.id, 'property_base_id': propA.id,
            'assigned_rm_id': self.rm_user.id})
        with self.assertRaises(ValidationError):
            wiz.action_create_recommended_inquiry()

    # ── Current status ────────────────────────────────────────────────────────

    def test_recommended_defaults_current_status_to_lead(self):
        primary = self._inquiry('9000000105', self._prop('A'))
        rec = self._recommend(primary, self._prop('B'))
        self.assertEqual(rec.current_status, 'lead',
                         "unset status defaults to 'lead' as before")

    def test_recommended_inquiry_always_starts_at_lead(self):
        """A recommended inquiry is new: nobody has contacted the buyer yet.

        The wizard used to let the RM pick any status, which is exactly the
        unverified status-setting the WhatsApp attempt gate exists to stop — so
        the field is gone and creation always parks at ``lead``.
        """
        primary = self._inquiry('9000000106', self._prop('A'))
        wiz = self.env['lead.recommend.property.wizard'].create({
            'inquiry_id': primary.id,
            'property_base_id': self._prop('B').id,
            'assigned_rm_id': self.rm_user.id,
        })
        rec = self.env['leads.new'].browse(
            wiz.action_create_recommended_inquiry()['res_id'])
        self.assertEqual(rec.current_status, 'lead')

    def test_recommended_inquiry_is_not_flagged_auto_created(self):
        """So the initial-nudge workflow does not message this buyer."""
        primary = self._inquiry('9000000107', self._prop('A'))
        wiz = self.env['lead.recommend.property.wizard'].create({
            'inquiry_id': primary.id,
            'property_base_id': self._prop('B').id,
            'assigned_rm_id': self.rm_user.id,
        })
        rec = self.env['leads.new'].browse(
            wiz.action_create_recommended_inquiry()['res_id'])
        self.assertFalse(rec.is_auto_created)
