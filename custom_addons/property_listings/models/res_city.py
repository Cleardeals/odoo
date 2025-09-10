from odoo import fields, models

class ResCity(models.Model):
    _name = 'res.city'
    _description = 'City'
    _order = 'name'

    name = fields.Char(required=True)
    state_id = fields.Many2one('res.country.state', string="State", required=True)
    country_id = fields.Many2one('res.country', string="Country", related='state_id.country_id', store=True)

    _sql_constraints = [
        ('name_state_uniq', 'unique (name, state_id)', 'City name must be unique per state!')
    ]