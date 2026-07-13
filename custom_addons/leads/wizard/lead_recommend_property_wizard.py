from odoo import api, fields, models
from odoo.exceptions import ValidationError


# ---------------------------------------------------------------------------
# Module : leads
# Model  : lead.recommend.property.wizard
# Purpose: Popup flow for creating recommended-type inquiry records.
# Owner  : Cleardeals Tech
# ---------------------------------------------------------------------------


class LeadRecommendPropertyWizard(models.TransientModel):
    _name = "lead.recommend.property.wizard"
    _description = "Recommend Property Wizard"

    inquiry_id = fields.Many2one(
        "leads.new",
        required=True,
        readonly=True,
    )

    property_base_id = fields.Many2one(
        "property.base",
        string="Recommended Property",
        required=True,
        context={"search_all_properties_for_lead": True},
    )

    assigned_rm_id = fields.Many2one(
        "res.users",
        string="Assigned RM",
    )

    source_id = fields.Many2one(
        "lead.source",
        string="Source",
        readonly=True,
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
        vals["assigned_rm_id"] = inquiry.user_id.id
        vals["source_id"] = inquiry.source_id.id
        return vals

    def action_create_recommended_inquiry(self):
        self.ensure_one()

        inquiry = self.inquiry_id
        if not inquiry:
            raise ValidationError("Inquiry is required.")

        # A recommended inquiry may be created from a primary OR from another
        # recommended inquiry.  The hierarchy stays flat (one level under the
        # primary): when the source is itself recommended, the new inquiry inherits
        # the SAME primary parent rather than nesting under a recommendation.
        if inquiry.inquiry_type == "primary":
            parent = inquiry
        else:
            parent = inquiry.parent_inquiry_id
            if not parent:
                raise ValidationError(
                    "This recommended inquiry has no parent primary inquiry, so a "
                    "new recommended inquiry cannot be attached. Please fix the "
                    "source inquiry's parent first.",
                )

        if not inquiry.phone:
            raise ValidationError(
                "Phone number is required to create a recommended inquiry.",
            )

        if not inquiry.source_id:
            raise ValidationError(
                "Source is required on the original inquiry.",
            )

        duplicate = self.env["leads.new"].sudo().search(
            [
                ("phone", "=", inquiry.phone),
                ("property_base_id", "=", self.property_base_id.id),
            ],
            limit=1,
        )
        if duplicate:
            raise ValidationError(
                "An inquiry already exists for this buyer and property.",
            )

        new_inquiry = self.env["leads.new"].with_context(
            automated_lead_creation=True,
        ).create(
            {
                "name": inquiry.name,
                "phone": inquiry.phone,
                "email": inquiry.email,
                "source_id": inquiry.source_id.id,
                "property_base_id": self.property_base_id.id,
                "user_id": (self.assigned_rm_id or inquiry.user_id).id,
                "state": "assigned",
                "current_status": "lead",
                "inquiry_type": "recommended",
                "parent_inquiry_id": parent.id,
            },
        )

        return {
            "type": "ir.actions.act_window",
            "res_model": "leads.new",
            "res_id": new_inquiry.id,
            "view_mode": "form",
            "target": "current",
        }
