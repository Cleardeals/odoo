from odoo import models, fields, api


class LeadPropertyInterest(models.Model):
    _name = 'lead.property.interest'
    _description = "Lead Recommended Property Interests"
    _order = "create_date desc"


    # [MIGRATION 19.0] Replaced legacy _sql_constraints with models.Constraint
    _lead_prop_uniq = models.Constraint(
        'UNIQUE(lead_id, property_id)',
        message='This property is already linked to the lead.'
    )

    lead_id = fields.Many2one('leads.new', string="Lead", ondelete="cascade", required=True)
    property_id = fields.Many2one('property.inventory', string="Property", required=True)

    # The models own status pipelines
    current_status = fields.Selection([
        ('busy', 'Busy'),
        ('lead', 'Lead'),
        ('ringing', 'Ringing'),
        ('call_back_later', 'Call Back Later'),
        ('site_visit_scheduled', 'Site Visit Scheduled'),
        ('option_not_matching_requirements', 'Option Not Matching Requirements'),
        ('details_shared_of_property', 'Details Shared of Property'),
        ('no_requirements', 'No Requirements'),
        ('detail_shared_and_interested_for_site_visit', 'Detail Shared and Interested for Site Visit'),
        ('switched_off', 'Switched Off'),
        ('requirement_closed', 'Requirement Closed'),
        ('property_sold_out', 'Property Sold Out'),
        ('rescheduled', 'Rescheduled'),
        ('budget_not_sufficient', 'Budget Not Sufficient'),
        ('site_visit_done', 'Site Visit Done'),
        ('number_not_in_use_wrong_number', 'Number Not in Use/Wrong Number'),
        ('other', 'Other')
    ], string='Current Status', default='lead', required=True)

    remarks = fields.Text(string='Remarks')
    site_visit_date = fields.Datetime(string='Site Visit Date', copy = False)

    site_visit_date_only = fields.Date(
        string="Site Visit Date (Recommended Property)",
        compute='_compute_site_visit_date_only',
        store=True, # Essential for filtering
        readonly=True
    )

    # # We link to the RM of the property for the security rules
    # property_rm_user_id = fields.Many2one(
    #     related='property_id.rm_user_id',
    #     store=True,
    #     readonly=True,
    #     string="Property's RM"
    # )

    property_bhk = fields.Char(
        related='property_id.bhk',
        readonly=True
    )

    property_location = fields.Char(
        related='property_id.location',
        readonly=True
    )

    feedback_general = fields.Selection([
        ('buyer_did_not_visit_property', 'Buyer Did Not Visit Property'),
        ('buyer_not_interested', 'Buyer Not Interested'),
        ('buyer_not_picking_call', 'Buyer Not Picking Call'),
        ('visit_needs_to_be_rescheduled', 'Visit Needs to be Rescheduled'),
        ('other', 'Other'),
    ], string='Feedback')

    feedback_site_visit_done = fields.Selection([
        ('requirements_not_matching', 'Requirements Not Matching'),
        ('buyer_liked_property', 'Buyer Liked Property'),
        ('buyer_requirement_closed', 'Buyer Requirement Closed'),
        ('buyer_visit_from_outside', 'Buyer Visit From Outside'),
        ('buyer_not_pickup_call', 'Buyer Not Picking Call'),
        ('other', 'Other')
    ], string='Feedback for Site Visit Done')

    @api.depends('site_visit_date')
    def _compute_site_visit_date_only(self):
        """
        Takes the 'site_visit_date' (Datetime) and stores
        just the 'date' part for easy filtering.
        """
        for rec in self:
            if rec.site_visit_date:
                rec.site_visit_date_only = rec.site_visit_date.date()
            else:
                rec.site_visit_date_only = False