from odoo import models, fields, api
import logging
import xml.etree.ElementTree as ET
from datetime import timedelta
import urllib.request
import urllib.parse
import urllib.error
import json
import requests
import hmac
import hashlib
import time
import re

_logger = logging.getLogger(__name__) 

class NewPortalLead(models.Model):
    _name = 'leads.new'
    _inherit = ['mail.thread', 'mail.activity.mixin']
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

    remarks = fields.Text('Remarks')

    site_visit_date = fields.Datetime(
        string="Site Visit Scheduled On",
        copy = False,
        index = True,
        tracking = True
    )

    site_visit_date_only = fields.Date(
        string="Site Visit Date (Main Property)",
        compute='_compute_site_visit_date_only',
        store=True, # Essential for filtering
        readonly=True
    )

    first_contact_datetime = fields.Datetime(
        string="First Contact On",
        readonly=True,
        copy=False,
        tracking=True
    )

    property_id = fields.Many2one('property.inventory', string='Related Property')
    user_id = fields.Many2one('res.users', string='Assigned RM', copy=False)

    property_bhk = fields.Char(
        related = 'property_id.bhk',
        string = 'Property BHK',
        readonly = True,
        store=True
    )

    property_location = fields.Char(
        related='property_id.location', 
        string="Property Location", 
        readonly=True, 
        store=True
    )

    property_city = fields.Char(
        related='property_id.city', 
        string="Property City", 
        readonly=True, 
        store=True
    )

    property_owner_name = fields.Char(
        related='property_id.owner_name', 
        string="Property Owner", 
        readonly=True,
        store=True
    )

    property_link = fields.Char(
        related='property_id.property_link',
        string="Property Link",
        readonly=True
    )

    process_notes = fields.Text('Processing Notes')

    phone_whatsapp_url = fields.Char(
        string="WhatsApp URL",
        compute='_compute_phone_whatsapp_url',
        store=False
    )

    phone_whatsapp_html = fields.Html(
        string="Phone",
        compute='_compute_phone_whatsapp_url',
        store=False
    )

    # Field for webhook queue
    is_webhook_sent = fields.Boolean(
        string="Webhook Sent",
        default=False,
        copy=False,
        index=True,
        help = "Tracks if this lead has been sent to the n8n webhook."
    )

    interest_ids = fields.One2many(
        'lead.property.interest',
        'lead_id',
        string="Recommended Properies"
    )

    create_date_only = fields.Date(
        string="Creation Date",
        compute='_compute_create_date_only',
        store=True, # 'store=True' is ESSENTIAL for it to be searchable
        readonly=True
    )
    


    @api.model
    def _standardize_phone(self, phone_number):
        """
        Strips all non-numeric characters from the phone number
        and returns a 10-digit number if possible.
        """
        if not phone_number:
            return ''
        
        numeric_phone = re.sub(r'\D', '', phone_number)

        # Check if it starts with 91 and is 12 digits long
        if len(numeric_phone) == 12 and numeric_phone.startswith('91'):
            return numeric_phone[2:]
        
        # Check if it's already 10 digits
        if len(numeric_phone) == 10:
            return numeric_phone
        
        _logger.warning(f"Phone number {phone_number} could not be standardized.")
        return numeric_phone  # Return as-is if it doesn't fit expected formats
    

    @api.model_create_multi
    def create(self, vals_list):
        # Create the new lead(s) first
        new_leads = super(NewPortalLead, self).create(vals_list)
        
        # --- NOTIFICATION LOGIC (CORRECTED) ---
        channel = "leads.new"
        notification_type = "bus_notification"
        message = {
            'ids': new_leads.ids,
            'model': 'leads.new',
            'event': 'create'
        }
        
      
        # --- CORRECTED LINE ---
        # Use _sendone() as the log helpfully suggested
        self.env['bus.bus']._sendone(channel, notification_type, message)
        # --- END CORRECTION ---
        
        return new_leads
    
    @api.model
    def create_lead_if_not_duplicate(self, lead_vals):
        """
        Central Function to create leads.
        Checks for duplicates before creating new lead.
        A duplicate is same phone + same portal_property_id in last 30 days.
        """
        phone_raw = lead_vals.get('phone')
        phone_clean = self._standardize_phone(phone_raw)
        portal_prop_id = lead_vals.get('portal_property_id')

        lead_vals['phone'] = phone_clean

        # if we don't have a phone or propertyID, we can't check for duplocates, so we just create the lead
        if not phone_clean or not portal_prop_id:
            _logger.info("Cannot check for duplicate (missing phone/prop_id), creating lead.")
            return self.create(lead_vals)
        
        # Look for an existing lead in the last 30 days
        time_limit = fields.Datetime.now() - timedelta(days=30)
        domain = [
            ('phone', '=', phone_clean),
            ('portal_property_id', '=', portal_prop_id),
            ('create_date', '>=', time_limit),
        ]
        # Search the domain for any existing or duplicate leads
        existing_lead = self.search(domain, limit=1)

        if existing_lead:
            _logger.info(f"Duplicate lead detected. Phone: {phone_clean}, Property: {portal_prop_id}. Skipping creation.")
            existing_lead.message_post(
                body=f"Duplicate inquiry received from {lead_vals.get('portal_name')}. Raw data: {lead_vals.get('raw_data')}",
                subject=f"Duplicate Inquiry ({lead_vals.get('portal_name')})"
            )
            return None
        else:
            # NOT A DUPLICATE
            return self.create(lead_vals)
        
    def write(self, vals):
        """
        Override write to automatically log 'first_contact_datetime'
        AND to send a bus notification.
        """
        
        # (Your existing logic for first_contact_datetime)
        leads_to_stamp = self.env['leads.new']
        first_contact_time = False
        if 'current_status' in vals and vals['current_status'] != 'lead':
            leads_to_stamp = self.filtered(lambda r: not r.first_contact_datetime)
            if leads_to_stamp:
                first_contact_time = fields.Datetime.now()
        
        res = super(NewPortalLead, self).write(vals)
        
        if leads_to_stamp and first_contact_time:
            leads_to_stamp.write({
                'first_contact_datetime': first_contact_time
            })
            
        # --- NOTIFICATION LOGIC (CORRECTED) ---
        channel = "leads.new"
        notification_type = "bus_notification"
        message = {
            'ids': self.ids,
            'model': 'leads.new',
            'event': 'write'
        }
    
        
        # --- CORRECTED LINE ---
        # Use _sendone() as the log helpfully suggested
        self.env['bus.bus']._sendone(channel, notification_type, message)
        # --- END CORRECTION ---
            
        return res

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
        This now runs in the same transaction as the cron job.
        """
        self.ensure_one()
        _logger.info(f"🔄 Processing lead {self.id}: {self.name} (state: {self.state})")
        
        if self.state != 'new':
            _logger.info(f"⏭️ Skipping lead {self.id}, state is {self.state}")
            return
        
        try:
            # 1. Try to find the matching property
            property_rec = self._find_property()
            
            if not property_rec:
                # Data Lag: Property not found
                msg = f"Attempt {fields.Datetime.now()}: Property not found for {self.portal_name} ID: {self.portal_property_id}"
                _logger.warning(f"⚠️ Lead {self.id}: {msg}")
                self.process_notes = msg + "\n"
                return
            
            _logger.info(f"✅ Lead {self.id}: Found property {property_rec.property_tag} (ID: {property_rec.id})")
            
            # 2. Try to find the correct RM
            rm_user = self._find_rm(property_rec)
            _logger.info(f"✅ Lead {self.id}: Found RM {rm_user.name} (ID: {rm_user.id})")

            # 3. Success assign the lead.
            self.write({
                'property_id': property_rec.id,
                'user_id': rm_user.id,
                'state': 'assigned',
                'process_notes': f"Successfully assigned to RM {rm_user.name} for property {property_rec.property_tag}.\n"
            })
            _logger.info(f"🎉 Lead {self.id}: Successfully assigned to {rm_user.name} for property {property_rec.property_tag}")

        except Exception as e:
            _logger.error(f"❌ Failed to process lead {self.id}: {e}", exc_info=True)
            self.write({
                'state': 'failed',
                'process_notes': f"Processing failed with error: {str(e)}\n"
            })

    # Assigning Unassigned leads cron job
    @api.model
    def _cron_reprocess_unassigned_leads(self):
        """ Called by the 4 hour cron to find and re-process leads
            that are still 'new' due to data lag.
        """

        _logger.info("CRON: Starting re-process for unassigned leads...")
        domain = [
            ('state', '=', 'new'),
            ('create_date', '<', fields.Datetime.now() - timedelta(hours=1))
        ]
        leads_to_retry = self.search(domain)
        _logger.info(f"CRON: Found {len(leads_to_retry)} unassigned leads to reprocess.")

        for lead in leads_to_retry:
            # --- MODIFICATION ---
            # Was: lead.with_delay(...)
            _logger.info(f"CRON: Re-processing lead {lead.id} synchronously...")
            try:
                lead._process_lead_logic()
            except Exception as e:
                # This safety block ensures one bad lead doesn't stop the whole cron
                _logger.error(f"CRON: Failed during synchronous re-process of lead {lead.id}: {e}", exc_info=True)
            # --- END MODIFICATION ---


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
                        'lead_phone': cntct_dtl.findtext('Phone'),
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
        """ 
        Fetches new leads from the Housing.com API using HMAC auth.
        """
        _logger.info("CRON: Attempting to fetch leads from Housing.com API...")
        HOUSING_ENDPOINT = "https://pahal.housing.com/api/v0/get-broker-leads"
        HEADERS = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36' 
        }
        
        # 1. Get credentials from Odoo System Parameters
        config = self.env['ir.config_parameter'].sudo()
        api_key = config.get_param('housing.api.key')
        api_id = config.get_param('housing.api.id')

        if not api_key or not api_id:
            _logger.error("CRITICAL: housing.api.key or housing.api.id not set in system parameters")
            return []

        try:
            # 2. Set time Paramters  20 minutes for 15 min cron
            end_time = int(time.time())
            start_time = end_time - (20 * 60)  # 20 minutes ago
            current_time_str = str(end_time)    

            # 3. Generate hash(H)
            hash_h = hmac.new(
                api_key.encode('utf-8'),
                current_time_str.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            # 4. Build request parameters
            params = {
                'start_date': start_time,
                'end_date': end_time,
                'current_time': current_time_str,
                'hash': hash_h,
                'id': api_id,
                'per_page': 1000,
            }

            # 5. make the API call
            response = requests.get(HOUSING_ENDPOINT, params=params, headers=HEADERS, timeout=30)
            response.raise_for_status() # Raise HTTPError for bad responses

            response_data = response.json() 

            # 6. Check  the response
            if 'apiErrors' in response_data:
                _logger.error(f"Housing.com API Errors: {json.dumps(response_data)}")
                return []
            
            if 'data' in response_data and response_data['data']:
                raw_leads = response_data['data']
                _logger.info(f'Housing.com: Found {len(raw_leads)} leads from API.')
                return self._parse_housing_response(raw_leads)
            
            _logger.info("Housing.com: API call successful, now new leads found.")
            return []
        
        except requests.exceptions.HTTPError as e:
            _logger.error(f"Housing.com HTTPError: {e.response.status_code} | Response : {e.response.text}")
        except Exception as e:
            _logger.error(f"Error fetching Housing.com leads: {str(e)}")
        
        return[]


    def _parse_housing_response(self, raw_leads):
        """
        Parses thel list of raw lead objects from HOusing.com
        asdn tranlates them into our standard dictionary format.
        """
        leads_list = []
        for lead in raw_leads:
            try:
                prop_name = lead.get('apartment_names', '')
                locality = lead.get('locality_name', '')
                if prop_name and locality:
                    project_str = f"{prop_name} in {locality}"
                else:
                    project_str = prop_name or locality or 'N/A'

                translated_lead = {
                    'lead_name': lead.get('lead_name'),
                    'lead_phone': lead.get('lead_phone'),
                    'lead_email': lead.get('lead_email'),
                    'property_code': str(lead.get('flat_id')),
                    'project': project_str,
                    'raw_json': lead,
                }

                # Simple Validation
                if not translated_lead['lead_phone']:
                    _logger.warning(f"Housing.com lead skipped due to missing phone: {json.dumps(lead)}")
                    continue

                leads_list.append(translated_lead)
            
            except Exception as e:
                _logger.warning(f"Error parsing one Housing.com lead: {str(e)}")

        return leads_list


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
                    try:
                        # 3. Create the leads.new record
                        lead_vals = {
                            'name': lead.get('lead_name'),
                            'phone': lead.get('lead_phone'),
                            'email': lead.get('lead_email'),
                            'project_name': lead.get('project'),
                            'portal_name': portal_name,
                            'portal_property_id': lead.get('property_code'),
                            'raw_data': json.dumps(lead.get('raw_json') or lead, indent=2),
                            'state': 'new',
                        }
                        new_lead = self.create_lead_if_not_duplicate(lead_vals)

                        # 4. Process the lead immediately (synchronously)
                        if new_lead:
                            _logger.info(f"Lead {new_lead.id} created, processing synchronously...")
                            new_lead._process_lead_logic()
                    
                    except Exception as e:
                        # This safety block ensures one bad lead doesn't stop the whole cron
                        _logger.error(f"CRON: Failed to create/process lead from {portal_name}: {e}", exc_info=True)


            except Exception as e:
                _logger.error(f"Failed to pull leads from {portal_name} API: {e}")


    @api.depends('phone')
    def _compute_phone_whatsapp_url(self):
        """
        Generates a WhatsApp URL using whatsapp protocol, prepending 91 if a 10-digit number is found.
        """

        for rec in self:
            if not rec.phone:
                rec.phone_whtasapp_url = False
                continue
                
            #1. Clear all non numeric characters
            sane_phone = re.sub(r'\D', '', rec.phone)
            number_to_use = False

            if len(sane_phone) == 10:
                number_to_use = f"91{sane_phone}"
            elif len(sane_phone) == 12 and sane_phone.startswith('91'):
                number_to_use = sane_phone
            elif len(sane_phone) == 11 and sane_phone.startswith('0'):
                number_to_use = f"91{sane_phone[1:]}"

            if number_to_use:
                rec.phone_whatsapp_url = f"whatsapp://send?phone={number_to_use}"
            else:
                rec.phone_whatsapp_url = False

    @api.depends('phone', 'phone_whatsapp_url')
    def _compute_phone_whatsapp_html(self):
        """
        Creates a simpel Whatsapp Link to open the desktop App
        """

        for rec in self:
            phone_display = rec.phone or ''

            if rec.phone_whatsapp_url:
                whatsapp_url = rec.phone_whatsapp_url

                # create a simple html link
                rec.phone_whatsapp_html = \
                    f'<a href="{whatsapp_url}" ' \
                    f'title="Click to open WhatsApp" ' \
                    f'style="text-decoration: none; cursor: pointer;">' \
                    f'<i class="fa fa.whatsapp" style="color:green; font-size: 16px;"/> {phone_display}</a>'
            else:
                rec.phone_whatsapp_html = phone_display

    # (Make sure 'import re' is at the top of your file)

    def action_whatsapp_with_copy(self):
        """
        This action prepares the data and calls a Client Action
        to handle the copying and link opening.
        
        [UPDATED to use the lead's FULL name]
        """
        self.ensure_one()
        
        # --- 1. Get WhatsApp URL ---
        if not self.phone_whatsapp_url:
            return
        whatsapp_url = self.phone_whatsapp_url
        
        # --- 2. Gather All Template Variables (with fallbacks) ---
        
        # {{Name}}
        # --- FIX: We now use the full name ---
        lead_name = self.name or "there"
        # (The line that caused the truncation has been removed)

        # {{portal}}
        portal_name = self.portal_name or "our portal" # Fallback

        # Get Property Details
        prop = self.property_id
        
        # {{BHK}}
        prop_bhk = "property" # Default fallback
        if prop and prop.bhk:
            prop_bhk = prop.bhk
            
        # {{Location}} & City
        prop_location = ""
        prop_city = ""
        prop_link = ""
        if prop:
            prop_location = prop.location or ""
            prop_city = prop.city or ""
            prop_link = prop.property_link or ""

        # --- 3. Build the Location String (e.g., "Location, City") ---
        
        # Clean the location (remove "A-", "B-", etc.)
        if prop_location:
            prop_location = re.sub(r'^[A-Z]-', '', prop_location).strip()

        location_parts = []
        if prop_location:
            location_parts.append(prop_location)
        if prop_city:
            location_parts.append(prop_city)
            
        location_city_str = ", ".join(filter(None, location_parts))
        if not location_city_str:
            location_city_str = "your area" # Final fallback

        # --- 4. Build Your New Message (in parts) ---
        
        message_parts = [
            f"Hello {lead_name},",
            "", # Creates a blank line
            f"We've received your requirement for a {prop_bhk} property in {location_city_str} through {portal_name}.",
            "", # Blank line
            "With cleardeals, you can purchase this at 0% brokerage.",
        ]
        
        if prop_link:
            message_parts.append(f"You can view the property here: {prop_link}")

        message_parts.append("") # Blank line
        message_parts.append("👉 Want to know more? Just type \"Hi\" to continue")

        message_text = "\n".join(message_parts)

        # --- 5. Return the Client Action ---
        return {
            'type': 'ir.actions.client',
            'tag': 'whatsapp_with_copy', # This tag MUST match your JS file
            'target': 'new',
            'context': {
                'whatsapp_url': whatsapp_url,
                'message_text': message_text,
            }
        }
    
    @api.model
    def _cron_send_new_lead_webhooks(self):
        """
        Called by a 1-minute cron.
        Finds all leads that have not been sent to the webhook.
        Sends them as a batch to n8n.
        
        [UPDATED to include more property details and RM Name]
        """
        # Get your n8n webhook URL from Odoo's system parameters
        config = self.env['ir.config_parameter'].sudo()
        webhook_url = config.get_param('n8n.new_lead_webhook_url')

        if not webhook_url:
            _logger.error("n8n.new_lead_webhook_url not set. Skipping webhook.")
            return
        
        # Find all unsent leads, limit to a safe batch size
        leads_to_send = self.search([
            ('is_webhook_sent', '=', False)
        ], limit=100)

        if not leads_to_send:
            _logger.info("No new leads to send to n8n webhook")
            return
        
        batch_payload = []
        for lead in leads_to_send:
            
            # --- Get linked property and its details safely ---
            prop = lead.property_id 
            
            prop_id = False
            prop_tag = False
            prop_bhk = False
            prop_location = False
            prop_city = False
            prop_link = False

            if prop: # Check if a property is linked
                prop_id = prop.id
                prop_tag = prop.property_tag
                prop_bhk = prop.bhk
                prop_location = prop.location
                prop_city = prop.city
                prop_link = prop.property_link
            
            # --- Get RM Name safely ---
            rm_name = lead.user_id.name if lead.user_id else False

            # Create the JSON object for this lead
            lead_data = {
                # Lead Info
                'lead_id': lead.id,
                'name': lead.name,
                'phone': lead.phone,
                'portal_name': lead.portal_name, # This is the "Portal Source"
                'portal_property_id': lead.portal_property_id,
                'rm_name': rm_name, # <-- THIS IS THE NEW FIELD
                
                # Property Info (now includes the new fields)
                'property_id': prop_id,
                'property_tag': prop_tag,
                'property_bhk': prop_bhk,
                'property_location': prop_location,
                'property_city': prop_city,
                'property_link': prop_link
            }
            batch_payload.append(lead_data)
        
        if not batch_payload:
             _logger.info("No leads to send after processing.")
             return

        _logger.info(f"Sending {len(batch_payload)} new leads to n8n webhook...")
        try:
            # Send the entire batch as one JSON list to n8n
            headers = {'Content-Type': 'application/json'}
            response = requests.post(
                webhook_url,
                data = json.dumps(batch_payload),
                headers=headers,
                timeout=10
            )

            # Check for a successful response
            response.raise_for_status()

            # If successful, mark all leads as sent
            leads_to_send.write({'is_webhook_sent': True})
            _logger.info(f"Successfully sent {len(batch_payload)} leads to n8n webhook.")

        except requests.exceptions.RequestException as e:
            _logger.error(f"Failed to send leads to n8n webhook: {str(e)}")

    @api.depends('create_date')
    def _compute_create_date_only(self):
        """
        Takes the full 'create_date' (Datetime) and stores
        just the 'date' part for easy filtering.
        """
        for rec in self:
            if rec.create_date:
                rec.create_date_only = rec.create_date.date()
            else:
                rec.create_date_only = False


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
