"""Interakt template client — pure helpers + pagination.

``test_send_template`` exercises ``wa.conversation.fetch_templates`` end-to-end;
this file unit-tests the parsing helpers that are easy to get subtly wrong
(double-encoded button JSON, variable ordering) and the pagination loop.
"""

from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.wa_communication.models import interakt_client as ic

_CLIENT = 'odoo.addons.wa_communication.models.interakt_client'


@tagged('post_install', '-at_install', 'wa_communication')
class TestInteraktHelpers(TransactionCase):
    """Pure-function helpers — no DB, no network."""

    # ── _parse_buttons ────────────────────────────────────────────────────────

    def test_parse_buttons_empty_double_encoded(self):
        # The notorious "\"{}\"" empty-buttons string must yield [] not raise.
        self.assertEqual(ic._parse_buttons('"{}"'), [])

    def test_parse_buttons_none_and_blank(self):
        self.assertEqual(ic._parse_buttons(None), [])
        self.assertEqual(ic._parse_buttons(''), [])

    def test_parse_buttons_list_of_dicts(self):
        raw = '[{"text": "Yes"}, {"text": "No"}]'
        self.assertEqual(ic._parse_buttons(raw), ['Yes', 'No'])

    def test_parse_buttons_double_encoded_list(self):
        # A JSON string wrapped again in a JSON string (two encode layers).
        raw = '"[{\\"text\\": \\"Visit\\"}]"'
        self.assertEqual(ic._parse_buttons(raw), ['Visit'])

    def test_parse_buttons_dict_keyed(self):
        raw = '{"0": {"text": "A"}, "1": {"text": "B"}}'
        self.assertEqual(sorted(ic._parse_buttons(raw)), ['A', 'B'])

    # ── _extract_variables ────────────────────────────────────────────────────

    def test_extract_variables_orders_and_dedups(self):
        slots = ic._extract_variables('Hello {{1}}', 'Visit {{1}} on {{2}} at {{2}}')
        header = [s for s in slots if s['scope'] == 'header']
        body = [s for s in slots if s['scope'] == 'body']
        self.assertEqual([s['position'] for s in header], [1])
        self.assertEqual([s['position'] for s in body], [1, 2])

    def test_extract_variables_none_text(self):
        self.assertEqual(ic._extract_variables(None, None), [])

    # ── _normalize_template ───────────────────────────────────────────────────

    def test_normalize_template_shape(self):
        t = ic._normalize_template({
            'name': 'welcome',
            'language': 'en',
            'category': 'UTILITY',
            'header': 'Hi {{1}}',
            'body': 'Your code is {{1}}',
            'footer': 'Team',
            'buttons': '"{}"',
            'approval_status': 'APPROVED',
        })
        self.assertEqual(t['name'], 'welcome')
        self.assertEqual(t['footer'], 'Team')
        self.assertEqual(t['buttons'], [])
        # header {{1}} + body {{1}} → two slots in two scopes.
        self.assertEqual(len(t['variables']), 2)


@tagged('post_install', '-at_install', 'wa_communication')
class TestInteraktFetch(TransactionCase):
    """fetch_templates pagination + error handling (mocked HTTP)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param(
            'wa_communication.interakt_api_key', 'TEST_KEY')

    def _resp(self, payload, status=200):
        r = MagicMock()
        r.status_code = status
        r.json.return_value = payload
        r.text = 'err'
        return r

    def test_pagination_follows_has_next(self):
        page1 = {'has_next': True, 'results': {'templates': [
            {'name': 'a', 'body': 'x'}]}}
        page2 = {'has_next': False, 'results': {'templates': [
            {'name': 'b', 'body': 'y'}]}}
        with patch(f'{_CLIENT}.requests.get',
                   side_effect=[self._resp(page1), self._resp(page2)]):
            out = ic.fetch_templates(self.env)
        self.assertEqual([t['name'] for t in out], ['a', 'b'])

    def test_non_json_response_raises(self):
        r = MagicMock()
        r.status_code = 200
        r.json.side_effect = ValueError('no json')
        with patch(f'{_CLIENT}.requests.get', return_value=r):
            with self.assertRaises(UserError):
                ic.fetch_templates(self.env)

    def test_transport_error_raises_usererror(self):
        import requests
        with patch(f'{_CLIENT}.requests.get',
                   side_effect=requests.RequestException('boom')):
            with self.assertRaises(UserError):
                ic.fetch_templates(self.env)

    def test_skips_templates_without_name(self):
        payload = {'has_next': False, 'results': {'templates': [
            {'name': '', 'body': 'x'}, {'name': 'keep', 'body': 'y'}]}}
        with patch(f'{_CLIENT}.requests.get', return_value=self._resp(payload)):
            out = ic.fetch_templates(self.env)
        self.assertEqual([t['name'] for t in out], ['keep'])
