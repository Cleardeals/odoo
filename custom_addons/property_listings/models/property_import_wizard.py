# -*- coding: utf-8 -*-
import base64
import csv
from io import StringIO
import logging
from odoo import fields, models
from odoo.exceptions import UserError
from datetime import datetime

_logger = logging.getLogger(__name__)

class PropertyImportWizard(models.TransientModel):
    _name = 'property.import.wizard'
    _description = 'Property Listings Import Wizard'

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

    def _clean_float(self, val, default=0.0):
        """Helper to clean and convert to float, handling 'Lacs' and 'Cr' suffixes."""
        cleaned = self._clean_string(val, to_lower=False)
        if cleaned is None:
            return default
        try:
            cleaned = cleaned.lower().replace(',', '').replace(' ', '')
            if 'lacs' in cleaned:
                return float(cleaned.replace('lacs', '')) * 100000
            elif 'cr' in cleaned:
                return float(cleaned.replace('cr', '')) * 10000000
            return float(cleaned)
        except ValueError:
            _logger.warning(f"Invalid float value '{val}', defaulting to {default}.")
            return default

    def _clean_int(self, val, default=0):
        """Helper to clean and convert to int, handling errors."""
        cleaned = self._clean_string(val, to_lower=False)
        if cleaned is None:
            return default
        try:
            return int(cleaned.replace(',', ''))
        except ValueError:
            _logger.warning(f"Invalid int value '{val}', defaulting to {default}.")
            return default

    def _clean_date(self, val, date_formats=['%Y-%m-%d', '%d/%m/%Y']):
        """Helper to clean and parse date strings with multiple formats."""
        cleaned = self._clean_string(val, to_lower=False)
        if cleaned is None:
            return None
        for date_format in date_formats:
            try:
                return datetime.strptime(cleaned, date_format).date()
            except ValueError:
                continue
        _logger.warning(f"Invalid date value '{val}', defaulting to today.")
        return fields.Date.today()

    def _map_selection_field(self, value, field_name):
        """Maps incoming selection field values to valid options."""
        selection_map = {
            'current_status': {
                'tenant-occupied': 'tenant_occupied',
                'self-occupied': 'self_occupied',
                'empty': 'empty',
            },
            'property_status': {
                'live-property': 'live',
                'sold-cd': 'sold',
                'service-expired': 'expired',
                'live': 'live',
                'sold': 'sold',
                'expired': 'expired',
            },
            'furniture_details': {
                'semi-furnished': 'semi_furnished',
                'full-furnished': 'furnished',
                'fully_furnished': 'furnished',
                'unfurnished': 'unfurnished',
                'furnished': 'furnished',
            },
            'service_validity': {
                '1-month': '1',
                '3-months': '3',
                '4-months': '3',  # Map 4-Months to 3 Months
                '5-months': '3',  # Map 5-Months to 3 Months
                '6-months': '6',
                '12-months': '12',
                '1': '1',
                '3': '3',
                '6': '6',
                '12': '12',
            },
            'listing_type': {
                'sell': 'sell',
                'rent': 'rent',
            },
            'property_type': {
                'residential': 'residential',
                'commercial': 'commercial',
            },
            'gst_status': {
                'gst': 'gst',
                'no_gst': 'no_gst',
            }
        }
        if not value or value.lower() in ('not filled', 'n/a', ''):
            return None
        mapped_value = selection_map.get(field_name, {}).get(value.lower(), None)
        if mapped_value is None:
            _logger.warning(f"Invalid value '{value}' for field '{field_name}', returning None.")
        return mapped_value

    def _clean_state_and_get_record(self, state_str, city_str, country_india, state_gujarat, state_maharashtra):
        """Cleans messy state data and returns the correct state record."""
        city_str = self._clean_string(city_str)
        if city_str and 'pune' in city_str.lower():
            return state_maharashtra

        state_str = self._clean_string(state_str)
        if state_str is None:
            state_str = ""

        state_mapping = {
            'gujrat': state_gujarat,
            'gujrata': state_gujarat,
            'gujart': state_gujarat,
            'gujarot': state_gujarat,
        }
        if state_str in state_mapping:
            return state_mapping[state_str]

        if state_str in ('', 'not filled', 'n/a'):
            return state_gujarat

        _logger.warning(f"Unrecognized state '{state_str}', defaulting to Gujarat.")
        return state_gujarat

    def _get_or_create_city(self, city_str, state_record):
        """Finds or creates a city record."""
        city_str = self._clean_string(city_str, to_lower=False)
        if city_str is None:
            return None
        
        city_name = city_str.title()
        City = self.env['res.city']
        
        city = City.search([
            ('name', '=', city_name),
            ('state_id', '=', state_record.id)
        ], limit=1)

        if not city:
            city = City.create({
                'name': city_name,
                'state_id': state_record.id,
            })
        return city

    def _get_or_create_location(self, location_str, city_record):
        """Extracts location from prefixed string and finds or creates it."""
        location_str = self._clean_string(location_str, to_lower=False)
        if location_str is None:
            return None

        clean_location_name = location_str
        if '-' in clean_location_name:
            clean_location_name = clean_location_name.split('-', 1)[1].strip()

        if not clean_location_name:
            return None
            
        Location = self.env['res.location']
        location = Location.search([
            ('name', '=ilike', clean_location_name),
            ('city_id', '=', city_record.id)
        ], limit=1)

        if not location:
            location = Location.create({
                'name': clean_location_name.title(),
                'city_id': city_record.id,
            })
        return location
    
    def _find_user_by_name(self, user_name):
        """Finds an Odoo user by their name and returns their ID."""
        user_name = self._clean_string(user_name, to_lower=False)
        if user_name is None:
            return None
        
        User = self.env['res.users']
        user_record = User.search([('name', '=ilike', user_name)], limit=1)
        
        return user_record.id if user_record else None

    def action_import_properties(self):
        """Main import logic with data cleaning."""
        if not self.csv_file:
            raise UserError("Please upload a CSV file.")

        decoded_file = base64.b64decode(self.csv_file).decode('utf-8')
        reader = csv.DictReader(StringIO(decoded_file))

        # Pre-fetch essential records
        ResCountry = self.env['res.country']
        ResCountryState = self.env['res.country.state']
        country_india = ResCountry.search([('code', '=', 'IN')], limit=1)
        if not country_india:
            raise UserError("Country 'India' with code 'IN' not found. Please ensure it exists.")
        
        state_gujarat = ResCountryState.search([('name', '=ilike', 'Gujarat'), ('country_id', '=', country_india.id)], limit=1)
        state_maharashtra = ResCountryState.search([('name', '=ilike', 'Maharashtra'), ('country_id', '=', country_india.id)], limit=1)
        if not state_gujarat or not state_maharashtra:
            raise UserError("States 'Gujarat' and/or 'Maharashtra' not found for India. Please create them first.")
        
        PropertyListing = self.env['property.listing']
        failed_records = []

        for row in reader:
            customer_name = self._clean_string(row.get('Name'), to_lower=False)
            if not customer_name:
                _logger.warning("Skipping row without customer_name.")
                continue
            
            # Clean and map location data
            state_record = self._clean_state_and_get_record(row.get('State', ''), row.get('City1', ''), country_india, state_gujarat, state_maharashtra)
            city_record = self._get_or_create_city(row.get('City1', ''), state_record)
            location_record = None
            if city_record:
                location_record = self._get_or_create_location(row.get('Location', ''), city_record)
            
            rm_id = self._find_user_by_name(row.get('Assignee)', ''))
            se_id = self._find_user_by_name(row.get('Sales_Executive', ''))

            # Build values dictionary
            vals = {
                'name': customer_name,
                'phone': self._clean_string(row.get('Phone'), to_lower=False),
                # 'email': self._clean_string(row.get('Email'), to_lower=False),
                'property_address': self._clean_string(row.get('Property_Address'), to_lower=False),
                'country_id': country_india.id,
                'state_id': state_record.id if state_record else None,
                'city_id': city_record.id if city_record else None,
                'location_id': location_record.id if location_record else None,
                'tag': self._clean_string(row.get('Tag'), to_lower=False),
                'bhk': self._clean_string(row.get('BHK'), to_lower=False),
                'property_type': self._map_selection_field(row.get('Property_Type'), 'property_type'),
                'residential_type': self._clean_string(row.get('Residential_Property'), to_lower=False),
                'commercial_type': self._clean_string(row.get('Commercial_Property_Type'), to_lower=False),
                'listing_type': self._map_selection_field(row.get('Sell_Rent'), 'listing_type'),
                'current_status': self._map_selection_field(row.get('Current_Status'), 'current_status'),
                #'property_on_floor': self._clean_string(row.get('Property_on_Floor'), to_lower=False),
                #'property_facing': self._clean_string(row.get('Property_Facing'), to_lower=False),
                #'lift_per_block': self._clean_string(row.get('No_Lift_per_Block'), to_lower=False),
                #'furniture_details': self._map_selection_field(row.get('Furniture_Details'), 'furniture_details'),
                #'age_of_property': self._clean_string(row.get('Age_of_Property'), to_lower=False),
                #'parking_details': self._clean_string(row.get('Parking_Details'), to_lower=False),
                #'bathroom': self._clean_string(row.get('Bathroom'), to_lower=False),
                #'super_built_up_plot_space': self._clean_string(row.get('Super_Built_up_Plot_Space'), to_lower=False),
                #'super_built_up_construction_area': self._clean_string(row.get('Super_Built_up_Construction_Area'), to_lower=False),
                #'carpet_construction_area': self._clean_string(row.get('Carpet_Construction_Area'), to_lower=False),
                #'carpet_plot_area': self._clean_string(row.get('Carpet_Plot_Area'), to_lower=False),
                
                #payment_package': self._clean_string(row.get('Payment_Package'), to_lower=False),
                ##'form_number': self._clean_string(row.get('Form_Number'), to_lower=False),
                #'property_price': self._clean_float(row.get('Property_Price')),
                #'payment_mode': self._clean_string(row.get('Payment_Mode'), to_lower=False),
                #'receipt_number': self._clean_string(row.get('Receipt_Number'), to_lower=False),
                #'service_validity': self._map_selection_field(row.get('Service_Validity'), 'service_validity'),
                #'package_amount': self._clean_float(row.get('Package_Amount')),
                #'net_amount': self._clean_float(row.get('Net_Amount')),
                #'due_amount': self._clean_float(row.get('Due_Amount')),
                #'total_package_amount': self._clean_float(row.get('Total_Package_Amount')),
                #'inventory_count': self._clean_int(row.get('Inventory_Count'), default=1),
                #'property_register_date': self._clean_date(row.get('Property_Register_Date')),
                #'gst_status': self._map_selection_field(row.get('GST_Status'), 'gst_status'),
                'rm_id': rm_id,
                'sales_executive_id': se_id,
                'property_link': self._clean_string(row.get('Property_Link'), to_lower=False),
                #'link_360_dgt': self._clean_string(row.get('Link_360_DGT'), to_lower=False),
                #'property_status': self._map_selection_field(row.get('Property_Status'), 'property_status'),
                #'property_sold_date': self._clean_date(row.get('Property_Sold_Date')),
                #'reason_for_unsold': self._clean_string(row.get('Reason_for_Unsold'), to_lower=False),
                #'instagram_reel': self._clean_string(row.get('Instagram_REEL')) == 'yes',
                #'id_99acres': self._clean_string(row.get('99acres_ID'), to_lower=False),
                #'id_housing': self._clean_string(row.get('Housing_ID'), to_lower=False),
                #'id_magicbricks': self._clean_string(row.get('Magicbricks_ID'), to_lower=False),
                #'id_olx': self._clean_string(row.get('OLX_ID'), to_lower=False),
            }

            # Create record with transaction handling
            try:
                with self.env.cr.savepoint():
                    PropertyListing.create(vals)
            except Exception as e:
                _logger.error(f"Error creating property listing for {customer_name}: {str(e)}")
                failed_records.append({'customer_name': customer_name, 'error': str(e)})
                continue

        # Log summary of failed records
        if failed_records:
            error_summary = "\n".join([f"{rec['customer_name']}: {rec['error']}" for rec in failed_records])
            _logger.warning(f"Import completed with {len(failed_records)} failed records:\n{error_summary}")
            raise UserError(f"Import completed with errors. {len(failed_records)} records failed:\n{error_summary}")

        return {'type': 'ir.actions.client', 'tag': 'reload'}