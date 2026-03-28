from odoo import api, fields, models
from odoo.exceptions import ValidationError


class LeadSourceCategory(models.Model):
    _name = "lead.source.category"
    _description = "Lead Source Category"
    _order = "sequence, id"

    _code_uniq = models.Constraint(
        "UNIQUE(code)",
        message="Lead source category code must be unique.",
    )

    name = fields.Char(required=True, index=True)
    code = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True, index=True)
    source_type = fields.Selection(
        [
            ("portal", "Portal"),
            ("manual", "Manual"),
        ],
        string="Source Type",
        required=True,
        default="manual",
        index=True,
    )


class LeadSource(models.Model):
    _name = "lead.source"
    _description = "Lead Source"
    _order = "sequence, name, id"

    _name_uniq = models.Constraint(
        "UNIQUE(name)",
        message="Lead source name must be unique.",
    )

    name = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True, index=True)

    category_id = fields.Many2one(
        "lead.source.category",
        string="Category",
        required=True,
        index=True,
        ondelete="restrict",
    )
    source_type = fields.Selection(
        related="category_id.source_type",
        store=True,
        readonly=True,
    )

    portal_code = fields.Selection(
        [
            ("99acres", "99acres"),
            ("Housing.com", "Housing.com"),
            ("MagicBricks", "MagicBricks"),
            ("OLX", "OLX"),
        ],
        string="Portal",
        index=True,
        help="Used for portal-listing based property matching.",
    )
    default_rm_user_id = fields.Many2one(
        "res.users",
        string="Fallback RM",
        domain="[(\"share\", \"=\", False)]",
        help="Used when a portal lead cannot be matched to a property; the lead will be assigned to this RM.",
    )

    @api.constrains("source_type", "portal_code")
    def _check_portal_code_consistency(self):
        for rec in self:
            if rec.source_type == "portal" and not rec.portal_code:
                raise ValidationError(
                    "Portal sources require a portal code for listing matching.",
                )
            if rec.source_type != "portal" and rec.portal_code:
                raise ValidationError(
                    "Only portal sources can have a portal code.",
                )
