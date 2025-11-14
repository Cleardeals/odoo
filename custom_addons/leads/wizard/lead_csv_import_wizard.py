import base64
import csv
from io import StringIO
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class LeadCsvImportWizard(models.TransientModel):
    _name = 'lead.csv.import.wizard'
    _description = 'Lead CSV Import Wizard'

    file_data = fields.Binary(string='CSV File', required=True)
    filename = fields.Char(string='File Name')

    def import_leads_from_csv(self):
        """
        [RECONFIGURED FOR OLX IMPORTS]
        [UPDATED to skip blank lines]
        """
        if not self.file_data:
            raise UserError(_('Please upload a CSV file.'))

        # --- Column Mapping (matches your CSV) ---
        COLUMN_MAPPING = {
            'name': 'Name',
            'phone': 'Phone Number',
            'email': 'Email Id',
            'olx_id': 'Inventory ID'
        }
        # --- End Configuration ---

        try:
            # --- Encoding Fallback ---
            decoded_data = base64.b64decode(self.file_data)
            try:
                data = decoded_data.decode('utf-8')
            except UnicodeDecodeError:
                _logger.warning("CSV file is not UTF-8, falling back to 'latin-1' encoding.")
                data = decoded_data.decode('latin-1')
            
            csv_data = StringIO(data, newline='')
            reader = csv.DictReader(csv_data) 
            
        except Exception as e:
            raise UserError(_("Failed to read file. Please ensure it's a valid CSV. Error: %s") % str(e))

        imported_count = 0
        failed_rows = []
        property_cache = {}
        
        LeadsNew = self.env['leads.new']
        PropertyInv = self.env['property.inventory']

        for index, row in enumerate(reader):
            row_num = index + 2 
            
            if not any(row.values()):
                continue
            
            # --- THIS IS THE FIX ---
            # Create a new dictionary where all keys (headers) are stripped of whitespace.
            # This fixes " Phone Number" vs "Phone Number"
            clean_row = {key.strip(): value for key, value in row.items() if key}
            # --- END FIX ---

            # --- Use the new 'clean_row' mapping to get data ---
            lead_name = clean_row.get(COLUMN_MAPPING['name'])
            lead_phone = clean_row.get(COLUMN_MAPPING['phone'])
            lead_email = clean_row.get(COLUMN_MAPPING['email'])
            olx_id = clean_row.get(COLUMN_MAPPING['olx_id'])
            # --- END OF CHANGES ---

            try:
                # --- 1. Validation ---
                if not lead_name:
                    failed_rows.append(f"Row {row_num}: Missing '{COLUMN_MAPPING['name']}'.")
                    continue
                if not lead_phone:
                    failed_rows.append(f"Row {row_num} ({lead_name}): Missing '{COLUMN_MAPPING['phone']}'.")
                    continue
                if not olx_id:
                    failed_rows.append(f"Row {row_num} ({lead_name}): Missing '{COLUMN_MAPPING['olx_id']}'.")
                    continue
                
                olx_id = olx_id.strip()

                # --- 2. Find Property (with Caching) ---
                prop = property_cache.get(olx_id)
                if not prop:
                    prop = PropertyInv.search([('olx_id', '=', olx_id)], limit=1)
                    if prop:
                        property_cache[olx_id] = prop
                    
                if not prop:
                    failed_rows.append(f"Row {row_num} ({lead_name}): Property not found for Inventory ID (OLX ID) '{olx_id}'.")
                    continue

                # --- 3. Find RM from Property ---
                rm_user = prop.rm_user_id
                if not rm_user:
                    failed_rows.append(f"Row {row_num} ({lead_name}): Property '{prop.name}' is not assigned to an RM.")
                    continue

                # --- 4. Prepare 'leads.new' Values ---
                create_vals = {
                    'name': lead_name,
                    'phone': lead_phone,
                    'email': lead_email if lead_email != 'null' else False, # Handle 'null' text
                    'portal_name': 'OLX',
                    'portal_property_id': olx_id,
                    'property_id': prop.id,
                    'user_id': rm_user.id,
                    'state': 'assigned',
                    'current_status': 'lead',
                    'raw_data': str(row)
                }

                # --- 5. Create Lead (using your existing duplicate check) ---
                new_lead = LeadsNew.create_lead_if_not_duplicate(create_vals)
                
                if new_lead:
                    imported_count += 1
                else:
                    failed_rows.append(f"Row {row_num} ({lead_name}): Duplicate lead detected (phone + property).")

            except Exception as e:
                failed_rows.append(f"Row {row_num} ({lead_name}): Failed to import. Error: {str(e)}")

        # --- Provide a summary ---
        if not failed_rows:
            message = _("Successfully imported %d leads.") % imported_count
            
            # Using the message wizard from your original code
            message_wizard = self.env['message.wizard'].create({'message': message})
            return {
                'name': _('Import Successful'),
                'type': 'ir.actions.act_window',
                'res_model': 'message.wizard',
                'view_mode': 'form',
                'res_id': message_wizard.id,
                'target': 'new',
            }

        error_details = "\n".join(failed_rows)
        if imported_count > 0:
            message = _("Import complete. Successfully imported %d leads.\n\nFailed Rows:\n%s") % (imported_count, error_details)
            title = _('Partial Import')
        else:
            message = _("Import complete. No leads were imported successfully.\n\nFailed Rows:\n%s") % (error_details)
            title = _('Import Failed')

        message_wizard = self.env['message.wizard'].create({'message': message})
        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'message.wizard',
            'view_mode': 'form',
            'res_id': message_wizard.id,
            'target': 'new',
        }

class MessageWizard(models.TransientModel):
    """
    A simple transient model to display a message to the user.
    """
    _name = 'message.wizard'
    _description = 'Message Wizard'

    # This is the field your XML view <field name="message".../> needs
    message = fields.Text(string="Message", readonly=True)