import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError


# ---------------------------------------------------------------------------
# Module : leads
# Model  : lead.site.visit.status / lead.site.visit.feedback.option / lead.site.visit
# Purpose: Configurable site-visit metadata and visit event history per inquiry.
# Owner  : Cleardeals Tech
# ---------------------------------------------------------------------------


class LeadSiteVisitStatus(models.Model):
    _name = "lead.site.visit.status"
    _description = "Lead Site Visit Status"
    _order = "sequence, id"

    _code_uniq = models.Constraint(
        "UNIQUE(code)",
        message="Site visit status code must be unique.",
    )

    name = fields.Char(required=True, index=True)
    code = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True, index=True)

    is_terminal = fields.Boolean(default=False)
    is_scheduled_status = fields.Boolean(default=False)
    is_reschedule_status = fields.Boolean(default=False)
    is_completed_status = fields.Boolean(default=False)
    is_cancelled_status = fields.Boolean(default=False)
    is_no_show_status = fields.Boolean(default=False)

    status_type = fields.Selection(
        [
            ("scheduled", "Scheduled"),
            ("rescheduled", "Rescheduled"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
            ("no_show", "No Show"),
            ("custom", "Custom"),
        ],
        string="Status Type",
        compute="_compute_status_type",
        inverse="_inverse_status_type",
        store=False,
    )

    allow_feedback_note = fields.Boolean(default=True)
    color = fields.Integer(default=0)

    @api.depends(
        "is_scheduled_status",
        "is_reschedule_status",
        "is_completed_status",
        "is_cancelled_status",
        "is_no_show_status",
    )
    def _compute_status_type(self):
        for rec in self:
            if rec.is_scheduled_status:
                rec.status_type = "scheduled"
            elif rec.is_reschedule_status:
                rec.status_type = "rescheduled"
            elif rec.is_completed_status:
                rec.status_type = "completed"
            elif rec.is_cancelled_status:
                rec.status_type = "cancelled"
            elif rec.is_no_show_status:
                rec.status_type = "no_show"
            else:
                rec.status_type = "custom"

    def _inverse_status_type(self):
        for rec in self:
            rec.is_scheduled_status = rec.status_type == "scheduled"
            rec.is_reschedule_status = rec.status_type == "rescheduled"
            rec.is_completed_status = rec.status_type == "completed"
            rec.is_cancelled_status = rec.status_type == "cancelled"
            rec.is_no_show_status = rec.status_type == "no_show"

    @api.constrains(
        "is_scheduled_status",
        "is_reschedule_status",
        "is_completed_status",
        "is_cancelled_status",
        "is_no_show_status",
    )
    def _check_single_status_type_flag(self):
        for rec in self:
            type_flags = [
                rec.is_scheduled_status,
                rec.is_reschedule_status,
                rec.is_completed_status,
                rec.is_cancelled_status,
                rec.is_no_show_status,
            ]
            if sum(bool(flag) for flag in type_flags) > 1:
                raise ValidationError(
                    "Only one status type can be selected per status.",
                )

    def write(self, vals):
        if "code" in vals:
            for rec in self:
                if rec.code and vals["code"] != rec.code:
                    raise ValidationError(
                        "Status code is immutable once created.",
                    )
        return super().write(vals)


class LeadSiteVisitFeedbackOption(models.Model):
    _name = "lead.site.visit.feedback.option"
    _description = "Lead Site Visit Feedback Option"
    _order = "status_id, sequence, id"

    _code_uniq = models.Constraint(
        "UNIQUE(code)",
        message="Site visit feedback code must be globally unique.",
    )

    _status_code_uniq = models.Constraint(
        "UNIQUE(status_id, code)",
        message="Feedback code must be unique inside a status.",
    )

    name = fields.Char(required=True, index=True)
    code = fields.Char(required=True, index=True)
    status_id = fields.Many2one(
        "lead.site.visit.status",
        required=True,
        ondelete="restrict",
        index=True,
    )

    category = fields.Selection(
        [
            ("intent", "Intent"),
            ("blocker", "Blocker"),
            ("property", "Property"),
            ("pricing", "Pricing"),
            ("operations", "Operations"),
            ("other", "Other"),
        ],
        default="other",
        required=True,
        index=True,
    )

    management_signal = fields.Selection(
        [
            ("positive_intent", "Positive Intent"),
            ("risk", "Risk"),
            ("loss_reason", "Loss Reason"),
            ("neutral", "Neutral"),
        ],
        default="neutral",
        required=True,
        index=True,
    )

    requires_note = fields.Boolean(default=False)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("code") and vals.get("name"):
                vals["code"] = re.sub(
                    r"[^a-z0-9]+", "_", vals["name"].strip().lower()
                ).strip("_")
        return super().create(vals_list)

    def write(self, vals):
        if "code" in vals:
            for rec in self:
                if rec.code and vals["code"] != rec.code:
                    raise ValidationError(
                        "Feedback code is immutable once created.",
                    )
        return super().write(vals)


class LeadSiteVisit(models.Model):
    _name = "lead.site.visit"
    _description = "Lead Site Visit"
    _order = "scheduled_datetime desc, id desc"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(compute="_compute_name", store=True)

    inquiry_id = fields.Many2one(
        "leads.new",
        string="Inquiry",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )

    property_base_id = fields.Many2one(
        "property.base",
        string="Property",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
        context={"search_all_properties_for_lead": True},
    )

    assigned_rm_id = fields.Many2one(
        "res.users",
        string="Assigned RM",
        index=True,
        tracking=True,
    )

    inquiry_type = fields.Selection(
        related="inquiry_id.inquiry_type",
        store=True,
        readonly=True,
    )

    inquiry_phone = fields.Char(
        related="inquiry_id.phone",
        string="Lead Phone",
        store=True,
        readonly=True,
        index=True,
    )

    scheduled_datetime = fields.Datetime(
        required=True,
        index=True,
        tracking=True,
    )

    scheduled_date = fields.Date(
        compute="_compute_scheduled_date",
        store=True,
        readonly=True,
        index=True,
    )

    status_id = fields.Many2one(
        "lead.site.visit.status",
        string="Status",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
        domain=[("active", "=", True)],
    )

    status_is_scheduled = fields.Boolean(
        related="status_id.is_scheduled_status",
        readonly=True,
        store=False,
    )

    status_is_rescheduled = fields.Boolean(
        related="status_id.is_reschedule_status",
        readonly=True,
        store=False,
    )

    status_is_completed = fields.Boolean(
        related="status_id.is_completed_status",
        readonly=True,
        store=False,
    )

    status_is_cancelled = fields.Boolean(
        related="status_id.is_cancelled_status",
        readonly=True,
        store=False,
    )

    status_is_no_show = fields.Boolean(
        related="status_id.is_no_show_status",
        readonly=True,
        store=False,
    )

    status_is_terminal = fields.Boolean(
        related="status_id.is_terminal",
        readonly=True,
        store=False,
    )

    feedback_option_id = fields.Many2one(
        "lead.site.visit.feedback.option",
        string="Feedback",
        ondelete="restrict",
        tracking=True,
        domain="[('status_id', '=', status_id), ('active', '=', True)]",
    )

    feedback_note = fields.Text(tracking=True)

    previous_visit_id = fields.Many2one(
        "lead.site.visit",
        string="Previous Visit",
        ondelete="set null",
        index=True,
    )

    root_visit_id = fields.Many2one(
        "lead.site.visit",
        string="Root Visit",
        ondelete="set null",
        index=True,
    )

    reschedule_iteration = fields.Integer(default=0, index=True)

    chain_reschedule_count = fields.Integer(
        compute="_compute_chain_reschedule_count",
        store=False,
    )

    status_changed_on = fields.Datetime(
        default=fields.Datetime.now,
        required=True,
        index=True,
    )

    active = fields.Boolean(default=True, index=True)

    is_overdue_open = fields.Boolean(
        string="Overdue",
        compute="_compute_is_overdue_open",
        store=False,
    )

    total_inquiry_visit_count = fields.Integer(
        string="Total Visits for Lead",
        compute="_compute_total_inquiry_visit_count",
        store=False,
    )

    # Calendar color — computed automatically from status_type + overdue state so
    # the calendar is always semantically color-coded regardless of admin setup.
    # Palette (Odoo $o-colors-complete, index 0-based):
    #   0  #a2a2a2  grey         → custom / unknown
    #   1  #ee2d2d  red          → cancelled / no-show
    #   2  #dc8534  orange       → rescheduled (upcoming)
    #   3  #e8bb1d  yellow       → overdue (scheduled/rescheduled past date)
    #   4  #5794dd  light blue   → scheduled (upcoming)
    #  10  #61c36e  green        → completed
    color = fields.Integer(
        string="Calendar Color",
        compute="_compute_color",
        store=False,
    )

    @api.depends(
        "status_id.status_type",
        "status_id.is_scheduled_status",
        "status_id.is_reschedule_status",
        "status_id.is_completed_status",
        "status_id.is_cancelled_status",
        "status_id.is_no_show_status",
        "scheduled_datetime",
    )
    def _compute_color(self):
        now = fields.Datetime.now()
        for rec in self:
            st = rec.status_id
            if not st:
                rec.color = 0
                continue
            is_open = st.is_scheduled_status or st.is_reschedule_status
            is_overdue = is_open and bool(rec.scheduled_datetime) and rec.scheduled_datetime < now
            if is_overdue:
                rec.color = 3          # yellow  — past date, feedback pending
            elif st.is_completed_status:
                rec.color = 10         # green   — done
            elif st.is_cancelled_status or st.is_no_show_status:
                rec.color = 1          # red     — terminated
            elif st.is_reschedule_status:
                rec.color = 2          # orange  — rescheduled, attention needed
            elif st.is_scheduled_status:
                rec.color = 4          # blue    — upcoming, neutral
            else:
                rec.color = 0          # grey    — custom / unknown

    @api.depends("inquiry_id", "scheduled_datetime", "status_id")
    def _compute_name(self):
        for rec in self:
            inquiry_name = rec.inquiry_id.display_name or "Inquiry"
            status_name = rec.status_id.name or "Visit"
            when = fields.Datetime.to_string(rec.scheduled_datetime) if rec.scheduled_datetime else "No Date"
            rec.name = f"{inquiry_name} | {status_name} | {when}"

    @api.depends("scheduled_datetime")
    def _compute_scheduled_date(self):
        for rec in self:
            rec.scheduled_date = rec.scheduled_datetime.date() if rec.scheduled_datetime else False

    @api.depends("root_visit_id", "reschedule_iteration")
    def _compute_chain_reschedule_count(self):
        for rec in self:
            root = rec.root_visit_id or rec
            rec.chain_reschedule_count = self.search_count(
                [
                    ("root_visit_id", "=", root.id),
                    ("reschedule_iteration", ">", 0),
                ],
            )

    @api.depends("scheduled_datetime", "status_id.is_scheduled_status", "status_id.is_reschedule_status")
    def _compute_is_overdue_open(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.is_overdue_open = (
                bool(rec.scheduled_datetime)
                and rec.scheduled_datetime < now
                and (rec.status_id.is_scheduled_status or rec.status_id.is_reschedule_status)
            )

    @api.depends("inquiry_id")
    def _compute_total_inquiry_visit_count(self):
        inquiry_ids = self.mapped("inquiry_id").ids
        if not inquiry_ids:
            self.total_inquiry_visit_count = 0
            return
        data = self.env["lead.site.visit"].read_group(
            [("inquiry_id", "in", inquiry_ids)],
            ["inquiry_id"],
            ["inquiry_id"],
        )
        counts = {d["inquiry_id"][0]: d["inquiry_id_count"] for d in data}
        for rec in self:
            rec.total_inquiry_visit_count = counts.get(rec.inquiry_id.id, 0) if rec.inquiry_id else 0

    @api.constrains("status_id", "feedback_option_id")
    def _check_feedback_status_match(self):
        for rec in self:
            # Terminal visits (incl. Rescheduled/Superseded) hold the reschedule-reason
            # feedback that was valid at the moment of transition — skip the check.
            if rec.status_id and rec.status_id.is_terminal:
                continue
            if rec.feedback_option_id and rec.feedback_option_id.status_id != rec.status_id:
                raise ValidationError(
                    "Selected feedback is not valid for the chosen status.",
                )

    @api.constrains("status_id", "previous_visit_id", "inquiry_id")
    def _check_reschedule_lineage(self):
        for rec in self:
            if rec.previous_visit_id and rec.previous_visit_id.inquiry_id != rec.inquiry_id:
                raise ValidationError(
                    "Previous visit must belong to the same inquiry.",
                )

            if rec.status_id.is_reschedule_status and not rec.previous_visit_id:
                raise ValidationError(
                    "Rescheduled visits require a previous visit reference.",
                )

    @api.constrains("feedback_option_id", "feedback_note")
    def _check_feedback_note_requirement(self):
        for rec in self:
            if rec.feedback_option_id and rec.feedback_option_id.requires_note and not (rec.feedback_note or "").strip():
                raise ValidationError(
                    "Feedback note is required for the selected feedback option.",
                )

    @api.constrains("inquiry_id", "status_id")
    def _check_no_concurrent_active_visit(self):
        # Bypass: reschedule flow creates the new visit before closing the old one.
        # The context flag prevents a false positive during that atomic operation.
        if self.env.context.get("skip_active_visit_check"):
            return
        for rec in self:
            # Terminal visits are closed — no conflict possible.
            if rec.status_id.is_terminal:
                continue
            other = self.search(
                [
                    ("inquiry_id", "=", rec.inquiry_id.id),
                    ("id", "!=", rec.id),
                    ("status_id.is_terminal", "=", False),
                ],
                limit=1,
            )
            if other:
                raise ValidationError(
                    f"This inquiry already has an active visit ({other.name}). "
                    "Update or close it before creating a new one."
                )

    @api.model_create_multi
    def create(self, vals_list):
        normalized_vals_list = []
        for vals in vals_list:
            vals = dict(vals)

            inquiry = self.env["leads.new"].browse(vals.get("inquiry_id"))
            if not inquiry:
                raise ValidationError("Inquiry is required for site visit creation.")

            if not vals.get("property_base_id"):
                vals["property_base_id"] = inquiry.property_base_id.id

            if not vals.get("property_base_id"):
                raise ValidationError(
                    "Property is required on inquiry before creating a site visit.",
                )

            if not vals.get("assigned_rm_id"):
                vals["assigned_rm_id"] = inquiry.user_id.id

            status = self.env["lead.site.visit.status"].browse(vals.get("status_id"))
            if status and status.is_reschedule_status and not vals.get("previous_visit_id"):
                latest = inquiry.site_visit_ids[:1]
                if latest:
                    vals["previous_visit_id"] = latest.id

            if vals.get("previous_visit_id"):
                previous_visit = self.browse(vals["previous_visit_id"])
                vals["root_visit_id"] = previous_visit.root_visit_id.id or previous_visit.id
                vals["reschedule_iteration"] = (previous_visit.reschedule_iteration or 0) + 1

            normalized_vals_list.append(vals)

        records = super().create(normalized_vals_list)

        for rec in records.filtered(lambda r: not r.root_visit_id):
            rec.root_visit_id = rec.id

        records._sync_inquiry_snapshot()

        return records

    def _prepare_inquiry_snapshot_vals(self):
        self.ensure_one()

        vals = {
            "site_visit_date": self.scheduled_datetime,
        }

        s = self.status_id
        if s.is_completed_status:
            vals["current_status"] = "site_visit_done"
        elif s.is_scheduled_status or s.is_reschedule_status:
            vals["current_status"] = "site_visit_scheduled"
        # Cancelled / no-show: leave current_status on leads.new unchanged.
        # There is no matching selection value in leads.new.current_status for
        # these states; the APIs read from lead.site.visit directly.  The UI
        # status badge will remain at the last known scheduled/completed value,
        # which is acceptable — the RM can see the true state on the visit form.

        return vals

    def _sync_inquiry_snapshot(self):
        for rec in self:
            if not rec.inquiry_id:
                continue
            rec.inquiry_id.sudo().write(rec._prepare_inquiry_snapshot_vals())

    def write(self, vals):
        vals = dict(vals)

        # Guard: terminal visits are immutable for status changes.
        # The reschedule flow bypasses this via skip_terminal_write context.
        if not self.env.context.get("skip_terminal_write") and "status_id" in vals:
            for rec in self:
                if rec.status_id.is_terminal:
                    raise ValidationError(
                        f"'{rec.status_id.name}' is a closed visit and cannot be updated. "
                        "Create a new visit from the inquiry if another appointment is needed."
                    )

        new_status = self.env["lead.site.visit.status"].browse(vals.get("status_id")) if vals.get("status_id") else False

        if new_status and new_status.is_reschedule_status:
            if "scheduled_datetime" not in vals:
                raise ValidationError(
                    "Set a new schedule date and time while rescheduling.",
                )

            # Search with active_test=False so the system-only Rescheduled
            # (code=superseded, active=False) status is found regardless of
            # the active field filter that defaults to True on all searches.
            superseded_status = self.env["lead.site.visit.status"].with_context(active_test=False).search(
                [("code", "=", "superseded")], limit=1
            )
            scheduled_status = self.env["lead.site.visit.status"].search(
                [("code", "=", "scheduled"), ("active", "=", True)], limit=1
            )
            new_visit_status = scheduled_status if scheduled_status else new_status

            for rec in self:
                # skip_active_visit_check: the old visit is still non-terminal at
                # this point; suppress the concurrent-visit guard so the new
                # scheduled visit can be inserted before we close the old one.
                self.with_context(skip_active_visit_check=True).create(
                    {
                        "inquiry_id": rec.inquiry_id.id,
                        "property_base_id": vals.get("property_base_id") or rec.property_base_id.id,
                        "assigned_rm_id": vals.get("assigned_rm_id") or rec.assigned_rm_id.id,
                        "scheduled_datetime": vals["scheduled_datetime"],
                        "status_id": new_visit_status.id,
                        "previous_visit_id": rec.id,
                        "active": vals.get("active", rec.active),
                    }
                )
                # Feedback is the reason for rescheduling — store it on
                # the old (Rescheduled/superseded) visit, not the fresh scheduled one.
                # super() bypasses our terminal-write guard — correct here since
                # we are the ones closing the old visit atomically.
                old_visit_vals = {"status_changed_on": fields.Datetime.now()}
                if superseded_status:
                    old_visit_vals["status_id"] = superseded_status.id
                if vals.get("feedback_option_id"):
                    old_visit_vals["feedback_option_id"] = vals["feedback_option_id"]
                if vals.get("feedback_note"):
                    old_visit_vals["feedback_note"] = vals["feedback_note"]
                super(LeadSiteVisit, rec).write(old_visit_vals)
            return True

        if "status_id" in vals and "status_changed_on" not in vals:
            vals["status_changed_on"] = fields.Datetime.now()

        res = super().write(vals)

        for rec in self:
            if rec.status_id.is_reschedule_status and not rec.previous_visit_id:
                raise ValidationError(
                    "Rescheduled visits require a previous visit reference.",
                )

        self._sync_inquiry_snapshot()

        return res

    def action_open_quick_update_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "lead.site.visit.quick.update.wizard",
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
            "context": {
                "default_visit_id": self.id,
                "active_id": self.id,
                "active_model": "lead.site.visit",
            },
        }

    def action_open_cancel_wizard(self):
        self.ensure_one()
        cancel_status = self.env["lead.site.visit.status"].search(
            [("code", "=", "cancelling"), ("active", "=", True)], limit=1
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "lead.site.visit.quick.update.wizard",
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
            "context": {
                "default_visit_id": self.id,
                "default_status_id": cancel_status.id if cancel_status else False,
                "active_id": self.id,
                "active_model": "lead.site.visit",
            },
        }

    def action_view_inquiry_visits(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Visits for this Lead",
            "res_model": "lead.site.visit",
            "view_mode": "list,form",
            "domain": [("inquiry_id", "=", self.inquiry_id.id)],
            "context": {},
        }

    def action_view_inquiry(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "leads.new",
            "res_id": self.inquiry_id.id,
            "view_mode": "form",
            "target": "current",
        }
