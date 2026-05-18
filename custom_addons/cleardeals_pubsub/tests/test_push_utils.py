"""Tests for the push_utils OIDC verification utility."""

import os
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase

from odoo.addons.cleardeals_pubsub.controllers.push_utils import (
    InvalidPushTokenError,
    verify_push_token,
)

_AUDIENCE = 'https://odoo.cleardeals.xyz/wa/pubsub/push'
_SA_EMAIL = 'pubsub-push@cleardeals-prod.iam.gserviceaccount.com'


class TestVerifyPushToken(TransactionCase):
    """Unit tests for :func:`verify_push_token`."""

    # ── Emulator shortcut ─────────────────────────────────────────────────────

    @patch.dict('os.environ', {'PUBSUB_EMULATOR_HOST': 'localhost:8085'})
    def test_emulator_skips_verification(self):
        """When PUBSUB_EMULATOR_HOST is set, verification is skipped."""
        result = verify_push_token('any-token', _AUDIENCE)
        self.assertEqual(result, {'emulator': True})

    @patch.dict('os.environ', {'PUBSUB_EMULATOR_HOST': 'localhost:8085'})
    def test_emulator_skips_with_empty_token(self):
        """Emulator shortcut applies even when the token string is empty."""
        result = verify_push_token('', _AUDIENCE)
        self.assertEqual(result, {'emulator': True})

    # ── Library not installed ─────────────────────────────────────────────────

    @patch(
        'odoo.addons.cleardeals_pubsub.controllers.push_utils._GOOGLE_AUTH_AVAILABLE',
        False,
    )
    def test_raises_runtime_error_when_library_missing(self):
        """RuntimeError is raised when google-auth is not installed."""
        env = {k: v for k, v in os.environ.items() if k != 'PUBSUB_EMULATOR_HOST'}
        with patch.dict('os.environ', env, clear=True):
            with self.assertRaises(RuntimeError):
                verify_push_token('some-token', _AUDIENCE)

    # ── Missing / empty token ─────────────────────────────────────────────────

    @patch(
        'odoo.addons.cleardeals_pubsub.controllers.push_utils._GOOGLE_AUTH_AVAILABLE',
        True,
    )
    def test_raises_on_empty_token(self):
        """InvalidPushTokenError is raised when the bearer token is empty."""
        env = {k: v for k, v in os.environ.items() if k != 'PUBSUB_EMULATOR_HOST'}
        with patch.dict('os.environ', env, clear=True):
            with self.assertRaises(InvalidPushTokenError):
                verify_push_token('', _AUDIENCE)

    # ── Successful verification ───────────────────────────────────────────────

    @patch(
        'odoo.addons.cleardeals_pubsub.controllers.push_utils._GOOGLE_AUTH_AVAILABLE',
        True,
    )
    @patch('odoo.addons.cleardeals_pubsub.controllers.push_utils._id_token')
    @patch('odoo.addons.cleardeals_pubsub.controllers.push_utils._google_requests')
    def test_returns_claims_on_valid_token(self, mock_requests, mock_id_token):
        """verify_push_token() returns JWT claims on a valid token."""
        mock_id_token.verify_oauth2_token.return_value = {
            'email': _SA_EMAIL,
            'sub': '12345',
            'aud': _AUDIENCE,
        }

        env = {k: v for k, v in os.environ.items() if k != 'PUBSUB_EMULATOR_HOST'}
        with patch.dict('os.environ', env, clear=True):
            claims = verify_push_token('valid.jwt.token', _AUDIENCE)

        self.assertEqual(claims['email'], _SA_EMAIL)
        mock_id_token.verify_oauth2_token.assert_called_once_with(
            'valid.jwt.token',
            mock_requests.Request(),
            audience=_AUDIENCE,
        )

    @patch(
        'odoo.addons.cleardeals_pubsub.controllers.push_utils._GOOGLE_AUTH_AVAILABLE',
        True,
    )
    @patch('odoo.addons.cleardeals_pubsub.controllers.push_utils._id_token')
    @patch('odoo.addons.cleardeals_pubsub.controllers.push_utils._google_requests')
    def test_email_assertion_passes_on_match(self, mock_requests, mock_id_token):
        """No error is raised when expected_email matches the token's email claim."""
        mock_id_token.verify_oauth2_token.return_value = {
            'email': _SA_EMAIL,
            'sub': '12345',
        }

        env = {k: v for k, v in os.environ.items() if k != 'PUBSUB_EMULATOR_HOST'}
        with patch.dict('os.environ', env, clear=True):
            claims = verify_push_token('valid.jwt.token', _AUDIENCE, expected_email=_SA_EMAIL)

        self.assertEqual(claims['email'], _SA_EMAIL)

    @patch(
        'odoo.addons.cleardeals_pubsub.controllers.push_utils._GOOGLE_AUTH_AVAILABLE',
        True,
    )
    @patch('odoo.addons.cleardeals_pubsub.controllers.push_utils._id_token')
    @patch('odoo.addons.cleardeals_pubsub.controllers.push_utils._google_requests')
    def test_email_assertion_fails_on_mismatch(self, mock_requests, mock_id_token):
        """InvalidPushTokenError is raised when the email claim does not match."""
        mock_id_token.verify_oauth2_token.return_value = {
            'email': 'wrong-account@other-project.iam.gserviceaccount.com',
            'sub': '99999',
        }

        env = {k: v for k, v in os.environ.items() if k != 'PUBSUB_EMULATOR_HOST'}
        with patch.dict('os.environ', env, clear=True):
            with self.assertRaises(InvalidPushTokenError):
                verify_push_token(
                    'valid.jwt.token',
                    _AUDIENCE,
                    expected_email=_SA_EMAIL,
                )

    # ── Invalid token ─────────────────────────────────────────────────────────

    @patch(
        'odoo.addons.cleardeals_pubsub.controllers.push_utils._GOOGLE_AUTH_AVAILABLE',
        True,
    )
    @patch('odoo.addons.cleardeals_pubsub.controllers.push_utils._id_token')
    @patch('odoo.addons.cleardeals_pubsub.controllers.push_utils._google_requests')
    def test_raises_on_expired_token(self, mock_requests, mock_id_token):
        """InvalidPushTokenError wraps a ValueError from google-auth."""
        mock_id_token.verify_oauth2_token.side_effect = ValueError('Token expired')

        env = {k: v for k, v in os.environ.items() if k != 'PUBSUB_EMULATOR_HOST'}
        with patch.dict('os.environ', env, clear=True):
            with self.assertRaises(InvalidPushTokenError, msg='Token expired'):
                verify_push_token('expired.jwt.token', _AUDIENCE)
