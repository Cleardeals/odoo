"""
GET /api/track/property/site-visits
--------------------------------------
Returns all site visits across all properties belonging to the owner
identified by `phone`. Pulls from TWO sources so no visit is missed:
  1. leads.new                — primary inquiry site visits
  2. lead.property.interest   — recommended property site visits

Classification rules
--------------------

  upcoming
      status = site_visit_scheduled AND date is in the future.

  pending_feedback
      status = site_visit_scheduled AND date is in the past AND
      feedback_general is empty or "other".
      The visit was scheduled but no meaningful outcome has been logged yet.
      RM action is needed — the buyer may not have shown up, the RM may
      not have followed up, or the outcome is simply unrecorded.

  cancelled
      status = site_visit_scheduled AND date is in the past AND
      feedback_general has a real value (e.g. "buyer_not_interested",
      "buyer_not_picking_call").
      The visit did not occur and the RM has logged a reason why.
      The feedback_general value is always included in the record.

  completed
      status = explicitly site_visit_done.
      feedback_site_visit_done is always included — it is the actual
      outcome of the visit.
      remarks is only included when feedback_site_visit_done = "other",
      because that is the only case where the RM describes the outcome
      in free text rather than selecting a dropdown value.

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
    "properties":  ["TAG1", "TAG2"],
    "tag_filter":  null,

    "upcoming": [
      {
        "source":              "primary" | "recommended",
        "lead_name":           "Ravi Shah",
        "lead_phone":          "9876543210",
        "property_tag":        "TAG1",
        "property_bhk":        "2BHK",
        "property_location":   "Maninagar",
        "site_visit_datetime": "2025-03-20T11:00:00",
        "site_visit_date":     "2025-03-20",
        "current_status":      "site_visit_scheduled",
        "remarks":             "Wants to see the terrace"
      }
    ],

    "pending_feedback": [
      {
        ...same base shape...,
        "current_status": "site_visit_scheduled",
        "note":           "Visit date has passed — awaiting RM feedback"
      }
    ],

    "cancelled": [
      {
        ...same base shape...,
        "current_status":   "site_visit_scheduled",
        "feedback_general": "buyer_not_interested" | "buyer_not_picking_call" | ...,
        "note":             "Visit did not occur due to buyer status"
      }
    ],

    "completed": [
      {
        ...same base shape...,
        "current_status":           "site_visit_done",
        "feedback_site_visit_done": "buyer_liked_property" | "deal_closed" | "other" | ...,
        "remarks":                  null  // only present when feedback_site_visit_done = "other"
      }
    ],

    "totals": {
      "upcoming":         2,
      "pending_feedback": 1,
      "cancelled":        1,
      "completed":        4
    }
  },
  "error": null
}
"""

import logging
from datetime import datetime

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




# ── New visit-model helpers ────────────────────────────────────────────────


def _get_active_visits(lead):
    """
    Return all non-superseded lead.site.visit records for this inquiry.

    Superseded visits are the closed leg of a reschedule chain and must be
    skipped so the API does not double-count rescheduled appointments.
    All other visits (scheduled, rescheduled, completed, cancelled, no-show)
    are included — a lead may have multiple active visits (e.g. one completed
    visit followed by a second scheduled visit).
    """
    return lead.sudo().site_visit_ids.filtered(
        lambda v: v.status_id.code != "superseded"
    )


def _classify_visit_new(visit, now: datetime) -> str:
    """
    Classify a lead.site.visit record using status-type flags.

    Returns one of: "upcoming" | "pending_feedback" | "cancelled" | "completed"
    """
    s = visit.status_id
    if s.is_completed_status:
        return "completed"
    if s.is_cancelled_status or s.is_no_show_status:
        return "cancelled"
    if visit.scheduled_datetime and visit.scheduled_datetime > now:
        return "upcoming"
    return "pending_feedback"


def _visit_from_lead_model(lead, visit, now: datetime) -> tuple[str, datetime, dict]:
    """
    Build (bucket, sort_key, record_dict) from a leads.new inquiry and its
    latest lead.site.visit record.

    Reads directly from lead.site.visit to bypass the stale snapshot problem:
      - feedback_option_id / feedback_note are never written back to leads.new
      - cancelled / no-show statuses are not synced to leads.new.current_status
    """
    bucket = _classify_visit_new(visit, now)
    prop = visit.property_base_id
    s = visit.status_id

    current_status_str = "site_visit_done" if s.is_completed_status else "site_visit_scheduled"

    # Primary source: feedback_option_id on the visit record (new model).
    # Fallback: legacy Selection fields on leads.new for visits where the RM
    # set feedback directly on the lead form rather than through the visit.
    feedback_option = visit.feedback_option_id
    feedback_code = feedback_option.code or None
    feedback_label = feedback_option.name or None
    feedback_note = visit.feedback_note or None

    if not feedback_code:
        _general_map = dict(lead._fields["feedback_general"].selection)
        _done_map = dict(lead._fields["feedback_site_visit_done"].selection)
        fallback_general_code = lead.feedback_general or None
        fallback_general_label = _general_map.get(fallback_general_code) if fallback_general_code else None
        fallback_done_code = lead.feedback_site_visit_done or None
        fallback_done_label = _done_map.get(fallback_done_code) if fallback_done_code else None
    else:
        fallback_general_code = fallback_general_label = None
        fallback_done_code = fallback_done_label = None

    record = {
        "source": lead.inquiry_type or "primary",
        "lead_name": lead.name or None,
        "lead_phone": lead.phone or None,
        "property_tag": prop.property_tag if prop else None,
        "property_bhk": prop.bhk if prop else None,
        "property_location": prop.location if prop else None,
        "site_visit_datetime": (
            visit.scheduled_datetime.isoformat() if visit.scheduled_datetime else None
        ),
        "site_visit_date": (
            visit.scheduled_date.isoformat() if visit.scheduled_date else None
        ),
        "current_status": current_status_str,
        "status_name": s.name or None,
        "remarks": feedback_note,
    }

    if bucket == "pending_feedback":
        record["note"] = "Visit date has passed — awaiting RM feedback"
    elif bucket == "cancelled":
        record["feedback_general"] = feedback_code or fallback_general_code
        record["feedback_general_label"] = feedback_label or fallback_general_label
        record["note"] = "Visit did not occur due to buyer status"
    elif bucket == "completed":
        record["feedback_site_visit_done"] = feedback_code or fallback_done_code
        record["feedback_site_visit_done_label"] = feedback_label or fallback_done_label

    return bucket, visit.scheduled_datetime, record


class SellerSiteVisitsController(http.Controller):
    @http.route(
        "/api/track/property/site-visits",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def property_site_visits(self, **kwargs):
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
        now = datetime.now()

        # Accumulate (sort_datetime, record) tuples per bucket
        buckets: dict[str, list[tuple[datetime, dict]]] = {
            "upcoming": [],
            "pending_feedback": [],
            "cancelled": [],
            "completed": [],
        }

        # ── All leads.new for the seller's properties (primary + recommended) ─
        all_leads = (
            get_primary_leads_for_tags(request.env, tags)
            | get_recommended_leads_for_tags(request.env, tags)
        )
        for lead in all_leads:
            for visit in _get_active_visits(lead):
                bucket, sort_key, record = _visit_from_lead_model(lead, visit, now)
                buckets[bucket].append((sort_key, record))

        # ── Sort each bucket ──────────────────────────────────────────────────
        # upcoming         → soonest first (ascending)
        # pending_feedback → most overdue first (ascending — oldest unresolved at top)
        # cancelled        → most recent first (descending)
        # completed        → most recent first (descending)
        upcoming_sorted = [
            r for _, r in sorted(buckets["upcoming"], key=lambda x: x[0])
        ]
        pending_feedback_sorted = [
            r for _, r in sorted(buckets["pending_feedback"], key=lambda x: x[0])
        ]
        cancelled_sorted = [
            r for _, r in sorted(buckets["cancelled"], key=lambda x: x[0], reverse=True)
        ]
        completed_sorted = [
            r for _, r in sorted(buckets["completed"], key=lambda x: x[0], reverse=True)
        ]

        data = {
            "owner_phone": phone,
            "properties": tags,
            "tag_filter": tag_filter,
            "upcoming": upcoming_sorted,
            "pending_feedback": pending_feedback_sorted,
            "cancelled": cancelled_sorted,
            "completed": completed_sorted,
            "totals": {
                "upcoming": len(upcoming_sorted),
                "pending_feedback": len(pending_feedback_sorted),
                "cancelled": len(cancelled_sorted),
                "completed": len(completed_sorted),
            },
        }
        return success_response(data)
