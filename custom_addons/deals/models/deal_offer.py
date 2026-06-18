from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DealOffer(models.Model):
    _name = "deal.offer"
    _description = "Offer for the deal"
    _inherit = ["mail.thread"]
    _order = "name"
    _rec_name = "name"

    name = fields.Char(string="Name", required=True, tracking=True)
    waive_off_type = fields.Selection(
        string="Waive Off",
        selection=[("percentage", "Percentage"), ("fixed", "Fixed Amount")],
        required=True,
        tracking=True,
        default="percentage",
    )
    waive_off_value = fields.Float(
        string="Waive Off Value", required=True, tracking=True
    )
    is_active = fields.Boolean(string="Active", default=True, index=True, tracking=True)

    # Constraints to ensure valid waive off values based on the selected type

    @api.constrains("waive_off_type", "waive_off_value")
    def _check_waive_off_value(self):
        for record in self:
            if record.waive_off_type == "percentage" and not (
                0 < record.waive_off_value < 100
            ):
                msg = "Percentage value must be greater than 0 and less than 100."
                raise ValidationError(
                    msg,
                )
            if record.waive_off_type == "fixed" and record.waive_off_value <= 0:
                msg_0 = "Fixed amount value must be greater than 0."
                raise ValidationError(msg_0)

    # Helper method to calculate the reduced amount based on the waive off type and value

    def apply_waive_off(self, base_amount):
        self.ensure_one()

        if self.waive_off_type == "percentage":
            reduced_amount = base_amount - (base_amount * self.waive_off_value / 100.0)
        elif self.waive_off_type == "fixed":
            reduced_amount = base_amount - self.waive_off_value
        else:
            reduced_amount = base_amount

        return max(0.0, reduced_amount)
