"""
GET /api/track/lead/site-visits
---------------------------------
Returns all site visits for a buyer across ALL of their inquiries —
both primary leads (leads.new) and recommended property interests
(lead.property.interest).

Classification rules  (mirrors seller site-visits logic exactly)
--------------------

  upcoming
      status = site_visit_scheduled AND date is in the future.

  pending_feedback
      status = site_visit_scheduled AND date is in the past AND
      feedback_general is empty or "other".
      Visit was never formally closed — no meaningful outcome logged yet.

  cancelled
      status = site_visit_scheduled AND date is in the past AND
      feedback_general has a real value (e.g. "buyer_not_interested",
      "buyer_not_picking_call").
      Visit did not occur and the RM has logged a reason why.

  rescheduled
      status = rescheduled.
      Previously scheduled slot was cancelled; new slot TBD or set.

  completed
      status = explicitly site_visit_done.
      feedback_site_visit_done is always included.
      remarks is only included when feedback_site_visit_done = "other"
      (RM described the outcome in free text instead of a dropdown value).

Query param
-----------
phone : str — buyer phone, with or without leading 91 (required)

Response shape
--------------
{
  "success": true,
  "data": {
    "buyer_phone": "9876543210",

    "upcoming": [
      {
        "inquiry_type":        "primary" | "recommended",
        "lead_id":             101,
        "lead_name":           "Ravi Shah",
        "source":              "MagicBricks",
        "property_tag":        "TAG1",
        "property_bhk":        "2BHK",
        "property_location":   "Maninagar",
        "property_city":       "Ahmedabad",
        "site_visit_datetime": "2025-03-20T11:00:00",
        "site_visit_date":     "2025-03-20",
        "current_status":      "site_visit_scheduled",
        "remarks":             "Ask for key from owner"
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
      "upcoming":         1,
      "pending_feedback": 1,
      "cancelled":        1,
      "rescheduled":      1,
      "completed":        3
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
from ..shared.response_utils import error_response, success_response

_logger = logging.getLogger(__name__)

_VISIT_STATUSES = {"site_visit_scheduled", "site_visit_done", "rescheduled"}

_EMPTY_FEEDBACK = {None, "", "other", False}


def _classify_visit(
    current_status: str,
    site_visit_date: datetime | None,
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

        if feedback_general in _EMPTY_FEEDBACK:
            return "pending_feedback"
        return "cancelled"

    return "pending_feedback"


def _build_base_record(
    source: str,
    lead_id: int,
    lead_name,
    lead_source,
    prop,
    site_visit_date,
    site_visit_date_only,
    current_status: str,
    remarks,
) -> dict:
    """Fields present in every bucket."""
    return {
        "inquiry_type": source,
        "lead_id": lead_id,
        "lead_name": lead_name or None,
        "source": lead_source or None,
        "property_tag": prop.property_tag if prop else None,
        "property_bhk": prop.bhk if prop else None,
        "property_location": prop.location if prop else None,
        "property_city": prop.city if prop else None,
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
    lead_id: int,
    lead_name,
    lead_source,
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
        lead_id=lead_id,
        lead_name=lead_name,
        lead_source=lead_source,
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
        lead_id=lead.id,
        lead_name=lead.name,
        lead_source=lead.source_id.name,
        prop=lead.property_base_id,
        site_visit_date=lead.site_visit_date,
        site_visit_date_only=lead.site_visit_date_only,
        current_status=lead.current_status,
        remarks=lead.remarks,
        feedback_general=lead.feedback_general,
        feedback_site_visit_done=lead.feedback_site_visit_done,
        now=now,
    )


def _visit_from_interest(
    interest,
    parent_lead,
    now: datetime,
) -> tuple[str, datetime, dict]:
    return _process_visit(
        source="recommended",
        lead_id=parent_lead.id,
        lead_name=parent_lead.name,
        lead_source=parent_lead.source_id.name,
        prop=interest.property_base_id,
        site_visit_date=interest.site_visit_date,
        site_visit_date_only=interest.site_visit_date_only,
        current_status=interest.current_status,
        remarks=interest.remarks,
        feedback_general=interest.feedback_general,
        feedback_site_visit_done=interest.feedback_site_visit_done,
        now=now,
    )


class BuyerSiteVisitsController(http.Controller):
    @http.route(
        "/api/track/lead/site-visits",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def lead_site_visits(self, **kwargs):
        """
        Query param: phone (required) — buyer's phone number.
        """
        auth_error = validate_api_key(request)
        if auth_error:
            return auth_error

        phone = extract_phone_from_request(request)
        if not phone:
            return error_response(400, "Valid 'phone' query parameter is required.")

        leads = request.env["leads.new"].sudo().search([("phone", "=", phone)])

        if not leads:
            return error_response(404, f"No inquiries found for phone {phone}.")

        now = datetime.now()

        # Accumulate (sort_datetime, record) tuples per bucket
        buckets: dict[str, list[tuple[datetime, dict]]] = {
            "upcoming": [],
            "pending_feedback": [],
            "cancelled": [],
            "rescheduled": [],
            "completed": [],
        }

        for lead in leads:
            # ── Primary lead site visit ───────────────────────────────────────
            if lead.site_visit_date and lead.current_status in _VISIT_STATUSES:
                bucket, sort_key, record = _visit_from_primary(lead, now)
                buckets[bucket].append((sort_key, record))

            # ── Recommended property site visits on this lead ─────────────────
            for interest in lead.interest_ids:
                if (
                    interest.site_visit_date
                    and interest.current_status in _VISIT_STATUSES
                ):
                    bucket, sort_key, record = _visit_from_interest(interest, lead, now)
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
            "buyer_phone": phone,
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
