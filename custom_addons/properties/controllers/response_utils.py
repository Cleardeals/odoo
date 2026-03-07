"""
HTTP response helpers for the Properties REST API.

Both helpers return a :class:`werkzeug.wrappers.Response` with
``Content-Type: application/json`` so controllers only need a single
``return`` statement.

Usage::

    from .response_utils import success_response, error_response

    return success_response({"id": 1, "name": "My Property"})
    return error_response(404, "Property not found.")
    return success_response(data, http_status=201)
"""

import datetime
import json

from werkzeug.wrappers import Response

_MIME = "application/json"


def success_response(data, http_status: int = 200) -> Response:
    """
    Build a JSON success response.

    Parameters
    ----------
    data:
        Any JSON-serialisable value (dict, list, …) that will be placed
        inside ``{"success": true, "data": <data>}``.
    http_status:
        HTTP status code.  Defaults to ``200 OK``.  Use ``201`` for
        newly created resources.

    Returns
    -------
    werkzeug.wrappers.Response
    """
    body = json.dumps(
        {
            "success": True,
            "data": data,
        },
        default=_json_default,
        ensure_ascii=False,
    )
    return Response(body, status=http_status, mimetype=_MIME)


def error_response(http_status: int, message: str) -> Response:
    """
    Build a JSON error response.

    Parameters
    ----------
    http_status:
        HTTP status code, e.g. ``400``, ``401``, ``403``, ``404``, ``422``,
        ``500``, ``503``.
    message:
        Human-readable error description returned to the caller.

    Returns
    -------
    werkzeug.wrappers.Response
    """
    body = json.dumps(
        {
            "success": False,
            "error": {
                "status": http_status,
                "message": message,
            },
        },
        ensure_ascii=False,
    )
    return Response(body, status=http_status, mimetype=_MIME)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _json_default(obj):
    """
    Fallback serialiser for types that are not natively JSON-serialisable.

    Handles:
    * ``datetime.date`` / ``datetime.datetime`` → ISO-8601 string
    * Odoo ``False`` (falsy singleton) → ``null``
    * Everything else → string representation (safe fallback)
    """
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    # Odoo stores empty relational fields as False; render as null
    if obj is False:
        return None
    return str(obj)
