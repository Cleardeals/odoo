"""
cleardeals_pubsub.controllers.push_utils — OIDC verification for Pub/Sub push.

GCP Pub/Sub attaches a Google-signed OIDC JWT to every push delivery in the
``Authorization: Bearer <token>`` header.  This module exposes a single
function, :func:`verify_push_token`, that validates the token before the
handler trusts the request body.

Importing
---------
Controllers in dependent addons import this directly::

    from odoo.addons.cleardeals_pubsub.controllers.push_utils import (
        verify_push_token,
        InvalidPushTokenError,
    )

Emulator behaviour
------------------
When ``PUBSUB_EMULATOR_HOST`` is set (local/staging development) the emulator
does **not** issue OIDC tokens, so verification is skipped entirely.  The
function returns a sentinel dict ``{'emulator': True}`` to let the caller
distinguish between a real verified identity and a skipped-dev path.
"""

import logging
import os
from typing import Optional

_logger = logging.getLogger(__name__)

# ── Library presence check ────────────────────────────────────────────────────

try:
    from google.auth.transport import requests as _google_requests
    from google.oauth2 import id_token as _id_token
    _GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    _GOOGLE_AUTH_AVAILABLE = False
    _logger.warning(
        'cleardeals_pubsub: google-auth is not installed.  '
        'OIDC push-token verification will be unavailable.  '
        'Install it with: pip install google-auth'
    )


# ── Public exception ──────────────────────────────────────────────────────────

class InvalidPushTokenError(Exception):
    """Raised when the OIDC token attached to a Pub/Sub push request is invalid.

    HTTP controllers should catch this and return 401 Unauthorized so that GCP
    retries the delivery later.
    """


# ── Public API ────────────────────────────────────────────────────────────────

def verify_push_token(
    bearer_token: str,
    audience: str,
    expected_email: Optional[str] = None,
) -> dict:
    """Verify the OIDC bearer token sent by GCP on a Pub/Sub push delivery.

    The token is validated against Google's public keys.  The ``audience``
    claim must match *audience* exactly (typically the full HTTPS URL of the
    push endpoint).  Optionally the caller can assert the issuing service
    account email via *expected_email*.

    When ``PUBSUB_EMULATOR_HOST`` is set the function returns immediately with
    a sentinel dict — the emulator never issues real OIDC tokens.

    Args:
        bearer_token:   Raw JWT string from the ``Authorization`` header
                        (strip the ``'Bearer '`` prefix before passing).
        audience:       Expected ``aud`` claim — the full push endpoint URL,
                        e.g. ``'https://odoo.cleardeals.xyz/wa/pubsub/push'``.
                        Store this in ``ir.config_parameter`` so it can be
                        updated without a code deploy.
        expected_email: Optional service-account email to assert against the
                        ``email`` claim (e.g.
                        ``'pubsub-push@cleardeals-prod.iam.gserviceaccount.com'``).
                        Pass ``None`` to skip the email check.

    Returns:
        dict: Decoded JWT claims on success.  Keys include ``'email'``,
        ``'sub'``, ``'aud'``, ``'iat'``, ``'exp'``.  Returns
        ``{'emulator': True}`` when running against the local emulator.

    Raises:
        InvalidPushTokenError: Token is missing, malformed, expired, or the
            audience / email assertion fails.
        RuntimeError: ``google-auth`` is not installed in a non-emulator env.
    """
    # ── Emulator shortcut ─────────────────────────────────────────────────────
    if os.environ.get('PUBSUB_EMULATOR_HOST'):
        _logger.debug(
            'cleardeals_pubsub.verify_push_token: PUBSUB_EMULATOR_HOST is set '
            '— skipping OIDC verification'
        )
        return {'emulator': True}

    # ── Library guard ─────────────────────────────────────────────────────────
    if not _GOOGLE_AUTH_AVAILABLE:
        raise RuntimeError(
            'google-auth is not installed.  Cannot verify OIDC push token.  '
            'Run: pip install google-auth'
        )

    # ── Token presence ────────────────────────────────────────────────────────
    if not bearer_token or not bearer_token.strip():
        raise InvalidPushTokenError(
            'Authorization header is missing or empty.  '
            'GCP Pub/Sub push deliveries must include an OIDC bearer token.'
        )

    # ── Cryptographic verification ────────────────────────────────────────────
    try:
        request = _google_requests.Request()
        claims: dict = _id_token.verify_oauth2_token(
            bearer_token.strip(),
            request,
            audience=audience,
        )
    except ValueError as exc:
        raise InvalidPushTokenError(
            f'OIDC token verification failed: {exc}'
        ) from exc

    # ── Optional email assertion ──────────────────────────────────────────────
    if expected_email is not None:
        token_email = claims.get('email', '')
        if token_email != expected_email:
            raise InvalidPushTokenError(
                f'OIDC token email mismatch: expected {expected_email!r}, '
                f'got {token_email!r}.'
            )

    _logger.debug(
        'cleardeals_pubsub.verify_push_token: verified token for %s',
        claims.get('email', '<unknown>'),
    )
    return claims
