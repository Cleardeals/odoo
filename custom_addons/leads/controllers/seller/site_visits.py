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

  rescheduled
      status = rescheduled.
      The previously scheduled slot was cancelled and a new one is
      pending confirmation or has been set.

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

    "rescheduled": [
      {
        ...same base shape...,
        "current_status": "rescheduled",
        "note":           "Visit was rescheduled — confirm new date with RM"
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
      "rescheduled":      1,
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

# Only records with these statuses are worth surfacing
_VISIT_STATUSES = {"site_visit_scheduled", "site_visit_done", "rescheduled"}

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


def _classify_visit(
    current_status: str,
    site_visit_date: datetime,
    now: datetime,
    feedback_general: str | None,
) -> str:
    """
    Determine which bucket a visit record belongs to.

    Returns one of: "upcoming" | "pending_feedback" | "cancelled" | "rescheduled" | "completed"
    """
    if current_status == "site_visit_done":
        return "completed"

    if current_status == "rescheduled":
        return "rescheduled"

    if current_status == "site_visit_scheduled":
        if site_visit_date > now:
            return "upcoming"
        # Date is in the past — check feedback_general to decide if the
        # RM has already logged a reason the visit didn't happen.
        if feedback_general in _EMPTY_FEEDBACK:
            return "pending_feedback"
        return "cancelled"

    # Safety fallback — should not reach here given _VISIT_STATUSES filter
    return "pending_feedback"


def _build_base_record(
    source: str,
    lead_name,
    lead_phone,
    prop,
    site_visit_date,
    site_visit_date_only,
    current_status: str,
    remarks,
) -> dict:
    """Fields present in every bucket."""
    return {
        "source": source,
        "lead_name": lead_name or None,
        "lead_phone": lead_phone or None,
        "property_tag": prop.property_tag if prop else None,
        "property_bhk": prop.bhk if prop else None,
        "property_location": prop.location if prop else None,
        "site_visit_datetime": (
            site_visit_date.isoformat() if site_visit_date else None
        ),
        "site_visit_date": (
            site_visit_date_only.isoformat() if site_visit_date_only else None
        ),
        "current_status": current_status or None,
        "remarks": remarks or None,
    }


def _apply_bucket_fields(
    record: dict,
    bucket: str,
    feedback_general: str | None,
    feedback_site_visit_done: str | None,
    remarks,
) -> dict:
    """
    Add bucket-specific fields to the record in-place and return it.

    pending_feedback — note only; no feedback value since none was logged.
    cancelled        — feedback_general (the reason) + note.
    rescheduled      — note only.
    completed        — feedback_site_visit_done always; remarks only when "other".
    upcoming         — no extra fields.
    """
    if bucket == "pending_feedback":
        record["note"] = "Visit date has passed — awaiting RM feedback"

    elif bucket == "cancelled":
        record["feedback_general"] = feedback_general
        record["note"] = "Visit did not occur due to buyer status"

    elif bucket == "rescheduled":
        record["note"] = "Visit was rescheduled — confirm new date with RM"

    elif bucket == "completed":
        record["feedback_site_visit_done"] = feedback_site_visit_done or None
        if feedback_site_visit_done == "other":
            record["remarks"] = remarks or None
        else:
            # Keep payload clean — remarks only matter when feedback is "other"
            record["remarks"] = None

    return record


def _process_visit(
    source: str,
    lead_name,
    lead_phone,
    prop,
    site_visit_date,
    site_visit_date_only,
    current_status: str,
    remarks,
    feedback_general,
    feedback_site_visit_done,
    now: datetime,
) -> tuple[str, datetime, dict]:
    """
    Full pipeline for one record: classify → build base → apply bucket fields.
    Returns (bucket, sort_key, record_dict).
    """
    bucket = _classify_visit(current_status, site_visit_date, now, feedback_general)

    record = _build_base_record(
        source=source,
        lead_name=lead_name,
        lead_phone=lead_phone,
        prop=prop,
        site_visit_date=site_visit_date,
        site_visit_date_only=site_visit_date_only,
        current_status=current_status,
        remarks=remarks,
    )

    _apply_bucket_fields(
        record=record,
        bucket=bucket,
        feedback_general=feedback_general,
        feedback_site_visit_done=feedback_site_visit_done,
        remarks=remarks,
    )

    return bucket, site_visit_date, record


def _visit_from_primary(lead, now: datetime) -> tuple[str, datetime, dict]:
    return _process_visit(
        source="primary",
        lead_name=lead.name,
        lead_phone=lead.phone,
        prop=lead.property_id,
        site_visit_date=lead.site_visit_date,
        site_visit_date_only=lead.site_visit_date_only,
        current_status=lead.current_status,
        remarks=lead.remarks,
        feedback_general=lead.feedback_general,
        feedback_site_visit_done=lead.feedback_site_visit_done,
        now=now,
    )


def _visit_from_recommended(interest, now: datetime) -> tuple[str, datetime, dict]:
    parent = interest.lead_id
    return _process_visit(
        source="recommended",
        lead_name=parent.name if parent else None,
        lead_phone=parent.phone if parent else None,
        prop=interest.property_id,
        site_visit_date=interest.site_visit_date,
        site_visit_date_only=interest.site_visit_date_only,
        current_status=interest.current_status,
        remarks=interest.remarks,
        feedback_general=interest.feedback_general,
        feedback_site_visit_done=interest.feedback_site_visit_done,
        now=now,
    )


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
            "rescheduled": [],
            "completed": [],
        }

        # ── Primary leads ─────────────────────────────────────────────────────
        primary_leads = get_primary_leads_for_tags(request.env, tags).filtered(
            lambda lead: (
                lead.site_visit_date and lead.current_status in _VISIT_STATUSES
            ),
        )
        for lead in primary_leads:
            bucket, sort_key, record = _visit_from_primary(lead, now)
            buckets[bucket].append((sort_key, record))

        # ── Recommended interests ─────────────────────────────────────────────
        recommended_interests = get_recommended_leads_for_tags(
            request.env,
            tags,
        ).filtered(
            lambda i: i.site_visit_date and i.current_status in _VISIT_STATUSES,
        )
        for interest in recommended_interests:
            bucket, sort_key, record = _visit_from_recommended(interest, now)
            buckets[bucket].append((sort_key, record))

        # ── Sort each bucket ──────────────────────────────────────────────────
        # upcoming         → soonest first (ascending)
        # pending_feedback → most overdue first (ascending — oldest unresolved at top)
        # cancelled        → most recent first (descending)
        # rescheduled      → most recent first (descending)
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
        rescheduled_sorted = [
            r
            for _, r in sorted(buckets["rescheduled"], key=lambda x: x[0], reverse=True)
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
            "rescheduled": rescheduled_sorted,
            "completed": completed_sorted,
            "totals": {
                "upcoming": len(upcoming_sorted),
                "pending_feedback": len(pending_feedback_sorted),
                "cancelled": len(cancelled_sorted),
                "rescheduled": len(rescheduled_sorted),
                "completed": len(completed_sorted),
            },
        }
        return success_response(data)
