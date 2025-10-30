from odoo import models, fields, api, _

class ImportedLead(models.Model):
    _name = "imported.lead"
    _description = "Imported CSV lead"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Lead Name", required=True, tracking=True)
    partner_name = fields.Char(string="Partner Name", tracking=True)
    phone = fields.Char(string="Phone", tracking=True)

    city = fields.Char(string="City", tracking=True)
    rm_user_id = fields.Many2one('res.users', string="Relationship Manager", tracking=True, required=True)

    source = fields.Selection([
        ('99acres', '99acres'),
        ('magicbricks', 'MagicBricks'),
        ('housing', 'Housing.com'),
        ('OLX', 'OLX'),
    ], string = 'Source', tracking=True)
    
    property_tag = fields.Char(string="Property Tag", tracking=True)
    description = fields.Text(string="Details")

    state = fields.Selection([
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('busy', 'Busy'),
    ], string="Status", default='new', tracking=True, index=True, required=True)

    @api.model
    def _read_group_stage_ids(self, stages, domain, order):
        """Helper to show all stages in Kanban view even if empty"""
        return self.env['imported.lead'].fields_get(['state'])['state']['selection']