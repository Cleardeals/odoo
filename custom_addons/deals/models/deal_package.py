from odoo import api, fields, models
from odoo.orm.model_classes import ValidationError


class DealPackage(models.Model):
    _name = "deal.package"
    _description = "Package of the deal"
    _inherit = ["mail.thread"]
    _order = "name"
    _rec_name = "name"

    name = fields.Char(string="Name", required=True, tracking=True)
    amount = fields.Monetary(
        string="Amount",
        required=True,
        tracking=True,
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: self.env.ref("base.INR"),
    )
    is_active = fields.Boolean(string="Active", default=True, tracking=True)

    @api.constrains("amount")
    def _check_amount_positive(self):
        for record in self:
            if record.amount < 0:
                msg = "Amount cannot be negative."
                raise ValidationError(msg)
