# -*- coding: utf-8 -*-
import logging
import re
from odoo import models, fields, api, _
from google.cloud import bigquery

_logger = logging.getLogger(__name__)

SUGGESTIONS_TABLE_ID = "cleardeals-459513.active_to_active.suggested_leads_for_properties"
BIGQUERY_PROJECT_ID = "cleardeals-459513"

class PropertyLeadSuggestion(models.Model):
    _name = 'property.lead.suggestion'
    _description = 'Suggested Lead for a Property'
    _order = 'generation_date desc, status asc'
    _rec_name = 'suggested_lead_phone'

    # --- SQL Constraints (Odoo 19 Style) ---
    _prop_lead_uniq = models.Constraint(
        'UNIQUE(property_inventory_id, suggested_lead_phone)',
        message='This lead is already a suggestion for this property.'
    )

    property_inventory_id = fields.Many2one(
        'property.inventory',
        string="Property",
        ondelete='cascade',
        required=True
    )
    property_tag = fields.Char(
        related='property_inventory_id.property_tag',
        store=True,
        string="Property Tag"
    )
    
    suggested_lead_phone = fields.Char(string="Lead Phone", required=True)
    
    suggested_lead_phone_whatsapp_url = fields.Char(
        string="WhatsApp URL",
        compute='_compute_suggested_lead_phone_whatsapp_url',
        store=False 
    )
    
    # [MIGRATION 19.0] Renamed string to avoid "Duplicate Label" warning
    suggested_lead_phone_html = fields.Html(
        string="Lead Phone Link",
        compute='_compute_suggested_lead_phone_html',
        store=False
    )
    
    lead_name = fields.Char(string="Lead Name")

    original_property_tag = fields.Char(string="Original Property")
    original_property_similarity = fields.Float(
        string="Similarity (%)",
        digits=(16, 2),
        aggregator="avg"  
    )
    contact_type = fields.Char(string="Lead's Current Status")

    # --- Date Fields ---
    generation_date = fields.Date(string="Suggested On", default=fields.Date.context_today)

    # [FIX] Computed Display Field for strict DD/MM/YYYY format
    generation_date_display = fields.Char(
        string="Suggested On", 
        compute='_compute_generation_date_display'
    )

    # --- RM Feedback Fields ---
    status = fields.Selection([
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('details_shared_of_property', 'Details Shared of Property'),
        ('not_interested', 'Not Interested'),
        ('interested', 'Interested'), 
        ('converted', 'Converted'),
        ('whatsapp_done', 'WhatsApp Done'),
        ('other', 'Other'),
    ], string="Status", default='new', index=True, required=True)

    rm_feedback = fields.Text(string="RM Feedback")

    @api.depends('generation_date')
    def _compute_generation_date_display(self):
        """Forces date to display as DD/MM/YYYY"""
        for rec in self:
            rec.generation_date_display = rec.generation_date.strftime('%d/%m/%Y') if rec.generation_date else ''

    @api.depends('suggested_lead_phone')
    def _compute_suggested_lead_phone_whatsapp_url(self):
        """
        Generates a WhatsApp URL using whatsapp:// protocol, prepending '91' 
        if a 10-digit Indian number is detected.
        """
        for rec in self:
            if not rec.suggested_lead_phone:
                rec.suggested_lead_phone_whatsapp_url = False
                continue

            # 1. Clean all non-numeric characters
            sane_phone = re.sub(r'\D', '', rec.suggested_lead_phone)
            
            number_to_use = False
            
            # 2. Check for common Indian number formats
            if len(sane_phone) == 10:
                # e.g., 9876543210 -> 919876543210
                number_to_use = f"91{sane_phone}"
            elif len(sane_phone) == 12 and sane_phone.startswith('91'):
                # e.g., 919876543210 -> 919876543210 (already correct)
                number_to_use = sane_phone
            elif len(sane_phone) == 11 and sane_phone.startswith('0'):
                # e.g., 09876543210 -> 919876543210
                number_to_use = f"91{sane_phone[1:]}"
            
            # 3. If a valid format was found, create the URL
            if number_to_use:
                # Use whatsapp:// protocol for direct desktop app opening
                rec.suggested_lead_phone_whatsapp_url = f"whatsapp://send?phone={number_to_use}"
            else:
                # Not a recognizable format, so don't create a link
                rec.suggested_lead_phone_whatsapp_url = False

    @api.depends('suggested_lead_phone', 'suggested_lead_phone_whatsapp_url')
    def _compute_suggested_lead_phone_html(self):
        """
        Creates a simple WhatsApp link to open the desktop app.
        """
        for rec in self:
            phone_display = rec.suggested_lead_phone or ''
            
            if rec.suggested_lead_phone_whatsapp_url:
                # Get the whatsapp:// URL
                whatsapp_url = rec.suggested_lead_phone_whatsapp_url
                
                # Create simple HTML link
                rec.suggested_lead_phone_html = \
                    f'<a href="{whatsapp_url}" ' \
                    f'title="Click to open WhatsApp" ' \
                    f'style="text-decoration: none; cursor: pointer;">' \
                    f'<i class="fa fa-whatsapp" style="color:green; font-size: 16px;"/> {phone_display}</a>'
            else:
                # Otherwise, just show the plain phone number
                rec.suggested_lead_phone_html = phone_display
    

    def action_whatsapp_with_copy(self):
        """
        This action prepares the data and calls a Client Action
        to handle the copying and link opening.
        """
        self.ensure_one()
        
        if not self.suggested_lead_phone_whatsapp_url:
            return

        whatsapp_url = self.suggested_lead_phone_whatsapp_url
        
        # --- ACCESS THE NEW PROPERTY FIELDS ---
        prop = self.property_inventory_id
        
        # Get property details
        prop_bhk = prop.bhk or "a property" # Fallback if BHK is empty
        prop_location = prop.location or ""
        prop_city = prop.city or ""
        prop_link = prop.property_link or ""
        
        # Get lead's name for a personal touch
        lead_name = self.lead_name or "there"
        if ' ' in lead_name:
             lead_name = lead_name.split(' ')[0] # Use first name only

        # --- NEW: Clean the location string ---
        # This removes prefixes like "A-", "B-", etc.
        if prop_location:
            # Replaces a pattern like "A-" at the start of the string with ""
            prop_location = re.sub(r'^[A-Z]-', '', prop_location)
        # ------------------------------------

        # Build location string, e.g., "Maninagar, Ahmedabad"
        location_parts = []
        if prop_location:
            location_parts.append(prop_location)
        if prop_city:
            location_parts.append(prop_city)
        location_str = ", ".join(location_parts)
        
        if not location_str:
            location_str = "your area"

        # 💬 YOUR NEW MESSAGE TEMPLATE
        message_parts = [
            f"Hey {lead_name}! 👋\n",
            f"Looking for {prop_bhk} in {location_str}? 🏡\n",
            "A new property matching your needs just went live — act fast before it’s taken!\n",
        ]

        # Add link only if it exists
        if prop_link:
            message_parts.append(f"💬 Click here more details: {prop_link}\n")
        else:
            message_parts.append("💬 Reply 'Hi' for more details!\n") 

        # Add the static footer
        message_parts.extend([
            "Cleardeals Advantage:",
            "0% Brokerage | Verified Properties | Faster Closures\n",
            "Reply \"Hi\" to get more details"
        ])

        # Join all parts with newlines
        message_text = "\n".join(message_parts)
        
        # Return an action that calls our JavaScript
        return {
            'type': 'ir.actions.client',
            'tag': 'whatsapp_with_copy', 
            'target': 'new',
            'context': {
                'whatsapp_url': whatsapp_url,
                'message_text': message_text,
            }
        }
            
            
    def action_log_feedback(self):
        """
        Opens a wizard for the RM to log feedback on this suggestion.
        """
        self.ensure_one() 
        return {
            'type': 'ir.actions.act_window',
            'name': _('Log Feedback for %s') % (self.lead_name or self.suggested_lead_phone),
            'res_model': 'suggestion.feedback.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_suggestion_id': self.id,
                'default_status': self.status,
                'default_rm_feedback': self.rm_feedback,
            }
        }

    @api.model
    def _cron_sync_suggestions(self):
        """
        Cron Job: Syncs NEW suggestions from the BigQuery table
        for the last 3 days, appending only those not already present.
        """
        _logger.info("Starting Optimized Lead Suggestions sync...")

        try:
            client = bigquery.Client(project=BIGQUERY_PROJECT_ID)
        except Exception as e:
            _logger.error(f"Failed to create BigQuery client: {e}")
            return

        # --- OPTIMIZATION 1: Fetch all properties into a dictionary ---
        _logger.info("Fetching all existing properties from Odoo...")
        try:
            PropertyInventory = self.env['property.inventory']
            all_props_recs = PropertyInventory.sudo().search_read([], ['property_tag'])
            # Create a map of {'property_tag': property_id}
            property_map = {rec['property_tag']: rec['id'] for rec in all_props_recs}
            _logger.info(f"Loaded {len(property_map)} properties into memory map.")
        except Exception as e:
            _logger.error(f"Failed to fetch property inventory: {e}")
            return
            
        # --- OPTIMIZATION 2: Fetch all existing suggestion keys into a set ---
        _logger.info("Fetching all existing suggestion keys from Odoo...")
        try:
            existing_sugg_recs = self.sudo().search_read([], ['property_inventory_id', 'suggested_lead_phone'])
            # Create a set of (property_id, 'lead_phone')
            existing_keys = {
                (rec['property_inventory_id'][0], rec['suggested_lead_phone'])
                for rec in existing_sugg_recs
            }
            _logger.info(f"Loaded {len(existing_keys)} existing suggestion keys into memory set.")
        except Exception as e:
            _logger.error(f"Failed to fetch existing suggestions: {e}")
            return


        # Fetch suggestions from the last 3 days, including current_status
        query = f"""
            SELECT
                active_property_tag,
                suggested_lead_phone,
                lead_name,
                original_property_tag,
                original_property_similarity,
                generation_date,
                current_status
            FROM `{SUGGESTIONS_TABLE_ID}`
            WHERE generation_date >= DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL 3 DAY)
        """

        try:
            _logger.info("Querying BigQuery for recent suggestions...")
            query_job = client.query(query)
            results = list(query_job.result())
            _logger.info(f"Fetched {len(results)} suggestions from BigQuery.")

            vals_to_create = []
            skipped_prop_not_found = 0
            skipped_already_exists = 0

            for row in results:
                # Basic validation
                if not row.active_property_tag or not row.suggested_lead_phone:
                    continue

                # --- OPTIMIZED LOOKUP (Fast) ---
                # Find the parent property ID from our Python dictionary
                prop_id = property_map.get(row.active_property_tag)
                
                if not prop_id:
                    _logger.warning(f"Skipping suggestion, property '{row.active_property_tag}' not found in Odoo property map.")
                    skipped_prop_not_found += 1
                    continue

                # --- OPTIMIZED LOOKUP (Fast) ---
                # Check if this suggestion key is in our Python set
                suggestion_key = (prop_id, row.suggested_lead_phone)
                
                if suggestion_key in existing_keys:
                    skipped_already_exists += 1
                    continue

                # If we reach here, it's a new suggestion. Add to our batch list.
                vals_to_create.append({
                    'property_inventory_id': prop_id,
                    'suggested_lead_phone': row.suggested_lead_phone,
                    'lead_name': row.lead_name,
                    'original_property_tag': row.original_property_tag,
                    'original_property_similarity': (row.original_property_similarity or 0.0) * 100.0,
                    'generation_date': row.generation_date,
                    'contact_type': row.current_status,
                    'status': 'new',
                })
                # Add the key to our set so we don't add it twice *in this run*
                existing_keys.add(suggestion_key)

            # --- OPTIMIZATION 3: Create all new records in one batch ---
            if vals_to_create:
                _logger.info(f"Creating {len(vals_to_create)} new suggestions in a batch...")
                self.sudo().create(vals_to_create)
                _logger.info("Batch creation complete.")
            else:
                _logger.info("No new suggestions to create.")

            _logger.info(f"Lead Suggestions Sync Summary: Created {len(vals_to_create)} new suggestions. Skipped {skipped_prop_not_found} (prop not found). Skipped {skipped_already_exists} (already exists).")

        except Exception as e:
            _logger.error(f"Error during Lead Suggestions sync BQ query or processing: {e}")
            self.env.cr.rollback()