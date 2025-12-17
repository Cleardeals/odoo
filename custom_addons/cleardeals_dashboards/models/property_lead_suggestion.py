# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class PropertyLeadSuggestion(models.Model):
    """
    Inherit the lead.suggestion model to add a stored, related field for RM.
    This makes dashboard grouping faster and easier in Odoo 19.
    """
    _inherit = 'property.lead.suggestion'

    rm_user_id = fields.Many2one(
        related='property_inventory_id.rm_user_id',
        string="Assigned RM",
        store=True,
        readonly=True,
        index=True
    )