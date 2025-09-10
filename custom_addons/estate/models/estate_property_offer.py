from odoo import fields, models, api
from datetime import timedelta
from odoo.exceptions import UserError

class EstatePropertyOffer(models.Model):
    _name = "estate.property.offer"
    _description = "Estate Property Offer"

    price = fields.Float("Price")
    status = fields.Selection(
        [
            ("accepted", "Accepted"),
            ("refused", "Refused"),
        ],
        string="Status",
        copy=False,
    )
    partner_id = fields.Many2one("res.partner", string="Partner", required=True)
    property_id = fields.Many2one("estate.property", string="Property", required=True)

    validity = fields.Integer(default=7, string='Offer Validity (days)', help='Validity period of the offer in days')
    date_deadline = fields.Date(compute='_compute_date_deadline', string='Offer Deadline', store=True, inverse='inverse_date_deadline')

    @api.depends('create_date', 'validity')
    def _compute_date_deadline(self):
        for record in self:
            start_date = record.create_date.date() if record.create_date else fields.Date.today()
            record.date_deadline = start_date + timedelta(days=record.validity)

    def inverse_date_deadline(self):
        for record in self:
            start_date = record.create_date.date() if record.create_date else fields.Date.today()
            record.validity = (record.date_deadline - start_date).days if record.date_deadline else 7

    def action_accept_offer(self):
        for record in self:
            if "accepted" in record.property_id.offer_ids.mapped('status'):
                raise UserError("Another offer has already been accepted for this property.")
            record.status = "accepted"
            record.property_id.selling_price = record.price
            record.property_id.buyer_id = record.partner_id
        
        return True
    

    def action_refuse_offer(self):
        for record in self:
            record.status = "refused"
        return True