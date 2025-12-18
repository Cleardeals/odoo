from odoo import models, fields, api

class RenewalLeadAssignment(models.Model):
    _name = "renewal.lead.assignment"
    _description = "Renewal Campaign Lead Assignment"
    _order = "assignment_timestamp desc"
    _rec_name = "lead_name"  # [MIGRATION] Added for UI readability

    owner_id = fields.Many2one('renewal.property.owner', string="Property Owner", required=True, ondelete='cascade')

    assignment_id = fields.Char(string="Assignment ID", required=True, index=True)
    lead_phone = fields.Char(string="Lead Phone", readonly=True)
    lead_name = fields.Char(string="Lead Name", readonly=True)
    assignment_timestamp = fields.Datetime(string="Assignment Timestamp", readonly=True)

    # [FIX] New Odoo 19 Constraint Syntax
    _assignment_id_uniq = models.Constraint(
        'UNIQUE(assignment_id)',
        message='This assignment ID already exists.'
    )