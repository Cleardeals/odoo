# -*- coding: utf-8 -*-
from odoo import models, fields, api

class RenewalLeadAssignment(models.Model):
    _name = "renewal.lead.assignment"
    _description = "Renewal Campaign Lead Assignment"
    _order = "assignment_timestamp desc"

    owner_id = fields.Many2one('renewal.property.owner', string="Property Owner", required=True, ondelete='cascade')

    assignment_id = fields.Char(string="Assignment ID", required=True, index=True)
    lead_phone = fields.Char(string="Lead Phone", readonly=True)
    lead_name = fields.Char(string="Lead Name", readonly=True)
    assignment_timestamp = fields.Datetime(string="Assignment Timestamp", readonly=True)

    _sql_constraints = [
        ('assignment_id_uniq', 'unique(assignment_id)', 'This assignment ID already exists.')
    ]