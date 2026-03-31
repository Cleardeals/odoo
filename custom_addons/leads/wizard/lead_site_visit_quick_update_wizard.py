from odoo import api, fields, models
from odoo.exceptions import ValidationError


# ---------------------------------------------------------------------------
# Module : leads
# Model  : lead.site.visit.quick.update.wizard
# Purpose: Fast status updates for existing site visits from inquiry/worklist.
# Owner  : Cleardeals Tech
# ---------------------------------------------------------------------------


class LeadSiteVisitQuickUpdateWizard(models.TransientModel):
    _name = "lead.site.visit.quick.update.wizard"
    _description = "Lead Site Visit Quick Update Wizard"

    visit_id = fields.Many2one(
        "lead.site.visit",
        string="Visit",
        required=True,
        readonly=True,
    )

    inquiry_id = fields.Many2one(
        "leads.new",
        related="visit_id.inquiry_id",
        readonly=True,
    )

    property_base_id = fields.Many2one(
        "property.base",
        related="visit_id.property_base_id",
        readonly=True,
    )

    assigned_rm_id = fields.Many2one(
        "res.users",
        related="visit_id.assigned_rm_id",
        readonly=True,
    )

    current_status_id = fields.Many2one(
        "lead.site.visit.status",
        string="Current Status",
        related="visit_id.status_id",
        readonly=True,
    )

    status_id = fields.Many2one(
        "lead.site.visit.status",
        string="New Status",
        required=True,
        domain=[("active", "=", True)],
    )

    scheduled_datetime = fields.Datetime(
        string="New Visit Date & Time",
    )

    feedback_option_id = fields.Many2one(
        "lead.site.visit.feedback.option",
        string="Feedback",
        domain="[('status_id', '=', status_id), ('active', '=', True)]",
    )

    feedback_note = fields.Text(
        string="Notes",
    )

    is_reschedule = fields.Boolean(
        related="status_id.is_reschedule_status",
        readonly=True,
    )

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)

        visit_id = vals.get("visit_id") or self.env.context.get("default_visit_id")
        if not visit_id and self.env.context.get("active_model") == "lead.site.visit":
            visit_id = self.env.context.get("active_id")

        if visit_id:
            vals["visit_id"] = visit_id
            visit = self.env["lead.site.visit"].browse(visit_id)
            vals.setdefault("status_id", visit.status_id.id)
        return vals

    def action_apply_update(self):
        self.ensure_one()

        if not self.visit_id:
            raise ValidationError("Visit is required.")

        vals = {
            "status_id": self.status_id.id,
            "feedback_option_id": self.feedback_option_id.id,
            "feedback_note": self.feedback_note,
        }

        if self.status_id.is_reschedule_status:
            if not self.scheduled_datetime:
                raise ValidationError(
                    "Rescheduled status requires a new date and time.",
                )
            vals["scheduled_datetime"] = self.scheduled_datetime
            self.visit_id.write(vals)
            updated_visit = self.visit_id.inquiry_id.latest_site_visit_id
        else:
            self.visit_id.write(vals)
            updated_visit = self.visit_id

        return {
            "type": "ir.actions.act_window",
            "res_model": "lead.site.visit",
            "res_id": updated_visit.id,
            "view_mode": "form",
            "target": "current",
        }
