from odoo import api, fields, models
from odoo.exceptions import ValidationError


# ---------------------------------------------------------------------------
# Module : leads
# Model  : lead.add.site.visit.wizard
# Purpose: Popup flow for adding a new site-visit event to an inquiry.
# Owner  : Cleardeals Tech
# ---------------------------------------------------------------------------


class LeadAddSiteVisitWizard(models.TransientModel):
    _name = "lead.add.site.visit.wizard"
    _description = "Add Site Visit Wizard"

    inquiry_id = fields.Many2one(
        "leads.new",
        required=True,
        readonly=True,
    )

    property_base_id = fields.Many2one(
        "property.base",
        string="Property",
        readonly=True,
    )

    assigned_rm_id = fields.Many2one(
        "res.users",
        string="Assigned RM",
    )

    scheduled_datetime = fields.Datetime(required=True)

    status_id = fields.Many2one(
        "lead.site.visit.status",
        string="Status",
        required=True,
        domain=[("active", "=", True)],
    )

    feedback_option_id = fields.Many2one(
        "lead.site.visit.feedback.option",
        string="Feedback",
        domain="[('status_id', '=', status_id), ('active', '=', True)]",
    )

    feedback_note = fields.Text()

    previous_visit_id = fields.Many2one(
        "lead.site.visit",
        string="Previous Visit",
        domain="[('inquiry_id', '=', inquiry_id)]",
    )

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)

        inquiry_id = vals.get("inquiry_id") or self.env.context.get("default_inquiry_id")
        if not inquiry_id and self.env.context.get("active_model") == "leads.new":
            inquiry_id = self.env.context.get("active_id")

        if not inquiry_id:
            return vals

        inquiry = self.env["leads.new"].browse(inquiry_id)
        vals["inquiry_id"] = inquiry.id
        vals["property_base_id"] = inquiry.property_base_id.id
        vals["assigned_rm_id"] = inquiry.user_id.id

        # Only carry the previous_visit link when the latest visit is still
        # active.  A terminal visit (completed / cancelled / no-show) closes
        # one appointment attempt; the new booking should start a fresh chain.
        latest = inquiry.latest_site_visit_id
        if latest and not latest.status_id.is_terminal:
            vals["previous_visit_id"] = latest.id

        # Pre-select "Scheduled" so the RM does not need to touch the status
        # field at all for the common case of booking a new visit.
        scheduled_status = self.env["lead.site.visit.status"].search(
            [("code", "=", "scheduled"), ("active", "=", True)], limit=1
        )
        if scheduled_status:
            vals.setdefault("status_id", scheduled_status.id)

        return vals

    def action_create_site_visit(self):
        self.ensure_one()

        if not self.inquiry_id:
            raise ValidationError("Inquiry is required.")

        visit = self.env["lead.site.visit"].create(
            {
                "inquiry_id": self.inquiry_id.id,
                "property_base_id": self.property_base_id.id,
                "assigned_rm_id": self.assigned_rm_id.id,
                "scheduled_datetime": self.scheduled_datetime,
                "status_id": self.status_id.id,
                "feedback_option_id": self.feedback_option_id.id,
                "feedback_note": self.feedback_note,
                "previous_visit_id": self.previous_visit_id.id,
            },
        )

        return {
            "type": "ir.actions.act_window",
            "res_model": "lead.site.visit",
            "res_id": visit.id,
            "view_mode": "form",
            "target": "current",
        }
