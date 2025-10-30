import base64
import csv
import io
import logging

from odoo import api, fields, models, _ 
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class LeadCsvImportWizard(models.TransientModel):
    """
    This wizard model handles the uploading and processing of CSV files to  create new lead.score records in Odoo.
    """

    _name = "lead.csv.import.wizard"
    _description = "Lead CSV Import Wizard"

    file_data = fields.Binary(string="CSV File", required=True, help="Upload the CSV file with leads to import. Headers must match the template.")

    filename = fields.Char(string="File Name", required=True)

    def import_leads_from_csv(self):
        """
        Main function to process the uploaded CSV file.
        It reads the file, maps columns from your CSV, and creates lead.score records.
        """
        self.ensure_one()

        if not self.file_data:
            raise UserError(_("Please upload a CSV file to import leads."))
        
        # Decode the uploaded file
        try:
            # Use 'utf-8-sig' to handle potential BOM (Byte Order Mark) at the start of some CSVs
            decoded_file = base64.b64decode(self.file_data).decode('utf-8-sig')
        except Exception as e:
            _logger.error(f"Error decoding uploaded file: {e}")
            raise UserError(_("Failed to decode file. Please ensure it is UTF-8 encoded. Error: %s") % str(e))
        
    
        # Use io.StringIO to read the decoded file as a CSV
        try:
            file_input = io.StringIO(decoded_file)
            # User DictReader tp read CSV rows as dictionaries
            reader = csv.DictReader(file_input)

            leads_created_count = 0
            leads_failed_count = 0
            failed_leads_info = []

            # Get environment models

            ImportedLead = self.env['imported.lead']
            User = self.env['res.users']

            source_map = {
                '99acres': '99acres',
                'magicbricks': 'MagicBricks',
                'housing': 'housing',
                'OLX': 'OLX',
            }

            for row in reader:
                try:
                    rm_name = row.get('Relationship-Manager')
                    source_name = row.get('Source')
                    lead_name = row.get('First Name')
                    property_tag = row.get('tag') or row.get('Tag') # Checks for both 'tag' and 'Tag'

                    if not lead_name:
                        _logger.warning("Skipping row with no 'First Name': %s", row)
                        leads_failed_count += 1
                        failed_leads_info.append(f"Row {reader.line_num}: Missing 'First Name'")
                        continue
                    
                    if not rm_name:
                        _logger.warning("Skipping lead '%s' with no 'Relationship-Manager'", lead_name)
                        leads_failed_count += 1
                        failed_leads_info.append(f"{lead_name}: Missing 'Relationship-Manager'")
                        continue

                    # --- Find the Relationship Manager (Salesperson) ---
                    user = User.search([('name', '=', rm_name)], limit=1)
                    if not user:
                        _logger.warning("RM '%s' not found. Skipping lead '%s'.", rm_name, lead_name)
                        leads_failed_count += 1
                        failed_leads_info.append(f"{lead_name}: RM '{rm_name}' not found.")
                        continue
                    
                    # --- Map the Source ---
                    source_key = source_map.get(source_name.lower()) if source_name else False
                    if source_name and not source_key:
                        _logger.warning("Source '%s' not recognized. Skipping source for lead '%s'.", source_name, lead_name)

                    # --- Build the description field from other columns ---
                    description_parts = [
                        f"Property Address: {row.get('Property-Address', 'N/A')}",
                        f"Property Type: {row.get('Property_Type', 'N/A')}",
                        f"BHK: {row.get('BHK', 'N/A')}",
                        f"Price Range: {row.get('Price_Range_Lacs_Rs', 'N/A')}",
                        f"Property Price: {row.get('Property-Price', 'N/A')}",
                        f"Property Link: {row.get('Property-Link', 'N/A')}",
                        f"99acres ID: {row.get('99acres-ID', 'N/A')}",
                    ]
                    description = "\n".join(description_parts)

                    # --- Create the imported.lead record ---
                    lead_vals = {
                        'name': f"Lead for {lead_name} - {property_tag or 'N/A'}",
                        'partner_name': lead_name,
                        'phone': row.get('Phone1'),
                        # email_from removed
                        'city': row.get('City'),
                        'rm_user_id': user.id,
                        'source': source_key,
                        'property_tag': property_tag,
                        'description': description,
                        'state': 'new', # Default state
                    }
                    
                    ImportedLead.create(lead_vals)
                    leads_created_count += 1

                except Exception as e:
                    _logger.error("Failed to import lead row: %s. Error: %s", row, str(e))
                    leads_failed_count += 1
                    failed_leads_info.append(f"Row {reader.line_num}: {str(e)}")

            # --- Provide feedback to the user ---
            if leads_failed_count > 0:
                message = _(
                    "Import completed with errors.\n\n"
                    "Successfully created: %s leads.\n"
                    "Failed to create: %s leads.\n\n"
                    "Errors (first 10):\n%s"
                ) % (leads_created_count, leads_failed_count, "\n".join(failed_leads_info[:10]))
                
                # Show the error in a separate wizard
                self.env['message.wizard'].create({'message': message}).show_message()
                return

            # Show success message
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Import Successful'),
                    'message': _('Successfully created %s new leads.') % leads_created_count,
                    'type': 'success',
                    'sticky': False,
                },
            }

        except Exception as e:
            _logger.error("Error during CSV processing: %s", str(e))
            raise UserError(_("An error occurred during import: %s") % str(e))

        # Close the wizard
        return {'type': 'ir.actions.act_window_close'}


# Helper wizard to show multi-line error messages
class MessageWizard(models.TransientModel):
    _name = 'message.wizard'
    _description = 'Message Wizard'

    message = fields.Text(string="Message", readonly=True)

    def show_message(self):
        self.ensure_one()
        return {
            'name': _('Import Report'),
            'type': 'ir.actions.act_window',
            'res_model': 'message.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }

                    