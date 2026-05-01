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
            rec.latest_site_visit_id = rec.sudo().site_visit_ids[:1]

    @api.depends("site_visit_ids")
    def _compute_site_visit_count(self):
        for rec in self:
            rec.site_visit_count = len(rec.sudo().site_visit_ids)

    @api.depends("phone")
    def _compute_all_phone_site_visit_ids(self):
        # Both queries must use sudo() explicitly.
        #
        # Using a cross-model domain like ("inquiry_id.phone", "=", phone) on a
        # sudo()'d lead.site.visit search is NOT sufficient: Odoo applies the
        # leads.new record rule (user_id = user.id) to the JOIN subquery even
        # when the outer model is queried with sudo().  This silently excludes
        # inquiries owned by other RMs, making the overall timeline show only
        # the current RM's visits.
        #
        # Solution: two separate sudo() queries so each model's record rules are
        # fully bypassed — first resolve all inquiry IDs for the phone, then
        # fetch all visits for those inquiry IDs.
        site_visit_model = self.env["lead.site.visit"].sudo()
        inquiry_model = self.env["leads.new"].sudo()
        for rec in self:
            if not rec.phone:
                rec.all_phone_site_visit_ids = site_visit_model
                continue
            inquiry_ids = inquiry_model.search([("phone", "=", rec.phone)]).ids
            if not inquiry_ids:
                rec.all_phone_site_visit_ids = site_visit_model
                continue
            rec.all_phone_site_visit_ids = site_visit_model.search(
                [("inquiry_id", "in", inquiry_ids)],
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
            # All visit data is fetched via rec.sudo() throughout.
            #
            # Two reasons:
            # 1. Record rules: rule_lead_site_visit_rm_own appends
            #    "assigned_rm_id = user.id" to every lead.site.visit query.
            #    Visits assigned to other RMs (e.g. a manager scheduled the
            #    visit, or inquiry.user_id was blank) would be silently hidden.
            # 2. Model-level ACL: when the Many2many result from
            #    _compute_all_phone_site_visit_ids (fetched with sudo) is
            #    accessed on the non-sudo rec, Odoo reconstructs the recordset
            #    using rec.env (non-sudo).  Subsequent field reads inside
            #    _build_timeline_html then trigger a model-level access check
            #    for lead.site.visit on the calling user, raising AccessError
            #    for users who do not hold the RM group (e.g. test accounts).
            #
            # Using rec_sudo for all visit reads ensures the sudo env flows
            # through to every field access inside _build_timeline_html.
            # _build_timeline_html is still called on rec (not rec_sudo) so
            # that self.env.user.has_group() reflects the actual user.
            rec_sudo = rec.sudo()
            rec.inquiry_timeline_html = rec._build_timeline_html(
                rec_sudo.site_visit_ids,
                show_inquiry=False,
            )
            rec.overall_timeline_html = rec._build_timeline_html(
                rec_sudo.all_phone_site_visit_ids,
                show_inquiry=True,
            )

    # ---------------------------------------------------------------------------
    # Color palette — keyed by status type.
    # accent   = left-bar colour and status text colour
    # bg_row   = row background tint (same for all rows in the chain block)
    # bg_row2  = kept for compatibility but not used for zebra any more
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

    # Lane colours for visit chains (git-graph style connector column).
    # Each distinct reschedule chain gets one colour; singletons get None.
    _CHAIN_LANE_COLORS = [
        "#4361ee",  # indigo
        "#f72585",  # magenta
        "#2ec4b6",  # teal
        "#fb8500",  # amber
        "#7209b7",  # purple
        "#e63946",  # crimson
        "#457b9d",  # steel-blue
        "#06d6a0",  # mint
    ]

    def _build_timeline_html(self, visits, show_inquiry):
        """Build the HTML table for the visit timeline.

        Chain detection uses the previous_visit_id directed graph, not
        root_visit_id.  This is robust for visits created before root_visit_id
        existed (where it is NULL) and for partially-migrated data.

        Algorithm:
        1.  Build successor_of: old_visit_id → newer_visit (who replaced whom).
        2.  Find chain_starts: visits with no predecessor in the current set.
        3.  Walk each chain oldest→newest; split at hard terminals
            (Completed, No-Show, dead-end Cancelled).
        4.  Reverse each sub-chain for display (newest first), sort chains by
            most-recently-active date.

        Banners appear only for multi-visit chains (singletons rely on status
        pills + colours).  Banners show only rescheduling history — not the
        outcome, which the status pill already communicates.
        """
        self.ensure_one()

        if not visits:
            return (
                "<div style='padding:12px 16px; border:1px dashed #ced4da; border-radius:6px;"
                " color:#6c757d; font-size:13px;'>"
                "No visit events recorded yet."
                "</div>"
            )

        is_manager = self.env.user.has_group("leads.group_lead_score_manager")
        by_id = {v.id: v for v in visits}

        # ── Step 1: Build directed graph via previous_visit_id ────────────────
        # previous_visit_id points to the OLDER visit that was superseded by this
        # one.  This graph is reliable even for data where root_visit_id was not
        # backfilled (e.g. visits created before that field existed).
        #
        # successor_of = old_visit_id → newer_visit that replaced it.
        #
        # For colour / badge / split logic we do NOT use "is in pointed_to" as
        # the forwarding-node test.  The add-visit wizard always pre-fills
        # previous_visit_id with the latest visit — including after a genuine
        # cancellation.  Instead, we test visit.status_id.code == 'superseded':
        # that status is written only by the proper reschedule write() flow and
        # unambiguously marks a midpoint in a chain.
        successor_of = {}
        for v in visits:
            prev_id = v.previous_visit_id.id if v.previous_visit_id else None
            if prev_id and prev_id in by_id:
                successor_of[prev_id] = v

        # ── Step 2: Find chain starts (oldest visit in each thread) ───────────
        # A chain start = visit whose predecessor is NOT present in this set.
        # Iterating oldest-first (reversed from newest-first ORM order) keeps
        # the walk order stable.
        chain_starts = [
            v for v in reversed(list(visits))
            if not (v.previous_visit_id and v.previous_visit_id.id in by_id)
        ]

        # ── Step 3: Walk chains oldest→newest, split at hard terminals ─────────
        # Completed and No-Show always close an appointment attempt.
        # A Cancelled visit closes an attempt ONLY when it has no successor in the
        # current set (i.e. it is a genuine cancellation, not a superseded/
        # forwarding node — those have is_cancelled_status=True in seed data but
        # are midpoints, not dead ends).
        raw_sub_chains = []
        for start in chain_starts:
            current_sub = []
            node = start
            while node is not None:
                current_sub.append(node)
                s = node.status_id
                is_hard_terminal = (
                    s.is_completed_status
                    or s.is_no_show_status
                    # cancelled = hard terminal UNLESS this is a superseded/forwarding
                    # slot from a proper reschedule (code='superseded').  All other
                    # cancel-family statuses (cancelling, cancelled) close the chain.
                    or (s.is_cancelled_status and s.code != 'superseded')
                )
                if is_hard_terminal:
                    raw_sub_chains.append(current_sub)
                    current_sub = []
                node = successor_of.get(node.id)
            if current_sub:
                raw_sub_chains.append(current_sub)

        # Reverse each sub-chain: built oldest→newest, display newest→oldest
        raw_sub_chains = [list(reversed(sc)) for sc in raw_sub_chains]

        # Sort: most-recently-active sub-chain first
        def _newest_dt(chain):
            return max(
                (v.scheduled_datetime for v in chain if v.scheduled_datetime),
                default=None,
            )
        raw_sub_chains.sort(key=_newest_dt, reverse=True)

        # ── Step 4: Per-attempt metadata ──────────────────────────────────────
        num_attempts = len(raw_sub_chains)
        attempt_meta = {}
        for idx, sub_chain in enumerate(raw_sub_chains):
            original = sub_chain[-1]            # oldest = first booked date for this attempt
            reschedule_count = len(sub_chain) - 1
            attempt_meta[idx] = {
                "visits_desc": sub_chain,
                "original": original,
                "reschedule_count": reschedule_count,
            }

        # ── Step 5: Assign lane colours (one per multi-visit chain) ───────────
        chain_lane_color = {}
        color_idx = 0
        for idx in range(num_attempts):
            if attempt_meta[idx]["reschedule_count"] > 0:
                chain_lane_color[idx] = self._CHAIN_LANE_COLORS[
                    color_idx % len(self._CHAIN_LANE_COLORS)
                ]
                color_idx += 1
            else:
                chain_lane_color[idx] = None    # singleton → neutral dot, no line

        # ── Step 6: Flatten to display rows ──────────────────────────────────
        display_rows = []
        for idx in range(num_attempts):
            visits_desc = attempt_meta[idx]["visits_desc"]
            n = len(visits_desc)
            for i, v in enumerate(visits_desc):
                pos = (
                    "singleton" if n == 1 else
                    "top" if i == 0 else
                    "bottom" if i == n - 1 else
                    "middle"
                )
                display_rows.append((v, idx, pos))

        # ── Legend strip ──────────────────────────────────────────────────────
        legend_html = "".join(
            f"<span style='display:inline-flex; align-items:center; gap:5px;"
            f" margin-right:14px; font-size:11px; color:#495057;'>"
            f"<span style='width:10px; height:10px; border-radius:50%; background:{col};"
            f" flex-shrink:0;'></span>{label}</span>"
            for col, label in [
                ("#198754", "Completed"),
                ("#fd7e14", "Scheduled"),
                ("#0d6efd", "Rescheduled"),
                ("#dc3545", "No Show"),
                ("#6c757d", "Cancelled"),
            ]
        )
        if any(chain_lane_color[i] for i in range(num_attempts)):
            legend_html += (
                f"<span style='margin-left:12px; padding-left:12px;"
                f" border-left:1px solid #dee2e6; display:inline-flex;"
                f" align-items:center; gap:5px; font-size:11px; color:#6c757d;'>"
                f"<span style='width:3px; height:18px; background:#4361ee;"
                f" border-radius:2px; display:inline-block;'></span>"
                f"Coloured line = same appointment thread"
                f"</span>"
            )

        # ── Column headers ────────────────────────────────────────────────────
        chs = (
            "padding:5px 10px; font-size:10px; font-weight:700; color:#6c757d;"
            " text-transform:uppercase; letter-spacing:0.4px; white-space:nowrap;"
        )
        header_row = (
            f"<tr style='border-bottom:2px solid #dee2e6; background:#f8f9fa;'>"
            f"<td style='{chs} width:36px; text-align:center;' title='Chronological visit number: #1 = first visit'>#</td>"
            f"<td style='width:20px; padding:0;'></td>"
            f"<td style='{chs} width:100px;'>Date</td>"
            f"<td style='{chs} width:80px;'>Time</td>"
            f"<td style='{chs} width:110px;'>Status</td>"
            f"<td style='{chs}'>Property</td>"
            f"<td style='{chs} width:130px;'>RM</td>"
            + (f"<td style='{chs}'>Inquiry</td>" if show_inquiry else "")
            + f"<td style='{chs}'>Feedback</td>"
            f"<td style='{chs} width:40px;'></td>"
            f"</tr>"
        )

        # ── Chronological visit numbers ───────────────────────────────────────
        # #1 = the earliest scheduled visit, #N = the most recent.
        # This lets the RM read "first visit was #1 on 04 Apr, we are now on #4."
        # Tiebreaker on id keeps numbering stable for same-day visits.
        _sorted_asc = sorted(
            [v for v, _idx, _pos in display_rows],
            key=lambda v: (v.scheduled_datetime or fields.Datetime.min, v.id),
        )
        _chrono_num = {v.id: i + 1 for i, v in enumerate(_sorted_asc)}

        # ── Rows ──────────────────────────────────────────────────────────────
        rows_html = ""
        display_num = 0
        total_cols = 9 + (1 if show_inquiry else 0)

        for visit, attempt_idx, connector_pos in display_rows:
            display_num += 1
            visit_num = _chrono_num[visit.id]
            lane_color = chain_lane_color[attempt_idx]
            meta = attempt_meta[attempt_idx]

            # ── Chain banner — only for multi-visit chains, only at the top ────
            # Shows only what the status pill cannot say: how many times the
            # booking was moved and what the original date was.
            # Single-visit (singleton) entries get no banner.
            if connector_pos == "top" and lane_color:
                rc = meta["reschedule_count"]
                orig_visit = meta["original"]
                orig_dt = (
                    fields.Datetime.context_timestamp(self, orig_visit.scheduled_datetime)
                    if orig_visit.scheduled_datetime else None
                )
                orig_str = orig_dt.strftime("%d %b %Y") if orig_dt else "—"
                rc_text = "Rescheduled once" if rc == 1 else f"Rescheduled {rc}\u00d7"
                lc = lane_color
                rows_html += (
                    f"<tr style='background:{lc}10;'>"
                    f"<td colspan='{total_cols}'"
                    f" style='padding:5px 10px; border-top:2px solid {lc}35;"
                    f" border-bottom:1px solid {lc}25;'>"
                    f"<span style='display:inline-flex; align-items:center; gap:8px;'>"
                    f"<span style='width:3px; height:14px; background:{lc};"
                    f" border-radius:2px; display:inline-block; flex-shrink:0;'></span>"
                    f"<span style='font-size:11px; color:#495057;'>{rc_text}</span>"
                    f"<span style='font-size:10px; color:#adb5bd;'>&middot;</span>"
                    f"<span style='font-size:11px; color:#6c757d;'>"
                    f"Originally booked for {orig_str}</span>"
                    f"</span></td></tr>"
                )

            # ── Date / time ───────────────────────────────────────────────────
            if visit.scheduled_datetime:
                localized_dt = fields.Datetime.context_timestamp(self, visit.scheduled_datetime)
                date_part = localized_dt.strftime("%d %b %Y")
                time_part = localized_dt.strftime("%I:%M %p")
            else:
                date_part = "—"
                time_part = ""

            # ── Status palette ────────────────────────────────────────────────
            # Visits with code='superseded' are mid-chain forwarding slots from the
            # proper reschedule write() flow.  They carry is_cancelled_status=True in
            # the seed to block further edits, but visually they are "rescheduled"
            # (old booking date moved forward).  All other cancelled-family statuses
            # (cancelling, cancelled) keep their own grey colour.
            s = visit.status_id
            if s.code == 'superseded':
                pk = "rescheduled"
            elif s.is_completed_status:
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
            row_bg = f"{lane_color}0a" if lane_color else p["bg_row"]

            # ── Visit number cell ─────────────────────────────────────────────
            # "↻ moved" badge: only on code='superseded' nodes — the old booking
            # slot that was moved forward by the proper reschedule flow.
            badge_html = ""
            if visit.status_id.code == 'superseded' and lane_color:
                badge_html = (
                    f"<br><span style='font-size:9px; color:{lane_color};"
                    f" white-space:nowrap;'>&#x21BB; moved</span>"
                )
            num_cell = (
                f"<td style='padding:8px 6px; text-align:center;"
                f" border-left:4px solid {accent}; vertical-align:middle;'>"
                f"<span style='font-size:11px; font-weight:700; color:{accent};'>"
                f"#{visit_num}</span>"
                f"{badge_html}"
                f"</td>"
            )

            # ── Connector column ──────────────────────────────────────────────
            # Line: CSS linear-gradient on the <td> background.
            # The <td> spans the full row height automatically — no height tricks.
            # The dot (status colour) sits at the gradient midpoint, making the
            # spine look continuous across consecutive rows.
            if lane_color:
                show_top = connector_pos in ("middle", "bottom")
                show_bottom = connector_pos in ("middle", "top")
                if show_top and show_bottom:
                    td_bg = lane_color
                elif show_top:
                    td_bg = f"linear-gradient(to bottom, {lane_color} 50%, transparent 50%)"
                elif show_bottom:
                    td_bg = f"linear-gradient(to bottom, transparent 50%, {lane_color} 50%)"
                else:
                    td_bg = "transparent"
                connector_cell = (
                    f"<td style='padding:0; width:20px; text-align:center;"
                    f" vertical-align:middle; background:{td_bg};'>"
                    f"<span style='display:inline-block; width:13px; height:13px;"
                    f" border-radius:50%; background:{accent};"
                    f" border:2.5px solid white;"
                    f" box-shadow:0 0 0 2px {lane_color}55;'></span>"
                    f"</td>"
                )
            else:
                connector_cell = (
                    f"<td style='padding:0; width:20px; text-align:center;"
                    f" vertical-align:middle;'>"
                    f"<span style='display:inline-block; width:8px; height:8px;"
                    f" border-radius:50%; background:#ced4da;'></span>"
                    f"</td>"
                )

            # ── Status pill ───────────────────────────────────────────────────
            status_pill = (
                f"<span style='display:inline-block; padding:2px 8px; border-radius:20px;"
                f" background:{accent}1a; color:{accent}; font-size:10px; font-weight:700;"
                f" letter-spacing:0.3px; text-transform:uppercase; border:1px solid {border};"
                f" white-space:nowrap;'>"
                f"{escape(s.name or 'Visit')}"
                f"</span>"
            )

            # ── Feedback ──────────────────────────────────────────────────────
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

            # ── Link arrow ────────────────────────────────────────────────────
            can_open = is_manager or visit.assigned_rm_id.id == self.env.uid
            link_cell_content = (
                f"<a href='/web#id={visit.id}&amp;model=lead.site.visit&amp;view_type=form'"
                f" title='Open visit record'"
                f" style='color:{accent}; font-size:15px; text-decoration:none;'>&#x2197;</a>"
                if can_open
                else "<span style='color:#dee2e6; font-size:13px;'>&#x1F512;</span>"
            )

            # ── Inquiry cell (overall timeline only) ──────────────────────────
            inquiry_cell = ""
            if show_inquiry:
                inquiry_name = escape(visit.inquiry_id.display_name or "—")
                inquiry_cell = (
                    f"<td style='padding:8px 10px; font-size:12px; color:#495057;"
                    f" max-width:140px; overflow:hidden; text-overflow:ellipsis;"
                    f" white-space:nowrap; vertical-align:middle;'>{inquiry_name}</td>"
                )

            td = (
                "padding:8px 10px; font-size:12px; color:#212529;"
                " vertical-align:middle; border-bottom:1px solid #f0f0f0;"
            )

            rows_html += (
                f"<tr style='background:{row_bg};'>"
                f"{num_cell}"
                f"{connector_cell}"
                f"<td style='{td} font-weight:600; white-space:nowrap;'>{date_part}</td>"
                f"<td style='{td} color:#6c757d; white-space:nowrap;'>{time_part}</td>"
                f"<td style='{td}'>{status_pill}</td>"
                f"<td style='{td} font-weight:500;"
                f" max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;'>"
                f"{escape(visit.property_base_id.sudo().display_name or '—')}</td>"
                f"<td style='{td} white-space:nowrap;'>"
                f"{escape(visit.assigned_rm_id.name or '—')}</td>"
                f"{inquiry_cell}"
                f"<td style='{td} max-width:200px;'>{feedback_content}</td>"
                f"<td style='{td} text-align:center;'>{link_cell_content}</td>"
                f"</tr>"
            )

        return (
            f"<div style='font-family:inherit;'>"
            f"<div style='margin-bottom:8px; padding:5px 0; border-bottom:1px solid #f0f0f0;"
            f" display:flex; align-items:center; flex-wrap:wrap; gap:4px;'>"
            f"{legend_html}"
            f"</div>"
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
