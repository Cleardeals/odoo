"""HTTP controller for the WA Pub/Sub push endpoint.

GCP Pub/Sub delivers inbound WA events (messages, receipts, bridge ACKs) to
``POST /wa/pubsub/push`` with a Google-signed OIDC JWT in the
``Authorization: Bearer <token>`` header.

Security model
--------------
1. Token verification:  :func:`verify_push_token` from ``cleardeals_pubsub``
   validates the OIDC JWT, checks the ``aud`` claim against
   ``wa_communication.inbound_push_audience``, and optionally asserts the
   signing service account email against
   ``wa_communication.inbound_push_sa_email``.

2. Token verification is skipped when ``PUBSUB_EMULATOR_HOST`` is set so the
   local Pub/Sub emulator can push events without real JWTs.

3. The controller always returns HTTP 200 once the envelope has been parsed,
   even if message processing fails — this prevents GCP from retrying the
   delivery indefinitely.  Processing errors are logged to ``wa.event.log``.

4. Invalid envelopes (malformed JSON, missing ``message.data``) return HTTP
   200 too (logged, dropped).  Only authentication failures return 401.
"""

import base64
import json
import logging
import os

from odoo import http
from odoo.http import request

from odoo.addons.cleardeals_pubsub.controllers.push_utils import (
    InvalidPushTokenError,
    verify_push_token,
)

_logger = logging.getLogger(__name__)

_AUDIENCE_KEY = 'wa_communication.inbound_push_audience'
_SA_EMAIL_KEY = 'wa_communication.inbound_push_sa_email'


class WaPubSubPushController(http.Controller):

    @http.route(
        '/wa/pubsub/push',
        type='http',
        auth='none',
        methods=['POST'],
        csrf=False,
        save_session=False,
        # In Odoo 19 routes default to readonly when ``auth='none'``.  This
        # endpoint *writes* (creates conversations, messages, event-log rows),
        # so it must be explicitly read/write — otherwise the handler runs in a
        # read-only transaction and relies on the implicit readonly→readwrite
        # retry, which wastes a request in production and fails outright under
        # HttpCase.  Declaring it here keeps the write intent unambiguous.
        readonly=False,
    )
    def wa_push(self, **_kwargs):
        """Receive and process one GCP Pub/Sub push delivery.

        Returns HTTP 200 on success, HTTP 401 on OIDC failure, and HTTP 200
        (with error logged) on all other failures to prevent GCP retries.
        """
        # ----------------------------------------------------------------
        # 1. Verify OIDC bearer token
        #
        # When PUBSUB_EMULATOR_HOST is set the local emulator never issues
        # real OIDC tokens, so we bypass the Authorization header check
        # entirely and let verify_push_token return its emulator sentinel.
        # ----------------------------------------------------------------
        is_emulator = bool(os.environ.get('PUBSUB_EMULATOR_HOST'))
        if is_emulator:
            bearer_token = ''
        else:
            auth_header = request.httprequest.headers.get('Authorization', '')
            if not auth_header.startswith('Bearer '):
                _logger.warning("wa_push: missing or malformed Authorization header")
                return request.make_response('Unauthorized', status=401)
            bearer_token = auth_header[len('Bearer '):]

        ICP = request.env['ir.config_parameter'].sudo()
        audience = ICP.get_param(_AUDIENCE_KEY, '')
        sa_email = ICP.get_param(_SA_EMAIL_KEY, '') or None

        try:
            verify_push_token(bearer_token, audience, expected_email=sa_email)
        except InvalidPushTokenError as exc:
            _logger.warning("wa_push: OIDC verification failed: %s", exc)
            return request.make_response('Unauthorized', status=401)

        # ----------------------------------------------------------------
        # 2. Parse the Pub/Sub push envelope
        # ----------------------------------------------------------------
        try:
            raw_body = request.httprequest.get_data(as_text=True)
            envelope = json.loads(raw_body)
            msg_obj = envelope.get('message') or {}
            pubsub_message_id: str = msg_obj.get('messageId', '')
            attributes: dict = msg_obj.get('attributes') or {}
            raw_b64: str = msg_obj.get('data', '')
            payload_bytes = base64.b64decode(raw_b64) if raw_b64 else b'{}'
            payload: dict = json.loads(payload_bytes)
        except Exception as exc:
            _logger.error(
                "wa_push: envelope parse failed — dropping message: %s", exc
            )
            # Return 200 to ACK the message and prevent infinite GCP retry.
            return request.make_response('OK', status=200)

        # ----------------------------------------------------------------
        # 3. Dispatch to the conversation router
        # ----------------------------------------------------------------
        try:
            request.env['wa.conversation'].sudo()._process_push_event(
                payload, attributes, pubsub_message_id
            )
        except Exception as exc:
            _logger.exception(
                "wa_push: dispatch raised for message %s: %s",
                pubsub_message_id,
                exc,
            )
            # Still return 200 — the error is logged inside _process_push_event.

        return request.make_response('OK', status=200)
