from odoo import fields, models


class DealPackage(models.Model):
    _name = "deal.package"
    _description = "Package of the deal"
    _inherit = ['mail.thread']
    _order = "name"
    _rec_name = "name"
    
    name = fields.Char(string="Name", required=True, tracking=True)
    amount = fields.Monetary(string="Amount", required=True, tracking=True, currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.user.company_id.currency_id,
    )
    is_active = fields.Boolean(string="Is Active?", default=True, tracking=True)
    