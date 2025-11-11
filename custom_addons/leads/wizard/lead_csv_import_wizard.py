import base64
import csv
from io import StringIO
from odoo import models, fields, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class LeadCsvImportWizard(models.TransientModel):
    _name = 'lead.csv.import.wizard'
    _description = 'Lead CSV Import Wizard'

    file_data = fields.Binary(string='CSV File', required=True)
    filename = fields.Char(string='File Name')

    def import_leads_from_csv(self):
        if not self.file_data:
            raise UserError(_('Please upload a CSV file.'))

        try:
            # Decode the file data
            data = base64.b64decode(self.file_data).decode('utf-8')
            csv_data = StringIO(data)
            reader = csv.DictReader(csv_data)
        except Exception as e:
            raise UserError(_("Failed to read file. Please ensure it's a valid UTF-8 CSV. Error: %s") % str(e))

        imported_count = 0
        failed_rows = []
        user_cache = {}

        for index, row in enumerate(reader):
            lead_name_for_error = row.get('First Name', 'N/A')
            try:
                # --- Find Relationship Manager ---
                rm_name_csv = row.get('Relationship-Manager') # e.g., 'Shivraj-Khachar'
                if not rm_name_csv:
                    failed_rows.append(f"Row {index + 2} ({lead_name_for_error}): Missing 'Relationship-Manager'.")
                    continue
                
                # --- FIX: Clean the name ---
                # Replace dashes with spaces to match Odoo user names
                rm_name_odoo = rm_name_csv.replace('-', ' ').strip() # e.g., 'Shivraj Khachar'

                if rm_name_odoo == "Bhumika Prajapati":
                    rm_name_odoo = "Bhoomika Prajapati"
                
                # Skip if the cleaned name is empty (e.g., CSV had only '-')
                if not rm_name_odoo:
                    failed_rows.append(f"Row {index + 2} ({lead_name_for_error}): Invalid RM name '-'.")
                    continue

                # Cache user lookups for efficiency
                # Use the *cleaned* name for cache key and searching
                if rm_name_odoo in user_cache:
                    rm_user = user_cache[rm_name_odoo]
                else:
                    # Search using the *cleaned* name
                    rm_user = self.env['res.users'].search([('name', '=', rm_name_odoo)], limit=1)
                    if not rm_user:
                        # Log the *original* CSV name so the user knows what failed
                        log_msg = f"User '{rm_name_odoo}' (from CSV '{rm_name_csv}') not found."
                        failed_rows.append(f"Row {index + 2} ({lead_name_for_error}): {log_msg}")
                        _logger.warning(log_msg) # Also log to server
                        continue
                    # Store in cache using the *cleaned* name
                    user_cache[rm_name_odoo] = rm_user
                
                # --- Get Source ---
                # Normalize source from CSV to match model's selection keys
                source_raw = row.get('Source', '').strip().lower()
                if source_raw == '99acres':
                    source_key = '99acres'
                elif source_raw == 'magicbricks':
                    source_key = 'MagicBricks'
                elif source_raw == 'housing.com' or source_raw == 'housing':
                    source_key = 'Housing'
                elif source_raw == 'olx':
                    source_key = 'OLX'
                else:
                    source_key = None # Will be blank if not matched

                # --- Prepare Create Values ---
                lead_title = f"Lead for {row.get('First Name', '')} - {row.get('tag', '')}"

                create_vals = {
                    'name': lead_title,
                    'partner_name': row.get('First Name'),
                    'phone': row.get('Phone1'),
                    'rm_user_id': rm_user.id,
                    'source': source_key,
                    'property_tag': row.get('Tag'),
                    'address': row.get('Property-Address'),
                    'price_range': row.get('Price_Range_Lacs_Rs'),
                    'city': row.get('City'),
                    'description': str(row), # Store the full row for reference
                    'state': 'new', # Default state
                }

                # Create the new lead
                self.env['imported.lead'].create(create_vals)
                imported_count += 1

            except Exception as e:
                failed_rows.append(f"Row {index + 2} ({lead_name_for_error}): Failed to import. Error: {str(e)}")

        # --- Provide a summary ---
        if not failed_rows:
            message = _("Successfully imported %d leads.") % imported_count
            return self.notify_success(message)

        error_details = "\n".join(failed_rows)

        if imported_count > 0:
            message = _("Import complete. Successfully imported %d leads.\n\nFailed Rows:\n%s") % (imported_count, error_details)
            title = _('Partial Import')
        else:
            message = _("Import complete. No leads were imported successfully.\n\nFailed Rows:\n%s") % (error_details)
            title = _('Import Failed')

        message_wizard = self.env['message.wizard'].create({
             'message': message
        })

        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'message.wizard',
            'view_mode': 'form',
            'res_id': message_wizard.id,
            'target': 'new',
        }


    def notify_success(self, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Import Successful'),
                'message': message,
                'type': 'success',
                'sticky': False,
            }
        }

class MessageWizard(models.TransientModel):
    """
    A simple transient model to display a message to the user.
    """
    _name = 'message.wizard'
    _description = 'Message Wizard'

    # This is the field your XML view <field name="message".../> needs
    message = fields.Text(string="Message", readonly=True)