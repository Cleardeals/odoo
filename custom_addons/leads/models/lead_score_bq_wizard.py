import logging
from google.cloud import bigquery
from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class LeadScoreBqWizard(models.TransientModel):
    _name = "lead.score.bq.wizard"
    _description = "BigQuery Lead Fetch Wizard"

    # state management for the wizard

    state = fields.Selection([
        ('init', 'Initial State'),
        ('done', 'Done')
    ], default='init', string='State')

    # Fiields to display the results to the user.

    leads_created = fields.Integer(string="Leads Created", readonly=True)
    leads_updated = fields.Integer(string="Leads Updated", readonly=True)

    def action_fetch_from_bigquery(self):
        """The main logic to connect to BQ and process records. """

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
        SELECT * 
        FROM `cleardeals-459513.lead_scoring.whatsapp_automation_list`
        WHERE standardized_phone IS NOT NULL
    """
        
        try:
            results = client.query(query).result()
            _logger.info("Fetched %s rows from BigQuery.", results.total_rows)
        except Exception as e:
            raise UserError(f"Failed to execute query: {str(e)}")
        
        LeadScore = self.env['lead.score']

        created_count = 0
        updated_count = 0

        for row in results:
            phone = row.get('standardized_phone')
            vals = {
                'name': row.get('customer_name'),
                'standardized_phone': phone,
                'predicted_score': row.get('predicted_score') or 0.0,
                'current_status': row.get('current_status') or 'lead',
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

            # Special handling for Many2One fields
            rm_name = row.get('assigned_rm')
            if rm_name:
                user = self.env['res.users'].search([('name', '=', rm_name)], limit=1)
                if user:
                    vals['assigned_rm_id'] = user.id
                else:
                    _logger.warning("Assigned RM '%s' not found in Odoo users.", rm_name)
            
            # Special Handling for date fields

            site_visit_str = row.get('site_visit_date')
            if site_visit_str:
                try:
                    date_obj = fields.datetime.strptime(site_visit_str, "%d/%m/%Y").date()
                    vals['site_visit_scheduled_date'] = date_obj
                except (ValueError, TypeError):
                    _logger.warning("Invalid date format for site_visit_date: %s for lead %s", site_visit_str, phone)

            # Perform the create or update logic based on standardized phone
            existing_lead = LeadScore.search([('standardized_phone', '=', phone)], limit=1)
            if existing_lead:
                existing_lead.write(vals)
                updateed_count += 1
            else:
                LeadScore.create(vals)
                created_count += 1
        
        self.write({
            'leads_created': created_count,
            'leads_updated': updated_count,
            'state': 'done'
        })

        return {
            'type': 'ir.actions.act_window',
            'name': 'BigQuery Fetch Result',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }