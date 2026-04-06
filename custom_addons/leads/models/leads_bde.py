from odoo import fields, models


class LeadsBde(models.Model):
    _name = "leads.bde"
    _description = "BDE (Business Development Executive)"
    _order = "name"

    name = fields.Char(string="Name", required=True, index=True)
    phone = fields.Char(string="Phone")
    email = fields.Char(string="Email")
    active = fields.Boolean(default=True)

    allowed_rm_ids = fields.Many2many(
        "res.users",
        "leads_bde_allowed_rm_rel",
        "bde_id",
        "user_id",
        string="Allowed RMs",
        domain="[('share', '=', False)]",
        help="RMs who are permitted to assign this BDE to their ops sale leads.",
    )
