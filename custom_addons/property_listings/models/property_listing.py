from odoo import api, fields, models

class PropertyListing(models.Model):
    _name = 'property.listing'
    _description = 'Onboarded Property Listing'

    # 1. Name of the owner of the property
    name = fields.Char(string="Owner Name", required=True)
    # 3. Phone number of the owner
    phone = fields.Char(string="Phone")
    # 4. Email of the owner
    # email = fields.Char(string="Email")
    # 35. Property Address
    property_address = fields.Text(string="Property Address")

    # 5, 6, 7. Location Details (Linked to other models)
    country_id = fields.Many2one('res.country', string="Country", default=lambda self: self.env.ref('base.in'))
    state_id = fields.Many2one('res.country.state', string="State", domain="[('country_id', '=', country_id)]")
    city_id = fields.Many2one('res.city', string="City", domain="[('state_id', '=', state_id)]")
    # 16. Location/Area
    location_id = fields.Many2one('res.location', string="Location", domain="[('city_id', '=', city_id)]")
    
    # 8. Tag
    tag = fields.Char(string="Property Tag")

    # 11, 13, 14, 15. Property Type and Specs
    bhk = fields.Char(string="BHK")
    property_type = fields.Selection([('residential', 'Residential'), ('commercial', 'Commercial')], string="Property Type")
    residential_type = fields.Char(string="Residential Type") # e.g., Apartment, Villa
    commercial_type = fields.Char(string="Commercial Type") # e.g., Office, Showroom

    # 17. Sell/Rent
    listing_type = fields.Selection([('sell', 'For Sell'), ('rent', 'For Rent')], string="Listing Type", default='sell')

    # 36 to 47. Detailed Specs
    current_status = fields.Selection([('self_occupied', 'Self Occupied'), ('empty', 'Empty'), ('tenant_occupied', 'Tenant Occupied')], string="Current Status")
    # property_on_floor = fields.Char(string="Property On Floor")
    # property_facing = fields.Char(string="Property Facing")
    # lift_per_block = fields.Char(string="No. of Lifts per Block")
    # furniture_details = fields.Selection([('unfurnished', 'Unfurnished'), ('semi_furnished', 'Semi-Furnished'), ('furnished', 'Furnished')], string="Furniture Details")
    # age_of_property = fields.Char(string="Age of Property (Years)")
    # parking_details = fields.Char(string="Parking Details")
    #bathroom = fields.Char(string="Bathrooms")
    #super_built_up_plot_space = fields.Char(string="Super Built-up Plot Space")
    #super_built_up_construction_area = fields.Char(string="Super Built-up Construction Area")
    #carpet_construction_area = fields.Char(string="Carpet Construction Area")
    #carpet_plot_area = fields.Char(string="Carpet Plot Area")

    # 18 to 34. Financial and Service Details
    #service_call_date = fields.Date(string="Service Call Date", required=True)
    #payment_package = fields.Char(string="Payment Package")
    #form_number = fields.Char(string="Form Number")
    #property_price = fields.Float(string="Property Price")
    #payment_mode = fields.Char(string="Payment Mode")
    #receipt_number = fields.Char(string="Receipt Number")
    #service_validity = fields.Selection([
    #    ('1', '1 Month'), ('3', '3 Months'), ('6', '6 Months'), ('12', '12 Months')
    #], string="Service Validity (Months)")
    #package_amount = fields.Float(string="Package Amount")
    #et_amount = fields.Float(string="Net Amount")
    #due_amount = fields.Float(string="Due Amount")
    #total_package_amount = fields.Float(string="Total Package Amount")
    #inventory_count = fields.Integer(string="Number of Inventory", default=1)
    #property_register_date = fields.Date(string="Property Register Date")
    #gst_status = fields.Selection([('gst', 'GST Applicable'), ('no_gst', 'No GST')], string="GST Status")
    
    # 2, 26, 33. Assigned Users
    rm_id = fields.Many2one('res.users', string="Relationship Manager")
    sales_executive_id = fields.Many2one('res.users', string="Sales Executive")
    # Note: 'Relationship Manager' is a duplicate of Assignee, so we use one field.

    # 48 to 57. Marketing and Status
    property_link = fields.Char(string="Property Website Link")
    #link_360_dgt = fields.Char(string="360 Video Link")
    #property_status = fields.Selection([
    #    ('live', 'Live'), ('expired', 'Expired'), ('sold', 'Sold')
    #], string="Listing Status", default='live')
    #property_sold_date = fields.Date(string="Property Sold Date")
    #reason_for_unsold = fields.Text(string="Reason For Unsold")
    #instagram_reel = fields.Boolean(string="Instagram Reel Made?")
    #id_99acres = fields.Char(string="99acres ID")
    #id_housing = fields.Char(string="Housing.com ID")
    #id_magicbricks = fields.Char(string="Magicbricks ID")
    #id_olx = fields.Char(string="OLX ID")

    # 9, 10. Odoo automatically handles create and write dates.

    def _cron_expire_listings(self):
        """ Automated action to expire property listings based on service validity."""
        for prop in self.search([('property_status', '=', 'live')]):
            if prop.service_validity and prop.property_register_date:
                expiry_date = fields.Date.add(prop.property_register_date, months=prop.service_validity)
                if fields.Date.today() > expiry_date:
                    prop.property_status = 'expired'
