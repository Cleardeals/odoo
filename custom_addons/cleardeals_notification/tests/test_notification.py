"""Tests for the reusable cleardeals.notification backend."""

import time
from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged

_BUS = 'odoo.addons.bus.models.bus.BusBus'


@tagged('post_install', '-at_install', 'cleardeals_notification')
class TestNotification(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Notif = cls.env['cleardeals.notification']
        s = str(int(time.time()))
        cls.ua = new_test_user(cls.env, login=f'cdn_a_{s}', groups='base.group_user')
        cls.ub = new_test_user(cls.env, login=f'cdn_b_{s}', groups='base.group_user')

    # ── notify(): persist + bus ───────────────────────────────────────────────

    def test_notify_persists_and_pushes_bus(self):
        captured = []

        def _cap(self2, target, ntype, message):
            captured.append((target, ntype, message))

        with patch.object(self.env['bus.bus'].__class__, '_sendone', _cap):
            recs = self.Notif.notify(
                self.ua, 'reassignment_request',
                title='Handover', body='Take over?',
                payload={'request_id': 7, 'suppress_key': '9199'},
                actionable=True)

        self.assertEqual(len(recs), 1)
        self.assertEqual(recs.user_id, self.ua)
        self.assertTrue(recs.is_actionable)
        self.assertTrue(recs.sticky)  # actionable ⇒ sticky
        # Bus pushed to the recipient's channel with the spread payload.
        self.assertEqual(len(captured), 1)
        target, ntype, msg = captured[0]
        self.assertEqual(target, 'cleardeals_notification_%d' % self.ua.id)
        self.assertEqual(ntype, 'cd_notification')
        self.assertEqual(msg['type'], 'reassignment_request')
        self.assertEqual(msg['request_id'], 7)            # payload spread
        self.assertEqual(msg['suppress_key'], '9199')
        self.assertEqual(msg['notification_id'], recs.id)

    def test_notify_multiple_users(self):
        with patch.object(self.env['bus.bus'].__class__, '_sendone'):
            recs = self.Notif.notify([self.ua.id, self.ub.id], 'lead_replied',
                                     title='Reply', body='hi')
        self.assertEqual(set(recs.mapped('user_id')), {self.ua, self.ub})

    def test_notify_empty_users_is_noop(self):
        self.assertFalse(self.Notif.notify([], 'x'))
        self.assertFalse(self.Notif.notify(False, 'x'))

    def test_payload_cannot_override_canonical_keys(self):
        with patch.object(self.env['bus.bus'].__class__, '_sendone'):
            rec = self.Notif.notify(
                self.ua, 'real_type',
                payload={'type': 'spoofed', 'notification_id': 999})
        d = rec._to_dict()
        self.assertEqual(d['type'], 'real_type')
        self.assertEqual(d['notification_id'], rec.id)

    # ── get_unread / counts / mark read (current-user scoped) ─────────────────

    def test_get_unread_scoped_to_current_user(self):
        with patch.object(self.env['bus.bus'].__class__, '_sendone'):
            self.Notif.notify(self.ua, 't1', title='A')
            self.Notif.notify(self.ub, 't2', title='B')
        a = self.Notif.with_user(self.ua).get_unread()
        titles = {n['title'] for n in a}
        self.assertIn('A', titles)
        self.assertNotIn('B', titles)

    def test_mark_read_and_count(self):
        with patch.object(self.env['bus.bus'].__class__, '_sendone'):
            r1 = self.Notif.notify(self.ua, 't', title='one')
            self.Notif.notify(self.ua, 't', title='two')
        self.assertEqual(self.Notif.with_user(self.ua).get_unread_count(), 2)
        self.Notif.with_user(self.ua).mark_read([r1.id])
        self.assertEqual(self.Notif.with_user(self.ua).get_unread_count(), 1)

    def test_mark_read_cannot_touch_others(self):
        with patch.object(self.env['bus.bus'].__class__, '_sendone'):
            rb = self.Notif.notify(self.ub, 't', title='b only')
        # ua tries to mark ub's notification read — silently ignored.
        self.Notif.with_user(self.ua).mark_read([rb.id])
        self.assertFalse(rb.is_read)

    def test_mark_all_read(self):
        with patch.object(self.env['bus.bus'].__class__, '_sendone'):
            self.Notif.notify(self.ua, 't', title='x')
            self.Notif.notify(self.ua, 't', title='y')
        self.Notif.with_user(self.ua).mark_all_read()
        self.assertEqual(self.Notif.with_user(self.ua).get_unread_count(), 0)

    # ── Record-rule isolation ─────────────────────────────────────────────────

    def test_user_cannot_read_others_notifications(self):
        with patch.object(self.env['bus.bus'].__class__, '_sendone'):
            rb = self.Notif.notify(self.ub, 't', title='secret')
        with self.assertRaises(AccessError):
            self.Notif.with_user(self.ua).browse(rb.id).read(['title'])
