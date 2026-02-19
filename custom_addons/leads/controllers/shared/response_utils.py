"""
response_utils.py
-----------------
Thin wrappers that produce consistent JSON envelopes across every endpoint.

Every response follows the same top-level shape:

    {
        "success": true | false,
        "data":    { ... } | null,
        "error":   null    | { "code": <int>, "message": <str> }
    }

HTTP status codes are set on the Response object by Odoo's routing layer,
so the helpers below return plain dicts that the controllers then pass to
`request.make_json_response()`.
"""

import json
import logging

from odoo.http import Response

_logger = logging.getLogger(__name__)


def success_response(data: dict | list, http_status: int = 200) -> Response:
    """Return a 2xx JSON response with a standard envelope."""
    payload = {
        "success": True,
        "data": data,
        "error": None,
    }
    return Response(
        json.dumps(payload, default=str),
        status=http_status,
        mimetype="application/json",
    )


def error_response(http_status: int, message: str) -> Response:
    """Return an error JSON response with a standard envelope."""
    payload = {
        "success": False,
        "data": None,
        "error": {
            "code": http_status,
            "message": message,
        },
    }

    _logger.error("API Error %s: %s", http_status, message)

    return Response(
        json.dumps(payload, default=str),
        status=http_status,
        mimetype="application/json",
    )
