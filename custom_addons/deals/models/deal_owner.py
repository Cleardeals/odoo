from odoo import fields, models

class DealOwner(models.Model):
    _name = "deal.owner"
    _description = "Owner of the property"
    _inherit = ['mail.thread']
    _order = "name"
    _rec_name = "name"

    _phone_uniq = models.Constraint(
        "UNIQUE(phone)",
        message="Phone number must be unique.",
    )

    name = fields.Char(string="Name", required=True, tracking=True)
    phone = fields.Char(string="Phone", required=True, tracking=True)
    email = fields.Char(string="Email")
    occupation = fields.Char(string="Occupation")
    is_builder = fields.Boolean(string="Is Builder?", default=False, tracking=True)

        
