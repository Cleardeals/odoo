"""
GET /api/track/property/ai-suggestions
----------------------------------------
Returns AI-generated lead suggestions for the seller's properties, sourced
from the property.lead.suggestion model (synced from BigQuery).

Paginated. Empty list is a valid response (not all properties have suggestions).

Query params
------------
phone        : str  — owner phone, with or without leading 91  (required)
property_tag : str  — filter to a single property tag          (optional)
page         : int  — page number, default 1                   (optional)
page_size    : int  — records per page, default 20, max 100    (optional)

Response shape
--------------
{
  "success": true,
  "data": {
    "owner_phone":  "9876543210",
    "properties":   ["TAG1"],
    "items": [
      {
        "property_tag":           "TAG1",
        "suggested_lead_name":    "Amit Patel",
        "suggested_lead_phone":   "9123456789",
        "original_property_tag":  "TAG0",    // the property the lead originally inquired about
        "similarity_pct":         87.5,
        "suggested_on":           "2025-01-10",
        "contact_type":           "site_visit_done",
        "rm_status":              "contacted",
        "rm_feedback":            "Interested, will call back tomorrow"
      }
    ],
    "pagination": { "page": 1, "page_size": 20, "total": 5, "total_pages": 1 }
  },
  "error": null
}
"""

import logging

from odoo import http
from odoo.http import request

from ..shared.auth import validate_api_key
from ..shared.phone_utils import extract_phone_from_request
from ..shared.property_resolver import get_properties_for_phone
from ..shared.response_utils import error_response, paginate, success_response

_logger = logging.getLogger(__name__)


def _serialize_suggestion(suggestion) -> dict:
    return {
        "property_tag": suggestion.property_tag or None,
        "suggested_lead_name": suggestion.lead_name or None,
        "suggested_lead_phone": suggestion.suggested_lead_phone or None,
        "original_property_tag": suggestion.original_property_tag or None,
        "suggested_on": (
            suggestion.generation_date.isoformat()
            if suggestion.generation_date
            else None
        ),
        "contact_type": suggestion.contact_type or None,
        "rm_status": suggestion.status or None,
        "rm_feedback": suggestion.rm_feedback or None,
    }


class SellerAiSuggestionsController(http.Controller):
    @http.route(
        "/api/track/property/ai-suggestions",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def property_ai_suggestions(self, **kwargs):
        """
        Query params: phone (required), property_tag (optional),
                      page (optional), page_size (optional).
        """
        auth_error = validate_api_key(request)
        if auth_error:
            return auth_error

        phone = extract_phone_from_request(request)
        if not phone:
            return error_response(400, "Valid 'phone' query parameter is required.")

        properties = get_properties_for_phone(request.env, phone)
        if not properties:
            return error_response(
                404,
                f"No properties found for phone number {phone}.",
            )

        # Optional single-property filter
        tag_filter = request.params.get("property_tag", "").strip() or None
        if tag_filter:
            properties = properties.filtered(lambda p: p.property_tag == tag_filter)
            if not properties:
                return error_response(
                    404,
                    f"No properties found for phone number {phone} with tag '{tag_filter}'.",
                )

        tags = properties.mapped("property_tag")

        suggestions = (
            request.env["property.lead.suggestion"]
            .sudo()
            .search([("property_tag", "in", tags)], order="generation_date desc")
        )

        records = [_serialize_suggestion(s) for s in suggestions]

        try:
            page = int(request.params.get("page", 1))
            page_size = int(request.params.get("page_size", 20))
        except (ValueError, TypeError):
            return error_response(
                400,
                "Invalid 'page' or 'page_size' parameter. Must be integers.",
            )

        paged = paginate(records, page, page_size)

        data = {
            "owner_phone": phone,
            "properties": tags,
            "tag_filter": tag_filter,
            **paged,
        }
        return success_response(data)
