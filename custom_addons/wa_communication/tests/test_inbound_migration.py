"""Inbound-first resilience — migration hardening.

Covers the path where a customer messages us FIRST, before any conversation
exists, across every edge case:

- robust phone normalization for lead auto-linking (``_standardize_phone`` reuse),
- self-healing auto-assignment of an old lead's chat to the lead's RM,
- manager triage notifications for messages nobody can be routed to,
- converting an orphan (phone-only) conversation into a real lead, and
- re-linking an orphan conversation when a matching lead is later created.

These call the OdooWaEvent dispatcher / model methods directly (no HTTP layer),
mirroring ``test_inbound_events.py``.
"""

from odoo.tests import tagged

from .common import WaTransactionCase


@tagged('post_install', '-at_install', 'wa_communication')
class TestInboundMigration(WaTransactionCase):

    def _process(self, event, msg_id='mig-1'):
        self.Conv._process_odoo_wa_event(event, msg_id)

    def _notif_recipients(self, notif_type):
        return self.env['cleardeals.notification'].sudo().search(
            [('notif_type', '=', notif_type)]).mapped('user_id').ids

    # ── A. Phone normalization links the right lead ───────────────────────────

    def test_old_lead_links_via_normalized_phone(self):
        """A 12-digit inbound phone links to a lead stored as bare 10 digits."""
        rm = self.make_user()
        lead = self.make_lead(phone='9876500001', user_id=rm.id)
        with self.mock_pubsub():
            self._process({
                'event_type': 'lead_replied',
                'phone': '919876500001',
                'wa_message_id': 'wamid.norm1',
                'message_text': 'hi',
                'occurred_at': '2026-03-01T08:00:00Z',
            })
        conv = self.Conv.sudo().search([('phone_number', '=', '919876500001')])
        self.assertEqual(conv.lead_id, lead,
                         "inbound must auto-link to the existing lead by phone")

    # ── B. Self-healing auto-assign to the lead's RM ──────────────────────────

    def test_old_lead_first_reply_autoassigns_to_lead_rm(self):
        """First inbound on a migrated lead publishes ONE assign for the lead RM."""
        rm = self.make_user()
        self.make_lead(phone='9876500002', user_id=rm.id)
        with self.mock_pubsub() as published:
            self._process({
                'event_type': 'lead_replied',
                'phone': '919876500002',
                'wa_message_id': 'wamid.assign1',
                'message_text': 'interested',
                'occurred_at': '2026-03-01T08:00:00Z',
            })
        assigns = [p for p in published
                   if p.payload.get('request_type') == 'assign']
        self.assertEqual(len(assigns), 1, "exactly one assign should be published")
        self.assertEqual(assigns[0].payload['rm_email'], rm.email)
        conv = self.Conv.sudo().search([('phone_number', '=', '919876500002')])
        self.assertTrue(conv.assignment_pending,
                        "assignment_pending must be set while confirmation is awaited")
        # The lead's RM is still notified of the reply.
        self.assertIn(rm.id, self._notif_recipients('lead_replied'))

    def test_autoassign_is_idempotent_across_replies(self):
        """A second inbound while pending must NOT publish another assign."""
        rm = self.make_user()
        self.make_lead(phone='9876500003', user_id=rm.id)
        with self.mock_pubsub() as published:
            for i in range(2):
                self._process({
                    'event_type': 'lead_replied',
                    'phone': '919876500003',
                    'wa_message_id': 'wamid.idem%d' % i,
                    'message_text': 'ping %d' % i,
                    'occurred_at': '2026-03-01T08:0%d:00Z' % i,
                }, msg_id='idem-%d' % i)
        assigns = [p for p in published
                   if p.payload.get('request_type') == 'assign']
        self.assertEqual(len(assigns), 1,
                         "auto-assign must fire once, not on every inbound")

    def test_autoassign_skips_rm_without_email_but_keeps_message(self):
        """RM with no email → no crash, no assign, message still persists + RM notified."""
        rm = self.make_user()
        rm.sudo().write({'email': False})
        self.make_lead(phone='9876500004', user_id=rm.id)
        with self.mock_pubsub() as published:
            self._process({
                'event_type': 'lead_replied',
                'phone': '919876500004',
                'wa_message_id': 'wamid.noemail',
                'message_text': 'hello?',
                'occurred_at': '2026-03-01T08:00:00Z',
            })
        assigns = [p for p in published
                   if p.payload.get('request_type') == 'assign']
        self.assertEqual(assigns, [], "no assign when the RM has no email")
        msg = self.Msg.sudo().search([('wa_message_id', '=', 'wamid.noemail')])
        self.assertEqual(len(msg), 1, "the inbound message must not be lost")
        self.assertIn(rm.id, self._notif_recipients('lead_replied'))

    # ── C. Manager triage for unroutable inbound ──────────────────────────────

    def test_unknown_number_notifies_managers(self):
        """An inbound from a number with no lead fans out to WA managers."""
        manager = self.make_user(manager=True)
        with self.mock_pubsub():
            self._process({
                'event_type': 'lead_replied',
                'phone': '915550009999',
                'wa_message_id': 'wamid.unknown',
                'message_text': 'is this available?',
                'occurred_at': '2026-03-01T08:00:00Z',
            })
        conv = self.Conv.sudo().search([('phone_number', '=', '915550009999')])
        self.assertTrue(conv, "an orphan conversation is still created")
        self.assertFalse(conv.lead_id, "no lead exists for an unknown number")
        self.assertIn(manager.id, self._notif_recipients('unrouted_inbound'),
                      "managers must be alerted to triage the message")

    # ── D. Create lead from chat (+ property routing) ─────────────────────────

    def _make_property(self, **vals):
        base = {'name': vals.pop('name', self._uniq('Prop '))}
        base.update(vals)
        return self.env['property.base'].sudo().create(base)

    def test_create_lead_from_chat_no_property_assigns_current_user(self):
        conv = self.make_conversation(assigned_user_id=False)
        self.make_message(conv, body='hey', sender_name='Ravi')
        with self.mock_pubsub():
            lead_id = self.Conv.create_lead_from_chat(conv.id, 'Ravi Kumar')
        lead = self.env['leads.new'].sudo().browse(lead_id)
        conv.invalidate_recordset()
        self.assertEqual(conv.lead_id.id, lead_id, "conversation must link to the new lead")
        self.assertEqual(lead.name, 'Ravi Kumar')
        self.assertEqual(lead.user_id.id, self.env.uid,
                         "with no property, the triaging RM owns the lead")

    def test_create_lead_from_chat_with_property_routes_to_property_rm(self):
        prop_rm = self.make_user()
        prop = self._make_property(rm_user_id=prop_rm.id)
        conv = self.make_conversation(assigned_user_id=False)
        with self.mock_pubsub() as published:
            lead_id = self.Conv.create_lead_from_chat(
                conv.id, 'Property Buyer', property_base_id=prop.id)
        lead = self.env['leads.new'].sudo().browse(lead_id)
        self.assertEqual(lead.user_id, prop_rm,
                         "lead must route to the property's RM")
        self.assertEqual(lead.property_base_id, prop)
        assigns = [p for p in published
                   if p.payload.get('request_type') == 'assign']
        self.assertEqual(len(assigns), 1)
        self.assertEqual(assigns[0].payload['rm_email'], prop_rm.email)

    def test_search_properties_returns_matches(self):
        self._make_property(name='Skyline Towers')
        self._make_property(name='Garden Villa')
        rows = self.Conv.search_properties('skyline')
        names = [r['name'] for r in rows]
        self.assertTrue(any('Skyline' in n for n in names))
        self.assertFalse(any('Garden' in n for n in names))

    # ── E. Re-link orphan conversation when a lead later appears ──────────────

    def test_orphan_conversation_relinks_on_lead_create(self):
        # Unknown number messages first → orphan conversation.
        with self.mock_pubsub():
            self._process({
                'event_type': 'lead_replied',
                'phone': '919876500077',
                'wa_message_id': 'wamid.orphan',
                'message_text': 'hello',
                'occurred_at': '2026-03-01T08:00:00Z',
            })
        conv = self.Conv.sudo().search([('phone_number', '=', '919876500077')])
        self.assertFalse(conv.lead_id)
        # The contact later becomes a real lead with the same number.
        rm = self.make_user()
        lead = self.make_lead(phone='9876500077', user_id=rm.id)
        conv.invalidate_recordset()
        self.assertEqual(conv.lead_id, lead,
                         "creating a matching lead must adopt the orphan conversation")
