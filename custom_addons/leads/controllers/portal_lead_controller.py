import json
import logging
from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

class PortalWebhookController(http.Controller):

    @http.route('/api/v1/magicbricks_webhook', type='http', auth='public', methods=['POST'], csrf=False)
    def handle_magicbricks_lead(self, **kwargs):
        """
        DEDICATED "Fast Lane" webhook for MagicBricks.
        It translates their payload to our 'leads.new' model.
        """

        # API KEY AUTHENTICATION
        try:
            # Get the key from the request header
            sent_key = request.httprequest.headers.get('X-API-KEY')

            # Get the correct key from Odoo's system parameters
            correct_key = request.env['ir.config_parameter'].sudo().get_param('magicbricks.api.key')

            # Compare the keys
            if not sent_key or not correct_key or sent_key != correct_key:
                _logger.warning("MagicBricks Webook: Failed auth, invalid API key.")
                return Response("Failed to Push Lead: Invalid API Key", status=401, mimetype='text/plain')
        
        except Exception as auth_err:
            _logger.error(f"MagicBricks Webhook: Auth check failed: {auth_err}")
            return Response("Failed to Push Lead: Internal Server Error", status=500, mimetype='text/plain')   


        data = json.loads(request.httprequest.data)

        try:
            # Validation
            required_fields = ['name', 'mobile', 'email', 'property_id']
            missing = [field for field in required_fields if not data.get(field)]
            

            if missing:
                _logger.warning(f"MagicBricks webhook rejected: Missing required Fields: {missing}. Data: {data}")
                return Response("Failed to push lead: Missing required fields.", status=400)
            
            #2. Translate MagicBricks fields to our leads.new fields

            lead_vals = {
                'name': data.get('name'),
                'phone': data.get('mobile'),
                'email': data.get('email'),
                'project_name': data.get('project'),
                'portal_name': 'MagicBricks',
                'portal_property_id': data.get('property_id'),
                'raw_data': json.dumps(data, indent=2),
                'state': 'new',
            }

            # 3. Create the basic lead record
            LeadModel = request.env['leads.new'].sudo()
            new_lead = LeadModel.create_lead_if_not_duplicate(lead_vals)

            # 4. Process the lead synchronously (removed queue_job dependency)
            if new_lead:
                try:
                    new_lead._process_lead_logic()
                    _logger.info(f"MagicBricks Lead processed successfully: {new_lead.name}")
                except Exception as process_err:
                    _logger.error(f"Failed to process MagicBricks lead {new_lead.name}: {process_err}")
                    # Lead is created but processing failed - can be retried later

            # 5. send success response
            return Response("Success: Lead punched in the CRM", status=200, mimetype='text/plain')

        except Exception as e:
            _logger.error(f"MagicBricks Webhook Exception: {e}. Raw data: {data}")
            return Response(f"Failed to Push Lead: {str(e)}", status=500, mimetype='text/plain')
        
    @http.route('/api/v1/99acres_webhook', type='http', auth='public', methods=['POST'], csrf=False)
    def handle_99acres_lead(self, **kwargs):
        """
        DEDICATED "Fast Lane" webhook for 99acres.
        It translates their payload to our 'leads.new' model.
        """

        # API KEY AUTHENTICATION
        try:
            # Get the key from the request header
            sent_key = request.httprequest.headers.get('X-API-KEY')

            # Get the correct key from Odoo's system parameters
            correct_key = request.env['ir.config_parameter'].sudo().get_param('99acres.webhook.api.key')

            # Compare the keys
            if not sent_key or not correct_key or sent_key != correct_key:
                _logger.warning("99acres Webook: Failed auth, invalid API key.")
                return Response("Failed to Push Lead: Invalid API Key", status=401, mimetype='text/plain')
        
        except Exception as auth_err:
            _logger.error(f"99acres Webhook: Auth check failed: {auth_err}")
            return Response("Failed to Push Lead: Internal Server Error", status=500, mimetype='text/plain')   


        data = json.loads(request.httprequest.data)

        try:
            # Validation
            required_fields = ['Name', 'Phone', 'ProdId']
            missing = [field for field in required_fields if not data.get(field)]
            

            if missing:
                _logger.warning(f"99acres webhook rejected: Missing required Fields: {missing}. Data: {data}")
                return Response("Failed to push lead: Missing required fields.", status=400)
            
            #2. Translate 99acres fields to our leads.new fields

            lead_vals = {
                'name': data.get('Name'),
                'phone': data.get('Phone'),
                'email': data.get('EmailId'),
                'project_name': data.get('Project'),
                'portal_name': '99acres',
                'portal_property_id': data.get('ProdId'),
                'raw_data': json.dumps(data, indent=2),
                'state': 'new',
            }

            # 3. Create the basic lead record
            LeadModel = request.env['leads.new'].sudo()
            new_lead = LeadModel.create_lead_if_not_duplicate(lead_vals)

            # 4. Process the lead synchronously (removed queue_job dependency)
            if new_lead:
                try:
                    new_lead._process_lead_logic()
                    _logger.info(f"99acres Lead processed successfully: {new_lead.name}")
                except Exception as process_err:
                    _logger.error(f"Failed to process 99acres lead {new_lead.name}: {process_err}")
                    # Lead is created but processing failed - can be retried later

            return Response("Success: Lead punched in the CRM", status=200, mimetype='text/plain')
        
        except Exception as e:
            _logger.error(f"99acres Webhook Exception: {e}. Raw data: {data}")
            return Response(f"Failed to Push Lead: {str(e)}", status=500, mimetype='text/plain')