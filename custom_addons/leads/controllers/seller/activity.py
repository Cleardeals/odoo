"""
GET /api/track/property/activity
----------------------------------
Returns granular lead-level records for all inquiries on the seller's
properties — both primary (leads.new) and recommended (lead.property.interest)
combined and sorted by inquiry date descending.

Query params
------------
phone       : str   — owner phone, with or without leading 91   (required)
property_tag: str   — filter to a single property tag           (optional)
page        : int   — page number, default 1                    (optional)
page_size   : int   — records per page, default 50, max 200     (optional)

Response shape (one item)
--------------------------
{
  "type":              "primary" | "recommended",
  "lead_id":           123,
  "lead_name":         "Ravi Shah",
  "lead_phone":        "9876543210",
  "portal":            "MagicBricks",
  "property_tag":      "TAG1",
  "property_bhk":      "2BHK",
  "property_location": "Maninagar",
  "inquiry_datetime":  "2024-12-01T14:30:00",   // create_date of leads.new
  "current_status":    "site_visit_scheduled",
  "first_contacted_on":"2024-12-02T10:00:00",
  "site_visit_datetime":"2024-12-05T11:00:00",
  "site_visit_date":   "2024-12-05",
  "remarks":           "Interested in 2nd floor",
  "feedback_general":  null,
  "feedback_site_visit_done": null
}
"""

import logging

from odoo import http
from odoo.http import request

from ..shared.auth import validate_api_key
from ..shared.phone_utils import extract_phone_from_request
from ..shared.property_resolver import (
    get_primary_leads_for_tags,
    get_properties_for_phone,
    get_recommended_leads_for_tags,
)
from ..shared.response_utils import error_response, paginate, success_response

_logger = logging.getLogger(__name__)


def _serialize_primary_lead(lead) -> dict:
    """
    Serialize a leads.new record into the unified activity shape.
    """
    prop = lead.property_base_id
    return {
        "type": "primary",
        "lead_name": lead.name or None,
        "lead_phone": lead.phone or None,
        "portal": lead.portal_name or None,
        "property_tag": prop.property_tag if prop else None,
        "property_bhk": prop.bhk if prop else None,
        "property_location": prop.location if prop else None,
        "inquiry_datetime": lead.create_date.isoformat() if lead.create_date else None,
        "current_status": lead.current_status or None,
        "first_contacted_on": (
            lead.first_contact_datetime.isoformat()
            if lead.first_contact_datetime
            else None
        ),
        "site_visit_datetime": (
            lead.site_visit_date.isoformat() if lead.site_visit_date else None
        ),
        "site_visit_date": (
            lead.site_visit_date_only.isoformat() if lead.site_visit_date_only else None
        ),
        "remarks": lead.remarks or None,
        "feedback_general": lead.feedback_general or None,
        "feedback_site_visit_done": lead.feedback_site_visit_done or None,
    }


def _serialize_recommended_lead(interest) -> dict:
    """Serialise a lead.property.interest record into the unified activity shape."""
    prop = interest.property_base_id
    parent_lead = interest.lead_id
    return {
        "type": "recommended",
        "lead_name": parent_lead.name if parent_lead else None,
        "lead_phone": parent_lead.phone if parent_lead else None,
        "portal": parent_lead.portal_name if parent_lead else None,
        "property_tag": prop.property_tag if prop else None,
        "property_bhk": prop.bhk if prop else None,
        "property_location": prop.location if prop else None,
        # For recommended, the inquiry datetime is when the interest record was created
        "inquiry_datetime": (
            interest.create_date.isoformat() if interest.create_date else None
        ),
        "current_status": interest.current_status or None,
        # first_contacted_on lives on the parent lead
        "first_contacted_on": (
            parent_lead.first_contact_datetime.isoformat()
            if parent_lead and parent_lead.first_contact_datetime
            else None
        ),
        "site_visit_datetime": (
            interest.site_visit_date.isoformat() if interest.site_visit_date else None
        ),
        "site_visit_date": (
            interest.site_visit_date_only.isoformat()
            if interest.site_visit_date_only
            else None
        ),
        "remarks": interest.remarks or None,
        "feedback_general": interest.feedback_general or None,
        "feedback_site_visit_done": interest.feedback_site_visit_done or None,
    }


class SellerActivityController(http.Controller):
    @http.route(
        "/api/track/property/activity",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def property_activity(self, **kwargs):
        """
        Query params: phone (required), property_tag (optional),
                      page (optional, default 1), page_size (optional, default 50).
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

        primary_leads = get_primary_leads_for_tags(request.env, tags)
        recommended_interests = get_recommended_leads_for_tags(request.env, tags)

        records = []
        for lead in primary_leads:
            records.append(_serialize_primary_lead(lead))
        for interest in recommended_interests:
            records.append(_serialize_recommended_lead(interest))

        records.sort(
            key=lambda r: r["inquiry_datetime"] or "",  # None values go last
            reverse=True,
        )

        try:
            page = int(request.params.get("page", 1))
            page_size = int(request.params.get("page_size", 50))
        except (ValueError, TypeError):
            return error_response(400, "'page' and 'page_size' must be integers.")

        paged = paginate(records, page, page_size)

        data = {
            "owner_phone": phone,
            "properties": tags,
            "tag_filter": tag_filter,
            **paged,
        }
        return success_response(data)
