"""``wa.message`` append-only invariants — the audit-trail guarantees.

Messages are an immutable ledger: structural fields can't change after creation
and rows can't be deleted individually.  These guarantees are load-bearing for
billing/audit, so they get their own tests.
"""

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import WaTransactionCase


@tagged('post_install', '-at_install', 'wa_communication')
class TestWaMessageModel(WaTransactionCase):

    def _msg(self, conv, **vals):
        return self.make_message(conv, **vals)

    def test_immutable_fields_reject_write(self):
        conv = self.make_conversation()
        msg = self._msg(conv, body='original')
        for field, value in (
            ('body', 'tampered'),
            ('direction', 'outbound'),
            ('kind', 'template'),
            ('occurred_at', '2030-01-01 00:00:00'),
        ):
            with self.assertRaises(ValidationError, msg='%s must be immutable' % field):
                msg.write({field: value})

    def test_mutable_status_field_is_allowed(self):
        conv = self.make_conversation()
        msg = self._msg(conv, direction='outbound', initiator='rm',
                        kind='freetext', status='sent')
        msg.write({'status': 'delivered'})  # must not raise
        self.assertEqual(msg.status, 'delivered')

    def test_allow_write_context_bypasses_immutability(self):
        conv = self.make_conversation()
        msg = self._msg(conv, body='original')
        msg.with_context(_wa_message_allow_write=True).write({'body': 'fixed'})
        self.assertEqual(msg.body, 'fixed')

    def test_unlink_blocked_by_default(self):
        conv = self.make_conversation()
        msg = self._msg(conv)
        with self.assertRaises(UserError):
            msg.unlink()

    def test_unlink_allowed_with_context(self):
        conv = self.make_conversation()
        msg = self._msg(conv)
        msg.with_context(_wa_message_allow_delete=True).unlink()
        self.assertFalse(msg.exists())

    def test_conversation_delete_cascades_messages(self):
        conv = self.make_conversation()
        self._msg(conv)
        self._msg(conv)
        conv_id = conv.id
        conv.unlink()
        remaining = self.Msg.sudo().search_count(
            [('conversation_id', '=', conv_id)])
        self.assertEqual(remaining, 0, "messages must cascade with their conversation")
