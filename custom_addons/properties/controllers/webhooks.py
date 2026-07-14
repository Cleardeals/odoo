"""
Properties inbound webhooks.

The Cleardeals website pushes property changes to Odoo in real time instead of
Odoo polling the website API every 3 hours.  Two endpoints mirror the two
website events:

POST /api/v1/properties/webhook/create
    Fired when a property is created on the website admin panel.

POST /api/v1/properties/webhook/update
    Fired when a property is updated on the website admin panel.

Auth      : X-API-Key header (same shared secret as the REST API).
Format    : application/json — the *exact* single-property envelope the website
            API returns:  ``{"success": true, "property": { …website fields… }}``
            (a bare property object without the envelope is also accepted).

Both routes are thin wrappers over ``property.base._upsert_one`` (see
models/property_sync.py).  The upsert is idempotent and keyed on the website
``id`` (uuid), so the endpoints survive retries and out-of-order delivery:
a "create" for an existing uuid updates it, an "update" for a missing uuid
creates it.  We keep two routes — rather than one — to match the website team's
two-event design and to preserve a create-vs-update signal in the access logs.

Why this reuses the *sync* mapper and NOT the REST PUT/PATCH controller:
the webhook payload uses the website's nested field names (``property_name``,
``owner_contact_no``, ``state.name``, ``details.bedroom_count``,
``sell_pricing.offer_price`` …) — exactly what ``_map_api_record`` parses —
whereas controllers.py expects flat Odoo field names.
"""

import logging

from odoo import http
from odoo.http import request

from .auth import validate_api_key
from .controllers import _parse_json_body
from .response_utils import error_response, success_response
from .serializers import serialize_property

_logger = logging.getLogger(__name__)


class PropertyWebhookController(http.Controller):
    """Inbound webhook endpoints for ``property.base``."""

    def _handle(self, intent: str):
        """
        Shared handler for both webhook routes.

        Parameters
        ----------
        intent:
            ``"create"`` or ``"update"`` — used only for logging / intent; the
            actual create-vs-update decision is made by the idempotent upsert.
        """
        ok, err = validate_api_key(request)
        if not ok:
            return err

        payload, err = _parse_json_body(request)
        if err:
            return err

        # Accept either the {"success": …, "property": {…}} envelope or a bare
        # property object.
        prop = payload.get("property", payload)
        if not isinstance(prop, dict):
            return error_response(
                400,
                "Request body must contain a 'property' object.",
            )

        media = prop.get("media")
        if media:
            # Media is intentionally not persisted yet (see module docstring).
            _logger.info(
                "Property webhook (%s): ignoring %d media item(s) for uuid=%s.",
                intent,
                len(media) if isinstance(media, list) else 1,
                prop.get("id"),
            )

        try:
            record, action = request.env["property.base"].sudo()._upsert_one(prop)
        except ValueError as exc:
            return error_response(422, str(exc))
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "Property webhook (%s): error upserting uuid=%s",
                intent,
                prop.get("id"),
            )
            return error_response(500, f"Failed to process property: {exc}")

        _logger.info(
            "Property webhook (%s): uuid=%s → %s (id=%d).",
            intent,
            prop.get("id"),
            action,
            record.id,
        )

        response_data = serialize_property(record)
        response_data["_webhook_action"] = action
        http_status = 201 if action == "created" else 200
        return success_response(response_data, http_status=http_status)

    # -----------------------------------------------------------------------
    # POST /api/v1/properties/webhook/create
    # -----------------------------------------------------------------------

    @http.route(
        "/api/v1/properties/webhook/create",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def webhook_create(self, **kwargs):
        """Handle a website 'property created' event."""
        return self._handle("create")

    # -----------------------------------------------------------------------
    # POST /api/v1/properties/webhook/update
    # -----------------------------------------------------------------------

    @http.route(
        "/api/v1/properties/webhook/update",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def webhook_update(self, **kwargs):
        """Handle a website 'property updated' event."""
        return self._handle("update")
