"""
GET /api/track/property/portal-performance
--------------------------------------------
Returns a per-source quality breakdown for all properties belonging to the
owner identified by the `phone` query parameter.

All sources are included in a single response. Recommended leads are
attributed to the source of the parent leads.new record.

Query params
------------
phone        : str  — owner phone, with or without leading 91  (required)
property_tag : str  — filter to a single property tag          (optional)

Response shape
--------------
{
  "success": true,
  "data": {
    "owner_phone": "9876543210",
    "properties":  ["TAG1"],
    "sources": {
      "MagicBricks": {
        "total_leads":          15,
        "primary_leads":        12,
        "recommended_leads":     3,
        "statuses": {
          "lead":                           3,
          "busy":                           1,
          "details_shared_of_property":     2,
          "site_visit_scheduled":           4,
          "site_visit_done":                3,
          "requirement_closed":             1,
          "other":                          1
        },
        "key_metrics": {
          "site_visit_scheduled": 4,
          "site_visit_done":      3,
        }
      },
      "99acres":    { ... },
      "Housing.com":{ ... },
      "OLX":        { ... },
      "Unknown":    { ... }
    }
  },
  "error": null
}
"""

import logging
from collections import defaultdict

from odoo import http
from odoo.http import request

from ..shared.auth import validate_api_key
from ..shared.phone_utils import extract_phone_from_request
from ..shared.property_resolver import (
    get_primary_leads_for_tags,
    get_properties_for_phone,
    get_recommended_leads_for_tags,
)
from ..shared.response_utils import error_response, success_response

_logger = logging.getLogger(__name__)


def _empty_source_block() -> dict:
    return {
        "total_leads": 0,
        "primary_leads": 0,
        "recommended_leads": 0,
        "statuses": defaultdict(int),
    }


class SellerPortalPerformanceController(http.Controller):
    @http.route(
        "/api/track/property/portal-performance",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def portal_performance(self, **kwargs):
        """
        Query params: phone (required), property_tag (optional).
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

        tag_filter = request.params.get("property_tag", "").strip() or None
        if tag_filter:
            properties = properties.filtered(lambda p: p.property_tag == tag_filter)
            if not properties:
                return error_response(
                    404,
                    f"No properties found for phone number {phone} with tag '{tag_filter}'.",
                )

        tags = properties.mapped("property_tag")

        source_data = defaultdict(_empty_source_block)

        primary_leads = get_primary_leads_for_tags(request.env, tags)
        for lead in primary_leads:
            source_name = lead.source_id.name if lead.source_id else "Unknown"
            source_data[source_name]["total_leads"] += 1
            source_data[source_name]["primary_leads"] += 1
            source_data[source_name]["statuses"][lead.current_status or "other"] += 1

        recommended_interests = get_recommended_leads_for_tags(request.env, tags)
        for interest in recommended_interests:
            source_name = (
                interest.lead_id.source_id.name
                if interest.lead_id and interest.lead_id.source_id
                else "Unknown"
            )
            source_data[source_name]["total_leads"] += 1
            source_data[source_name]["recommended_leads"] += 1
            source_data[source_name]["statuses"][
                interest.current_status or "other"
            ] += 1

        serialised = {}
        for source_name, block in source_data.items():
            total = block["total_leads"]
            svd = block["statuses"].get("site_visit_done", 0)
            svs = block["statuses"].get("site_visit_scheduled", 0)

            serialised[source_name] = {
                "total_leads": total,
                "primary_leads": block["primary_leads"],
                "recommended_leads": block["recommended_leads"],
                "statuses": dict(block["statuses"]),  # plain dict for JSON
                "key_metrics": {
                    "site_visit_scheduled": svs,
                    "site_visit_done": svd,
                },
            }

        data = {
            "owner_phone": phone,
            "properties": tags,
            "tag_filter": tag_filter,
            "sources": serialised,
        }
        return success_response(data)
