from odoo import fields, models

class ResLocation(models.Model):
    _name = 'res.location'
    _description = 'Property Location/Area'
    _order = 'name'

    name = fields.Char(required=True)
    city_id = fields.Many2one('res.city', string="City", required=True)

    _sql_constraints = [
        ('name_city_uniq', 'unique (name, city_id)', 'Location name must be unique per city!')
    ]