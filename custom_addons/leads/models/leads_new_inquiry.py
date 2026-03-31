from odoo import api, fields, models
from odoo.exceptions import ValidationError
from markupsafe import escape


# ---------------------------------------------------------------------------
# Module : leads
# Model  : leads.new (extension)
# Purpose: Inquiry typing and site-visit action hooks on lead inquiries.
# Owner  : Cleardeals Tech
# ---------------------------------------------------------------------------


class LeadsNewInquiry(models.Model):
    _inherit = "leads.new"

    inquiry_type = fields.Selection(
        [
            ("primary", "Primary Inquiry"),
            ("recommended", "Recommended Inquiry"),
        ],
        default="primary",
        required=True,
        index=True,
        tracking=True,
    )

    parent_inquiry_id = fields.Many2one(
        "leads.new",
        string="Parent Inquiry",
        ondelete="set null",
        index=True,
        tracking=True,
    )

    child_inquiry_ids = fields.One2many(
        "leads.new",
        "parent_inquiry_id",
        string="Recommended Inquiries",
    )

    site_visit_ids = fields.One2many(
        "lead.site.visit",
        "inquiry_id",
        string="Site Visits",
    )

    latest_site_visit_id = fields.Many2one(
        "lead.site.visit",
        compute="_compute_latest_site_visit",
        store=False,
    )

    site_visit_count = fields.Integer(
        compute="_compute_site_visit_count",
        store=False,
    )

    all_phone_site_visit_ids = fields.Many2many(
        "lead.site.visit",
        compute="_compute_all_phone_site_visit_ids",
        string="Overall Lead Timeline",
        store=False,
    )

    inquiry_timeline_html = fields.Html(
        compute="_compute_timeline_html",
        sanitize=False,
        string="Inquiry Timeline View",
    )

    overall_timeline_html = fields.Html(
        compute="_compute_timeline_html",
        sanitize=False,
        string="Overall Timeline View",
    )

    @api.depends("site_visit_ids.scheduled_datetime")
    def _compute_latest_site_visit(self):
        for rec in self:
            rec.latest_site_visit_id = rec.site_visit_ids[:1]

    @api.depends("site_visit_ids")
    def _compute_site_visit_count(self):
        for rec in self:
            rec.site_visit_count = len(rec.site_visit_ids)

    @api.depends("phone")
    def _compute_all_phone_site_visit_ids(self):
        site_visit_model = self.env["lead.site.visit"]
        for rec in self:
            if not rec.phone:
                rec.all_phone_site_visit_ids = site_visit_model
                continue
            rec.all_phone_site_visit_ids = site_visit_model.search(
                [("inquiry_id.phone", "=", rec.phone)],
                order="scheduled_datetime desc, id desc",
            )

    @api.depends(
        "phone",
        "site_visit_ids.scheduled_datetime",
        "site_visit_ids.status_id",
        "site_visit_ids.feedback_option_id",
        "site_visit_ids.property_base_id",
        "site_visit_ids.assigned_rm_id",
    )
    def _compute_timeline_html(self):
        for rec in self:
            rec.inquiry_timeline_html = rec._build_timeline_html(
                rec.site_visit_ids,
                show_inquiry=False,
            )
            rec.overall_timeline_html = rec._build_timeline_html(
                rec.all_phone_site_visit_ids,
                show_inquiry=True,
            )

    # ---------------------------------------------------------------------------
    # Color palette — keyed by status type.
    # accent   = left-bar colour and status text colour
    # bg_row   = alternating row background (first row lighter)
    # bg_row2  = second shade for odd/even zebra (slightly more tinted)
    # border   = pill border and separator line colour
    # ---------------------------------------------------------------------------
    _TIMELINE_PALETTE = {
        "completed":  {"accent": "#198754", "bg_row": "#eef8f2", "bg_row2": "#daf0e5", "border": "#b2dfcc"},
        "rescheduled":{"accent": "#0d6efd", "bg_row": "#edf4ff", "bg_row2": "#d9e9ff", "border": "#b6d0fb"},
        "scheduled":  {"accent": "#fd7e14", "bg_row": "#fff5eb", "bg_row2": "#ffe8cf", "border": "#fcd3a8"},
        "no_show":    {"accent": "#dc3545", "bg_row": "#fff0f1", "bg_row2": "#fde0e2", "border": "#f5b7bb"},
        "cancelled":  {"accent": "#6c757d", "bg_row": "#f4f5f6", "bg_row2": "#e9eaeb", "border": "#d3d6da"},
        "default":    {"accent": "#6c757d", "bg_row": "#f4f5f6", "bg_row2": "#e9eaeb", "border": "#d3d6da"},
    }

    def _build_timeline_html(self, visits, show_inquiry):
        self.ensure_one()

        if not visits:
            return (
                "<div style='padding:12px 16px; border:1px dashed #ced4da; border-radius:6px;"
                " color:#6c757d; font-size:13px;'>"
                "No visit events recorded yet."
                "</div>"
            )

        is_manager = self.env.user.has_group("leads.group_lead_score_manager")

        # ── Legend strip ──────────────────────────────────────────────────────
        legend_items = [
            ("#198754", "Completed"),
            ("#fd7e14", "Scheduled"),
            ("#0d6efd", "Rescheduled"),
            ("#dc3545", "No Show"),
            ("#6c757d", "Cancelled"),
        ]
        legend_html = "".join(
            f"<span style='display:inline-flex; align-items:center; gap:5px;"
            f" margin-right:14px; font-size:11px; color:#495057;'>"
            f"<span style='width:10px; height:10px; border-radius:50%; background:{col};"
            f" flex-shrink:0;'></span>{label}</span>"
            for col, label in legend_items
        )

        # ── Column header row ─────────────────────────────────────────────────
        col_header_style = (
            "padding:5px 10px; font-size:10px; font-weight:700; color:#6c757d;"
            " text-transform:uppercase; letter-spacing:0.4px; white-space:nowrap;"
        )
        header_row = (
            f"<tr style='border-bottom:2px solid #dee2e6; background:#f8f9fa;'>"
            f"<td style='{col_header_style} width:28px; text-align:center;'>#</td>"
            f"<td style='{col_header_style} width:100px;'>Date</td>"
            f"<td style='{col_header_style} width:80px;'>Time</td>"
            f"<td style='{col_header_style} width:110px;'>Status</td>"
            f"<td style='{col_header_style}'>Property</td>"
            f"<td style='{col_header_style} width:130px;'>RM</td>"
            + (f"<td style='{col_header_style}'>Inquiry</td>" if show_inquiry else "")
            + f"<td style='{col_header_style}'>Feedback</td>"
            f"<td style='{col_header_style} width:40px;'></td>"
            f"</tr>"
        )

        # ── One <tr> per visit ────────────────────────────────────────────────
        rows_html = ""
        for idx, visit in enumerate(visits, start=1):
            # Date / time
            if visit.scheduled_datetime:
                localized_dt = fields.Datetime.context_timestamp(self, visit.scheduled_datetime)
                date_part = localized_dt.strftime("%d %b %Y")
                time_part = localized_dt.strftime("%I:%M %p")
            else:
                date_part = "—"
                time_part = ""

            # Palette
            s = visit.status_id
            if s.is_completed_status:
                pk = "completed"
            elif s.is_reschedule_status:
                pk = "rescheduled"
            elif s.is_scheduled_status:
                pk = "scheduled"
            elif s.is_no_show_status:
                pk = "no_show"
            elif s.is_cancelled_status:
                pk = "cancelled"
            else:
                pk = "default"

            p = self._TIMELINE_PALETTE[pk]
            accent = p["accent"]
            border = p["border"]
            row_bg = p["bg_row"] if idx % 2 == 1 else p["bg_row2"]

            # Visit number — show reschedule iteration badge inline
            iter_val = visit.reschedule_iteration or 0
            visit_num = f"#{idx}"
            num_cell = (
                f"<td style='padding:8px 6px; text-align:center; border-left:4px solid {accent};'>"
                f"<span style='font-size:11px; font-weight:700; color:{accent};'>{visit_num}</span>"
                + (
                    f"<br><span style='font-size:9px; font-weight:700; color:#fff;"
                    f" background:#0d6efd; padding:0 4px; border-radius:3px;'>R{iter_val}</span>"
                    if iter_val > 0 else ""
                )
                + f"</td>"
            )

            # Status pill
            status_pill = (
                f"<span style='display:inline-block; padding:2px 8px; border-radius:20px;"
                f" background:{accent}1a; color:{accent}; font-size:10px; font-weight:700;"
                f" letter-spacing:0.3px; text-transform:uppercase; border:1px solid {border};"
                f" white-space:nowrap;'>"
                f"{escape(s.name or 'Visit')}"
                f"</span>"
            )

            # Feedback: option + note truncated
            feedback_parts = []
            if visit.feedback_option_id and visit.feedback_option_id.name:
                feedback_parts.append(escape(visit.feedback_option_id.name))
            if visit.feedback_note and visit.feedback_note.strip():
                truncated = escape(visit.feedback_note.strip()[:60])
                suffix = "…" if len(visit.feedback_note.strip()) > 60 else ""
                feedback_parts.append(
                    f"<span style='color:#6c757d; font-style:italic;'>{truncated}{suffix}</span>"
                )
            feedback_content = (
                "<br>".join(feedback_parts) if feedback_parts
                else "<span style='color:#ced4da;'>—</span>"
            )

            # Link
            can_open = is_manager or visit.assigned_rm_id.id == self.env.uid
            link_cell_content = (
                f"<a href='/web#id={visit.id}&amp;model=lead.site.visit&amp;view_type=form'"
                f" title='Open visit record'"
                f" style='color:{accent}; font-size:15px; text-decoration:none;'>&#x2197;</a>"
                if can_open
                else "<span style='color:#dee2e6; font-size:13px;'>&#x1F512;</span>"
            )

            # Inquiry cell (only when show_inquiry=True)
            inquiry_cell = ""
            if show_inquiry:
                inquiry_name = escape(visit.inquiry_id.display_name or "—")
                inquiry_cell = (
                    f"<td style='padding:8px 10px; font-size:12px; color:#495057;"
                    f" max-width:140px; overflow:hidden; text-overflow:ellipsis;"
                    f" white-space:nowrap;'>{inquiry_name}</td>"
                )

            td = (
                "padding:8px 10px; font-size:12px; color:#212529;"
                " vertical-align:middle; border-bottom:1px solid #f0f0f0;"
            )

            rows_html += (
                f"<tr style='background:{row_bg};'>"
                f"{num_cell}"
                f"<td style='{td} font-weight:600; white-space:nowrap;'>{date_part}</td>"
                f"<td style='{td} color:#6c757d; white-space:nowrap;'>{time_part}</td>"
                f"<td style='{td}'>{status_pill}</td>"
                f"<td style='{td} font-weight:500;"
                f" max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;'>"
                f"{escape(visit.property_base_id.display_name or '—')}</td>"
                f"<td style='{td} white-space:nowrap;'>"
                f"{escape(visit.assigned_rm_id.name or '—')}</td>"
                f"{inquiry_cell}"
                f"<td style='{td} max-width:200px;'>{feedback_content}</td>"
                f"<td style='{td} text-align:center;'>{link_cell_content}</td>"
                f"</tr>"
            )

        return (
            f"<div style='font-family:inherit;'>"
            # Legend
            f"<div style='margin-bottom:8px; padding:5px 0; border-bottom:1px solid #f0f0f0;'>"
            f"{legend_html}"
            f"</div>"
            # Table — 100 % width, no side margins
            f"<div style='overflow-x:auto; border:1px solid #dee2e6; border-radius:6px;'>"
            f"<table style='width:100%; border-collapse:collapse; font-size:13px;'>"
            f"<thead>{header_row}</thead>"
            f"<tbody>{rows_html}</tbody>"
            f"</table>"
            f"</div>"
            f"</div>"
        )

    def action_open_add_site_visit_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "lead.add.site.visit.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_inquiry_id": self.id,
                "active_id": self.id,
                "active_model": "leads.new",
            },
        }

    def action_open_recommend_property_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "lead.recommend.property.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_inquiry_id": self.id,
                "active_id": self.id,
                "active_model": "leads.new",
            },
        }

    def action_view_site_visits(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Site Visits",
            "res_model": "lead.site.visit",
            "view_mode": "list,form,pivot,graph",
            "domain": [("inquiry_id", "=", self.id)],
            "context": {
                "default_inquiry_id": self.id,
                "default_property_base_id": self.property_base_id.id,
                "default_assigned_rm_id": self.user_id.id,
            },
        }

    def action_view_all_phone_site_visits(self):
        self.ensure_one()
        if not self.phone:
            raise ValidationError("Phone number is required to view overall lead timeline.")

        return {
            "type": "ir.actions.act_window",
            "name": "Overall Lead Timeline",
            "res_model": "lead.site.visit",
            "view_mode": "list,form,pivot,graph",
            "domain": [("inquiry_id.phone", "=", self.phone)],
            "context": {
                "search_default_group_inquiry": 1,
            },
        }

    def action_open_update_latest_visit_wizard(self):
        self.ensure_one()
        if not self.latest_site_visit_id:
            raise ValidationError("No site visit found to update for this inquiry.")

        return {
            "type": "ir.actions.act_window",
            "res_model": "lead.site.visit.quick.update.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_visit_id": self.latest_site_visit_id.id,
                "active_id": self.latest_site_visit_id.id,
                "active_model": "lead.site.visit",
            },
        }
