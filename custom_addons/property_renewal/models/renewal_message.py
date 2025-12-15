from odoo import models, fields, api

class RenewalMessage(models.Model):
    _name = 'renewal.message'
    _description = 'Property Renewal Message Log'
    _order = 'event_timestamp desc'

    property_tag = fields.Char(string="Property Tag")

    property_id = fields.Many2one('property.listing', string='Property', required=True, ondelete='cascade')

    assigned_rm_id = fields.Many2one('res.users', string='Assigned RM', required=True)

    owner_name = fields.Char(string='Owner Name')
    owner_phone = fields.Char(string='Owner Phone')

    event_type = fields.Selection([
        ('clicked_see_lead', 'Clicked See Lead'),
        ('not_interested_in_seeing_lead', 'Not Interested in Seeing Lead'),
        ('no_rm_support', 'No RM Support Needed'),
        ('wants_renewal', 'Wants Renewal'),
    ])

    event_timestamp = fields.Datetime(string='Event Timestamp', default=fields.Datetime.now)
    state = fields.Selection([
        ('pending_response', 'Pending Response'),
        ('responded', 'Responded'),
        ('out_of_funnel', 'Out of Funnel'),
    ], string="Status", default='pending_response', index = True)

    @api.onchange('event_type')
    def _onchange_event_type(self):
        if self.event_type == 'not_interested_in_seeing_lead' or self.event_type == 'no_rm_support':
            self.state = 'out_of_funnel'
        elif self.event_type == 'wants_renewal' or self.event_type == 'clicked_see_lead':
            self.state = 'responded'
        else:
            self.state = 'pending_response'


    @api.onchange('property_tag')
    def _onchange_property_tag(self):
        if self.property_tag:
            property_record = self.env['property.listing'].search([('tag', '=', self.property_tag)], limit=1)

            if property_record:
                self.property_id = property_record.id
                self.assigned_rm_id = property_record.rm_id
                self.owner_phone = property_record.phone

                full_owner_name = property_record.name or ''
                extracted_name = full_owner_name

                if 'Mr. ' in full_owner_name:
                    extracted_name = 'Mr. ' + full_owner_name.split('Mr. ')[-1]
                elif 'Ms. ' in full_owner_name:
                    extracted_name = 'Ms. ' + full_owner_name.split('Ms. ')[-1]
                elif 'Mrs. ' in full_owner_name:
                    extracted_name = 'Mrs. ' + full_owner_name.split('Mrs. ')[-1]

                self.owner_name = extracted_name
            else:
                self.property_id = False
                self.assigned_rm_id = False
                self.owner_name = ''
                self.owner_phone = ''

                return {
                    'warning': {
                        'title' : 'Not Found',
                        'message' : 'No property found with the given tag.'
                    }
                }