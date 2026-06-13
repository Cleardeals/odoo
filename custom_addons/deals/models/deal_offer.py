from odoo import fields, models, api
from odoo.exceptions import ValidationError


class DealOffer(models.Model):
    _name = "deal.offer"
    _description = "Offer for the deal"
    _inherit = ['mail.thread']
    _order = "name"
    _rec_name = "name"
    
    name = fields.Char(string="Name", required=True, tracking=True)
    waive_off_type = fields.Selection(
        string="Waive Off",
        selection=[
            ('percentage', 'Percentage'),
            ('amount', 'Amount')
        ],
        required=True,
        tracking=True,
        default='percentage'
    )
    waive_off_value = fields.Float(string="Waive Off Value", required=True, tracking=True)
    is_active = fields.Boolean(
        string="Is Active?",
        default=True,
        index=True,
        tracking=True
    )
    
    @api.constrains('waive_off_type', 'waive_off_value')
    def _check_waive_off_value(self):
        for record in self:
            if record.waive_off_type == 'percentage' and not (0 < record.waive_off_value < 100):
                raise ValidationError("Percentage value must be greater than 0 and less than 100.")
            elif record.waive_off_type == 'amount' and record.waive_off_value <= 0:
                raise ValidationError("Amount value must be greater than 0.")
    