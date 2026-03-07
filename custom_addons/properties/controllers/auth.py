"""
API key authentication helper for the Properties REST API.

The expected key is stored in an ``ir.config_parameter`` entry with the
technical key ``properties.api_key``.  Every inbound request must supply the
same value in the ``X-API-Key`` HTTP header.

Usage::

    from .auth import validate_api_key

    ok, err = validate_api_key(request)
    if not ok:
        return err          # already a Response object
"""

import hmac
import logging

from odoo import http

from .response_utils import error_response

_logger = logging.getLogger(__name__)

_API_KEY_PARAM = "properties.api_key"
_HEADER_NAME = "X-API-Key"


def validate_api_key(request: http.Request):
    """
    Validate the ``X-API-Key`` header against the value stored in
    ``ir.config_parameter``.

    Parameters
    ----------
    request:
        The active Odoo HTTP request object.

    Returns
    -------
    tuple[bool, Response | None]
        ``(True, None)`` when the key is valid.
        ``(False, error_response)`` when authentication fails.
    """
    # 1. Read the expected key from system parameters.
    #    Use sudo() so the config param is accessible regardless of the
    #    caller's session user (public/portal/internal).
    expected_key = (
        request.env["ir.config_parameter"].sudo().get_param(_API_KEY_PARAM, default="")
    )

    if not expected_key:
        _logger.warning(
            "Properties API: system parameter '%s' is not set. "
            "All API requests will be rejected until it is configured.",
            _API_KEY_PARAM,
        )
        return False, error_response(
            503,
            "API authentication is not configured on this server. "
            f"Set the '{_API_KEY_PARAM}' system parameter to enable the API.",
        )

    # 2. Read the key supplied by the caller.
    supplied_key = request.httprequest.headers.get(_HEADER_NAME, "")

    if not supplied_key:
        return False, error_response(
            401,
            f"Missing '{_HEADER_NAME}' header.",
        )

    # 3. Constant-time comparison to prevent timing-oracle attacks.
    if not hmac.compare_digest(supplied_key, expected_key):
        _logger.warning(
            "Properties API: rejected request with invalid API key "
            "(remote=%s, path=%s).",
            request.httprequest.remote_addr,
            request.httprequest.path,
        )
        return False, error_response(403, "Invalid API key.")

    return True, None
