"""Tests for the Send-Template flow — Interakt template fetch + template send."""

from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

_SAMPLE_RESPONSE = {
    "count": 1,
    "has_next": False,
    "results": {
        "templates": [
            {
                "id": "ea5258f4-f13c-4694-9c7c-0a8443d15c7f",
                "name": "test123",
                "display_name": "gsheet_Test",
                "language": "en",
                "category": "UTILITY",
                "header": None,
                "body": "Hi {{1}},\n\nThis is a test utility template dated {{2}}"
                        "\n\nBest Regards,\nInterakt Team",
                "footer": None,
                "buttons": "\"{}\"",
                "approval_status": "APPROVED",
                "variable_present": "Yes",
            }
        ]
    },
}

_CLIENT = 'odoo.addons.wa_communication.models.interakt_client'


@tagged('post_install', '-at_install', 'wa_communication')
class TestSendTemplate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Conv = cls.env['wa.conversation']
        cls.env['ir.config_parameter'].sudo().set_param(
            'wa_communication.interakt_api_key', 'TEST_KEY')
        cls.env['ir.config_parameter'].sudo().set_param(
            'wa_communication.interakt_base_url', 'https://api.interakt.ai')

    def _mock_get(self, payload=_SAMPLE_RESPONSE, status=200):
        resp = MagicMock()
        resp.status_code = status
        resp.json.return_value = payload
        resp.text = 'err'
        return resp

    def test_fetch_templates_parses_variables(self):
        with patch(f'{_CLIENT}.requests.get', return_value=self._mock_get()):
            templates = self.Conv.fetch_templates()
        self.assertEqual(len(templates), 1)
        t = templates[0]
        self.assertEqual(t['name'], 'test123')
        # {{1}} and {{2}} in the body → two body variable slots, no header slot.
        body_vars = [v for v in t['variables'] if v['scope'] == 'body']
        header_vars = [v for v in t['variables'] if v['scope'] == 'header']
        self.assertEqual([v['position'] for v in body_vars], [1, 2])
        self.assertEqual(header_vars, [])
        # The "\"{}\"" empty-buttons string must parse to no buttons, not raise.
        self.assertEqual(t['buttons'], [])

    def test_fetch_templates_missing_key_raises(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'wa_communication.interakt_api_key', '')
        with self.assertRaises(UserError):
            self.Conv.fetch_templates()

    def test_fetch_templates_http_error_raises(self):
        with patch(f'{_CLIENT}.requests.get',
                   return_value=self._mock_get(status=401)):
            with self.assertRaises(UserError):
                self.Conv.fetch_templates()

    def test_send_template_queues_message_and_publishes(self):
        # Own the chat so the assignee gate (Feature 3) lets us send.
        conv = self.Conv.create({
            'phone_number': '919876543210',
            'assigned_user_id': self.env.uid,
        })
        captured = []

        def _fake_publish(self2, topic, payload):
            captured.append((topic, payload))

        pubsub_cls = type(self.env['cleardeals.pubsub'])
        with patch.object(pubsub_cls, 'publish_async', _fake_publish):
            msg = conv.send_message(
                kind='template', template_name='test123',
                body_values=['Nirat', '2026-06-03'])
            # Flush deferred post-commit publish so we can assert on it.
            self.env.cr.postcommit.run()

        self.assertEqual(msg.kind, 'template')
        self.assertEqual(msg.template_name, 'test123')
        self.assertEqual(msg.status, 'queued')
        self.assertTrue(captured, "a send request must be published")
        _topic, payload = captured[-1]
        self.assertEqual(payload['request_type'], 'send')
        self.assertEqual(payload['kind'], 'template')
        self.assertEqual(payload['template_name'], 'test123')
        self.assertEqual(payload['body_values'], ['Nirat', '2026-06-03'])
