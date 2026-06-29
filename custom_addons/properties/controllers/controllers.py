"""
Properties REST API — full CRUD controller.

Base path : /api/v1/properties
Auth      : X-API-Key header (validated via :func:`auth.validate_api_key`)
Format    : application/json (in & out)

Endpoints
---------
GET    /api/v1/properties
    Paginated, filterable list of property.base records.

GET    /api/v1/properties/<identifier>
    Single-record lookup.  <identifier> tried in order:
      1. Odoo integer id
      2. uuid field
      3. prop_id (short code)
      4. owner_phone

PUT    /api/v1/properties
    Create a new property.base record.

PATCH  /api/v1/properties/<identifier>
    Update an existing record.  <identifier> resolved identically to GET.

DELETE /api/v1/properties/<identifier>
    Hard-delete a property.base record.
"""

import json
import logging

from odoo import http
from odoo.http import request

from .auth import validate_api_key
from .response_utils import error_response, success_response
from .serializers import serialize_property

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Field allow-lists  (prevents mass-assignment of arbitrary model fields)
# ---------------------------------------------------------------------------

# Fields the caller may supply when *creating* a property (PUT).
_ALLOWED_CREATE_FIELDS = {
    "uuid",
    "prop_id",
    "form_no",
    "name",
    "reg_date",
    "prop_type",
    "prop_sub_type",
    "for_sell",
    "state",
    "city",
    "location",
    "pricing",
    "pricing_unit",
    "owner_name",
    "owner_phone",
    "owner_email",
    "rm_user_id",  # pass as integer (res.users id)
    "bedroom_count",
    "gmaps_url",
    "property_tag",
    "portal_listings",  # list[dict] handled separately
    "service_expiry_date",
    "welcome_call_date",
    "is_active",
}

# Fields the caller may supply when *updating* a property (PATCH).
# Computed / readonly-by-design fields are excluded.
_ALLOWED_UPDATE_FIELDS = _ALLOWED_CREATE_FIELDS.copy()

_PORTAL_NAME_MAP = {
    "99acres": "99acres",
    "housing.com": "Housing.com",
    "housing": "Housing.com",
    "magicbricks": "MagicBricks",
    "magicbricks.com": "MagicBricks",
    "olx": "OLX",
    "squareyards": "SquareYards",
    "square yards": "SquareYards",
    "square_yards": "SquareYards",
}


# ---------------------------------------------------------------------------
# Helper utilities local to this module
# ---------------------------------------------------------------------------


def _parse_json_body(req):
    """
    Parse the request body as JSON.

    Returns
    -------
    tuple[dict | None, Response | None]
        ``(data_dict, None)`` on success, ``(None, error_response)`` on failure.
    """
    ct = req.httprequest.content_type or ""
    if "application/json" not in ct:
        return None, error_response(
            415,
            "Content-Type must be 'application/json'.",
        )
    try:
        raw = req.httprequest.data
        payload = json.loads(raw)
    except (ValueError, TypeError) as exc:
        return None, error_response(400, f"Invalid JSON payload: {exc}")

    if not isinstance(payload, dict):
        return None, error_response(400, "Request body must be a JSON object.")

    return payload, None


def _sanitise_fields(payload: dict, allowed: set) -> tuple:
    """
    Keep only keys that exist in *allowed* and warn about extras.

    Returns
    -------
    tuple[dict, list[str]]
        ``(clean_dict, list_of_ignored_keys)``
    """
    ignored = [k for k in payload if k not in allowed]
    clean = {k: v for k, v in payload.items() if k in allowed}
    return clean, ignored


def _normalise_portal_name(raw_name):
    if raw_name is None:
        return None
    return _PORTAL_NAME_MAP.get(str(raw_name).strip().lower())


def _sanitise_portal_listings(portal_listings):
    """
    Validate and normalize portal listing payload.

    Expected shape:
      [
        {
          "portal_name": "99acres|Housing.com|MagicBricks|OLX|SquareYards",
          "portal_listing_id": "...",
          "listing_label": "..." (optional),
          "active": true|false (optional, default true),
        },
      ]
    """
    if portal_listings is None:
        return None, None

    if not isinstance(portal_listings, list):
        return None, error_response(
            422,
            "Field 'portal_listings' must be a JSON array.",
        )

    clean = []
    for idx, item in enumerate(portal_listings, start=1):
        if not isinstance(item, dict):
            return None, error_response(
                422,
                f"portal_listings[{idx}] must be an object.",
            )

        canonical_portal = _normalise_portal_name(item.get("portal_name"))
        if not canonical_portal:
            return None, error_response(
                422,
                f"portal_listings[{idx}].portal_name is invalid.",
            )

        portal_listing_id = (item.get("portal_listing_id") or "").strip()
        if not portal_listing_id:
            return None, error_response(
                422,
                f"portal_listings[{idx}].portal_listing_id is required.",
            )

        clean.append(
            {
                "portal_name": canonical_portal,
                "portal_listing_id": portal_listing_id,
                "listing_label": item.get("listing_label") or False,
                "active": bool(item.get("active", True)),
            },
        )

    return clean, None


def _replace_portal_listings(record, portal_listings_clean):
    """Replace all portal listings on a property with the provided list."""
    if portal_listings_clean is None:
        return

    listing_model = request.env["property.portal.listing"].sudo()
    record.sudo().portal_listing_ids.unlink()

    for item in portal_listings_clean:
        values = dict(item)
        values["property_base_id"] = record.id
        listing_model.create(values)


def _resolve_identifier(env, identifier: str):
    """
    Look up a ``property.base`` record by *identifier*, trying four
    strategies in order:

    1. Odoo integer database ``id``
    2. ``uuid`` field
    3. ``prop_id`` (short code)
    4. ``owner_phone``

    Returns the *first* match found, or an empty recordset.
    """
    Model = env["property.base"].sudo()

    # Strategy 1: numeric Odoo id
    if identifier.isdigit():
        rec = Model.browse(int(identifier)).exists()
        if rec:
            return rec

    # Strategy 2: uuid
    rec = Model.search([("uuid", "=", identifier)], limit=1)
    if rec:
        return rec

    # Strategy 3: prop_id (short code)
    rec = Model.search([("prop_id", "=", identifier)], limit=1)
    if rec:
        return rec

    # Strategy 4: owner_phone
    # owner_phone may hold multiple numbers in one string (e.g. "9033870424 8735999816"),
    # so use 'like' to match any record whose phone field contains the supplied number.
    # Guard against accidental matches for short numeric identifiers that are intended
    # as database IDs (e.g., deleting id "398" should not match owner_phone "...398...").
    normalized_phone = identifier.replace("+", "").replace("-", "").replace(" ", "")
    if normalized_phone.isdigit() and len(normalized_phone) >= 10:
        rec = Model.search([("owner_phone", "like", identifier)], limit=1)
        if rec:
            return rec

    return Model  # empty recordset


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


class PropertyApiController(http.Controller):
    """REST API controller for ``property.base``."""

    # -----------------------------------------------------------------------
    # GET /api/v1/properties  — paginated, filterable list
    # -----------------------------------------------------------------------

    @http.route(
        "/api/v1/properties",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def list_properties(self, **kwargs):
        """
        Return a paginated list of properties.

        Query string parameters
        -----------------------
        page        int     Page number (1-based).  Default: 1.
        page_size   int     Records per page (1-200).  Default: 20.
        is_active   bool    Filter by active status ("true" / "false").
        for_sell    bool    Filter by listing type ("true" / "false").
        city        str     Exact city match.
        state       str     Exact state match.
        prop_type   str     Exact property type match.
        prop_id     str     Exact short-code match.
        form_no     str     Exact form number match.
        owner_phone str     Exact owner phone match.
        portal_name str     Portal source filter (99acres / Housing.com / MagicBricks / OLX / SquareYards).
        portal_listing_id str Exact portal listing ID via property.portal.listing relation.
        search      str     ilike match against property name.
        """
        ok, err = validate_api_key(request)
        if not ok:
            return err

        params = request.httprequest.args

        # --- Pagination parameters -----------------------------------------
        try:
            page = max(1, int(params.get("page", 1)))
        except ValueError:
            return error_response(400, "'page' must be an integer.")

        try:
            page_size = min(200, max(1, int(params.get("page_size", 20))))
        except ValueError:
            return error_response(400, "'page_size' must be an integer (1-200).")

        # --- Build domain -------------------------------------------------------
        domain = []

        def _bool_param(name):
            raw = params.get(name)
            if raw is None:
                return None
            return raw.lower() not in ("false", "0", "no", "")

        is_active = _bool_param("is_active")
        if is_active is not None:
            domain.append(("is_active", "=", is_active))

        for_sell = _bool_param("for_sell")
        if for_sell is not None:
            domain.append(("for_sell", "=", for_sell))

        for exact_field in ("city", "state", "prop_type", "prop_id", "form_no"):
            val = params.get(exact_field)
            if val:
                domain.append((exact_field, "=", val))

        # owner_phone may store multiple numbers in one field; use 'like' so a
        # single number matches even when others are present in the same string.
        phone_filter = params.get("owner_phone")
        if phone_filter:
            domain.append(("owner_phone", "like", phone_filter))

        portal_name = params.get("portal_name")
        if portal_name:
            canonical_portal = _normalise_portal_name(portal_name)
            if not canonical_portal:
                return error_response(400, "Invalid 'portal_name' filter value.")
            domain.append(("portal_listing_ids.portal_name", "=", canonical_portal))

        portal_listing_id = params.get("portal_listing_id")
        if portal_listing_id:
            domain.append(
                ("portal_listing_ids.portal_listing_id", "=", portal_listing_id.strip())
            )

        search_term = params.get("search")
        if search_term:
            domain.append(("name", "ilike", search_term))

        # --- Query -------------------------------------------------------------
        Model = request.env["property.base"].sudo()
        total = Model.search_count(domain)
        offset = (page - 1) * page_size
        records = Model.search(
            domain,
            limit=page_size,
            offset=offset,
            order="reg_date desc, id desc",
        )

        data = {
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": -(-total // page_size),  # ceiling division
            "results": [serialize_property(r) for r in records],
        }
        return success_response(data)

    # -----------------------------------------------------------------------
    # GET /api/v1/properties/<identifier>  — single record
    # -----------------------------------------------------------------------

    @http.route(
        "/api/v1/properties/<string:identifier>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        save_session=False,
    )
    def get_property(self, identifier: str, **kwargs):
        """
        Retrieve a single property by id, uuid, prop_id, or owner_phone.
        """
        ok, err = validate_api_key(request)
        if not ok:
            return err

        record = _resolve_identifier(request.env, identifier.strip())
        if not record:
            return error_response(
                404,
                f"No property found for identifier '{identifier}'.",
            )

        return success_response(serialize_property(record))

    # -----------------------------------------------------------------------
    # PUT /api/v1/properties  — create a new property
    # -----------------------------------------------------------------------

    @http.route(
        "/api/v1/properties",
        type="http",
        auth="public",
        methods=["PUT"],
        csrf=False,
        save_session=False,
    )
    def create_property(self, **kwargs):
        """
        Create a new ``property.base`` record.

        Request body (JSON object) may contain any field from the
        allowed-create list.  Unknown fields are ignored and reported in the
        response.

        Returns ``201 Created`` with the full serialised record.
        """
        ok, err = validate_api_key(request)
        if not ok:
            return err

        payload, err = _parse_json_body(request)
        if err:
            return err

        vals, ignored = _sanitise_fields(payload, _ALLOWED_CREATE_FIELDS)
        portal_listings_clean, err = _sanitise_portal_listings(
            vals.pop("portal_listings", None),
        )
        if err:
            return err

        if not vals:
            return error_response(422, "No valid fields supplied in the request body.")

        # Basic required-field validation
        if not vals.get("name"):
            return error_response(422, "Field 'name' is required.")

        try:
            record = request.env["property.base"].sudo().create(vals)
            _replace_portal_listings(record, portal_listings_clean)
        except Exception as exc:
            _logger.exception("Properties API: error creating property")
            return error_response(500, f"Failed to create property: {exc}")

        response_data = serialize_property(record)
        if ignored:
            response_data["_ignored_fields"] = ignored

        return success_response(response_data, http_status=201)

    # -----------------------------------------------------------------------
    # PATCH /api/v1/properties/<identifier>  — partial update
    # -----------------------------------------------------------------------

    @http.route(
        "/api/v1/properties/<string:identifier>",
        type="http",
        auth="public",
        methods=["PATCH"],
        csrf=False,
        save_session=False,
    )
    def update_property(self, identifier: str, **kwargs):
        """
        Partially update an existing property record.

        ``<identifier>`` is resolved via the same four-strategy lookup used
        by the GET single-record endpoint (id → uuid → prop_id → owner_phone).

        Only fields listed in the allowed-update list are applied; the rest
        are ignored and surfaced as ``_ignored_fields`` in the response.

        Returns ``200 OK`` with the updated serialised record.
        """
        ok, err = validate_api_key(request)
        if not ok:
            return err

        record = _resolve_identifier(request.env, identifier.strip())
        if not record:
            return error_response(
                404,
                f"No property found for identifier '{identifier}'.",
            )

        payload, err = _parse_json_body(request)
        if err:
            return err

        vals, ignored = _sanitise_fields(payload, _ALLOWED_UPDATE_FIELDS)
        portal_listings_clean, err = _sanitise_portal_listings(
            vals.pop("portal_listings", None),
        )
        if err:
            return err

        if not vals and portal_listings_clean is None:
            return error_response(422, "No valid fields supplied for update.")

        try:
            if vals:
                record.sudo().write(vals)
            _replace_portal_listings(record, portal_listings_clean)
        except Exception as exc:
            _logger.exception(
                "Properties API: error updating property id=%s",
                record.id,
            )
            return error_response(500, f"Failed to update property: {exc}")

        response_data = serialize_property(record)
        if ignored:
            response_data["_ignored_fields"] = ignored

        return success_response(response_data)

    # -----------------------------------------------------------------------
    # DELETE /api/v1/properties/<identifier>  — hard delete
    # -----------------------------------------------------------------------

    @http.route(
        "/api/v1/properties/<string:identifier>",
        type="http",
        auth="public",
        methods=["DELETE"],
        csrf=False,
        save_session=False,
    )
    def delete_property(self, identifier: str, **kwargs):
        """
        Hard-delete a ``property.base`` record.

        ``<identifier>`` is resolved via the four-strategy lookup.
        Returns ``200 OK`` with the deleted record's identifiers on success.

        .. warning::
            This is an irreversible operation.  The record is permanently
            removed from the database.
        """
        ok, err = validate_api_key(request)
        if not ok:
            return err

        record = _resolve_identifier(request.env, identifier.strip())
        if not record:
            return error_response(
                404,
                f"No property found for identifier '{identifier}'.",
            )

        # Capture identifiers before deletion for the response body
        deleted_info = {
            "id": record.id,
            "uuid": record.uuid or None,
            "prop_id": record.prop_id or None,
            "name": record.name or None,
        }

        try:
            record.sudo().unlink()
        except Exception as exc:
            _logger.exception(
                "Properties API: error deleting property id=%s",
                deleted_info["id"],
            )
            return error_response(500, f"Failed to delete property: {exc}")

        return success_response(
            {
                "message": "Property permanently deleted.",
                "deleted": deleted_info,
            },
        )
