from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)   

class NewPortalLead(models.Model):
    _name = 'leads.new'
    _description = "New Leads from Portals"
    _order = 'create_date desc'

    # Lead Fields

    name = fields.Char('Lead Name', required=True, index=True)
    phone = fields.Char('Phone Number', required=True, index=True)
    email = fields.Char('Email Address', index=True)   
    portal_name = fields.Char('Portal Source', help="e.g., Magicbricks, 99acres")
    project_name = fields.Char('Project Name', help="Project Name from portal")
    raw_data = fields.Text('Raw Data Dump')

    # Processing and Assignment Fields

    state = fields.Selection([
        ('new', 'New'),
        ('assigned', 'Assigned'),
        ('failed', 'Failed Assignment'),
    ], default='new', required=True, tracking=True, index=True, copy=False)

    property_id = fields.Many2one('property.inventory', string='Related Property')
    user_id = fields.Many2one('res.users', string='Assigned RM', tracking=True, copy=False)
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
    
    @api.job(default_channel='root.portal_lead_processing')
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

            
