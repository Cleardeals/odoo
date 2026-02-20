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

    # 5xx = real server errors → log as error
    # 4xx = client mistakes (bad key, not found) → log as warning only
    if http_status >= 500:
        _logger.error("Track API %s: %s", http_status, message)
    else:
        _logger.warning("Track API %s: %s", http_status, message)

    return Response(
        json.dumps(payload, default=str),
        status=http_status,
        mimetype="application/json",
    )


def paginate(items: list, page: int, page_size: int) -> dict:
    """
    Slice a list and return a pagination meta-block alongside the page items.

    Parameters
    ----------
    items     : the full unsorted/sorted list to paginate
    page      : 1-based page number (values < 1 are clamped to 1)
    page_size : records per page (clamped to min 1, max 200)

    Returns
    -------
    {
        "items": [...],
        "pagination": {
            "page":        <int>,
            "page_size":   <int>,
            "total":       <int>,
            "total_pages": <int>
        }
    }

    Usage
    -----
        paged = paginate(records, page, page_size)
        data = {
            "owner_phone": phone,
            **paged,          # inlines "items" and "pagination" into data
        }
        return success_response(data)
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 200))  # hard cap at 200

    total = len(items)
    total_pages = max(1, -(-total // page_size))  # ceiling division

    start = (page - 1) * page_size
    end = start + page_size

    return {
        "items": items[start:end],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
    }
