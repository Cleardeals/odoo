"""
GET /api/track/property/funnel
-------------------------------
Returns a conversion funnel aggregated across all portals and all properties
belonging to the owner identified by the `phone` query parameter.

The funnel covers both primary leads (leads.new) and recommended leads
(lead.property.interest) combined.

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
    "properties": ["TAG1", "TAG2"],
    "tag_filter": null | "TAG1",
    "funnel": {
      "total_inquiries": 42,
      "stages": {
        "lead":                                       {"count": 10, "pct_of_total": 23.8},
        "busy":                                       {"count":  3, "pct_of_total":  7.1},
        "ringing":                                    {"count":  2, "pct_of_total":  4.8},
        "call_back_later":                            {"count":  1, "pct_of_total":  2.4},
        "details_shared_of_property":                 {"count":  5, "pct_of_total": 11.9},
        "detail_shared_and_interested_for_site_visit":{"count":  4, "pct_of_total":  9.5},
        "option_not_matching_requirements":           {"count":  0, "pct_of_total":  0.0},
        "site_visit_scheduled":                       {"count":  6, "pct_of_total": 14.3},
        "rescheduled":                                {"count":  1, "pct_of_total":  2.4},
        "site_visit_done":                            {"count":  4, "pct_of_total":  9.5},
        "requirement_closed":                         {"count":  3, "pct_of_total":  7.1},
        "no_requirements":                            {"count":  2, "pct_of_total":  4.8},
        "property_sold_out":                          {"count":  0, "pct_of_total":  0.0},
        "budget_not_sufficient":                      {"count":  0, "pct_of_total":  0.0},
        "switched_off":                               {"count":  1, "pct_of_total":  2.4},
        "number_not_in_use_wrong_number":             {"count":  0, "pct_of_total":  0.0},
        "other":                                      {"count":  0, "pct_of_total":  0.0}
      },
      "key_metrics": {
        "contacted":            15,
        "site_visit_scheduled":  6,
        "site_visit_done":       4,
        "closed_or_lost":        5
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

# All possible status values across leads.new and lead.property.interest
ALL_FUNNEL_STAGES = [
    "lead",
    "busy",
    "ringing",
    "call_back_later",
    "details_shared_of_property",
    "detail_shared_and_interested_for_site_visit",
    "option_not_matching_requirements",
    "site_visit_scheduled",
    "rescheduled",
    "site_visit_done",
    "requirement_closed",
    "no_requirements",
    "property_sold_out",
    "budget_not_sufficient",
    "switched_off",
    "number_not_in_use_wrong_number",
    "other",
]

# Logical groupings for key_metrics block
_CONTACTED_STAGES = {
    "busy",
    "ringing",
    "call_back_later",
    "details_shared_of_property",
    "detail_shared_and_interested_for_site_visit",
    "option_not_matching_requirements",
    "site_visit_scheduled",
    "rescheduled",
    "site_visit_done",
    "requirement_closed",
    "no_requirements",
    "property_sold_out",
    "budget_not_sufficient",
    "switched_off",
}
_CLOSED_STAGES = {
    "requirement_closed",
    "no_requirements",
    "property_sold_out",
    "budget_not_sufficient",
}


class SellerFunnelController(http.Controller):
    @http.route(
        "/api/track/property/funnel",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def property_funnel(self, **kwargs):
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

        # Collect statuses from both sources
        stage_counts = defaultdict(int)

        primary_leads = get_primary_leads_for_tags(request.env, tags)
        for lead in primary_leads:
            status = lead.current_status or "other"
            stage_counts[status] += 1

        recommended_interests = get_recommended_leads_for_tags(request.env, tags)
        for interest in recommended_interests:
            status = interest.current_status or "other"
            stage_counts[status] += 1

        total = len(primary_leads) + len(recommended_interests)

        # Build stages dict — ensure all known stages are present even if zero
        def pct(count):
            return round((count / total) * 100, 1) if total > 0 else 0.0

        stages = {
            stage: {
                "count": stage_counts.get(stage, 0),
                "pct_of_total": pct(stage_counts.get(stage, 0)),
            }
            for stage in ALL_FUNNEL_STAGES
        }

        # Key metrics rollups
        contacted = sum(stage_counts[stage] for stage in _CONTACTED_STAGES)
        closed_or_lost = sum(stage_counts[stage] for stage in _CLOSED_STAGES)

        data = {
            "owner_phone": phone,
            "properties": tags,
            "tag_filter": tag_filter,
            "funnel": {
                "total_inquiries": total,
                "stages": stages,
                "key_metrics": {
                    "contacted": contacted,
                    "site_visit_scheduled": stage_counts.get("site_visit_scheduled", 0),
                    "site_visit_done": stage_counts.get("site_visit_done", 0),
                    "closed_or_lost": closed_or_lost,
                },
            },
        }
        return success_response(data)
