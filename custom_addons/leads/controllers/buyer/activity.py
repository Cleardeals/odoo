"""
GET /api/track/lead/activity
-----------------------------
Returns the full activity picture for a buyer identified by their phone number.

The buyer may have:
  - Multiple primary inquiries (separate leads.new records for different properties)
  - Multiple recommended properties per inquiry (lead.property.interest records)
  - Primary inquiries with no property linked (portal ID not matched yet)

All of these cases are handled gracefully.

Query param
-----------
phone : str — buyer phone, with or without leading 91 (required)

Response shape
--------------
{
  "success": true,
  "data": {
    "buyer_phone": "9876543210",
    "summary": {
      "total_inquiries":        5,   // total primary leads.new records found
      "total_properties":       7,   // primary + recommended properties combined
      "site_visits_scheduled":  2,
      "site_visits_done":       1
    },
    "primary_inquiries": [
      {
        "lead_id":             101,
        "lead_name":           "Ravi Shah",
        "source":              "MagicBricks",
        "inquiry_datetime":    "2025-01-10T09:00:00",
        "current_status":      "site_visit_scheduled",
        "first_contacted_on":  "2025-01-11T10:00:00",
        "remarks":             "Wants east-facing flat",
        "feedback_general":    null,
        "feedback_site_visit_done": null,
        "has_property":        true,
        "property": {
          "property_tag":     "TAG1",
          "bhk":              "2BHK",
          "location":         "Maninagar",
          "city":             "Ahmedabad",
          "property_link":    "https://..."
        } | null,
        "site_visit_datetime": "2025-02-20T11:00:00",
        "site_visit_date":     "2025-02-20",
        "recommended_properties": [
          {
            "interest_id":          55,
            "property_tag":         "TAG2",
            "bhk":                  "2BHK",
            "location":             "Navrangpura",
            "city":                 "Ahmedabad",
            "property_link":        "https://...",
            "current_status":       "details_shared_of_property",
            "site_visit_datetime":  null,
            "site_visit_date":      null,
            "remarks":              null
          }
        ]
      }
    ]
  },
  "error": null
}
"""

import logging

from odoo import http
from odoo.http import request

from ..shared.auth import validate_api_key
from ..shared.phone_utils import extract_phone_from_request
from ..shared.response_utils import error_response, success_response

_logger = logging.getLogger(__name__)


def _get_latest_active_visit(lead):
    """Return the most recent non-superseded site visit for a leads.new record, or False."""
    return lead.sudo().site_visit_ids.filtered(
        lambda v: v.status_id.code != "superseded"
    )[:1]


def _serialize_property(prop) -> dict | None:
    if not prop:
        return None
    return {
        "property_tag": prop.property_tag or None,
        "bhk": prop.bhk or None,
        "location": prop.location or None,
        "city": prop.city or None,
        "property_link": prop.property_link or None,
    }


def _serialize_recommended_lead(inquiry) -> dict:
    prop = inquiry.sudo().property_base_id or None
    visit = _get_latest_active_visit(inquiry)
    return {
        "interest_id": inquiry.id,
        "property_tag": prop.property_tag if prop else None,
        "bhk": prop.bhk if prop else None,
        "location": prop.location if prop else None,
        "city": prop.city if prop else None,
        "property_link": prop.property_link if prop else None,
        "current_status": inquiry.current_status or None,
        "site_visit_datetime": (
            inquiry.site_visit_date.isoformat() if inquiry.site_visit_date else None
        ),
        "site_visit_date": (
            inquiry.site_visit_date_only.isoformat()
            if inquiry.site_visit_date_only
            else None
        ),
        "remarks": (visit.feedback_note or None) if visit else None,
    }


def _serialize_primary_lead(lead) -> dict:
    prop = lead.property_base_id or None
    visit = _get_latest_active_visit(lead)

    s = visit.status_id if visit else None
    feedback_code = (visit.feedback_option_id.code or None) if visit else None
    feedback_general = feedback_code if (s and (s.is_cancelled_status or s.is_no_show_status)) else None
    feedback_done = feedback_code if (s and s.is_completed_status) else None

    recommended = [_serialize_recommended_lead(c) for c in lead.sudo().child_inquiry_ids]

    return {
        "lead_id": lead.id,
        "lead_name": lead.name or None,
        "source": lead.source_id.name or None,
        "inquiry_datetime": (
            lead.create_date.isoformat() if lead.create_date else None
        ),
        "current_status": lead.current_status or None,
        "first_contacted_on": (
            lead.first_contact_datetime.isoformat()
            if lead.first_contact_datetime
            else None
        ),
        "remarks": (visit.feedback_note or None) if visit else None,
        "feedback_general": feedback_general,
        "feedback_site_visit_done": feedback_done,
        "has_property": bool(prop),
        "property": _serialize_property(prop),
        "site_visit_datetime": (
            lead.site_visit_date.isoformat() if lead.site_visit_date else None
        ),
        "site_visit_date": (
            lead.site_visit_date_only.isoformat() if lead.site_visit_date_only else None
        ),
        "recommended_properties": recommended,
    }


class BuyerActivityController(http.Controller):
    @http.route(
        "/api/track/lead/activity",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def lead_activity(self, **kwargs):
        """
        Query param: phone (required) — buyer's phone number.
        """
        auth_error = validate_api_key(request)
        if auth_error:
            return auth_error

        phone = extract_phone_from_request(request)
        if not phone:
            return error_response(400, "Valid 'phone' query parameter is required.")

        leads = (
            request.env["leads.new"]
            .sudo()
            .search(
                [("phone", "=", phone), ("inquiry_type", "=", "primary")],
                order="create_date desc",
            )
        )

        if not leads:
            return error_response(
                404,
                f"No Inquiries found for phone number {phone}.",
            )

        site_visits_scheduled = 0
        site_visits_done = 0
        total_properties = 0

        serialised_leads = []
        for lead in leads:
            serialised = _serialize_primary_lead(lead)
            serialised_leads.append(serialised)

            # Count property touchpoints
            if lead.property_base_id:
                total_properties += 1
            total_properties += len(lead.sudo().child_inquiry_ids)

            # Count visit milestones for the primary lead using live visit status flags
            primary_visit = _get_latest_active_visit(lead)
            if primary_visit:
                ps = primary_visit.status_id
                if ps.is_scheduled_status or ps.is_reschedule_status:
                    site_visits_scheduled += 1
                elif ps.is_completed_status:
                    site_visits_done += 1

            # Count visit milestones for each recommended child inquiry
            for child in lead.sudo().child_inquiry_ids:
                child_visit = _get_latest_active_visit(child)
                if child_visit:
                    cs = child_visit.status_id
                    if cs.is_scheduled_status or cs.is_reschedule_status:
                        site_visits_scheduled += 1
                    elif cs.is_completed_status:
                        site_visits_done += 1

        data = {
            "buyer_phone": phone,
            "summary": {
                "total_inquiries": len(leads),
                "total_properties": total_properties,
                "site_visits_scheduled": site_visits_scheduled,
                "site_visits_done": site_visits_done,
            },
            "primary_inquiries": serialised_leads,
        }
        return success_response(data)
