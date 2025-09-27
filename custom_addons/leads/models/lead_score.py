from odoo import fields, models, api 
from datetime import timedelta, date

class LeadScore(models.Model):
    _name = 'lead.score'
    _description = 'Lead Scoring Record From BQ (Table name : whatsapp_automation_list, Dataset name : lead_scoring, Project ID: cleardeals-459513)'
    _order = 'predicted_score desc'

    # Core Lead Information
    name = fields.Char(string='Lead Name', required=True)
    assigned_rm_id = fields.Many2one('res.users', string='Assigned RM')
    standardized_phone = fields.Char(string = 'Standardized Phone')

    # Scoring Information
    predicted_score = fields.Float(string='Predicted Score')
    #current_status = fields.Char(string='Current Status (Stage in Funnel)')

    current_status = fields.Selection([
        ('busy', 'Busy'),
        ('lead', 'Lead'),
        ('ringing', 'Ringing'),
        ('call_back_later', 'Call Back Later'),
        ('site_visit_scheduled', 'Site Visit Scheduled'),
        ('option_not_matching_requirements', 'Option Not Matching Requirements'),
        ('details_shared_of_property', 'Details Shared of Property'),
        ('no_requirements', 'No Requirements'),
        ('details_shared_and_interested_for_site_visit', 'Details Shared and Interested for Site Visit'),
        ('switched_off', 'Switched Off'),
        ('requirement_closed', 'Requirement Closed'),
        ('property_sold_out', 'Property Sold Out'),
        ('rescheduled', 'Rescheduled'),
        ('budget_not_sufficient', 'Budget Not Sufficient'),
        ('site_visit_done', 'Site Visit Done'),
        ('number_not_in_use_wrong_number', 'Number Not in Use/Wrong Number'),
        ('other', 'Other')
    ], string='Current Status', default='lead', required=True)


    #Property Details
    project_name = fields.Char(string='Project Name')
    property_type = fields.Char(string='Property Type')
    property_tag = fields.Char(string='Property Tag')
    property_address = fields.Char(string='Property Address')
    bhk = fields.Char(string='BHK')
    price_range = fields.Char(string='Price Range (Lacs)')
    carpet_area = fields.Char(string='Carpet Area (Sqft)')
    super_built_up_area = fields.Char(string='Super Built-up Area')
    property_link = fields.Char(string='Property Link')
    location = fields.Char(string='Location')
    property_on_floor = fields.Char(string='Property on Floor')
    property_facing = fields.Char(string='Property Facing')
    furniture_details = fields.Char(string='Furniture Details')
    age_of_property = fields.Char(string='Age of Property')
    parking_details = fields.Char(string='Parking Details')
    bathroom = fields.Char(string='Bathrooms')
    offer_price = fields.Char(string='Offer Price (Lacs)')

    # Fields for RM Interaction
    site_visit_scheduled_date = fields.Date(string='Site Visit Scheduled For Date')
    #feedback = fields.Text(string='Feedback')
    feedback = fields.Selection([
        ('buyer_did_not_visit_property', 'Buyer Did Not Visit Property'),
        ('buyer_not_interested', 'Buyer Not Interested'),
        ('buyer_not_picking_call', 'Buyer Not Picking Call'),
        ('visit_needs_to_be_rescheduled', 'Visit Needs to be Rescheduled'),
    ], string='Feedback')
    next_follow_up_date = fields.Date(
        string='Next Follow-up Date',
        compute = '_compute_next_follow_up_date',
        inverse = '_inverse_next_follow_up_date',
        store=True,
        readonly=False)
    
    state = fields.Selection([
        ('busy', 'Busy'),
        ('lead', 'Lead'),
        ('ringing', 'Ringing'),
        ('call_back_later', 'Call Back Later'),
        ('site_visit_scheduled', 'Site Visit Scheduled'),
        ('option_not_matching_requirements', 'Option Not Matching Requirements'),
        ('details_shared_of_property', 'Details Shared of Property'),
        ('no_requirements', 'No Requirements'),
        ('details_shared_and_interested_for_site_visit', 'Details Shared and Interested for Site Visit'),
        ('switched_off', 'Switched Off'),
        ('requirement_closed', 'Requirement Closed'),
        ('property_sold_out', 'Property Sold Out'),
        ('rescheduled', 'Rescheduled'),
        ('budget_not_sufficient', 'Budget Not Sufficient'),
        ('number_not_in_use_wrong_number', 'Number Not in Use/Wrong Number'),
        ('site_visit_done', 'Site Visit Done'),
        ('other', 'Other')
    ], string='Status', default='lead', required=True)

    is_actionable_today = fields.Boolean(
        string='Is Actionable Today',
        compute='_compute_is_actionable_today',
        store=True,
        help="True if the follow-up date is today or earlier.")
    
    whatsapp_response_ids = fields.One2many(
        'whatsapp.response', 
        'lead_id', 
        string='WhatsApp Responses ID'
    )



        # You probably also have a field for the count, make sure it's there
    whatsapp_response_count = fields.Integer(
        compute='_compute_whatsapp_response_count', 
        string='Response Count'
    )

    def _compute_whatsapp_response_count(self):
        for lead in self:
            lead.whatsapp_response_count = len(lead.whatsapp_response_ids)
    
    @api.depends('next_follow_up_date')
    def _compute_is_actionable_today(self):
        """ Compute if the lead is actionable today based on the next follow-up date."""
        today = date.today()
        for lead in self:
            lead.is_actionable_today = (not lead.next_follow_up_date) or (lead.next_follow_up_date <= today)


    @api.depends('current_status', 'site_visit_scheduled_date')
    def _compute_next_follow_up_date(self):
        """ Compute the follow-up date based on the state and the site visit date."""
        for lead in self:
            if (lead.current_status == 'site_visit_scheduled' or lead.current_status == 'rescheduled') and lead.site_visit_scheduled_date:
                lead.next_follow_up_date = lead.site_visit_scheduled_date + timedelta(days=1)
            else:
                # if the follow up date was never set the default is today.
                if not lead.next_follow_up_date:
                    lead.next_follow_up_date = fields.Date.context_today(lead)

    def _inverse_next_follow_up_date(self):
        """ Allows the user to manually set the next follow-up date.
        or sets the site visit date if the state is correct.
        """

        for lead in self:
            if lead.current_status == 'site_visit_scheduled' or lead.current_status == 'rescheduled':
                lead.site_visit_scheduled_date = lead.next_follow_up_date - timedelta(days=1)

    @api.onchange('current_status')
    def _onchange_state_set_follow_up(self):
        """When the state changes in the UI, set a default follow-up date."""
        if self.current_status != 'site_visit_scheduled' and self.current_status != 'rescheduled':
            self.next_follow_up_date = fields.Date.context_today(self) + timedelta(days=1)

    def action_open_bigquery_wizard(self):
        """ This method is called by the button. """
        action = self.env['ir.actions.act_window']._for_xml_id('leads.action_fetch_leads_wizard')
        return action


