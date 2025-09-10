from odoo import models, fields

class EstatePropertyTag(models.Model):
    _name = 'estate.property.tag'
    _description = 'Real Estate Property Tag'
    name = fields.Char(required=True, string='Name', help='Name of the property tag')

    