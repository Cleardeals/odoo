# -*- coding: utf-8 -*-
import base64
import csv
from io import StringIO
import logging
from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class LeadImportWizard(models.TransientModel):
    _name = 'lead.import.wizard'
    _description = 'Lead Scoring Import Wizard'

    csv_file = fields.Binary(string="CSV File", required=True)
    file_name = fields.Char(string="File Name")

    def _clean_string(self, val, to_lower=True):
        """Helper to clean string values, handling nulls and placeholders."""
        if not val:
            return None
        clean_val = val.strip()
        if clean_val.lower() in ('', 'not filled', 'n/a', 'null'):
            return None
        return clean_val.lower() if to_lower else clean_val

    def _find_user_by_name(self, user_name):
        """Finds an Odoo user by their name with fuzzy matching."""
        user_name = self._clean_string(user_name, to_lower=False)
        _logger.info(f"Searching for user: '{user_name}'")
        if user_name is None:
            _logger.warning("User name is None after cleaning, defaulting to Admin.")
            return self.env.ref('base.user_admin').id

        User = self.env['res.users']
        user_record = User.search([('name', '=ilike', user_name)], limit=1)
        
        if not user_record:
            _logger.warning(f"User '{user_name}' not found, defaulting to Admin.")
            return self.env.ref('base.user_admin').id

        return user_record.id

    def _find_property_by_name(self, property_name):
        """Finds a property listing by its title and returns its ID."""
        if not property_name or property_name.strip().lower() in ('', 'not filled', 'n/a'):
            return None
        Property = self.env['property.listing']
        # This assumes property names are unique. If not, this will pick the first one it finds.
        property_record = Property.search([('name', '=ilike', property_name.strip())], limit=1)
        return property_record.id if property_record else None

    def _clean_lead_status(self, status_str):
        """Maps the status from the CSV to the keys in the Odoo selection field."""
        if not status_str:
            return 'lead' # Default value

        status_map = {
            'busy': 'busy',
            'lead': 'lead',
            'ringing': 'ringing',
            'call back later': 'call_back_later',
            'site visit scheduled': 'site_visit_scheduled',
            'option not matching requirements': 'option_not_matching_requirements',
            'details shared of property': 'details_shared_of_property',
            'no requiremnets' : 'no_requirements',
            'details shared and interested for site visit': 'details_shared_and_interested_for_site_visit',
            'switched off': 'switched_off',
            'requirement closed': 'requirement_closed',
            'property sold out': 'property_sold_out',
            'rescheduled': 'rescheduled',
            'budget not sufficient': 'budget_not_sufficient',
            'number not in use/wrong number': 'number_not_in_use_wrong_number',
            'others': 'other',

        }
        return status_map.get(status_str.strip().lower(), 'lead') # Default to 'lead' if not found

    def action_import_leads(self):
        """ The main logic for parsing the CSV and creating lead score records. """
        if not self.csv_file:
            raise UserError("Please upload a CSV file.")

        decoded_file = base64.b64decode(self.csv_file).decode('utf-8')
        reader = csv.DictReader(StringIO(decoded_file))

        LeadScore = self.env['lead.score']
        
        for row in reader:
            lead_name = row.get('customer_name', '').strip()
            if not lead_name:
                continue

            # Find related records
            rm_id = self._find_user_by_name(row.get('assigned_rm'))
            #property_id = self._find_property_by_name(row.get('Project_Name'))
            
            # Clean and map the status
            lead_state = self._clean_lead_status(row.get('current_status'))

            try:
                vals = {
                    'name': lead_name,
                    'standardized_phone': row.get('standardized_phone', '').strip(),
                    'predicted_score': float(row.get('predicted_score') or 0.0),
                    'current_status': lead_state,

                    # Link to other models
                    'assigned_rm_id': rm_id,
                    #'property_id': property_id,
                    'project_name': row.get('Project_Name', '').strip(),
                    'property_type': row.get('Property_Type', '').strip(),
                    'property_tag': row.get('property_tag', '').strip(),
                    'property_address': row.get('Property_Address', '').strip(),
                    'bhk': row.get('BHK', '').strip(),
                    'price_range': row.get('Price_Range_Lacs_Rs', '').strip(),
                    'carpet_area': row.get('Carpet_Construction_Area', '').strip(),
                    'super_built_up_area': row.get('Super_Built_up_Construction_Area', '').strip(),
                    'property_link': row.get('Property_Link', '').strip(),
                    'location': row.get('Location', '').strip(),
                    'property_on_floor': row.get('Property_On_Floor', '').strip(),
                    'property_facing': row.get('Property_Facing', '').strip(),
                    'furniture_details': row.get('Furniture_Details', '').strip(),
                    'age_of_property': row.get('Age_Of_Property', '').strip(),
                    'parking_details': row.get('Parking_Details', '').strip(),
                    'offer_price': row.get('Offer_Price', '').strip(),
                    'bathroom': row.get('Bathroom', '').strip(),
                    
                    # Fields for RM Interaction
                    'state': lead_state,
                    'site_visit_scheduled_date': row.get('site_visit_date') or None,
                }
                LeadScore.create(vals)
            except (ValueError, TypeError) as e:
                _logger.warning(f"Could not import lead '{lead_name}' due to a data conversion error: {e}")
                continue
            
        return {'type': 'ir.actions.client', 'tag': 'reload'}