"""
GET /api/track/property/summary
--------------------------------
Returns a high-level summary of inquiry activity for all properties
belonging to the owner identified by the `phone` query parameter.

Query params
------------
phone        : str  — owner phone, with or without leading 91  (required)
property_tag : str  — filter to a single property tag          (optional)
                      When omitted, all properties for the owner are aggregated.

Response shape
--------------
{
  "success": true,
  "data": {
    "owner_phone": "9876543210",
    "properties": [
      {
        "property_tag": "TAG1",
        "name": "Sunrise Residency",
        "rm_name": "Bhoomika Prajapati",
        "phone": "9876543210"
      }
    ],
    "tag_filter": null | "TAG1",
    "inquiries": {
      "total":       42,
      "primary":     35,
      "recommended":  7,
    "source_breakdown": {
        "MagicBricks":  {"primary": 10, "recommended": 3},
        "99acres":      {"primary": 15, "recommended": 2},
        "Housing.com":  {"primary":  8, "recommended": 2},
        "OLX":          {"primary":  2, "recommended": 0},
        "Unknown":      {"primary":  0, "recommended": 0}
      }
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


class SellerSummaryController(http.Controller):
    @http.route(
        "/api/track/property/summary",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def property_summary(self, **kwargs):
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

        # Build per-property detail list
        property_details = [
            {
                "property_tag": prop.property_tag,
                "name": prop.name or None,
                "rm_name": prop.rm_user_id.name if prop.rm_user_id else None,
                "phone": prop.rm_user_id.phone if prop.rm_user_id else None,
            }
            for prop in properties
        ]

        # Primary leads (leads.new records linked to the owner's properties)
        primary_leads = get_primary_leads_for_tags(request.env, tags)

        # Recommended leads — leads.new records with inquiry_type='recommended'
        recommended_leads = get_recommended_leads_for_tags(request.env, tags)

        # Source breakdown
        source_breakdown = defaultdict(lambda: {"primary": 0, "recommended": 0})

        for lead in primary_leads:
            source_name = lead.source_id.name if lead.source_id else "Unknown"
            source_breakdown[source_name]["primary"] += 1

        for inquiry in recommended_leads:
            source_name = inquiry.source_id.name if inquiry.source_id else "Unknown"
            source_breakdown[source_name]["recommended"] += 1

        data = {
            "owner_phone": phone,
            "properties": property_details,
            "tag_filter": tag_filter,
            "inquiries": {
                "total": len(primary_leads) + len(recommended_leads),
                "primary": len(primary_leads),
                "recommended": len(recommended_leads),
                "source_breakdown": dict(source_breakdown),
            },
        }
        return success_response(data)
