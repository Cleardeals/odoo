import base64
import csv
import io
import logging

try:
    import openpyxl
except ImportError:
    openpyxl = None

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LeadImportWizard(models.TransientModel):
    _name = "lead.csv.import.wizard"
    _description = "Lead Import Wizard (Multi-File)"

    file_ids = fields.Many2many(
        "ir.attachment",
        string="Upload Files",
        help="Upload one or more .csv or .xlsx files",
    )

    def import_leads(self):
        """
        Iterates through all uploaded files and processes them.
        """
        if not self.file_ids:
            raise UserError(_("Please upload at least one file."))

        # Global counters for the batch
        total_imported = 0
        all_failed_rows = []

        # Cache properties to avoid repeated DB lookups across files
        property_cache = {}

        LeadsNew = self.env["leads.new"].with_context(automated_lead_creation=True)
        olx_source = LeadsNew._get_or_create_source("OLX", source_type="portal")

        COLUMN_MAPPING = {
            "name": "Name",
            "phone": "Phone Number",
            "email": "Email Id",
            "olx_id": "Inventory ID",
        }

        # --- LOOP THROUGH EACH FILE ---
        for attachment in self.file_ids:
            filename = attachment.name.lower()
            file_label = f"[{attachment.name}]"  # Used for error messages

            _logger.info("Processing file: %s", filename)

            try:
                decoded_data = base64.b64decode(attachment.datas)
            except Exception as e:
                all_failed_rows.append(
                    f"{file_label} Critical: Could not decode file. {e!s}",
                )
                continue

            rows_to_process = []

            # --- 1. PARSE FILE (Excel vs CSV) ---
            try:
                if filename.endswith(".xlsx"):
                    if not openpyxl:
                        raise UserError(_("The library 'openpyxl' is missing."))

                    wb = openpyxl.load_workbook(
                        filename=io.BytesIO(decoded_data),
                        read_only=True,
                        data_only=True,
                    )
                    ws = wb.active
                    all_rows = list(ws.iter_rows(values_only=True))

                    if not all_rows:
                        all_failed_rows.append(f"{file_label} Warning: File is empty.")
                        continue

                    headers = [
                        str(h).strip() if h is not None else "" for h in all_rows[0]
                    ]

                    for row_values in all_rows[1:]:
                        if not any(row_values):
                            continue
                        row_dict = dict(zip(headers, row_values))
                        rows_to_process.append(row_dict)

                elif filename.endswith(".csv"):
                    try:
                        data_str = decoded_data.decode("utf-8")
                    except UnicodeDecodeError:
                        data_str = decoded_data.decode("latin-1")

                    csv_file = io.StringIO(data_str, newline="")
                    reader = csv.DictReader(csv_file)
                    reader.fieldnames = (
                        [name.strip() for name in reader.fieldnames]
                        if reader.fieldnames
                        else []
                    )

                    for row in reader:
                        if any(row.values()):
                            rows_to_process.append(row)
                else:
                    all_failed_rows.append(
                        f"{file_label} Skipped: Unsupported file format.",
                    )
                    continue

            except Exception as e:
                all_failed_rows.append(
                    f"{file_label} Critical Error parsing file: {e!s}",
                )
                continue

            # --- 2. PROCESS ROWS FOR THIS FILE ---
            for index, row in enumerate(rows_to_process):
                row_num = index + 2

                # Helper to get values safely
                clean_row = {str(k).strip(): v for k, v in row.items() if k}

                def get_val(key):
                    val = clean_row.get(key)
                    return str(val).strip() if val is not None else False

                lead_name = get_val(COLUMN_MAPPING["name"])
                lead_phone = get_val(COLUMN_MAPPING["phone"])
                lead_email = get_val(COLUMN_MAPPING["email"])
                olx_id = get_val(COLUMN_MAPPING["olx_id"])

                if lead_phone and lead_phone.endswith(".0"):
                    lead_phone = lead_phone[:-2]

                # Validation
                if not lead_name:
                    all_failed_rows.append(f"{file_label} Row {row_num}: Missing Name.")
                    continue
                if not lead_phone:
                    all_failed_rows.append(
                        f"{file_label} Row {row_num}: Missing Phone.",
                    )
                    continue

                if olx_id:
                    olx_id = olx_id.strip("'")

                try:
                    # Logic: New Lead (Unassigned) vs Assigned
                    state = "new"
                    property_base_id = False
                    user_id = False
                    process_notes = ""

                    if olx_id:
                        if olx_id in property_cache:
                            prop = property_cache[olx_id]
                        else:
                            prop = LeadsNew._resolve_property_from_portal(
                                "OLX",
                                olx_id,
                            )
                            # Cache both hits AND misses (empty recordset) to
                            # avoid a repeated DB query for the same olx_id.
                            property_cache[olx_id] = prop

                        if prop:
                            property_base_id = prop.id
                            if prop.rm_user_id:
                                user_id = prop.rm_user_id.id
                                state = "assigned"
                                process_notes = f"Source: {attachment.name}. Assigned to {prop.rm_user_id.name}."
                            else:
                                state = "new"
                                process_notes = f"Source: {attachment.name}. Matched Property {prop.name}, no RM."
                        else:
                            state = "new"
                            process_notes = f"Source: {attachment.name}. Portal Listing ID '{olx_id}' not found."
                    else:
                        state = "new"
                        process_notes = f"Source: {attachment.name}. No Portal Listing ID."

                    # Create Lead
                    create_vals = {
                        "name": lead_name,
                        "phone": lead_phone,
                        "email": lead_email
                        if lead_email and lead_email.lower() != "null"
                        else False,
                        "source_id": olx_source.id,
                        "portal_property_id": olx_id,
                        "property_base_id": property_base_id,
                        "user_id": user_id,
                        "state": state,
                        "current_status": "lead",
                        "process_notes": process_notes,
                        "raw_data": str(clean_row),
                    }

                    new_lead = LeadsNew.create_lead_if_not_duplicate(create_vals)

                    if new_lead:
                        total_imported += 1
                    else:
                        # Optional: Log duplicates if you want to see them in the report
                        # all_failed_rows.append(f"{file_label} Row {row_num}: Duplicate Lead.")
                        pass

                except Exception as e:
                    all_failed_rows.append(
                        f"{file_label} Row {row_num}: System Error: {e!s}",
                    )

        # --- FINAL SUMMARY REPORT ---
        error_details = "\n".join(all_failed_rows)

        if total_imported > 0:
            message = f"Batch Complete! Successfully imported {total_imported} leads from {len(self.file_ids)} file(s)."
            if all_failed_rows:
                message += f"\n\nWarnings/Errors:\n{error_details}"
        else:
            message = (
                f"Batch Complete. No leads were imported.\n\nErrors:\n{error_details}"
            )

        return {
            "name": "Batch Import Result",
            "type": "ir.actions.act_window",
            "res_model": "message.wizard",
            "view_mode": "form",
            "res_id": self.env["message.wizard"].create({"message": message}).id,
            "target": "new",
        }


class MessageWizard(models.TransientModel):
    _name = "message.wizard"
    _description = "Message Wizard"
    message = fields.Text(string="Message", readonly=True)
