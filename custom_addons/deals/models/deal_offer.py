from odoo import fields, models


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
    