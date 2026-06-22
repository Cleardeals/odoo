from odoo import fields, models


class Deal(models.Model):
    _name = "deal"
    _description = "Contain information related to transaction, property."
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "deal_id"
    _rec_name = "deal_id"
    
    deal_id = fields.Char(string="Deal ID", required=True, copy=False, readonly=True, index=True, default=lambda self: self.env['ir.sequence'].next_by_code('deal.deal_id'))
    property_id = fields.Many2one('property.base', string="Property", required=True, ondelete='restrict', index=True, tracking=True)
    owner_id = fields.Many2one('deal.owner', string="Owner", required=True, tracking=True)
    bde_id = fields.Many2one('lead.bde', string="BDE", required=True, tracking=True)
    deal_type = fields.Selection([
            ('regular', 'Regular'), 
            ('ops_sale_lead', 'Ops Sale Lead'), 
            ('renewal', 'Renewal')],
            string="Deal Type", 
            required=True, 
            index=True, 
            tracking=True, 
            default='regular'
        )
    is_offer = fields.Boolean(string="Is Offer", default=False, tracking=True)
    offer_id = fields.Many2one('deal.offer', string="Offer", required=True, tracking=True, domain=[('is_active', '=', True)])
    package_id = fields.Many2one('deal.package', string="Package", required=True, tracking=True)
    package_amount = fields.Monetary(string="Package Amount", required=True, tracking=True, currency_field='currency_id', domain=[('is_active', '=', True)])
    gross_amount = fields.Monetary(string="Gross Amount", required=True, tracking=True, currency_field='currency_id')
    currency_id = fields.Many2one(
            "res.currency",
            string="Currency",
            default=lambda self: self.env.ref("base.INR"),
        )
    transaction_ids = fields.One2many('deal.transaction', 'deal_id', string="Transactions")
    deal_status = fields.Selection([
            ('registration', 'Registration'),
            ('live', 'Live'),
            ('sold', 'Sold'),
            ('renewed', 'Renewed'),
            ('closed', 'Closed')], 
            string="Deal Status", 
            required=True, 
            tracking=True, 
            default='registration'
        )
    closed_reason = fields.Selection([
            ('package_expired', 'Package Expired'),
            ('deal_cancelled', 'Deal Cancelled')],
            string="Closed Reason",
            tracking=True
        )
    is_full_payment = fields.Boolean(string="Is Full Payment", default=False, tracking=True)
    registration_date = fields.Date(string="Registration Date", required=True, tracking=True, default=fields.Date.context_today)
    closed_at = fields.Datetime(string="Closed At", tracking=True, readonly=True)
    
    
