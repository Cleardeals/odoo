from odoo import models, fields

class NewLead(models.Model):
    _name = 'leads.new'
    -description = "New Leads"
    _inherit = ['mail.thread', 'mail.activity.mixin'] # For Chatter

    name = fields.Char('Lead Name', required=True, tracking=True)
