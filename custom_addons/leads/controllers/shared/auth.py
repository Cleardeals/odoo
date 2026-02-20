"""
auth.py
-------
Centralised API key authentication for all Track API endpoints.

How it works
------------
- Every protected route calls `validate_api_key(request)` before any logic.
- The expected key is stored in Odoo's ir.config_parameter under the key
  `track_api.secret_key`, so it can be rotated without a code deploy.
- The caller must send the key in the `X-API-Key` HTTP header.

Setup (run once in Odoo shell or Settings → Technical → System Parameters)
---------------------------------------------------------------------------
    self.env['ir.config_parameter'].sudo().set_param(
        'track_api.secret_key', 'your-strong-secret-here'
    )

Usage in a controller
---------------------
    from ..shared.auth import validate_api_key
    from ..shared.response_utils import error_response

    class MyController(http.Controller):
        @http.route('/api/track/...', type='http', auth='public',
                    methods=['GET'], csrf=False)
        def my_route(self, **kwargs):
            auth_error = validate_api_key(request)
            if auth_error:
                return auth_error
            # ... rest of handler
"""

import hmac as _hmac
import logging

from odoo.http import Response

from .response_utils import error_response

_logger = logging.getLogger(__name__)

_PARAM_KEY = "track_api.secret_key"
_HEADER_KEY = "X-API-Key"


def validate_api_key(request) -> Response | None:
    """
    Validates the API key supplied in the X-API-Key request header.

    Returns
    -------
    None                  — if the key is valid (caller can proceed)
    Response (403/500)    — if the key is missing, wrong, or unconfigured
                            (caller must return this immediately)

    Example
    -------
        auth_error = validate_api_key(request)
        if auth_error:
            return auth_error
    """
    try:
        expected_key = request.env["ir.config_parameter"].sudo().get_param(_PARAM_KEY)
    except Exception as e:  # noqa: BLE001
        _logger.error("track_api auth: failed to read system parameter: %s", e)
        return error_response(500, "Authentication configuration error.")

    if not expected_key:
        _logger.error(
            "track_api auth: system parameter '%s' is not set. "
            "Set it via Settings → Technical → System Parameters.",
            _PARAM_KEY,
        )
        return error_response(500, "API key not configured on server.")

    provided_key = request.httprequest.headers.get(_HEADER_KEY, "").strip()

    if not provided_key:
        _logger.warning("track_api auth: request missing %s header.", _HEADER_KEY)
        return error_response(401, f"Missing API key in {_HEADER_KEY} header.")

    keys_match = _hmac.compare_digest(
        provided_key.encode("utf-8"),
        expected_key.encode("utf-8"),
    )

    if not keys_match:
        _logger.warning("track_api auth: invalid API key provided.")
        return error_response(403, "Invalid API key.")

    return None
