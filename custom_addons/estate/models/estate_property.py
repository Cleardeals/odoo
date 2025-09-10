# -*- coding: utf-8 -*-
from odoo import fields, models, api
from odoo.exceptions import UserError
from datetime import timedelta

class EstateProperty(models.Model):
    _name = 'estate.property'
    _description = 'Real Estate Property'

    # CORRECTED: Use 'string' instead of 'name' for the label
    name = fields.Char(required=True, string='Title', help='Name of the property')
    # CORRECTED: Provide a string literal for the label, not the 'name' object
    description = fields.Text(string='Description', help='Description of the property')
    postcode = fields.Char(string='Postcode', help='Postcode of the property')
    # Use a lambda function for dynamic defaults
    date_availability = fields.Date(
        copy=False,
        default=lambda self: fields.Date.add(fields.Date.today(), months=3),
        string='Available From',
        help='Date when the property is available for sale'
    )
    
    tag_ids = fields.Many2many("estate.property.tag", string="Tags")
    expected_price = fields.Float(required=True, string='Expected Price', help='Expected selling price of the property')
    selling_price = fields.Float(readonly=True, copy=False)
    bedrooms = fields.Integer(default=2, string='Bedrooms', help='Number of bedrooms')
    living_area = fields.Integer(string='Living Area (sqm)', help='Size of the living area in square meters')
    facades = fields.Integer(string='Facades', help='Number of facades')
    garage = fields.Boolean(string='Garage', help='Is there a garage?')
    garden = fields.Boolean(string='Garden', help='Is there a garden?')
    garden_area = fields.Integer(string='Garden Area (sqm)', help='Size of the garden area in square meters')
    garden_orientation = fields.Selection(
        selection=[
            ('north', 'North'),
            ('south', 'South'),
            ('east', 'East'),
            ('west', 'West')
        ],
        string="Garden Orientation"
    )
    property_type_id = fields.Many2one("estate.property.type", string="Property Type")
    salesperson_id = fields.Many2one("res.users", string="Salesperson", default=lambda self: self.env.user)
    buyer_id = fields.Many2one("res.partner", string="Buyer", copy=False)
    active = fields.Boolean(default=True)
    state = fields.Selection(
        selection=[
            ('new', 'New'),
            ('offer_received', 'Offer Received'),
            ('offer_accepted', 'Offer Accepted'),
            ('sold', 'Sold'),
            ('canceled', 'Canceled')
        ],
        string="Status",
        default='new',
        required=True,
        copy=False
    )
    offer_ids = fields.One2many("estate.property.offer", "property_id", string="Offers")
    total_area = fields.Integer(compute='_compute_total_area', string='Total Area (sqm)', store=True)
    best_price = fields.Float(compute='_compute_best_price', string='Best Offer', store=True)

    

    @api.depends('living_area', 'garden_area')
    def _compute_total_area(self):
        for record in self:
            record.total_area = record.living_area + record.garden_area
    
    @api.depends('offer_ids.price')
    def _compute_best_price(self):
        for record in self:
            if record.offer_ids:
                record.best_price = max(record.offer_ids.mapped('price'))
            else:
                record.best_price = 0.0


    def action_set_sold(self):
        for record in self:
            if record.state == 'canceled':
                raise UserError("Canceled properties cannot be sold.")
            record.state = 'sold'
        return True
    
    def action_cancel(self):
        for record in self:
            if record.state == 'sold':
                raise UserError("Sold properties cannot be canceled.")
            record.state = 'canceled'
        return True 