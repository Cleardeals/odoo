"""``wa.conversation`` lookup + computed fields.

Covers the phone→conversation resolution (including lead auto-linking with the
91-prefix strip), the computed ``name`` / ``window_state`` / ``interakt_url``
fields, and the phone-uniqueness constraint.
"""

from datetime import datetime, timedelta

import psycopg2
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import WaTransactionCase


@tagged('post_install', '-at_install', 'wa_communication')
class TestConversationModel(WaTransactionCase):

    # ── _get_or_create_for_phone ──────────────────────────────────────────────

    def test_get_or_create_creates_then_reuses(self):
        phone = self._uniq_phone()
        c1 = self.Conv._get_or_create_for_phone(phone)
        c2 = self.Conv._get_or_create_for_phone(phone)
        self.assertEqual(c1, c2, "second call must return the same conversation")

    def test_get_or_create_autolinks_lead_by_phone(self):
        # Conversation stores 91 + 10 digits; the lead stores the bare 10 digits.
        lead = self.make_lead(phone='9876500011')
        conv = self.Conv._get_or_create_for_phone('919876500011')
        self.assertEqual(conv.lead_id, lead,
                         "new conversation should auto-link the matching lead")

    def test_get_or_create_no_lead_match_leaves_blank(self):
        conv = self.Conv._get_or_create_for_phone('910000000999')
        self.assertFalse(conv.lead_id)

    # ── Computed fields ───────────────────────────────────────────────────────

    def test_name_prefers_lead_then_phone(self):
        conv = self.make_conversation(phone_number='911112223334')
        self.assertEqual(conv.name, '911112223334')
        lead = self.make_lead(name='Asha Buyer', phone='1112223334')
        conv.lead_id = lead.id
        conv.invalidate_recordset()
        self.assertEqual(conv.name, 'Asha Buyer')

    def test_window_state_compute(self):
        conv = self.make_conversation()
        conv.window_expires_at = datetime.utcnow() + timedelta(hours=1)
        conv.invalidate_recordset()
        self.assertEqual(conv.window_state, 'open')
        conv.window_expires_at = datetime.utcnow() - timedelta(hours=1)
        conv.invalidate_recordset()
        self.assertEqual(conv.window_state, 'closed')
        conv.window_expires_at = False
        conv.invalidate_recordset()
        self.assertEqual(conv.window_state, 'closed')

    def test_interakt_inbox_url_compute(self):
        conv = self.make_conversation(phone_number='919998887776')
        self.assertIn('channelPhoneNumber=919998887776', conv.interakt_inbox_url)

    def test_message_count_compute(self):
        conv = self.make_conversation()
        self.make_message(conv)
        self.make_message(conv)
        conv.invalidate_recordset()
        self.assertEqual(conv.message_count, 2)

    # ── Constraints ───────────────────────────────────────────────────────────

    def test_phone_number_unique(self):
        phone = self._uniq_phone()
        self.make_conversation(phone_number=phone)
        self.env.flush_all()
        # The UNIQUE constraint fires at flush time; force it inside the guard.
        with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.IntegrityError):
            self.make_conversation(phone_number=phone)
            self.env.flush_all()
