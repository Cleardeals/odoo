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

    def test_segment_label_shows_property_name_not_lead_name(self):
        """Regression: the DISCUSSING chip (segment.display_name) must name the
        PROPERTY the span is about, never the person/lead name."""
        self._enable()
        propA = self._property(name='Siddhipriya Imperial')
        lead = self.make_lead(phone='9000000099', name='Nirat',
                              property_base_id=propA.id)
        conv = self.make_conversation(phone_number='919000000099')
        self._process(self._workflow_sent_event(conv, lead))
        seg = conv.active_segment_id
        self.assertTrue(seg)
        self.assertEqual(seg.display_name, 'Siddhipriya Imperial',
                         "chip shows the property name, not 'Nirat'")

    def test_segment_label_falls_back_to_property_via_inquiry(self):
        """Even when the span carries only its inquiry (no own property_base_id),
        the label resolves through inquiry_id.property_base_id.name."""
        self._enable()
        prop = self._property(name='Mahashakti Apartment')
        lead = self.make_lead(phone='9000000098', name='Nirat',
                              property_base_id=prop.id)
        conv = self.make_conversation(phone_number='919000000098')
        seg = self.Segment.create({
            'conversation_id': conv.id,
            'inquiry_id': lead.id,          # inquiry set, property_base_id left blank
        })
        self.assertEqual(seg.display_name, 'Mahashakti Apartment')

    def test_segment_label_explicit_label_wins(self):
        """An explicit human label (e.g. a bare 'New topic') still takes priority."""
        self._enable()
        conv = self.make_conversation(phone_number='919000000097')
        seg_id = self.Conv.start_segment(conv.id, label='Diwali Offer')
        seg = self.Segment.browse(seg_id)
        self.assertEqual(seg.display_name, 'Diwali Offer')

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

    def test_set_active_segment_flips_active_context(self):
        """Accepting a 'switch to X?' suggestion activates that segment and
        deactivates the previous one."""
        self._enable()
        propA = self._property()
        propB = self._property()
        leadA = self.make_lead(phone='9000000011', property_base_id=propA.id)
        leadB = self.make_lead(phone='9000000011', property_base_id=propB.id)
        conv = self.make_conversation(phone_number='919000000011')
        seg_a = self.Conv.start_segment(conv.id, inquiry_id=leadA.id)
        # A quoted-reply created B's segment without activating it.
        seg_b = conv._owa_ensure_segment(inquiry=leadB, activate=False)
        conv.invalidate_recordset()
        self.assertEqual(conv.active_segment_id.id, seg_a)

        self.Conv.set_active_segment(conv.id, seg_b.id)
        conv.invalidate_recordset()
        self.assertEqual(conv.active_segment_id, seg_b)
        self.assertTrue(seg_b.is_active)
        self.assertFalse(self.Segment.browse(seg_a).is_active)

    # ── Property-anchored "New topic" + dedup + guard ─────────────────────────

    def test_new_topic_property_no_inquiry_creates_property_span(self):
        """'New topic' on a property with no inquiry yet opens a property-anchored,
        inquiry-less span (deterministic anchor, not a free-text label)."""
        self._enable()
        prop = self._property()
        conv = self.make_conversation(phone_number='919000000020')
        res = self.Conv.start_property_topic(conv.id, prop.id)
        self.assertEqual(res['action'], 'started')
        seg = self.Segment.browse(res['segment_id'])
        self.assertFalse(seg.inquiry_id, "no inquiry exists for this property yet")
        self.assertEqual(seg.property_base_id, prop, "span is anchored to the property")
        conv.invalidate_recordset()
        self.assertEqual(conv.active_segment_id, seg)

    def test_new_topic_same_property_twice_is_idempotent(self):
        """Clicking 'New topic' for the same property twice reuses the one span —
        no silent duplicate (the old label-only duplication bug)."""
        self._enable()
        prop = self._property()
        conv = self.make_conversation(phone_number='919000000021')
        r1 = self.Conv.start_property_topic(conv.id, prop.id)
        r2 = self.Conv.start_property_topic(conv.id, prop.id)
        self.assertEqual(r1['segment_id'], r2['segment_id'], "same span reused")
        self.assertEqual(len(conv.segment_ids), 1, "exactly one span for the property")

    def test_new_topic_existing_inquiry_switches_no_dup(self):
        """'New topic' on a property that already has an inquiry does NOT open an
        orphan span — it guides the RM to the existing inquiry (consideration #4)."""
        self._enable()
        prop = self._property()
        lead = self.make_lead(phone='9000000022', property_base_id=prop.id)
        conv = self.make_conversation(phone_number='919000000022')
        res = self.Conv.start_property_topic(conv.id, prop.id)
        self.assertEqual(res['action'], 'exists')
        self.assertEqual(res['inquiry_id'], lead.id)
        # No inquiry-less span was created; the active span points at the inquiry.
        self.assertFalse(conv.segment_ids.filtered(lambda s: not s.inquiry_id),
                         "must not create an orphan span when the inquiry exists")
        conv.invalidate_recordset()
        self.assertEqual(conv.active_segment_id.inquiry_id, lead)

    def test_pre_inquiry_message_effective_property_from_segment(self):
        """A message in a property-anchored span attributes to that property even
        before its inquiry exists — analytics are correct from the start."""
        self._enable()
        prop = self._property()
        conv = self.make_conversation(phone_number='919000000023')
        seg_id = self.Conv.start_property_topic(conv.id, prop.id)['segment_id']
        msg = self.make_message(conv, body='about it', segment_id=seg_id,
                                occurred_at='2026-01-02 10:00:00')
        self.assertFalse(msg.effective_inquiry_id, "no inquiry yet")
        self.assertEqual(msg.effective_property_id, prop,
                         "property resolves from the span before the inquiry exists")

    def test_flag_off_start_property_topic_is_noop(self):
        self._enable(False)
        prop = self._property()
        conv = self.make_conversation(phone_number='919000000024')
        res = self.Conv.start_property_topic(conv.id, prop.id)
        self.assertEqual(res['action'], 'noop')
        self.assertFalse(conv.segment_ids)

    def test_legacy_label_only_dedups_by_label(self):
        """The off-catalog free-text path still works and no longer duplicates —
        same normalized label reuses the one span."""
        self._enable()
        conv = self.make_conversation(phone_number='919000000025')
        s1 = self.Conv.start_segment(conv.id, label='Green Acres 2BHK')
        s2 = self.Conv.start_segment(conv.id, label='  green acres 2bhk ')
        self.assertEqual(s1, s2, "normalized label dedups the span")
        self.assertEqual(len(conv.segment_ids), 1)

    # ── Binding on inquiry creation (every path) ──────────────────────────────

    def test_new_inquiry_create_binds_property_segment(self):
        """Creating an inquiry for a phone+property with a pending property-anchored
        span binds it — via the leads.new create hook, so it works no matter HOW the
        inquiry is created (this covers the recommend-wizard disconnect)."""
        self._enable()
        prop = self._property()
        conv = self.make_conversation(phone_number='919000000026')
        seg_id = self.Conv.start_property_topic(conv.id, prop.id)['segment_id']
        msg = self.make_message(conv, body='pre-inquiry', segment_id=seg_id,
                                occurred_at='2026-01-02 10:00:00')

        # Any creation path — here a plain make_lead — must bind the span.
        lead = self.make_lead(phone='9000000026', property_base_id=prop.id)

        seg = self.Segment.browse(seg_id)
        seg.invalidate_recordset()
        msg.invalidate_recordset()
        self.assertEqual(seg.inquiry_id, lead, "span binds to the new inquiry")
        self.assertEqual(msg.effective_inquiry_id, lead)
        self.assertEqual(msg.effective_property_id, prop)

    def test_new_inquiry_create_does_not_bind_when_property_differs(self):
        """Binding is deterministic by property — an inquiry for a DIFFERENT property
        must not hijack a pending span."""
        self._enable()
        propA = self._property()
        propB = self._property()
        conv = self.make_conversation(phone_number='919000000027')
        seg_id = self.Conv.start_property_topic(conv.id, propA.id)['segment_id']
        self.make_lead(phone='9000000027', property_base_id=propB.id)
        seg = self.Segment.browse(seg_id)
        seg.invalidate_recordset()
        self.assertFalse(seg.inquiry_id, "a different property must not bind the span")

    # ── Migration: collapse duplicate label-only spans ────────────────────────

    def _load_migration(self):
        import importlib.util
        import os
        path = os.path.join(os.path.dirname(__file__), '..',
                            'migrations', '1.2.5', 'post-migrate.py')
        spec = importlib.util.spec_from_file_location('wa_migr_125', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_migration_collapses_duplicate_label_only_segments(self):
        """The 1.2.5 post-migration merges pre-existing duplicate inquiry-less spans
        (same conversation+property) into the earliest, repointing messages and the
        active pointer — without touching immutable facts."""
        self._enable()
        prop = self._property()
        conv = self.make_conversation(phone_number='919000000028')
        Seg = self.Segment.sudo()
        keep = Seg.create({'conversation_id': conv.id, 'property_base_id': prop.id,
                           'started_at': '2026-01-01 10:00:00'})
        dup = Seg.create({'conversation_id': conv.id, 'property_base_id': prop.id,
                          'started_at': '2026-01-01 11:00:00'})
        msg = self.make_message(conv, body='on dup', segment_id=dup.id,
                                occurred_at='2026-01-02 10:00:00')
        conv.active_segment_id = dup.id
        self.env.flush_all()

        self._load_migration().migrate(self.env.cr, '1.2.5')
        self.env.invalidate_all()

        self.assertFalse(dup.exists(), "the duplicate span is removed")
        self.assertTrue(keep.exists(), "the earliest span survives")
        self.assertEqual(msg.segment_id, keep, "messages repoint to the survivor")
        self.assertEqual(conv.active_segment_id, keep, "active pointer follows")

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

    # ── "View Lead" target follows the discussing inquiry ─────────────────────

    def test_view_lead_falls_back_to_anchor_when_no_active_segment(self):
        self._enable()
        propA = self._property()
        leadA = self.make_lead(phone='9000000020', property_base_id=propA.id)
        conv = self.make_conversation(phone_number='919000000020', lead_id=leadA.id)
        self.assertEqual(conv._owa_view_lead_id(), leadA.id,
                         "with no discussing segment, View Lead uses the anchor lead")

    def test_view_lead_prefers_active_segment_inquiry(self):
        self._enable()
        propA = self._property()
        propB = self._property()
        leadA = self.make_lead(phone='9000000021', property_base_id=propA.id)
        leadB = self.make_lead(phone='9000000021', property_base_id=propB.id)
        # Anchor is A, but the chat is currently discussing B.
        conv = self.make_conversation(phone_number='919000000021', lead_id=leadA.id)
        self.Conv.start_segment(conv.id, inquiry_id=leadB.id)
        self.assertEqual(conv.active_segment_id.inquiry_id, leadB)
        self.assertEqual(conv._owa_view_lead_id(), leadB.id,
                         "View Lead follows the inquiry in the discussing chip")

    # ── RM without leads.new access can still use the switcher ────────────────

    def _lead_rm(self):
        """An RM with the leads role: reads all properties but, by record rule,
        only their own leads — exactly the account that hit the New-topic error."""
        rm = self.make_user()
        rm.group_ids = [
            (4, self.env.ref('leads.group_lead_score_rm').id),
            (4, self.env.ref('properties.group_property_rm').id),
        ]
        return rm

    def test_rm_without_lead_access_can_start_new_topic(self):
        """An RM opening a New topic on a number whose inquiry is owned by ANOTHER
        RM (so the record rule hides it) must not trip an AccessError when the
        conversation's inquiry_ids are recomputed/flushed."""
        self._enable()
        propA = self._property()
        propB = self._property()
        other = self.make_user()
        # A lead on the number owned by someone else → unreadable to our RM.
        self.make_lead(phone='9000000023', property_base_id=propA.id, user_id=other.id)
        conv = self.make_conversation(phone_number='919000000023')
        rm = self._lead_rm()
        conv.assigned_user_id = rm.id
        res = self.Conv.with_user(rm).start_property_topic(conv.id, propB.id)
        self.assertEqual(res.get('action'), 'started',
                         "the RM opens a new property topic with no AccessError")
        self.assertTrue(conv.active_segment_id)

    def test_rm_thread_lists_inquiries_it_cannot_read(self):
        """The switcher lists every inquiry on the number even when the RM has no
        direct read access to some of them (served sudo)."""
        self._enable()
        propA = self._property()
        leadA = self.make_lead(phone='9000000024', property_base_id=propA.id)
        conv = self.make_conversation(phone_number='919000000024')
        rm = self.make_user()
        conv.assigned_user_id = rm.id
        data = self.Conv.with_user(rm).get_thread(conv.id)
        self.assertIn('conversation', data)
        self.assertEqual([i['id'] for i in data['conversation']['inquiries']],
                         [leadA.id])

    def test_view_lead_resolves_label_only_segment_by_property(self):
        self._enable()
        propA = self._property()
        propB = self._property()
        leadA = self.make_lead(phone='9000000022', property_base_id=propA.id)
        leadB = self.make_lead(phone='9000000022', property_base_id=propB.id)
        conv = self.make_conversation(phone_number='919000000022', lead_id=leadA.id)
        # A property-only (label) segment with no bound inquiry, but B exists.
        self.Conv.start_segment(conv.id, property_base_id=propB.id)
        self.assertFalse(conv.active_segment_id.inquiry_id)
        self.assertEqual(conv._owa_view_lead_id(), leadB.id,
                         "a label-only segment resolves to the matching inquiry")
