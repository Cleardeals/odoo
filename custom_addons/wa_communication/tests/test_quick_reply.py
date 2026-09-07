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

    # ── List quick replies ────────────────────────────────────────────────────

    def test_defaults_to_text_kind(self):
        r = self.QR.with_user(self.rm_a).create({'title': 'T', 'body': 'hi'})
        self.assertEqual(r.kind, 'text')
        self.assertIsNone(r._parsed_list_payload())

    def test_list_quick_reply_parses_payload(self):
        import json
        payload = {'button': 'View options', 'sections': [
            {'title': 'Homes', 'rows': [{'id': 'r1', 'title': '2 BHK'}]}]}
        r = self.QR.with_user(self.rm_a).create({
            'title': 'Home types', 'body': 'Pick one', 'kind': 'list',
            'list_payload': json.dumps(payload),
        })
        parsed = r._parsed_list_payload()
        self.assertEqual(parsed['button'], 'View options')
        self.assertEqual(parsed['sections'][0]['rows'][0]['title'], '2 BHK')

    def test_get_for_composer_carries_kind_and_list_payload(self):
        import json
        self.QR.with_user(self.rm_a).create({
            'title': 'LQR', 'body': 'body', 'kind': 'list',
            'list_payload': json.dumps({'button': 'Go', 'sections': [
                {'title': 'S', 'rows': [{'id': 'r1', 'title': 'A'}]}]}),
        })
        row = next(r for r in self.QR.with_user(self.rm_a).get_for_composer()
                   if r['title'] == 'LQR')
        self.assertEqual(row['kind'], 'list')
        self.assertEqual(row['list_payload']['button'], 'Go')

    def test_list_quick_reply_row_title_over_24_chars_rejected(self):
        """A saved list with an over-long row title would fail at send time with
        an opaque Interakt 400 — reject it while the author is still here."""
        import json
        from odoo.exceptions import ValidationError
        long_title = 'Liked & Want Another visit with family'   # 38 chars
        with self.assertRaises(ValidationError) as ctx:
            self.QR.with_user(self.rm_a).create({
                'title': 'FB', 'body': 'b', 'kind': 'list',
                'list_payload': json.dumps({'button': 'Show Feedback', 'sections': [
                    {'title': 'S', 'rows': [{'id': 'r1', 'title': long_title}]}]}),
            })
        self.assertIn(long_title, str(ctx.exception))

    def test_list_quick_reply_row_title_exactly_24_chars_allowed(self):
        import json
        r = self.QR.with_user(self.rm_a).create({
            'title': 'FB', 'body': 'b', 'kind': 'list',
            'list_payload': json.dumps({'button': 'Show Feedback', 'sections': [
                {'title': 'S', 'rows': [
                    {'id': 'r1', 'title': 'Looking for more options'}]}]}),
        })
        self.assertEqual(r._parsed_list_payload()['sections'][0]['rows'][0]['title'],
                         'Looking for more options')

    def test_list_quick_reply_button_over_20_chars_rejected(self):
        import json
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.QR.with_user(self.rm_a).create({
                'title': 'FB', 'body': 'b', 'kind': 'list',
                'list_payload': json.dumps({'button': 'B' * 21, 'sections': [
                    {'title': 'S', 'rows': [{'id': 'r1', 'title': 'ok'}]}]}),
            })

    def test_text_quick_reply_ignores_list_limits(self):
        """A text reply with a long body is untouched by the list caps."""
        r = self.QR.with_user(self.rm_a).create({
            'title': 'T', 'body': 'x' * 500, 'kind': 'text'})
        self.assertEqual(r.kind, 'text')

    def test_malformed_list_payload_returns_none(self):
        r = self.QR.with_user(self.rm_a).create({
            'title': 'bad', 'body': 'b', 'kind': 'list',
            'list_payload': 'not json{',
        })
        self.assertIsNone(r._parsed_list_payload())
