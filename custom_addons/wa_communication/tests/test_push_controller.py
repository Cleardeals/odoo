"""Tests for the wa_communication push controller and event routing.

These are HTTP-level integration tests that mock OIDC verification so they
run without a live GCP project.  All Pub/Sub publish calls are also patched
out so no external network calls are made.
"""

import base64
import json
from unittest.mock import MagicMock, patch

from odoo.tests import HttpCase, tagged


def _b64_json(data: dict) -> str:
    """Return ``data`` as a base64-encoded JSON string (Pub/Sub data field)."""
    return base64.b64encode(json.dumps(data).encode()).decode()


def _make_envelope(payload: dict, message_id: str = 'test-msg-001') -> bytes:
    """Build a minimal GCP Pub/Sub push envelope containing ``payload``."""
    return json.dumps({
        'message': {
            'data': _b64_json(payload),
            'messageId': message_id,
            'attributes': {},
        },
        'subscription': 'projects/test-project/subscriptions/wa-odoo-events',
    }).encode()


def _wa_message_payload(
    from_phone: str = '919876543210',
    body: str = 'Hello Cleardeals',
    wa_msg_id: str = 'wamid.test001',
) -> dict:
    """Build a WA Cloud API webhook payload for one inbound text message."""
    return {
        'object': 'whatsapp_business_account',
        'entry': [{
            'id': 'WBA_ID',
            'changes': [{
                'value': {
                    'messaging_product': 'whatsapp',
                    'metadata': {
                        'display_phone_number': '911234567890',
                        'phone_number_id': 'PN_ID',
                    },
                    'contacts': [{'profile': {'name': 'Test Customer'}, 'wa_id': from_phone}],
                    'messages': [{
                        'from': from_phone,
                        'id': wa_msg_id,
                        'timestamp': '1700000000',
                        'type': 'text',
                        'text': {'body': body},
                    }],
                },
                'field': 'messages',
            }],
        }],
    }


def _wa_status_payload(
    wa_msg_id: str = 'wamid.test001',
    status: str = 'delivered',
) -> dict:
    """Build a WA Cloud API webhook payload for a status update."""
    return {
        'object': 'whatsapp_business_account',
        'entry': [{
            'changes': [{
                'value': {
                    'messaging_product': 'whatsapp',
                    'statuses': [{
                        'id': wa_msg_id,
                        'status': status,
                        'timestamp': '1700000001',
                        'recipient_id': '919876543210',
                    }],
                },
                'field': 'messages',
            }],
        }],
    }


# Patch target: suppress OIDC verification in all test cases
_VERIFY_PATCH = (
    'odoo.addons.cleardeals_pubsub.controllers.push_utils.verify_push_token'
)


@tagged('post_install', '-at_install', 'wa_communication')
class TestWaPushController(HttpCase):
    """HTTP-level tests for POST /wa/pubsub/push."""

    def setUp(self):
        super().setUp()
        # Seed config parameters so the controller can read them
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('wa_communication.inbound_push_audience', 'https://test.example/wa/pubsub/push')
        ICP.set_param('wa_communication.inbound_push_sa_email', '')
        ICP.set_param('wa_communication.topic_odoo_wa_requests', 'cd-test-odoo-wa-requests')

    def _post_push(self, payload: dict, token: str = 'valid-token') -> object:
        """POST the push envelope to the controller and return the response."""
        return self.url_open(
            '/wa/pubsub/push',
            data=_make_envelope(payload),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {token}',
            },
        )

    # ------------------------------------------------------------------
    # Auth tests
    # ------------------------------------------------------------------

    def test_missing_auth_header_returns_401(self):
        resp = self.url_open(
            '/wa/pubsub/push',
            data=_make_envelope({'object': 'test'}),
            headers={'Content-Type': 'application/json'},
        )
        self.assertEqual(resp.status_code, 401)

    def test_oidc_failure_returns_401(self):
        from odoo.addons.cleardeals_pubsub.controllers.push_utils import InvalidPushTokenError
        with patch(_VERIFY_PATCH, side_effect=InvalidPushTokenError('bad token')):
            resp = self._post_push({'object': 'test'})
        self.assertEqual(resp.status_code, 401)

    # ------------------------------------------------------------------
    # Inbound message tests
    # ------------------------------------------------------------------

    def test_inbound_text_message_creates_conversation_and_message(self):
        payload = _wa_message_payload(
            from_phone='919000000001',
            body='I want to visit the flat',
            wa_msg_id='wamid.inbound001',
        )
        with patch(_VERIFY_PATCH):
            resp = self._post_push(payload)

        self.assertEqual(resp.status_code, 200)

        conv = self.env['wa.conversation'].sudo().search(
            [('phone_number', '=', '919000000001')], limit=1
        )
        self.assertTrue(conv, "Conversation should have been created")

        msg = self.env['wa.message'].sudo().search(
            [('wa_message_id', '=', 'wamid.inbound001')], limit=1
        )
        self.assertTrue(msg, "Message record should have been created")
        self.assertEqual(msg.direction, 'inbound')
        self.assertEqual(msg.body, 'I want to visit the flat')
        self.assertEqual(msg.status, 'delivered')

    def test_duplicate_wa_message_id_is_silently_dropped(self):
        payload = _wa_message_payload(
            from_phone='919000000002',
            wa_msg_id='wamid.dup001',
        )
        with patch(_VERIFY_PATCH):
            self._post_push(payload)
            self._post_push(payload)  # duplicate

        count = self.env['wa.message'].sudo().search_count(
            [('wa_message_id', '=', 'wamid.dup001')]
        )
        self.assertEqual(count, 1, "Duplicate message should be dropped")

    # ------------------------------------------------------------------
    # Status update tests
    # ------------------------------------------------------------------

    def test_status_update_updates_message_status(self):
        # Pre-create a wa.message with a known wa_message_id
        conv = self.env['wa.conversation'].sudo().create({
            'phone_number': '919000000003',
        })
        msg = self.env['wa.message'].sudo().create({
            'conversation_id': conv.id,
            'wa_message_id': 'wamid.status001',
            'direction': 'outbound',
            'initiator': 'rm',
            'kind': 'freetext',
            'body': 'We will call you shortly.',
            'status': 'sent',
            'occurred_at': '2024-01-01 10:00:00',
        })

        payload = _wa_status_payload(wa_msg_id='wamid.status001', status='read')
        with patch(_VERIFY_PATCH):
            resp = self._post_push(payload)

        self.assertEqual(resp.status_code, 200)
        msg.invalidate_recordset()
        self.assertEqual(msg.status, 'read')

    # ------------------------------------------------------------------
    # Event log tests
    # ------------------------------------------------------------------

    def test_inbound_message_creates_event_log_entry(self):
        payload = _wa_message_payload(
            from_phone='919000000004',
            wa_msg_id='wamid.log001',
        )
        with patch(_VERIFY_PATCH):
            self._post_push(payload, token='tok')

        log = self.env['wa.event.log'].sudo().search(
            [('event_type', '=', 'wa_message_inbound')],
            order='create_date desc',
            limit=1,
        )
        self.assertTrue(log, "Event log entry should have been created")
        self.assertEqual(log.direction, 'inbound')
        self.assertEqual(log.status, 'processed')

    def test_event_log_is_immutable(self):
        log = self.env['wa.event.log'].sudo()._log(
            event_type='test_event',
            direction='inbound',
            payload={'x': 1},
            status='processed',
        )
        from odoo.exceptions import AccessError
        with self.assertRaises(AccessError):
            log.write({'event_type': 'changed'})
        with self.assertRaises(AccessError):
            log.unlink()
