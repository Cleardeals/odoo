from odoo import models, fields, api
import logging
import xml.etree.ElementTree as ET
from datetime import timedelta
import urllib.request
import urllib.parse
import urllib.error
import json

_logger = logging.getLogger(__name__)   

class NewPortalLead(models.Model):
    _name = 'leads.new'
    _description = "New Leads from Portals"
    _order = 'create_date desc'

    # Lead Fields

    name = fields.Char('Lead Name', required=True, index=True)
    phone = fields.Char('Phone Number', index=True)
    email = fields.Char('Email Address', index=True)   
    portal_name = fields.Char('Portal Source', help="e.g., Magicbricks, 99acres")
    project_name = fields.Char('Project Name', help="Project Name from portal")
    portal_property_id = fields.Char('Portal Property ID', help="The property ID as per the portal", index=True)
    raw_data = fields.Text('Raw Data Dump')

    # Processing and Assignment Fields

    state = fields.Selection([
        ('new', 'New'),
        ('assigned', 'Assigned'),
        ('failed', 'Failed Assignment'),
    ], default='new', required=True, index=True, copy=False)

    property_id = fields.Many2one('property.inventory', string='Related Property')
    user_id = fields.Many2one('res.users', string='Assigned RM', copy=False)
    process_notes = fields.Text('Processing Notes')

    def _find_property(self):
        """ Finds the synced property based on the portal name and the portal ID."""

        self.ensure_one()
        portal = self.portal_name
        portal_pid = self.portal_property_id

        if not portal or not portal_pid:
            return self.env['property.inventory']
        
        portal_field_map = {
            'MagicBricks': 'magicbricks_id',
            '99acres' : 'ninety_nine_acres_id',
            'Housing.com': 'housing_id',
            'OLX' : 'olx_id',
        }

        field_to_search = portal_field_map.get(portal)

        if not field_to_search:
            _logger.warning(f"Lead {self.id}: No field mapping for portal '{portal}'")
            return self.env['property.inventory']
        
        # Build the dynamic domain
        domain = [
            (field_to_search, '=', portal_pid)
        ]

        _logger.info(f"Searching for property with domain: {domain}")
        return self.env['property.inventory'].search(domain, limit=1)
    
    def _find_rm(self, property_id):
        """ Finds the correct RM from the property record."""
        self.ensure_one()
        
        if property_id and property_id.rm_user_id:
            return property_id.rm_user_id
        
        # Fallback: Assign to the administrator if no RM is found on the property
        _logger.warning(f"Property {property_id.property_tag} has no RM. Assigning to admin")
        return self.env.ref('base.user_admin')
    
    def _process_lead_logic(self):
        """
        The slow job. This runs in the background via a queue job
        """
        self.ensure_one()
        if self.state != 'new':
            _logger.info(f"Skipping lead {self.id}, state is {self.state}")
            return
        
        try:
            # 1. Try to find the matching property
            property_rec = self._find_property()
            
            if not property_rec:
                # Data Lag: Property not found
                self.process_notes = f"Attempt {fields.Datetime.now()}: Property not found for {self.portal_name} ID: {self.portal_property_id}\n"
                return
            
            # 2. Try to find the correct RM
            rm_user = self._find_rm(property_rec)

            # 3. Success assign the lead.
            self.write({
                'property_id': property_rec.id,
                'user_id': rm_user.id,
                'state': 'assigned',
                'process_notes': f"Successfully assigned to RM {rm_user.name} for property {property_rec.property_tag}.\n"
            })

        except Exception as e:
            _logger.error(f"Failed to process lead {self.id}: {e}")
            self.write({
                'state': 'failed',
                'process_notes': f"Processing failed with error: {str(e)}\n"
            })

    # Assigning Unassigned leads cron job
    @api.model
    def _cron_reprocess_unassigned_leads(self):
        """ Called by the 4 hour cron to find and requeue leads
            that are still 'new' due to data lag.
        """

        _logger.info("CRON: Starting re-process for unassigned leads...")
        domain = [
            ('state', '=', 'new'),
            ('create_date', '<', fields.Datetime.now() - fields.Date.timedelta(hours=1))
        ]
        leads_to_retry = self.search(domain)
        _logger.info(f"CRON: Found {len(leads_to_retry)} unassigned leads to reprocess.")

        for lead in leads_to_retry:
            lead.with_delay(
                description=f"RETRY: Processing portal lead ID {lead.id}: {lead.name}"
            )._process_lead_logic()


    def _api_fetch_99acres(self):
        """
        Builds the XML, sends the POST request to 99acres, and returns a list of leads.
        """
        _logger.info("Attempting to fetch leads from 99acres API...")

        API_URL = "https://www.99acres.com/99api/v1/getmy99Response/OeAuXClO43hwseaXEQ/uid/"
        DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

        # Get credentials from Odoo System Parameters
        config = self.env['ir.config_parameter'].sudo()
        username = config.get_param('99acres.api.username')
        password = config.get_param('99acres.api.password')

        if not username or not password:
            _logger.error("CRITICAL: 99acres.api.username or .password not set in system parameters.")
            return []
        
        # 2. Set time range: 20 minutes ago to now
        now = fields.Datetime.now()
        start_time = fields.Datetime.subtract(now, minutes=20)
        start_date = start_time.strftime(DATE_FORMAT)
        end_date = now.strftime(DATE_FORMAT)

        # 3. Build the XML request body
        xml_request = f"""<?xml version='1.0'?>
        <query>
            <user_name>{username}</user_name>
            <pswd>{password}</pswd>
            <start_date>{start_date}</start_date>
            <end_date>{end_date}</end_date>
        </query>"""

        # 4. Build POST data using urllib
        payload = {'xml': xml_request}
        # Encode the payload into bytes
        data = urllib.parse.urlencode(payload).encode('utf-8')

        _logger.info(f"99acres: Requesting leads from {start_date} to {end_date}")

        # 5. Make the API call 
        try:
            req = urllib.request.Request(API_URL, data=data, method='POST')

            # Open the url
            with urllib.request.urlopen(req, timeout=30) as response:
                # Read and decode the response
                response_body = response.read().decode('utf-8')

                # Check for HTTP success
                if response.status != 200:
                    _logger.error(f"99acres HTTP Error: {response.status} | Response: {response_body}")
                    return []
                
                # 6. Parse the XML response
                return self._parse_99acres_response(response_body)

        except urllib.error.HTTPError as e:
            # Handle the HTTP Errors
            _logger.error(f"99acres HTTPError: {e.code} - {e.reason}")
            try:
                # Try to read the error body
                _logger.error(f"Response Body: {e.read().decode('utf-8')}")
            except Exception:
                pass
        
        except urllib.error.URLError as e:
            # Handle other errors 
            _logger.error(f"99acres URLError: {e.reason}")
        except Exception as e:
            _logger.error(f"Error Fetching 99acres leads: {e}")
        
        return []
    
    def _parse_99acres_response(self, xml_string):
        """
        Parses the XML String and returns a list of lead dicitionaries.
        """
        _logger.info("Parsing 99acres response XML...")
        leads_list = []
        try:
            root = ET.fromstring(xml_string)

            # Check for API error
            if root.get('ActionStatus') == 'False':
                error_msg = root.findtext('.//Message', 'Unknown error')
                _logger.error(f"99acres API Error: {error_msg}")
                return []
            
            for resp in root.findall('Resp'):
                try:
                    qry_dtl = resp.find('QryDtl')
                    cntct_dtl = resp.find('CntctDtl')
                    if qry_dtl is None or cntct_dtl is None:
                        _logger.warning("Skipping a Resp entry due to missing QryDtl or CntctDtl.")
                        continue

                    # Translate their field names to the keys our
                    # _cron_pull_external_leads method expects.
                    lead_data = {
                        'lead_name': cntct_dtl.findtext('Name'),
                        'lead_email': cntct_dtl.findtext('Email'),
                        'lead_mobile': cntct_dtl.findtext('Phone'),
                        'project' : qry_dtl.findtext('CmpctLabl', 'N/A'),
                        'property_code': qry_dtl.findtext('ProdId', 'N/A'),
                        'raw_json': {
                            'QueryInfo': qry_dtl.findtext('QryInfo', 'N/A'),
                            'ReceivedOn': qry_dtl.findtext('RcvdOn', 'N/A'),
                            'ResponseType': qry_dtl.findtext('ResType', 'N/A'),
                        }
                    }
                    leads_list.append(lead_data)
                except Exception as e:
                    _logger.warning(f"Error parsing one 99acres lead: {str(e)}")
                
            _logger.info(f"99acres: Parsed {len(leads_list)} leads")
            return leads_list 
        
        except ET.ParseError as e:
            _logger.error(f"Failed to parse 99acres XML response: {e}")
            return []
        
    def _api_fetch_housing(self):
        """ Placeholder for future Housing.com API integration."""
        return []

    @api.model
    def _cron_pull_external_leads(self):
        """
        Called by the 15 minutes cron to pull leads from all
        non-webhook portals and create leads.new records.
        """
        portal_mappers = {
            '99acres': self._api_fetch_99acres,
            'Housing.com': self._api_fetch_housing,
        }
        
        for portal_name, fetch_method in portal_mappers.items():
            try:
                # 1. Call the specific API fetch method
                leads = fetch_method()

                # 2. Process the results
                _logger.info(f"CRON: Found {len(leads)} leads from {portal_name} API.")
                for lead in leads:
                    # 3. Create the leads.new record
                    lead_vals = {
                        'name': lead.get('lead_name'),
                        'phone': lead.get('lead_mobile'),
                        'email': lead.get('lead_email'),
                        'project_name': lead.get('project'),
                        'portal_name': portal_name,
                        'portal_property_id': lead.get('property_code'),
                        'raw_data': json.dumps(lead.get('raw_json') or lead, indent=2),
                        'state': 'new',
                    }
                    new_lead = self.create(lead_vals)

                    # 4. Enqueue the processing job
                    new_lead.with_delay(
                        description = f"Processing {portal_name} Lead: {new_lead.name}"
                    )._process_lead_logic()

            except Exception as e:
                _logger.error(f"Failed to pull leads from {portal_name} API: {e}")
