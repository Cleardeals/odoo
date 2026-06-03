"""Tests for wa.quick.reply — personal/shared scoping + record rules."""

import time

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'wa_communication')
class TestQuickReply(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.QR = cls.env['wa.quick.reply']
        suffix = str(int(time.time()))
        cls.rm_a = new_test_user(
            cls.env, login=f'rm_a_qr_{suffix}', groups='base.group_user')
        cls.rm_b = new_test_user(
            cls.env, login=f'rm_b_qr_{suffix}', groups='base.group_user')
        cls.manager = new_test_user(
            cls.env, login=f'wa_mgr_qr_{suffix}',
            groups='base.group_user,wa_communication.group_wa_manager')

    def test_personal_isolation(self):
        """RM A's personal reply is invisible to RM B; both see shared."""
        a_personal = self.QR.with_user(self.rm_a).create({
            'title': 'A only', 'body': 'private to A',
        })
        # Manager creates a shared reply (no owner).
        shared = self.QR.with_user(self.manager).create({
            'title': 'Team', 'body': 'shared text', 'user_id': False,
        })
        self.assertTrue(shared.is_shared)
        self.assertFalse(a_personal.is_shared)

        b_visible = self.QR.with_user(self.rm_b).search([])
        self.assertIn(shared, b_visible, "shared reply must be visible to RM B")
        self.assertNotIn(a_personal, b_visible, "A's personal reply must be hidden from B")

    def test_get_for_composer(self):
        """get_for_composer returns own + shared, excludes others' personal."""
        self.QR.with_user(self.rm_a).create({'title': 'A1', 'body': 'a body'})
        self.QR.with_user(self.rm_b).create({'title': 'B1', 'body': 'b body'})
        self.QR.with_user(self.manager).create(
            {'title': 'S1', 'body': 's body', 'user_id': False})

        titles = {r['title'] for r in
                  self.QR.with_user(self.rm_a).get_for_composer()}
        self.assertIn('A1', titles)
        self.assertIn('S1', titles)
        self.assertNotIn('B1', titles)

    def test_user_cannot_create_shared(self):
        """A plain user cannot create a shared (ownerless) reply."""
        with self.assertRaises(AccessError):
            self.QR.with_user(self.rm_a).create({
                'title': 'sneaky shared', 'body': 'x', 'user_id': False,
            })

    def test_user_cannot_edit_others_personal(self):
        """RM B cannot read/write RM A's personal reply."""
        a_personal = self.QR.with_user(self.rm_a).create(
            {'title': 'A only', 'body': 'private'})
        with self.assertRaises(AccessError):
            self.QR.with_user(self.rm_b).browse(a_personal.id).write({'body': 'hacked'})

    def test_manager_manages_shared(self):
        """Manager can create, edit and delete shared replies."""
        shared = self.QR.with_user(self.manager).create(
            {'title': 'Team', 'body': 'v1', 'user_id': False})
        shared.with_user(self.manager).write({'body': 'v2'})
        self.assertEqual(shared.body, 'v2')
        shared.with_user(self.manager).unlink()
