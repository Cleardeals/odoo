import logging
from datetime import datetime

from google.cloud import bigquery

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# --- Pointing to Customer_Data as the main source ---
MASTER_PROPERTY_TABLE = "cleardeals-459513.cleardeals_dataset.Customer_Data"
BIGQUERY_PROJECT_ID = "cleardeals-459513"


class PropertyInventory(models.Model):
    _name = "property.inventory"
    _description = "Master Property Inventory for RM Dashboard"
    _order = "service_expiry_date asc, property_tag"
    _rec_name = "property_tag"

    # --- SQL Constraints (Odoo 19 Style) ---
    _property_tag_uniq = models.Constraint(
        "UNIQUE(property_tag)",
        message="Property Tag must be unique.",
    )

    property_tag = fields.Char(
        string="Property Tag",
        readonly=True,
        index=True,
        required=True,
    )
    owner_name = fields.Char(string="Owner Name", readonly=True)
    owner_phone = fields.Char(string="Owner Phone", readonly=True)
    rm_user_id = fields.Many2one(
        "res.users",
        string="Assigned RM",
        readonly=True,
        index=True,
    )

    # --- Real Date Fields (For Logic & Sorting) ---
    service_expiry_date = fields.Date(
        string="Service Expiry Date",
        readonly=True,
        index=True,
    )
    welcome_call_date = fields.Date(
        string="Welcome Call Date",
        readonly=True,
        index=True,
    )

    # --- Computed Display Fields (For UI Formatting DD/MM/YYYY) ---
    service_expiry_date_display = fields.Char(
        string="Service Expiry Date",
        compute="_compute_date_displays",
    )
    welcome_call_date_display = fields.Char(
        string="Welcome Call Date",
        compute="_compute_date_displays",
    )

    # Legacy field from BQ, kept if needed, but display logic moved to computed fields
    service_expiry_date_str = fields.Char(
        string="Expiry Date (Original)",
        readonly=True,
    )

    # Status field to track if property is active
    is_active = fields.Boolean(
        string="Is Active",
        default=True,
        readonly=True,
        index=True,
    )

    # --- Property Details ---
    bhk = fields.Char(string="BHK", readonly=True)
    location = fields.Char(string="Location", readonly=True)
    city = fields.Char(string="City", readonly=True)
    property_link = fields.Char(string="Property Link", readonly=False)

    # --- Portal IDs ---
    ninety_nine_acres_id = fields.Char(string="99acres ID", readonly=True, index=True)
    housing_id = fields.Char(string="Housing.com ID", readonly=True, index=True)
    magicbricks_id = fields.Char(string="Magicbricks ID", readonly=True, index=True)
    olx_id = fields.Char(string="OLX ID", readonly=True, index=True)

    suggestion_ids = fields.One2many(
        "property.lead.suggestion",
        "property_inventory_id",
        string="Suggested Leads",
    )

    suggestion_count = fields.Integer(
        string="Total Suggestions",
        compute="_compute_suggestion_counts",
        store=True,
    )
    new_suggestion_count = fields.Integer(
        string="New Suggestions",
        compute="_compute_suggestion_counts",
        store=True,
    )

    @api.depends("suggestion_ids", "suggestion_ids.status")
    def _compute_suggestion_counts(self):
        """Calculates total and new suggestions for the Kanban/Form view."""
        for prop in self:
            prop.suggestion_count = len(prop.suggestion_ids)
            prop.new_suggestion_count = len(
                prop.suggestion_ids.filtered(lambda s: s.status == "new"),
            )

    @api.depends("service_expiry_date", "welcome_call_date")
    def _compute_date_displays(self):
        """
        Formats dates strictly as DD/MM/YYYY for display purposes.
        This overrides Odoo's default locale formatting (e.g. 'Dec 14').
        """
        for rec in self:
            rec.service_expiry_date_display = (
                rec.service_expiry_date.strftime("%d/%m/%Y")
                if rec.service_expiry_date
                else ""
            )
            rec.welcome_call_date_display = (
                rec.welcome_call_date.strftime("%d/%m/%Y")
                if rec.welcome_call_date
                else ""
            )

    @api.model
    def _cron_sync_properties(self):
        """
        Cron Job: Syncs ACTIVE properties from BigQuery Customer_Data.
        """
        _logger.info(
            "Starting ACTIVE Property Inventory sync from BigQuery Customer_Data...",
        )

        try:
            client = bigquery.Client(project=BIGQUERY_PROJECT_ID)
        except Exception as e:  # noqa: BLE001
            _logger.error("Failed to create BigQuery client: %s", e)
            return

        query = f"""
            WITH LatestPropertyData AS (
                SELECT
                    *,
                    ROW_NUMBER() OVER(
                        PARTITION BY Tag
                        ORDER BY SAFE.PARSE_TIMESTAMP('%d-%m-%Y %H:%M:%S', Created_Date) DESC,
                                 upload_timestamp DESC
                    ) as rn
                FROM `{MASTER_PROPERTY_TABLE}`
                WHERE Tag IS NOT NULL AND TRIM(Tag) != ''
            ),
            PropertiesWithStatus AS (
                SELECT
                    Tag AS property_tag,
                    REGEXP_EXTRACT(Name, r'(?:Mr\\.|Mrs\\.|Dr\\.)\\s?([A-Za-z\\s]+)') AS owner_name,
                    Phone AS owner_phone,
                    Assignee AS assigned_rm,
                    Service_Expiry_Date,
                    Property_Status,
                    `99acres_ID` as ninety_nine_acres_id,
                    SPLIT(CAST(Housing_ID AS STRING), '.')[OFFSET(0)] AS housing_id,
                    SPLIT(CAST(Magicbricks_ID AS STRING), '.')[OFFSET(0)] AS magicbricks_id,
                    SPLIT(CAST(OLX_ID AS STRING), '.')[OFFSET(0)] AS olx_id,
                    BHK,
                    Location,
                    City1 AS city,
                    Property_Link,

                    COALESCE(
                        SAFE.PARSE_DATE('%d/%m/%Y', Service_Expiry_Date),
                        SAFE.PARSE_DATE('%d-%m-%Y', Service_Expiry_Date)
                    ) as expiry_date,
                    COALESCE(
                        SAFE.PARSE_DATE('%d/%m/%Y', Welcome_Call_Date),
                        SAFE.PARSE_DATE('%d-%m-%Y', Welcome_Call_Date)
                    ) as welcome_call_date,
                    CASE
                        WHEN Property_Status IN ('Sold-CD', 'Sold-Others', 'Rented-CD') THEN 'Sold'
                        WHEN COALESCE(
                            SAFE.PARSE_DATE('%d/%m/%Y', Service_Expiry_Date),
                            SAFE.PARSE_DATE('%d-%m-%Y', Service_Expiry_Date)
                        ) < CURRENT_DATE('Asia/Kolkata') THEN 'Expired'
                        ELSE 'Active'
                    END AS calculated_status
                FROM LatestPropertyData
                WHERE rn = 1
            )
            SELECT
                property_tag,
                owner_name,
                owner_phone,
                assigned_rm,
                Service_Expiry_Date,
                expiry_date,
                welcome_call_date,
                calculated_status,
                ninety_nine_acres_id,
                housing_id,
                magicbricks_id,
                olx_id,
                BHK,
                Location,
                city,
                Property_Link
            FROM PropertiesWithStatus
            WHERE calculated_status = 'Active'
            ORDER BY expiry_date ASC NULLS LAST
        """

        try:
            _logger.info("Running BigQuery query to fetch active properties...")
            query_job = client.query(query)
            results = list(query_job.result())
            _logger.info(f"✅ Fetched {len(results)} active properties from BigQuery.")

            Users = self.env["res.users"]

            _logger.info("Fetching existing properties from Odoo...")
            existing_props = self.search_read([], ["property_tag", "is_active"])
            existing_props_map = {prop["property_tag"]: prop for prop in existing_props}
            _logger.info(
                f"Found {len(existing_props_map)} existing properties in Odoo.",
            )

            created_count = 0
            updated_count = 0
            skipped_null_date = 0
            missing_rm_count = 0
            bq_active_tags = set()

            for row in results:
                if not row.property_tag:
                    continue

                bq_active_tags.add(row.property_tag)

                if row.expiry_date is None:
                    skipped_null_date += 1
                    _logger.debug(
                        f"Skipping '{row.property_tag}': NULL expiry_date despite Active status",
                    )
                    continue

                rm_user_id = False
                assigned_rm_name = row.assigned_rm
                if assigned_rm_name:
                    try:
                        clean_rm_name = str(assigned_rm_name).strip()
                        if clean_rm_name:
                            rm_user = Users.search(
                                [("name", "=", clean_rm_name)],
                                limit=1,
                            )
                            if rm_user:
                                rm_user_id = rm_user.id
                            else:
                                _logger.warning(
                                    f"Property '{row.property_tag}': RM '{clean_rm_name}' not found in Odoo Users.",
                                )
                                missing_rm_count += 1
                    except Exception as user_search_err:
                        _logger.error(
                            "Error searching for RM user '%s': %s",
                            assigned_rm_name,
                            user_search_err,
                        )

                service_expiry_date = None
                service_expiry_date_str = (
                    row.Service_Expiry_Date if row.Service_Expiry_Date else ""
                )

                try:
                    if isinstance(row.expiry_date, str):
                        service_expiry_date = datetime.strptime(
                            row.expiry_date,
                            "%Y-%m-%d",
                        ).date()
                    else:
                        service_expiry_date = row.expiry_date

                    if not service_expiry_date:
                        _logger.warning(
                            f"Property '{row.property_tag}': Failed to parse date '{row.Service_Expiry_Date}'",
                        )
                        skipped_null_date += 1
                        continue
                except Exception as date_err:
                    _logger.warning(
                        f"Property '{row.property_tag}': Error converting expiry date: {date_err}",
                    )
                    continue

                welcome_call_date = None
                try:
                    if row.welcome_call_date:
                        if isinstance(row.welcome_call_date, str):
                            welcome_call_date = datetime.strptime(
                                row.welcome_call_date,
                                "%Y-%m-%d",
                            ).date()
                        else:
                            welcome_call_date = row.welcome_call_date
                except Exception as welcome_date_err:
                    _logger.warning(
                        f"Property '{row.property_tag}': Error converting welcome call date: {welcome_date_err}",
                    )
                    welcome_call_date = None

                vals = {
                    "property_tag": row.property_tag,
                    "owner_name": row.owner_name if row.owner_name else "",
                    "owner_phone": row.owner_phone if row.owner_phone else "",
                    "rm_user_id": rm_user_id,
                    "service_expiry_date": service_expiry_date,
                    "service_expiry_date_str": service_expiry_date_str,
                    "welcome_call_date": welcome_call_date,
                    "is_active": True,
                    "bhk": row.BHK if row.BHK else "",
                    "location": row.Location if row.Location else "",
                    "city": row.city if row.city else "",
                    "property_link": row.Property_Link if row.Property_Link else "",
                    "ninety_nine_acres_id": row.ninety_nine_acres_id
                    if row.ninety_nine_acres_id
                    else False,
                    "housing_id": row.housing_id if row.housing_id else False,
                    "magicbricks_id": row.magicbricks_id
                    if row.magicbricks_id
                    else False,
                    "olx_id": row.olx_id if row.olx_id else False,
                }

                existing_prop_data = existing_props_map.get(row.property_tag)

                try:
                    if existing_prop_data:
                        prop_id = existing_prop_data["id"]
                        prop_record = self.browse(prop_id)
                        prop_record.write(vals)
                        updated_count += 1
                    else:
                        self.create(vals)
                        created_count += 1

                    if (created_count + updated_count) % 100 == 0:
                        self.env.cr.commit()

                except Exception as db_err:
                    _logger.error(
                        f"Database error processing property '{row.property_tag}': {db_err}",
                    )
                    self.env.cr.rollback()
                    continue

            _logger.info(
                "Deactivating properties that are no longer active in BigQuery...",
            )
            tags_in_odoo = set(existing_props_map.keys())
            tags_to_deactivate = tags_in_odoo - bq_active_tags
            deactivated_count = 0

            if tags_to_deactivate:
                prop_ids_to_deactivate = []
                for tag in tags_to_deactivate:
                    prop_data = existing_props_map[tag]
                    if prop_data["is_active"]:
                        prop_ids_to_deactivate.append(prop_data["id"])

                if prop_ids_to_deactivate:
                    try:
                        properties_to_deactivate = self.browse(prop_ids_to_deactivate)
                        properties_to_deactivate.write({"is_active": False})
                        deactivated_count = len(properties_to_deactivate)
                        _logger.info(
                            "Successfully deactivated %s properties.",
                            deactivated_count,
                        )
                    except Exception as deactivation_err:
                        _logger.error(
                            "Error deactivating properties: %s",
                            deactivation_err,
                        )
                        self.env.cr.rollback()

            _logger.info("")
            _logger.info("========== Property Inventory Sync Summary ==========")
            _logger.info(f"  Total records fetched from BQ: {len(results)}")
            _logger.info(f"  Processed BQ tags: {len(bq_active_tags)}")
            _logger.info("  Successfully created: %s", created_count)
            _logger.info("  Successfully updated: %s", updated_count)
            _logger.info("  Deactivated (Sold/Expired): %s", deactivated_count)
            _logger.info("  Skipped (NULL expiry date): %s", skipped_null_date)
            if missing_rm_count > 0:
                _logger.warning(
                    "  Missing RM assignments (warnings): %s",
                    missing_rm_count,
                )
            _logger.info("=====================================================")

            self.env.cr.commit()

        except Exception as e:
            _logger.error("Error during Property Inventory sync: %s", e)
            import traceback

            _logger.error(traceback.format_exc())
            self.env.cr.rollback()

    @api.model
    def _cron_cleanup_expired_properties(self):
        """
        Separate cron job to mark properties as inactive if they've expired.
        """
        _logger.info("Starting cleanup of expired properties...")
        try:
            today = fields.Date.today()
            expired_properties = self.search(
                [
                    ("service_expiry_date", "<", today),
                    ("is_active", "=", True),
                ],
            )

            if expired_properties:
                expired_properties.write({"is_active": False})
                _logger.info(
                    f"Marked {len(expired_properties)} properties as inactive (expired)",
                )
            else:
                _logger.info("No expired properties found")

        except Exception as e:
            _logger.error("Error during expired properties cleanup: %s", e)
