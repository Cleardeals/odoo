"""Inquiry-attribution segments (Phase 1a) — the correctable inquiry layer.

A phone is a *lead*; a phone+property is an *inquiry* (``leads.new``).  One phone
holds many inquiries, but WhatsApp is one thread per phone.  ``wa.conversation.segment``
captures *which inquiry a span of the thread is about* as a re-pointable label, so
attribution can be corrected — even bound to an inquiry created after the fact —
without ever mutating the immutable ``wa.message`` facts.

The whole layer is gated by ``wa_communication.segments_enabled``: with it off the
system behaves exactly as before (these tests assert that too).
"""

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import WaTransactionCase


@tagged('post_install', '-at_install', 'wa_communication')
class TestSegments(WaTransactionCase):

    def setUp(self):
        super().setUp()
        self.Segment = self.env['wa.conversation.segment']

    def _enable(self, on=True):
        self.env['ir.config_parameter'].sudo().set_param(
            'wa_communication.segments_enabled', '1' if on else '0')

    def _property(self, **vals):
        base = {'name': vals.pop('name', self._uniq('Prop '))}
        base.update(vals)
        return self.env['property.base'].sudo().create(base)

    def _process(self, event, msg_id='seg-1'):
        self.Conv._process_odoo_wa_event(event, msg_id)

    def _workflow_sent_event(self, conv, lead, **over):
        evt = {
            'event_type': 'message_sent',
            'phone': conv.phone_number,
            'actor_id': lead.id,
            'actor_type': 'buyer_inquiry',
            'workflow_slug': 'nurturing_v2',
            'template_name': 'site_visit_v1',
            'wa_message_id': self._uniq('wamid_'),
            'occurred_at': '2026-01-01T10:00:00Z',
        }
        evt.update(over)
        return evt

    # ── Flag OFF — dormant, today's behaviour ─────────────────────────────────

    def test_flag_off_workflow_send_creates_no_segment(self):
        self._enable(False)
        propA = self._property()
        lead = self.make_lead(phone='9000000001', property_base_id=propA.id)
        conv = self.make_conversation(phone_number='919000000001')
        self._process(self._workflow_sent_event(conv, lead))
        msg = conv.message_ids.filtered(lambda m: m.direction == 'outbound')
        self.assertTrue(msg)
        self.assertFalse(msg.segment_id, "no segment is created when the flag is off")
        self.assertFalse(conv.segment_ids)
        # effective_* fall back to lead_id — i.e. unchanged analytics keys.
        self.assertEqual(msg.effective_inquiry_id, lead)
        self.assertEqual(msg.effective_property_id, propA)

    # ── Flag ON — deterministic attribution ───────────────────────────────────

    def test_workflow_send_opens_segment_for_inquiry(self):
        self._enable()
        propA = self._property()
        lead = self.make_lead(phone='9000000002', property_base_id=propA.id)
        conv = self.make_conversation(phone_number='919000000002')
        self._process(self._workflow_sent_event(conv, lead))
        msg = conv.message_ids.filtered(lambda m: m.direction == 'outbound')
        self.assertTrue(msg.segment_id, "a workflow send is a deterministic signal")
        self.assertEqual(msg.segment_id.inquiry_id, lead)
        self.assertEqual(msg.segment_id.property_base_id, propA)
        self.assertTrue(msg.segment_id.is_active)
        self.assertEqual(conv.active_segment_id, msg.segment_id)
        self.assertEqual(msg.effective_property_id, propA)

    def test_two_inquiries_each_get_their_own_segment(self):
        self._enable()
        propA = self._property()
        propB = self._property()
        leadA = self.make_lead(phone='9000000003', property_base_id=propA.id)
        leadB = self.make_lead(phone='9000000003', property_base_id=propB.id)
        conv = self.make_conversation(phone_number='919000000003')

        self._process(self._workflow_sent_event(conv, leadA))
        self._process(self._workflow_sent_event(conv, leadB))

        msgs = conv.message_ids.filtered(lambda m: m.direction == 'outbound')
        by_prop = {m.effective_property_id: m for m in msgs}
        self.assertIn(propA, by_prop)
        self.assertIn(propB, by_prop)
        self.assertNotEqual(by_prop[propA].segment_id, by_prop[propB].segment_id,
                            "each inquiry is tracked in its own segment")
        # The conversation surfaces both inquiries.
        self.assertIn(leadA, conv.inquiry_ids)
        self.assertIn(leadB, conv.inquiry_ids)

    def test_relink_segment_recomputes_effective_on_messages(self):
        self._enable()
        propA = self._property()
        propB = self._property()
        leadA = self.make_lead(phone='9000000004', property_base_id=propA.id)
        leadB = self.make_lead(phone='9000000004', property_base_id=propB.id)
        conv = self.make_conversation(phone_number='919000000004')
        self._process(self._workflow_sent_event(conv, leadA))
        msg = conv.message_ids.filtered(lambda m: m.direction == 'outbound')
        self.assertEqual(msg.effective_property_id, propA)

        # Correct the attribution: this span was actually about B.
        self.Conv.relink_segment(msg.segment_id.id, leadB.id)
        msg.invalidate_recordset()
        self.assertEqual(msg.effective_inquiry_id, leadB)
        self.assertEqual(msg.effective_property_id, propB,
                         "re-pointing the segment reclassifies its messages")
        # The immutable create-time lead_id is untouched.
        self.assertEqual(msg.lead_id, leadA)

    def test_move_message_to_segment(self):
        self._enable()
        propA = self._property()
        propB = self._property()
        leadA = self.make_lead(phone='9000000005', property_base_id=propA.id)
        leadB = self.make_lead(phone='9000000005', property_base_id=propB.id)
        conv = self.make_conversation(phone_number='919000000005')
        segB = self.Conv.start_segment(conv.id, inquiry_id=leadB.id)
        msg = self.make_message(conv, body='stray', occurred_at='2026-01-02 10:00:00')
        self.Conv.move_message_to_segment(msg.id, segB)
        msg.invalidate_recordset()
        self.assertEqual(msg.effective_property_id, propB)

    # ── Drift: inquiry created AFTER the conversation ─────────────────────────

    def test_label_only_segment_links_on_create_lead_from_chat(self):
        """RM opens a 'Property B' segment before B's inquiry exists; creating the
        inquiry from chat binds the span and reclassifies its messages."""
        self._enable()
        conv = self.make_conversation(assigned_user_id=False,
                                      phone_number='919000000006')
        # Label-only segment (no inquiry yet) + a message filed into it.
        seg_id = self.Conv.start_segment(conv.id, label='Property B')
        seg = self.Segment.browse(seg_id)
        self.assertFalse(seg.inquiry_id)
        msg = self.make_message(conv, body='about the 2BHK', sender_name='Asha',
                                segment_id=seg.id, occurred_at='2026-01-02 11:00:00')
        self.assertFalse(msg.effective_inquiry_id, "unlinked span has no inquiry yet")

        prop = self._property()
        with self.mock_pubsub():
            lead_id = self.Conv.create_lead_from_chat(
                conv.id, 'Asha Roy', property_base_id=prop.id)

        seg.invalidate_recordset()
        msg.invalidate_recordset()
        self.assertEqual(seg.inquiry_id.id, lead_id,
                         "the active label-only segment binds to the new inquiry")
        self.assertEqual(msg.effective_inquiry_id.id, lead_id)
        self.assertEqual(msg.effective_property_id, prop)

    # ── Swipe-reply to another property's (older) message ─────────────────────

    def test_swipe_reply_to_other_property_files_under_quoted_inquiry(self):
        """Replying to an OLD template for a different property must attribute the
        reply to THAT property's inquiry — even if the template predates segments
        (no segment_id) and the event's actor_id resolves to the active inquiry —
        and must not flip the RM's active context."""
        self._enable()
        propA = self._property()
        propV = self._property()
        leadA = self.make_lead(phone='9000000010', property_base_id=propA.id)
        leadV = self.make_lead(phone='9000000010', property_base_id=propV.id)
        conv = self.make_conversation(phone_number='919000000010')

        # Active context is property A.
        seg_a = self.Conv.start_segment(conv.id, inquiry_id=leadA.id)
        # An OLD outbound template for property V, predating segments (no segment).
        tpl = self.make_message(
            conv, direction='outbound', initiator='workflow', kind='template',
            wa_message_id='tpl-vaish', lead_id=leadV.id,
            occurred_at='2026-01-01 09:00:00')
        self.assertFalse(tpl.segment_id, "the old template predates segments")

        # Lead swipe-replies to that V template; actor_id resolves to A (the active
        # inquiry) — the quoted template's inquiry (V) must still win.
        self._process({
            'event_type': 'lead_replied',
            'phone': conv.phone_number,
            'actor_id': leadA.id,
            'actor_type': 'buyer_inquiry',
            'wa_message_id': 'inb-vaish-1',
            'source_message_id': 'tpl-vaish',
            'message_text': 'Hi',
            'occurred_at': '2026-01-02T10:00:00Z',
        })

        reply = conv.message_ids.filtered(lambda m: m.wa_message_id == 'inb-vaish-1')
        self.assertTrue(reply)
        self.assertEqual(reply.segment_id.inquiry_id, leadV,
                         "reply is filed under the quoted template's inquiry")
        self.assertEqual(reply.effective_property_id, propV)
        # The RM's active context must NOT have flipped to V.
        conv.invalidate_recordset()
        self.assertEqual(conv.active_segment_id.id, seg_a,
                         "a quoted reply must not hijack the active inquiry")

    # ── Immutability still holds ──────────────────────────────────────────────

    def test_segment_id_is_writable_but_facts_remain_immutable(self):
        self._enable()
        conv = self.make_conversation(phone_number='919000000007')
        seg_id = self.Conv.start_segment(conv.id, label='X')
        msg = self.make_message(conv, body='hi', occurred_at='2026-01-02 12:00:00')
        # Moving to a segment is allowed (attribution is mutable)...
        msg.segment_id = seg_id
        self.assertEqual(msg.segment_id.id, seg_id)
        # ...but the immutable facts are still rejected.
        with self.assertRaises(ValidationError):
            msg.write({'body': 'tampered'})
