"""
GET /web/leads/property_activity/<property_id>
-----------------------------------------------
Internal JSON endpoint — Odoo session auth only (no API key required).
Complements the existing public seller endpoints (activity, summary,
site_visits, funnel) which identify properties by owner phone + API key.
This one identifies the property by its Odoo database ID and uses the
user's Odoo session, so it is safe to call directly from form view widgets.

Returns a unified dashboard payload combining:
  - KPI counts (total inquiries, status buckets, by source)
  - Paginated activity records (primary + recommended, newest first)
  - Site visit breakdown (upcoming / pending_feedback / completed / cancelled)

All ORM queries reuse the same resolver helpers as the public seller API.
"""

import csv
import io
import logging
from datetime import datetime, timezone

from odoo import http
from odoo.http import request



_logger = logging.getLogger(__name__)

_EMPTY_FEEDBACK = {None, "", "other", False}

# Status → display bucket used for KPI cards.
# "lead" (initial / never contacted) is intentionally absent — those inquiries
# count toward the total but not toward any specific sub-bucket KPI.
_STATUS_BUCKET = {
    "busy":                                         "contacted",
    "ringing":                                      "contacted",
    "call_back_later":                              "contacted",
    "switched_off":                                 "contacted",
    "other":                                        "contacted",
    "details_shared_of_property":                   "details_shared",
    "detail_shared_and_interested_for_site_visit":  "details_shared",
    "site_visit_scheduled":                         "site_visit_scheduled",
    "rescheduled":                                  "site_visit_scheduled",
    "site_visit_done":                              "site_visit_done",
    "option_not_matching_requirements":             "not_interested",
    "no_requirements":                              "not_interested",
    "requirement_closed":                           "not_interested",
    "property_sold_out":                            "not_interested",
    "budget_not_sufficient":                        "not_interested",
    "number_not_in_use_wrong_number":               "not_interested",
}


def _serialize_lead(lead, rec_type="primary"):
    prop = lead.property_base_id
    parent = lead
    return {
        "type": rec_type,
        "lead_id": parent.id if parent else None,
        "lead_name": (parent.name if parent else None) or "",
        "lead_phone": (parent.phone if parent else None) or "",
        "source": (parent.source_id.name if parent and parent.source_id else None) or "Unknown",
        "assigned_rm": (parent.user_id.name if parent and parent.user_id else None) or "",
        "property_tag": prop.property_tag if prop else "",
        "property_bhk": prop.bhk if prop else "",
        "property_location": prop.location if prop else "",
        "inquiry_date": lead.create_date.strftime("%Y-%m-%d") if lead.create_date else None,
        "inquiry_datetime": lead.create_date.isoformat() if lead.create_date else None,
        "current_status": lead.current_status or "lead",
        "site_visit_date": (
            lead.site_visit_date_only.isoformat() if lead.site_visit_date_only else None
        ),
        "site_visit_datetime": (
            lead.site_visit_date.isoformat() if lead.site_visit_date else None
        ),
        "feedback_general": lead.feedback_general or None,
        "feedback_site_visit_done": lead.feedback_site_visit_done or None,
        "remarks": lead.remarks or None,
    }


def _serialize_site_visit(visit, now):
    """Serialize a lead.site.visit record into a dashboard-ready dict.

    Uses the proper site visit model fields (status flags, feedback_option_id,
    chain linkage) instead of the snapshot fields on leads.new.
    """
    inquiry = visit.inquiry_id
    status = visit.status_id
    rm = visit.assigned_rm_id or (inquiry.user_id if inquiry else None)
    return {
        "visit_id": visit.id,
        "inquiry_id": inquiry.id if inquiry else None,
        "lead_name": (inquiry.name or "") if inquiry else "",
        "lead_phone": (inquiry.phone or "") if inquiry else "",
        "source": (
            (inquiry.source_id.name if inquiry.source_id else None) if inquiry else None
        ) or "Unknown",
        "assigned_rm": (rm.name or "") if rm else "",
        "scheduled_datetime": (
            visit.scheduled_datetime.isoformat() if visit.scheduled_datetime else None
        ),
        "scheduled_date": (
            visit.scheduled_date.isoformat() if visit.scheduled_date else None
        ),
        # Status from the configurable status model — not the old string selection
        "status_name": status.name if status else "",
        "status_type": status.status_type if status else "custom",
        # Timeline chain info
        "reschedule_iteration": visit.reschedule_iteration or 0,
        "root_visit_id": (visit.root_visit_id.id if visit.root_visit_id else visit.id),
        "previous_visit_id": (visit.previous_visit_id.id if visit.previous_visit_id else None),
        # Feedback from the configurable feedback option model
        "feedback": visit.feedback_option_id.name if visit.feedback_option_id else None,
        "feedback_note": visit.feedback_note or None,
        "is_overdue": visit.is_overdue_open,
        # Pre-computed display bucket — used by the JS grouping logic so that
        # custom statuses (e.g. "Cancelling" with is_cancelled_status=True but
        # status_type="custom") are routed to the correct tab without relying
        # on status_type string matching in the browser.
        "sv_bucket": _sv_bucket(status, visit, now),
    }


def _sv_bucket(status, visit, now):
    """Return the display bucket string for a lead.site.visit record.

    Boolean flags are the primary signal; status_type string is the fallback
    so this works even when the flags are not explicitly configured.

    Reschedule is always treated as non-terminal: some Odoo setups mark the
    old rescheduled slot as is_cancelled_status=True to close it, but it must
    never land in the Cancelled tab — it is an intermediate step in the chain.
    """
    if not status:
        return "custom"
    # Completed — boolean flag or status_type
    if status.is_completed_status or status.status_type == "completed":
        return "completed"
    # Reschedule BEFORE cancel — some configs set both flags; reschedule wins
    is_resch = status.is_reschedule_status or status.status_type == "rescheduled"
    is_sched = status.is_scheduled_status or status.status_type == "scheduled"
    if is_resch or is_sched:
        sv_dt = (
            visit.scheduled_datetime.replace(tzinfo=None)
            if visit.scheduled_datetime else None
        )
        return "upcoming" if sv_dt and sv_dt >= now else "pending_feedback"
    # True cancellation / no-show
    if (
        status.is_cancelled_status
        or status.is_no_show_status
        or status.status_type in ("cancelled", "no_show")
    ):
        return "cancelled"
    return "custom"


class PropertyActivityDashboardController(http.Controller):

    @http.route(
        "/web/leads/property_activity/<int:property_id>",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def property_activity_dashboard(self, property_id, **kwargs):
        env = request.env

        prop = env["property.base"].browse(property_id)
        if not prop.exists():
            return {"error": f"Property {property_id} not found."}

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # ── Primary leads — inquiry_type=primary only ──────────────────
        # We already have the Odoo DB id; no need to go through property_tag.
        # Recommended inquiries (inquiry_type=recommended) are queried separately
        # below so they surface as the correct type in the dashboard.
        primary_leads = (
            env["leads.new"]
            .sudo()
            .search(
                [
                    ("property_base_id", "=", property_id),
                    ("inquiry_type", "=", "primary"),
                ],
                order="create_date desc",
            )
        )

        # ── Recommended leads — leads.new records created via the
        #    Recommend Property wizard (inquiry_type=recommended) ──────────
        recommended = (
            env["leads.new"]
            .sudo()
            .search(
                [
                    ("property_base_id", "=", property_id),
                    ("inquiry_type", "=", "recommended"),
                ],
                order="create_date desc",
            )
        )

        # ── Site visits — loaded FIRST to build KPI override sets ─────────
        # Uses lead.site.visit model with configurable status flags and the
        # full timeline chain (root_visit_id, reschedule_iteration).
        # Queried before the KPI loop so that a lead whose current_status is
        # stale (e.g. "site_visit_done" but a new visit is now scheduled) is
        # correctly counted in "site_visit_scheduled" in the KPI cards.
        sv_records = (
            env["lead.site.visit"]
            .sudo()
            .search(
                [("property_base_id", "=", property_id)],
                order="scheduled_datetime desc",
            )
        )
        # Inquiry IDs that currently have at least one future-dated scheduled visit.
        inquiry_scheduled_sv = set()
        site_visits = {
            "all": [],
            "upcoming": [],
            "pending_feedback": [],
            "completed": [],
            "cancelled": [],
        }
        for sv in sv_records:
            status = sv.status_id
            if not status:
                continue
            row = _serialize_site_visit(sv, now)
            site_visits["all"].append(row)
            inquiry_id = sv.inquiry_id.id if sv.inquiry_id else None
            if status.is_completed_status:
                site_visits["completed"].append(row)
            elif status.is_cancelled_status or status.is_no_show_status:
                site_visits["cancelled"].append(row)
            elif status.is_scheduled_status or status.is_reschedule_status:
                sv_dt = sv.scheduled_datetime.replace(tzinfo=None) if sv.scheduled_datetime else None
                if sv_dt and sv_dt >= now:
                    site_visits["upcoming"].append(row)
                    if inquiry_id:
                        inquiry_scheduled_sv.add(inquiry_id)
                else:
                    site_visits["pending_feedback"].append(row)
        site_visits["totals"] = {
            k: len(v) for k, v in site_visits.items() if k not in ("totals", "all")
        }

        # ── KPI counts ────────────────────────────────────────────────────
        # "lead" (initial / uncontacted) is NOT in _STATUS_BUCKET, so those
        # inquiries count toward the total but not any sub-bucket KPI.
        # Active scheduled visits override current_status so the KPI reflects
        # where the lead is RIGHT NOW, not the last manually set status.
        kpi = {
            "total": len(primary_leads) + len(recommended),
            "primary": len(primary_leads),
            "recommended": len(recommended),
            "contacted": 0,
            "details_shared": 0,
            "site_visit_scheduled": 0,
            "site_visit_done": 0,
            "not_interested": 0,
        }
        for lead in primary_leads:
            if lead.id in inquiry_scheduled_sv:
                bucket = "site_visit_scheduled"
            else:
                bucket = _STATUS_BUCKET.get(lead.current_status)
                if bucket is None:
                    continue  # uncontacted ("lead" status) — not shown in any sub-bucket
            kpi[bucket] = kpi.get(bucket, 0) + 1
        for rec in recommended:
            if rec.id in inquiry_scheduled_sv:
                bucket = "site_visit_scheduled"
            else:
                bucket = _STATUS_BUCKET.get(rec.current_status)
                if bucket is None:
                    continue
            kpi[bucket] = kpi.get(bucket, 0) + 1

        # ── Source breakdown ───────────────────────────────────────────────
        source_counts = {}
        for lead in primary_leads:
            src = lead.source_id.name if lead.source_id else "Unknown"
            source_counts.setdefault(src, {"primary": 0, "recommended": 0})
            source_counts[src]["primary"] += 1
        for rec in recommended:
            src = rec.source_id.name if rec.source_id else "Unknown"
            source_counts.setdefault(src, {"primary": 0, "recommended": 0})
            source_counts[src]["recommended"] += 1

        # ── Activity records (combined, sorted by date desc) ───────────────
        activity = []
        for lead in primary_leads:
            activity.append(_serialize_lead(lead, "primary"))
        for rec in recommended:
            activity.append(_serialize_lead(rec, "recommended"))
        activity.sort(key=lambda r: r["inquiry_datetime"] or "", reverse=True)

        return {
            "property_id": property_id,
            "property_tag": prop.property_tag or "",
            "property_name": prop.name or "",
            "kpi": kpi,
            "source_breakdown": source_counts,
            "activity": activity,
            "site_visits": site_visits,
        }

    @http.route(
        "/web/leads/property_activity/<int:property_id>/export.csv",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def property_activity_export_csv(self, property_id, **kwargs):
        env = request.env

        prop = env["property.base"].browse(property_id)
        if not prop.exists():
            return request.not_found()

        # ── Primary + Recommended leads (both leads.new) ──────────────────
        primary_leads = (
            env["leads.new"]
            .sudo()
            .search(
                [
                    ("property_base_id", "=", property_id),
                    ("inquiry_type", "=", "primary"),
                ],
                order="create_date desc",
            )
        )
        recommended = (
            env["leads.new"]
            .sudo()
            .search(
                [
                    ("property_base_id", "=", property_id),
                    ("inquiry_type", "=", "recommended"),
                ],
                order="create_date desc",
            )
        )

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "Type", "Date", "Buyer Name", "Phone", "Source", "Assigned RM",
            "Status", "Site Visit Date", "Feedback (SV)", "Feedback (General)", "Remarks",
        ])

        for row in list(primary_leads) + list(recommended):
            rec_type = row.inquiry_type or "primary"
            parent = row
            writer.writerow([
                rec_type,
                row.create_date.strftime("%Y-%m-%d") if row.create_date else "",
                (parent.name if parent else "") or "",
                (parent.phone if parent else "") or "",
                (parent.source_id.name if parent and parent.source_id else "") or "Unknown",
                (parent.user_id.name if parent and parent.user_id else "") or "",
                row.current_status or "",
                row.site_visit_date_only.isoformat() if row.site_visit_date_only else "",
                row.feedback_site_visit_done or "",
                row.feedback_general or "",
                row.remarks or "",
            ])

        filename = f"property_activity_{prop.property_tag or property_id}.csv"
        csv_bytes = buf.getvalue().encode("utf-8-sig")  # utf-8-sig adds BOM for Excel
        return request.make_response(
            csv_bytes,
            headers=[
                ("Content-Type", "text/csv; charset=utf-8"),
                ("Content-Disposition", f'attachment; filename="{filename}"'),
                ("Content-Length", len(csv_bytes)),
            ],
        )
