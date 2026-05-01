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


def _get_latest_active_visit(lead):
    """
    Return the latest non-superseded lead.site.visit for this inquiry.

    "Superseded" visits are the old, now-closed leg of a reschedule chain.
    They carry historical context but do not represent a current appointment.
    We filter them out so the API always reflects the actual current state.
    """
    return lead.sudo().site_visit_ids.filtered(
        lambda v: v.status_id.code != "superseded"
    )[:1]


def _classify_visit(visit, now: datetime) -> str:
    """
    Classify a lead.site.visit record into an API bucket.

    Returns one of: "upcoming" | "pending_feedback" | "cancelled" | "completed"

    Relies on the status-type flags on lead.site.visit.status rather than
    comparing string codes.  This is robust to status name changes and covers
    all terminal states correctly — including no-show, which the old snapshot-
    based approach could not represent at all.
    """
    s = visit.status_id
    if s.is_completed_status:
        return "completed"
    if s.is_cancelled_status or s.is_no_show_status:
        return "cancelled"
    # Scheduled or rescheduled: gate on future/past datetime
    if visit.scheduled_datetime and visit.scheduled_datetime > now:
        return "upcoming"
    return "pending_feedback"


def _visit_from_lead(lead, visit, now: datetime) -> tuple[str, datetime, dict]:
    """
    Build (bucket, sort_key, record_dict) for a leads.new inquiry and its
    latest lead.site.visit record.

    Reads directly from lead.site.visit to avoid the stale snapshot problem:
      - feedback_option_id / feedback_note are never written back to leads.new
        by _sync_inquiry_snapshot, so reading leads.new.feedback_* always
        returns empty for visits managed through the new visit model.
      - cancelled / no-show statuses are not synced to leads.new.current_status
        at all, so reading that field misclassifies them as pending_feedback.
    """
    bucket = _classify_visit(visit, now)
    prop = visit.property_base_id
    s = visit.status_id

    # Map to the legacy current_status strings for response backward compat.
    # Clients key on the bucket name for routing, but current_status is kept
    # for informational display.
    current_status_str = "site_visit_done" if s.is_completed_status else "site_visit_scheduled"

    feedback_code = visit.feedback_option_id.code or None
    feedback_note = visit.feedback_note or None

    record = {
        "inquiry_type": lead.inquiry_type or "primary",
        "lead_id": lead.id,
        "lead_name": lead.name or None,
        "source": lead.source_id.name if lead.source_id else None,
        "property_tag": prop.property_tag if prop else None,
        "property_bhk": prop.bhk if prop else None,
        "property_location": prop.location if prop else None,
        "property_city": prop.city if prop else None,
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
            "completed": [],
        }

        for lead in leads:
            # Covers both primary and recommended inquiries: each leads.new
            # record (regardless of inquiry_type) owns its own site visits
            # through the lead.site.visit model.  Legacy lead.property.interest
            # recommended visits are not shown here — they predate the visit
            # model and have no lead.site.visit records.
            visit = _get_latest_active_visit(lead)
            if not visit:
                continue
            bucket, sort_key, record = _visit_from_lead(lead, visit, now)
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
            "buyer_phone": phone,
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
