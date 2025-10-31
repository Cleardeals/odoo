from odoo import models, fields, api

class ImportedLead(models.Model):
    _name = 'imported.lead'
    _description = 'Imported CSV Lead'
    _inherit = ['mail.thread', 'mail.activity.mixin'] # Added mail.activity.mixin

    name = fields.Char(string='Lead Title', required=True, tracking=True)
    partner_name = fields.Char(string='Contact Name', tracking=True)
    phone = fields.Char(string='Phone', tracking=True)
    
    # NEW: Added City field
    city = fields.Char(string="City", tracking=True)

    source = fields.Selection([
        ('99acres', '99acres'),
        ('MagicBricks', 'MagicBricks'), # Kept uppercase 'M' to match CSV/Wizard
        ('Housing', 'Housing'),       # Kept uppercase 'H' to match CSV/Wizard
        ('OLX', 'OLX'),
    ], string='Source', tracking=True)
    
    property_tag = fields.Char(string='Property Tag', tracking=True)
    address = fields.Text(string='Property Address', tracking=True)
    price_range = fields.Char(string='Price Range', tracking=True)
    
    rm_user_id = fields.Many2one('res.users', string='Relationship Manager', tracking=True)
    description = fields.Text(string='Full Row Data')

    # NEW: Added Status field for Kanban
    state = fields.Selection([
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('busy', 'Busy'),
    ], string="Status", default='new', tracking=True, index=True, required=True)

    @api.model
    def _read_group_stage_ids(self, stages, domain, order):
        """Helper to show all stages in Kanban view even if empty"""
        return self.env['imported.lead'].fields_get(['state'])['state']['selection']

