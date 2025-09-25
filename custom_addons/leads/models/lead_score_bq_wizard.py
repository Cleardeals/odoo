import logging
from google.cloud import bigquery
from odoo import fields, models
from odoo.exceptions import UserError
from datetime import datetime

_logger = logging.getLogger(__name__)

class LeadScoreBqWizard(models.TransientModel):
    _name = "lead.score.bq.wizard"
    _description = "BigQuery Lead Fetch Wizard"

    state = fields.Selection([
        ('init', 'Initial State'),
        ('done', 'Done')
    ], default='init', string='State')
    leads_created = fields.Integer(string="Leads Created", readonly=True)
    leads_updated = fields.Integer(string="Leads Updated", readonly=True)

    def action_fetch_from_bigquery(self):
        """The main logic to connect to BQ and process records."""
        self.ensure_one()

        config_param = self.env['ir.config_parameter'].sudo()
        project_id = config_param.get_param('google.bq.project_id')

        if not project_id:
            raise UserError("BigQuery Project ID is not configured. Please set 'google.bq.project_id' in system parameters.")
        
        try:
            client = bigquery.Client(project=project_id)
            client.list_datasets(max_results=1) 
            _logger.info("Successfully connected to BigQuery project %s.", project_id)
        except Exception as e:
            _logger.error("Failed to connect to BigQuery: %s", str(e))
            raise UserError(f"Failed to connect to BigQuery: {str(e)}")
        
        query = """
        SELECT * FROM `cleardeals-459513.lead_scoring.whatsapp_automation_list`
        WHERE standardized_phone IS NOT NULL
        """
        
        try:
            results = client.query(query).result()
            _logger.info("Fetched %s rows from BigQuery.", results.total_rows)
        except Exception as e:
            raise UserError(f"Failed to execute query: {str(e)}")
        
        LeadScore = self.env['lead.score']
        status_mapping = {
            'site visit scheduled': 'site_visit_scheduled',
            'busy': 'busy',
            'lead': 'lead',
            'ringing': 'ringing',
            'call back later': 'call_back_later',
            'call back from client': 'call_back_later',
            'sales-lead-ops': 'lead',
            'option not matching requirements': 'option_not_matching_requirements',
            'details shared of property': 'details_shared_of_property',
            'no requirements': 'no_requirements',
            'details shared and interested for site visit': 'details_shared_and_interested_for_site_visit',
            'switched off': 'switched_off',
            'requirement closed': 'requirement_closed',
            'property sold out': 'property_sold_out',
            'rescheduled': 'rescheduled',
            'budget not sufficient': 'budget_not_sufficient',
            'number not in use/wrong number': 'number_not_in_use_wrong_number',
            'other': 'other',
        }

        created_count = 0
        updated_count = 0
        unmatched_rms = set()

        for row in results:
            phone = row.get('standardized_phone')
            if not phone:
                continue

            raw_status = row.get('current_status') or 'lead'
            mapped_status = status_mapping.get(raw_status.lower(), 'lead')

            vals = {
                'name': row.get('customer_name'),
                'standardized_phone': phone,
                'predicted_score': row.get('predicted_score') or 0.0,
                'current_status': mapped_status,
                'project_name': row.get('Project_Name'),
                'property_tag': row.get('property_tag'),
                'property_address': row.get('Property_Address'),
                'bhk': row.get('BHK'),
                'price_range': row.get('Price_Range_Lacs_Rs'),
                'carpet_area': row.get('Carpet_Construction_Area'),
                'super_built_up_area': row.get('Super_Built_up_Construction_Area'),
                'property_link': row.get('Property_Link'),
                'location': row.get('Location'),
                'property_on_floor': row.get('Property_On_Floor'),
                'property_facing': row.get('Property_Facing'),
                'furniture_details': row.get('Furniture_Details'),
                'age_of_property': row.get('Age_Of_Property'),
                'parking_details': row.get('Parking_Details'),
                'offer_price': row.get('Offer_Price'),
                'bathroom': row.get('Bathroom'),
            }

            rm_name = row.get('assigned_rm')
            if rm_name:
                user = self.env['res.users'].search([('name', '=ilike', rm_name.strip())], limit=1)
                if user:
                    vals['assigned_rm_id'] = user.id
                else:
                    unmatched_rms.add(rm_name)
                    _logger.warning("Assigned RM '%s' not found for lead %s", rm_name, phone)
            
            # The site_visit_date is now handled conditionally inside the update logic,
            # so we prepare the value but don't add it to 'vals' just yet.
            site_visit_date_obj = None
            site_visit_str = row.get('site_visit_date')
            if site_visit_str:
                try:
                    site_visit_date_obj = datetime.strptime(site_visit_str, '%d/%m/%Y').date()
                    vals['site_visit_scheduled_date'] = site_visit_date_obj
                except (ValueError, TypeError):
                    _logger.warning("Invalid date format for site_visit_date: %s for lead %s", site_visit_str, phone)

            try:
                existing_lead = LeadScore.search([('standardized_phone', '=', phone)], limit=1)

                if not existing_lead:
                    LeadScore.create(vals)
                    created_count += 1
                    continue

                # --- UPDATED LOGIC FOR HANDLING EXISTING LEADS ---

                # 1. (NEW) If status is site visit scheduled/rescheduled, check for date mismatch.
                if existing_lead.current_status in ['site_visit_scheduled', 'rescheduled']:
                    odoo_date = existing_lead.site_visit_scheduled_date
                    
                    # Compare only if both dates are available.
                    if site_visit_date_obj and odoo_date and site_visit_date_obj != odoo_date:
                        _logger.info(
                            f"Skipping update for {phone}: Site visit date mismatch. "
                            f"Odoo ({odoo_date}) is preserved over BQ ({site_visit_date_obj})."
                        )
                        continue # Skip entire update, preserving Odoo data

                # 2. If status is 'rescheduled', skip data update but "touch" the record.
                # This acts as a fallback if the date check above didn't apply.
                if existing_lead.current_status == 'rescheduled':
                    existing_lead.write({})
                    _logger.info(f"Skipping update for {phone}: Odoo status is 'rescheduled'.")
                    continue
                
                # 3. If feedback is filled, skip the update.
                if existing_lead.feedback:
                    if existing_lead.feedback == 'visit_needs_to_be_rescheduled':
                        existing_lead.write({})
                        _logger.info(f"Skipping update for {phone}: Feedback requires rescheduling.")
                    else:
                        _logger.info(f"Skipping update for {phone}: Feedback is already filled in Odoo.")
                    continue
                
                # If no skip conditions are met, perform the update.
                existing_lead.write(vals)
                updated_count += 1

            except Exception as e:
                _logger.error("Error processing lead %s: %s", phone, str(e))
                continue

        if unmatched_rms:
            _logger.warning("Unmatched RM names: %s", ", ".join(unmatched_rms))

        self.write({
            'leads_created': created_count,
            'leads_updated': updated_count,
            'state': 'done'
        })

        return {
            'type': 'ir.actions.act_window',
            'name': 'BigQuery Import Result',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }