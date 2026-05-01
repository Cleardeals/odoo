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

# Only statuses used by the legacy lead.property.interest snapshot path.
_LEGACY_VISIT_STATUSES = {"site_visit_scheduled", "site_visit_done"}

# feedback_general values treated as "nothing meaningful logged yet"
_EMPTY_FEEDBACK = {None, "", "other", False}

FEEDBACK_GENERAL_MAP = {
    "buyer_did_not_visit_property": "Buyer Did Not Visit Property",
    "buyer_not_interested": "Buyer Not Interested",
    "buyer_not_picking_call": "Buyer Not Picking Call",
    "visit_needs_to_be_rescheduled": "Visit Needs to be Rescheduled",
    "other": "Other",
}

FEEDBACK_DONE_MAP = {
    "buyer_liked_property": "Buyer Liked Property",
    "buyer_requirement_closed": "Buyer Requirement Closed",
    "buyer_visit_from_outside": "Buyer Visit From Outside",
    "buyer_not_pickup_call": "Buyer Not Picking Call",
    "planning_for_second_visit": "Planning for Second Visit",
    "negotiation_stage": "Negotiation Stage",
    "visit_done_confirmed_by_owner": "Visit Done - Confirmed by Owner",
    "looking_for_more_options": "Looking for More Options",
    "price_is_high": "Price is High",
    "location_mismatch": "Location Mismatch",
    "deal_closed": "Deal Closed",
    "other": "Other",
}


# ── New visit-model helpers ────────────────────────────────────────────────


def _get_latest_active_visit(lead):
    """
    Return the latest non-superseded lead.site.visit for this inquiry.

    Superseded visits are the closed leg of a reschedule chain and must be
    skipped so the API reflects the actual current appointment state.
    """
    return lead.sudo().site_visit_ids.filtered(
        lambda v: v.status_id.code != "superseded"
    )[:1]


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
    feedback_code = visit.feedback_option_id.code or None
    feedback_note = visit.feedback_note or None

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
        "remarks": feedback_note,
    }

    if bucket == "pending_feedback":
        record["note"] = "Visit date has passed — awaiting RM feedback"
    elif bucket == "cancelled":
        record["feedback_general"] = feedback_code
        record["note"] = "Visit did not occur due to buyer status"
    elif bucket == "completed":
        record["feedback_site_visit_done"] = feedback_code

    return bucket, visit.scheduled_datetime, record


# ── Legacy snapshot helpers (lead.property.interest) ──────────────────────


def _classify_legacy_visit(
    current_status: str,
    site_visit_date: datetime,
    now: datetime,
    feedback_general: str | None,
) -> str:
    """
    Classify a legacy lead.property.interest record.

    This path is retained for backward compatibility with interest records that
    predate the lead.site.visit model.  New visits are handled by
    _classify_visit_new / _visit_from_lead_model instead.
    """
    if current_status == "site_visit_done":
        return "completed"

    if current_status == "site_visit_scheduled":
        if site_visit_date > now:
            return "upcoming"
        if feedback_general in _EMPTY_FEEDBACK:
            return "pending_feedback"
        return "cancelled"

    return "pending_feedback"


def _visit_from_recommended_legacy(interest, now: datetime) -> tuple[str, datetime, dict]:
    """
    Build (bucket, sort_key, record_dict) from a legacy lead.property.interest record.

    Retained for backward compatibility with interest records that predate the
    lead.site.visit model.  New recommended inquiries use leads.new +
    lead.site.visit and are handled by _visit_from_lead_model instead.
    """
    parent = interest.lead_id
    current_status = interest.current_status
    site_visit_date = interest.site_visit_date
    feedback_general = interest.feedback_general
    feedback_site_visit_done = interest.feedback_site_visit_done

    bucket = _classify_legacy_visit(current_status, site_visit_date, now, feedback_general)

    record = {
        "source": "recommended",
        "lead_name": parent.name if parent else None,
        "lead_phone": parent.phone if parent else None,
        "property_tag": interest.property_base_id.property_tag if interest.property_base_id else None,
        "property_bhk": interest.property_base_id.bhk if interest.property_base_id else None,
        "property_location": interest.property_base_id.location if interest.property_base_id else None,
        "site_visit_datetime": site_visit_date.isoformat() if site_visit_date else None,
        "site_visit_date": interest.site_visit_date_only.isoformat() if interest.site_visit_date_only else None,
        "current_status": current_status or None,
        "remarks": interest.remarks or None,
    }

    if bucket == "pending_feedback":
        record["note"] = "Visit date has passed — awaiting RM feedback"
    elif bucket == "cancelled":
        record["feedback_general"] = feedback_general
        record["note"] = "Visit did not occur due to buyer status"
    elif bucket == "completed":
        record["feedback_site_visit_done"] = feedback_site_visit_done or None
        if feedback_site_visit_done == "other":
            record["remarks"] = interest.remarks or None
        else:
            record["remarks"] = None

    return bucket, site_visit_date, record


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
        # get_primary_leads_for_tags returns all leads.new with property_base_id
        # in the seller's property set — this covers both inquiry_type='primary'
        # and inquiry_type='recommended' records transparently.
        for lead in get_primary_leads_for_tags(request.env, tags):
            visit = _get_latest_active_visit(lead)
            if not visit:
                continue
            bucket, sort_key, record = _visit_from_lead_model(lead, visit, now)
            buckets[bucket].append((sort_key, record))

        # ── Legacy lead.property.interest records ─────────────────────────────
        # Retained for visits created before the lead.site.visit model existed.
        for interest in get_recommended_leads_for_tags(request.env, tags).filtered(
            lambda i: i.site_visit_date and i.current_status in _LEGACY_VISIT_STATUSES,
        ):
            bucket, sort_key, record = _visit_from_recommended_legacy(interest, now)
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
