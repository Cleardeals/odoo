import hashlib
import hmac
import json
import logging
import re
import time
from datetime import timedelta

import pytz
import requests
from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)


class NewPortalLead(models.Model):
    _name = "leads.new"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Leads"
    _order = "create_date desc"

    # Lead Fields
    name = fields.Char("Lead Name", required=True, index=True, tracking=True)
    phone = fields.Char("Phone Number", index=True, tracking=True)
    email = fields.Char("Email Address", index=True, tracking=True)
    source_id = fields.Many2one(
        "lead.source",
        string="Source",
        index=True,
        tracking=True,
    )
    source_type = fields.Selection(
        related="source_id.source_type",
        store=True,
        readonly=True,
    )
    portal_name = fields.Char(
        string="Legacy Portal Name",
        related="source_id.name",
        store=True,
        readonly=True,
    )
    project_name = fields.Char("Project Name", help="Project Name from portal")
    portal_property_id = fields.Char(
        "Portal Property ID",
        help="The property ID as per the portal",
        index=True,
    )
    raw_data = fields.Text("Raw Data Dump")

    # Processing and Assignment Fields
    state = fields.Selection(
        [
            ("new", "New"),
            ("assigned", "Assigned"),
            ("failed", "Failed Assignment"),
        ],
        default="new",
        required=True,
        index=True,
        copy=False,
        tracking=True,
    )

    current_status = fields.Selection(
        [
            ("busy", "Busy"),
            ("lead", "Lead"),
            ("ringing", "Ringing"),
            ("call_back_later", "Call Back Later"),
            ("site_visit_scheduled", "Site Visit Scheduled"),
            ("option_not_matching_requirements", "Option Not Matching Requirements"),
            ("details_shared_of_property", "Details Shared of Property"),
            ("no_requirements", "No Requirements"),
            (
                "detail_shared_and_interested_for_site_visit",
                "Detail Shared and Interested for Site Visit",
            ),
            ("switched_off", "Switched Off"),
            ("requirement_closed", "Requirement Closed"),
            ("property_sold_out", "Property Sold Out"),
            ("rescheduled", "Rescheduled"),
            ("budget_not_sufficient", "Budget Not Sufficient"),
            ("site_visit_done", "Site Visit Done"),
            ("number_not_in_use_wrong_number", "Number Not in Use/Wrong Number"),
            ("other", "Other"),
        ],
        string="Current Status",
        default="lead",
        required=True,
        tracking=True,
    )

    remarks = fields.Text("Remarks", tracking=True)

    feedback_general = fields.Selection(
        [
            ("buyer_did_not_visit_property", "Buyer Did Not Visit Property"),
            ("buyer_not_interested", "Buyer Not Interested"),
            ("buyer_not_picking_call", "Buyer Not Picking Call"),
            ("visit_needs_to_be_rescheduled", "Visit Needs to be Rescheduled"),
            ("other", "Other"),
        ],
        string="Feedback",
        tracking=True,
    )

    feedback_site_visit_done = fields.Selection(
        [
            ("buyer_liked_property", "Buyer Liked Property"),
            ("buyer_requirement_closed", "Buyer Requirement Closed"),
            ("buyer_visit_from_outside", "Buyer Visit From Outside"),
            ("buyer_not_pickup_call", "Buyer Not Picking Call"),
            ("planning_for_second_visit", "Planning for Second Visit"),
            ("negotiation_stage", "Negotiation Stage"),
            ("visit_done_confirmed_by_owner", "Visit Done - Confirmed by Owner"),
            ("looking_for_more_options", "Looking for More Options"),
            ("price_is_high", "Price is High"),
            ("location_mismatch", "Location Mismatch"),
            ("deal_closed", "Deal Closed"),
            ("other", "Other"),
        ],
        string="Feedback for Site Visit Done",
        tracking=True,
    )

    is_ops_sale_lead = fields.Boolean(
        string="Is Ops Sale Lead",
        default=False,
        tracking=True,
    )

    site_visit_date = fields.Datetime(
        string="Site Visit Scheduled On",
        copy=False,
        index=True,
        tracking=True,
    )

    site_visit_date_only = fields.Date(
        string="Site Visit Date (Main Property)",
        compute="_compute_site_visit_date_only",
        store=True,  # Essential for filtering
        readonly=True,
    )

    first_contact_datetime = fields.Datetime(
        string="First Contact On",
        readonly=True,
        copy=False,
        tracking=True,
    )

    # Keeps pointing to property.inventory — matches the existing DB column (6 000+
    # historical leads were assigned using property.inventory IDs). Never change
    # this comodel without a proper DB migration; doing so breaks upgrades.
    property_id = fields.Many2one(
        "property.inventory",
        string="Related Property (Legacy)",
        index=True,
    )

    # NEW field — links to the canonical property.base model.
    # Populated going forward by _process_lead_logic() and backfilled for
    # historical leads via the Lead Property Migration Wizard.
    property_base_id = fields.Many2one(
        "property.base",
        string="Related Property",
        copy=False,
        index=True,
        tracking=True,
        context={"search_all_properties_for_lead": True},
    )

    user_id = fields.Many2one(
        "res.users",
        string="Assigned RM",
        copy=False,
        tracking=True,
    )

    # ------------------------------------------------------------------
    # New related fields — sourced from property.base (property_base_id).
    # Populated as property_base_id gets backfilled / set on new leads.
    # Once the migration is complete these become the primary display fields.
    # ------------------------------------------------------------------

    base_property_tag = fields.Char(
        related="property_base_id.property_tag",
        string="Property Tag",
        readonly=True,
        store=True,
    )

    base_property_bhk = fields.Char(
        related="property_base_id.bhk",
        string="Property BHK",
        readonly=True,
        store=True,
    )

    base_property_location = fields.Char(
        related="property_base_id.location",
        string="Property Location",
        readonly=True,
        store=True,
    )

    base_property_city = fields.Char(
        related="property_base_id.city",
        string="Property City",
        readonly=True,
        store=True,
    )

    base_property_owner_name = fields.Char(
        related="property_base_id.owner_name",
        string="Property Owner",
        readonly=True,
        store=True,
    )

    base_property_link = fields.Char(
        related="property_base_id.property_link",
        string="Property Link",
        readonly=True,
        store=True,
    )

    process_notes = fields.Text("Processing Notes")

    phone_whatsapp_url = fields.Char(
        string="WhatsApp URL",
        compute="_compute_phone_whatsapp_url",
        store=False,
    )

    phone_whatsapp_html = fields.Html(
        string="Phone",
        compute="_compute_phone_whatsapp_html",
        store=False,
    )

    # Field for webhook queue
    is_webhook_sent = fields.Boolean(
        string="Webhook Sent",
        default=False,
        copy=False,
        index=True,
        help="Tracks if this lead has been sent to the n8n webhook.",
    )

    interest_ids = fields.One2many(
        "lead.property.interest",
        "lead_id",
        string="Recommended Properies",
        store=True,
    )

    all_associated_properties = fields.Many2many(
        "property.base",
        relation="leads_new_property_base_rel",
        string="All Associated Properties",
        compute="_compute_all_associated_properties",
        store=True,
        help="Includes property_base_id (primary) and all recommended properties.",
    )

    x_migrated_date = fields.Datetime(string="Migration Date Temp")

    create_date_only = fields.Date(
        string="Creation Date",
        compute="_compute_create_date_only",
        store=True,
        readonly=True,
    )

    # --- Compute Methods ---

    @api.depends("property_base_id", "interest_ids.property_base_id")
    def _compute_all_associated_properties(self):
        """
        Combines the primary property (property_base_id) and all recommended
        properties (interest_ids.property_base_id) into a single Many2many field.
        """
        for lead in self:
            properties = lead.property_base_id

            if lead.interest_ids:
                properties |= lead.interest_ids.mapped("property_base_id")

            lead.all_associated_properties = properties

    @api.depends("create_date")
    def _compute_create_date_only(self):
        """
        Converts the UTC 'create_date' to IST before extracting the Date.
        This ensures 2:00 AM IST is recorded as 'Today', not 'Yesterday'.
        """
        ist_timezone = pytz.timezone("Asia/Kolkata")
        for rec in self:
            if rec.create_date:
                # 1. Convert UTC timestamp to IST
                utc_time = rec.create_date.replace(tzinfo=pytz.UTC)
                ist_time = utc_time.astimezone(ist_timezone)

                # 2. Extract the Date from the IST time
                rec.create_date_only = ist_time.date()
            else:
                rec.create_date_only = False

    @api.depends("site_visit_date")
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

    @api.model
    def _standardize_phone(self, phone_number):
        """
        Strips all non-numeric characters from the phone number
        and returns a 10-digit number if possible.
        """
        if not phone_number:
            return ""

        numeric_phone = re.sub(r"\D", "", phone_number)

        # Check if it starts with 91 and is 12 digits long
        if len(numeric_phone) == 12 and numeric_phone.startswith("91"):
            return numeric_phone[2:]

        # Check if it's already 10 digits
        if len(numeric_phone) == 10:
            return numeric_phone

        _logger.warning("Phone number %s could not be standardized.", phone_number)
        return numeric_phone  # Return as-is if it doesn't fit expected formats

    @api.model_create_multi
    def create(self, vals_list):
        automated_creation = bool(self.env.context.get("automated_lead_creation"))

        normalized_vals_list = []
        for vals in vals_list:
            vals = dict(vals)
            vals["phone"] = self._standardize_phone(vals.get("phone"))

            if not vals.get("source_id") and vals.get("portal_name"):
                source = self._get_or_create_source(
                    vals.get("portal_name"),
                    source_type="portal",
                )
                if source:
                    vals["source_id"] = source.id

            if not vals.get("source_id"):
                raise ValidationError("A lead source is required.")

            if not automated_creation:
                duplicate_domain, _, _ = self._compute_duplicate_domain(vals)
                if duplicate_domain:
                    existing_lead = self.sudo().search(duplicate_domain, limit=1)
                    if existing_lead:
                        status_selection = dict(self._fields["current_status"].selection)
                        status_label = status_selection.get(
                            existing_lead.current_status,
                            existing_lead.current_status or "Unknown",
                        )
                        rm_name = existing_lead.user_id.name or "Unassigned"
                        raise ValidationError(
                            "Duplicate lead detected in last 30 days for the same phone/property criteria.\n"
                            f"Assigned RM: {rm_name}\n"
                            f"Current Status: {status_label}",
                        )

                # Manual leads are always owned by the creator and start assigned.
                vals["state"] = "assigned"
                vals["user_id"] = self.env.user.id

            normalized_vals_list.append(vals)

        # Suppress automatic chatter log on creation.
        # Context must be set on `self` before super() — calling
        # super().with_context().create() returns the same overridden method
        # and causes infinite recursion.
        new_leads = super(
            NewPortalLead,
            self.with_context(mail_create_nolog=True),
        ).create(normalized_vals_list)

        non_portal_leads = new_leads.filtered(
            lambda lead: lead.source_type and lead.source_type != "portal",
        )
        for lead in non_portal_leads:
            source_name = lead.source_id.name or "Unknown"
            creator_name = lead.create_uid.name or "System"
            body = Markup(
                "<p><strong>Manual Lead Created</strong><br/>"
                "Source: %s<br/>"
                "Created By: %s</p>"
            ) % (
                html_escape(source_name),
                html_escape(creator_name),
            )
            lead.message_post(
                body=body,
                subtype_xmlid="mail.mt_note",
            )

        channel = "leads.new"
        notification_type = "bus_notification"
        message = {
            "ids": new_leads.ids,
            "model": "leads.new",
            "event": "create",
        }

        self.env["bus.bus"]._sendone(channel, notification_type, message)

        return new_leads

    @api.model
    def _canonical_portal_code(self, source_name):
        normalized = (source_name or "").strip().lower()
        portal_map = {
            "99acres": "99acres",
            "housing.com": "Housing.com",
            "housing": "Housing.com",
            "magicbricks": "MagicBricks",
            "magicbricks.com": "MagicBricks",
            "olx": "OLX",
        }
        return portal_map.get(normalized)

    @api.model
    def _get_or_create_source(self, source_name, source_type="portal"):
        source_name = (source_name or "").strip()
        if not source_name:
            return self.env["lead.source"]

        source_model = self.env["lead.source"].sudo()
        category_model = self.env["lead.source.category"].sudo()

        existing = source_model.search([("name", "=", source_name)], limit=1)
        if existing:
            return existing

        if source_type == "portal":
            portal_code = self._canonical_portal_code(source_name)
            if not portal_code:
                source_type = "manual"

        if source_type == "portal":
            category = self.env.ref(
                "leads.lead_source_category_portal",
                raise_if_not_found=False,
            )
            if not category:
                category = category_model.search(
                    [("code", "=", "portals")],
                    limit=1,
                )
            if not category:
                category = category_model.create(
                    {
                        "name": "Portals",
                        "code": "portals",
                        "source_type": "portal",
                        "sequence": 10,
                    }
                )
            return source_model.create(
                {
                    "name": source_name,
                    "category_id": category.id,
                    "portal_code": portal_code,
                }
            )

        default_category = category_model.search(
            [("source_type", "=", "manual")],
            order="sequence, id",
            limit=1,
        )
        if not default_category:
            default_category = category_model.create(
                {
                    "name": "Manual",
                    "code": "manual",
                    "source_type": "manual",
                    "sequence": 999,
                }
            )
        return source_model.create(
            {
                "name": source_name,
                "category_id": default_category.id,
            }
        )

    @api.model
    def _compute_duplicate_domain(self, lead_vals):
        """Build duplicate-check domain using the same criteria for all lead inflows."""
        phone_raw = lead_vals.get("phone")
        phone_clean = self._standardize_phone(phone_raw)
        source_id = lead_vals.get("source_id")
        if not source_id and lead_vals.get("source"):
            source = self._get_or_create_source(lead_vals.get("source"))
            source_id = source.id
            lead_vals["source_id"] = source_id
        if not source_id and lead_vals.get("portal_name"):
            source = self._get_or_create_source(
                lead_vals.get("portal_name"),
                source_type="portal",
            )
            source_id = source.id
            lead_vals["source_id"] = source_id

        portal_prop_id = lead_vals.get("portal_property_id")
        lead_vals["phone"] = phone_clean

        if not phone_clean:
            return None, phone_clean, portal_prop_id

        source = self.env["lead.source"].browse(source_id) if source_id else False
        property_base_id = lead_vals.get("property_base_id")

        if not portal_prop_id and not property_base_id:
            return None, phone_clean, portal_prop_id

        resolved_property = self._resolve_property_from_source(
            source,
            portal_prop_id,
        )

        if resolved_property:
            lead_vals.setdefault("property_base_id", resolved_property.id)

        time_limit = fields.Datetime.now() - timedelta(days=30)
        if resolved_property:
            domain = [
                ("phone", "=", phone_clean),
                ("property_base_id", "=", resolved_property.id),
                ("create_date", ">=", time_limit),
            ]
        elif property_base_id:
            domain = [
                ("phone", "=", phone_clean),
                ("property_base_id", "=", property_base_id),
                ("create_date", ">=", time_limit),
            ]
        else:
            domain = [
                ("phone", "=", phone_clean),
                ("source_id", "=", source_id),
                ("portal_property_id", "=", portal_prop_id),
                ("create_date", ">=", time_limit),
            ]

        return domain, phone_clean, portal_prop_id

    @api.model
    def create_lead_if_not_duplicate(self, lead_vals):
        """
        Central Function to create leads.
        Checks for duplicates before creating new lead.
        Preferred duplicate key: same phone + same resolved property_base_id
        in last 30 days (so multiple portal IDs on the same property don't
        create duplicates).

        Fallback (when no portal-listing mapping exists yet):
        same phone + same portal source + same portal_property_id in 30 days.
        """
        duplicate_domain, phone_clean, portal_prop_id = self._compute_duplicate_domain(
            lead_vals,
        )

        if not duplicate_domain and not phone_clean:
            _logger.info(
                "Cannot check for duplicate (missing phone), creating lead.",
            )
            return self.with_context(automated_lead_creation=True).create(lead_vals)

        if not duplicate_domain:
            _logger.info(
                "Cannot check for duplicate (no portal listing ID and no property), creating lead.",
            )
            return self.with_context(automated_lead_creation=True).create(lead_vals)

        existing_lead = self.sudo().search(duplicate_domain, limit=1)

        if existing_lead:
            _logger.info(
                "Duplicate lead detected. Phone: %s, Portal Property ID: %s. Skipping creation.",
                phone_clean,
                portal_prop_id,
            )
            return None
        else:  # noqa: RET505
            return self.with_context(automated_lead_creation=True).create(lead_vals)

    def write(self, vals):
        """
        Override write to automatically log 'first_contact_datetime'
        AND to send a bus notification.
        """

        leads_to_stamp = self.env["leads.new"]
        first_contact_time = False
        if "current_status" in vals and vals["current_status"] != "lead":
            leads_to_stamp = self.filtered(lambda r: not r.first_contact_datetime)
            if leads_to_stamp:
                first_contact_time = fields.Datetime.now()

        res = super().write(vals)

        if leads_to_stamp and first_contact_time:
            leads_to_stamp.write(
                {
                    "first_contact_datetime": first_contact_time,
                },
            )

        channel = "leads.new"
        notification_type = "bus_notification"
        message = {
            "ids": self.ids,
            "model": "leads.new",
            "event": "write",
        }

        self.env["bus.bus"]._sendone(channel, notification_type, message)

        return res

    # --- Lead Processing & Assignment ---

    @api.model
    def _resolve_property_from_source(self, source, portal_listing_id):
        """Resolve a property.base from source + listing ID."""
        source_rec = source
        if isinstance(source, int):
            source_rec = self.env["lead.source"].browse(source)

        portal = (source_rec.portal_code or "").strip() if source_rec else ""
        portal_pid = (portal_listing_id or "").strip()

        if not portal or not portal_pid:
            return self.env["property.base"]

        listing = (
            self.env["property.portal.listing"]
            .sudo()
            .search(
                [
                    ("portal_name", "=", portal),
                    ("portal_listing_id", "=", portal_pid),
                    ("active", "=", True),
                ],
                limit=1,
            )
        )
        return listing.property_base_id if listing else self.env["property.base"]

    def _find_property(self):
        """Finds the synced property from property.portal.listing."""

        self.ensure_one()
        property_rec = self._resolve_property_from_source(
            self.source_id,
            self.portal_property_id,
        )
        if not property_rec:
            _logger.warning(
                "Lead %s: No portal listing found for source '%s' and listing ID '%s'",
                self.id,
                self.source_id.display_name,
                self.portal_property_id,
            )
        return property_rec

    def _find_rm(self, property_base):
        """Finds the correct RM from a property.base record."""
        self.ensure_one()

        if property_base and property_base.rm_user_id:
            return property_base.rm_user_id

        _logger.warning(
            "Property %s has no RM. Assigning to admin",
            property_base.display_name if property_base else "(none)",
        )
        return self.env.ref("base.user_admin")

    def _process_lead_logic(self):
        """
        Processes lead assignment.
        If Property is found, assigns to the linked RM.
        If Property is NOT found, assigns based on Portal:
        - 99acres -> Pratham Bhandari
        - MagicBricks -> Mayuri Malivad
        - Housing.com/OLX -> Naresh Rojiya
        """
        self.ensure_one()
        _logger.info(
            "🔄 Processing lead %s: %s (state: %s)",
            self.id,
            self.name,
            self.state,
        )

        if self.state != "new":
            _logger.info("⏭️ Skipping lead %s, state is %s", self.id, self.state)
            return

        try:
            property_rec = self._find_property()
            rm_user = False
            notes = ""

            if property_rec:
                _logger.info(
                    "✅ Lead %s: Found property %s (ID: %s)",
                    self.id,
                    property_rec.property_tag,
                    property_rec.id,
                )
                rm_user = self._find_rm(property_rec)
                _logger.info(
                    "✅ Lead %s: Found RM %s (ID: %s)",
                    self.id,
                    rm_user.name,
                    rm_user.id,
                )
                notes = f"Successfully assigned to RM {rm_user.name} for property {property_rec.property_tag}.\n"

            if not property_rec:
                source_name = self.source_id.display_name or "Unknown"
                msg = f"Property not found for {source_name} ID: {self.portal_property_id}"
                _logger.warning(
                    "⚠️ Lead %s: %s. Attempting to assign to default RM.",
                    self.id,
                    msg,
                )

                rm_user = self.source_id.default_rm_user_id

                if not rm_user:
                    _logger.error(
                        "No default RM configured for source '%s'. Assigning to Administrator.",
                        source_name,
                    )
                    rm_user = self.env.ref("base.user_admin")

                notes = f"{msg}\nAssigned to Default RM: {rm_user.name}.\n"

            self.write(
                {
                    "property_base_id": property_rec.id if property_rec else False,
                    "user_id": rm_user.id,
                    "state": "assigned",
                    "process_notes": notes,
                },
            )

            _logger.info(
                "🎉 Lead %s: Successfully assigned to %s for property %s",
                self.id,
                rm_user.name,
                property_rec.property_tag if property_rec else "N/A",
            )

        except Exception as e:
            _logger.exception("❌ Failed to process lead %s", self.id)
            self.write(
                {
                    "state": "failed",
                    "process_notes": f"Processing failed with error: {e!s}\n",
                },
            )

    # --- Cron Jobs ---

    @api.model
    def _cron_reprocess_unassigned_leads(self):
        """Called by the 4 hour cron to find and re-process leads
        that are still 'new' due to data lag.
        """
        _logger.info("CRON: Starting re-process for unassigned leads...")
        domain = [
            ("state", "=", "new"),
            ("create_date", "<", fields.Datetime.now() - timedelta(hours=1)),
        ]
        leads_to_retry = self.search(domain)
        _logger.info(
            "CRON: Found %s unassigned leads to reprocess.",
            len(leads_to_retry),
        )

        for lead in leads_to_retry:
            _logger.info("CRON: Re-processing lead %s synchronously...", lead.id)
            try:
                lead._process_lead_logic()
            except Exception:
                _logger.exception(
                    "CRON: Failed during synchronous re-process of lead %s",
                    lead.id,
                )

    # --- HOUSING.COM PULL METHOD ---
    def _api_fetch_housing(self):
        """
        Fetches new leads from the Housing.com API using HMAC auth.
        """
        _logger.info("CRON: Attempting to fetch leads from Housing.com API...")
        HOUSING_ENDPOINT = "https://pahal.housing.com/api/v0/get-broker-leads"
        HEADERS = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36",
        }

        config = self.env["ir.config_parameter"].sudo()
        api_key = config.get_param("housing.api.key")
        api_id = config.get_param("housing.api.id")

        if not api_key or not api_id:
            _logger.error(
                "CRITICAL: housing.api.key or housing.api.id not set in system parameters",
            )
            return []

        try:
            end_time = int(time.time())
            start_time = end_time - (20 * 60)  # 20 minutes ago
            current_time_str = str(end_time)

            hash_h = hmac.new(
                api_key.encode("utf-8"),
                current_time_str.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

            params = {
                "start_date": start_time,
                "end_date": end_time,
                "current_time": current_time_str,
                "hash": hash_h,
                "id": api_id,
                "per_page": 1000,
            }

            response = requests.get(
                HOUSING_ENDPOINT,
                params=params,
                headers=HEADERS,
                timeout=30,
            )
            response.raise_for_status()
            response_data = response.json()

            if "apiErrors" in response_data:
                _logger.error("Housing.com API Errors: %s", json.dumps(response_data))
                return []

            if response_data.get("data"):
                raw_leads = response_data["data"]
                _logger.info("Housing.com: Found %s leads from API.", len(raw_leads))
                return self._parse_housing_response(raw_leads)

            _logger.info("Housing.com: API call successful, no new leads found.")
            return []

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else "N/A"
            response_text = e.response.text if e.response else ""
            _logger.error(
                "Housing.com HTTPError: %s | Response: %s",
                status_code,
                response_text,
            )
        except requests.exceptions.RequestException as e:
            _logger.error("Error fetching Housing.com leads: %s", e)
        except ValueError as e:
            _logger.error("Invalid JSON in Housing.com API response: %s", e)

        return []

    def _parse_housing_response(self, raw_leads):
        """
        Parses the list of raw lead objects from Housing.com
        and translates them into our standard dictionary format.
        """
        leads_list = []
        for lead in raw_leads:
            try:
                prop_name = lead.get("apartment_names", "")
                locality = lead.get("locality_name", "")
                if prop_name and locality:
                    project_str = f"{prop_name} in {locality}"
                else:
                    project_str = prop_name or locality or "N/A"

                translated_lead = {
                    "lead_name": lead.get("lead_name"),
                    "lead_phone": lead.get("lead_phone"),
                    "lead_email": lead.get("lead_email"),
                    "property_code": str(lead.get("flat_id")),
                    "project": project_str,
                    "raw_json": lead,
                }

                if not translated_lead["lead_phone"]:
                    _logger.warning(
                        "Housing.com lead skipped due to missing phone: %s",
                        json.dumps(lead),
                    )
                    continue

                leads_list.append(translated_lead)

            except (AttributeError, TypeError, ValueError, KeyError) as e:
                _logger.warning("Error parsing one Housing.com lead: %s", e)

        return leads_list

    @api.model
    def _cron_pull_external_leads(self):
        """
        Called by the 15 minutes cron to pull leads from all
        non-webhook portals and create leads.new records.
        --- UPDATED: 99acres has been removed ---
        """
        portal_mappers = {
            "Housing.com": self._api_fetch_housing,
        }
        for portal_name, fetch_method in portal_mappers.items():
            try:
                source = self._get_or_create_source(portal_name, source_type="portal")
                leads = fetch_method()
                _logger.info(
                    "CRON: Found %s leads from %s API.",
                    len(leads),
                    portal_name,
                )
                for lead in leads:
                    try:
                        lead_vals = {
                            "name": lead.get("lead_name"),
                            "phone": lead.get("lead_phone"),
                            "email": lead.get("lead_email"),
                            "project_name": lead.get("project"),
                            "source_id": source.id,
                            "portal_property_id": lead.get("property_code"),
                            "raw_data": json.dumps(
                                lead.get("raw_json") or lead,
                                indent=2,
                            ),
                            "state": "new",
                        }
                        new_lead = self.with_context(
                            automated_lead_creation=True,
                        ).create_lead_if_not_duplicate(lead_vals)

                        if new_lead:
                            _logger.info(
                                "Lead %s created, processing synchronously...",
                                new_lead.id,
                            )
                            new_lead._process_lead_logic()

                    except Exception:
                        _logger.exception(
                            "CRON: Failed to create/process lead from %s",
                            portal_name,
                        )

            except (
                requests.exceptions.RequestException,
                ValueError,
                TypeError,
                KeyError,
            ) as e:
                _logger.error("Failed to pull leads from %s API: %s", portal_name, e)

    # --- WhatsApp Button Methods ---

    @api.depends("phone")
    def _compute_phone_whatsapp_url(self):
        """
        Generates a WhatsApp URL using whatsapp protocol, prepending 91 if a 10-digit number is found.
        """
        for rec in self:
            if not rec.phone:
                rec.phone_whatsapp_url = False
                continue

            sane_phone = re.sub(r"\D", "", rec.phone)
            number_to_use = False

            if len(sane_phone) == 10:
                number_to_use = f"91{sane_phone}"
            elif len(sane_phone) == 12 and sane_phone.startswith("91"):
                number_to_use = sane_phone
            elif len(sane_phone) == 11 and sane_phone.startswith("0"):
                number_to_use = f"91{sane_phone[1:]}"

            if number_to_use:
                rec.phone_whatsapp_url = f"whatsapp://send?phone={number_to_use}"
            else:
                rec.phone_whatsapp_url = False

    @api.depends("phone", "phone_whatsapp_url")
    def _compute_phone_whatsapp_html(self):
        """
        Creates a simple Whatsapp Link to open the desktop App
        """
        for rec in self:
            phone_display = rec.phone or ""

            if rec.phone_whatsapp_url:
                whatsapp_url = rec.phone_whatsapp_url

                rec.phone_whatsapp_html = (
                    f'<a href="{whatsapp_url}" '
                    f'title="Click to open WhatsApp" '
                    f'style="text-decoration: none; cursor: pointer;">'
                    f'<i class="fa fa-whatsapp" style="color:green; font-size: 16px;"/> {phone_display}</a>'
                )
            else:
                rec.phone_whatsapp_html = phone_display

    def action_whatsapp_with_copy(self):
        """
        This action prepares the data and calls a Client Action
        to handle the copying and link opening.
        """
        self.ensure_one()

        if not self.phone_whatsapp_url:
            return None
        whatsapp_url = self.phone_whatsapp_url
        lead_name = self.name or "there"
        source_name = self.source_id.name or "our source"

        # Get Property Details
        prop = self.property_base_id
        prop_bhk = "property"  # Default fallback
        prop_location = ""
        prop_city = ""
        prop_link = ""
        if prop:
            prop_bhk = prop.bhk or "property"
            prop_location = prop.location or ""
            prop_city = prop.city or ""
            prop_link = prop.property_link or ""

        # Build the Location String
        if prop_location:
            prop_location = re.sub(r"^[A-Z]-", "", prop_location).strip()
        location_parts = []
        if prop_location:
            location_parts.append(prop_location)
        if prop_city:
            location_parts.append(prop_city)
        location_city_str = ", ".join(filter(None, location_parts))
        if not location_city_str:
            location_city_str = "your area"

        # Build Your New Message
        message_parts = [
            f"Hello {lead_name},",
            "",
            f"We've received your requirement for a {prop_bhk} property in {location_city_str} through {source_name}.",
            "",
            "With cleardeals, you can purchase this at 0% brokerage.",
        ]

        if prop_link:
            message_parts.append(f"You can view the property here: {prop_link}")

        message_parts.append("")
        message_parts.append('👉 Want to know more? Just type "Hi" to continue')
        message_text = "\n".join(message_parts)

        # Return the Client Action
        return {
            "type": "ir.actions.client",
            "tag": "whatsapp_with_copy",
            "target": "new",
            "context": {
                "whatsapp_url": whatsapp_url,
                "message_text": message_text,
            },
        }

    # --- n8n Webhook Cron ---

    @api.model
    def _cron_send_new_lead_webhooks(self):
        """
        Called by a 1-minute cron.
        Finds all leads that have not been sent to the webhook.
        Sends them as a batch to n8n.
        [UPDATED to include more property details and RM Name]
        """
        config = self.env["ir.config_parameter"].sudo()
        webhook_url = config.get_param("n8n.new_lead_webhook_url")

        if not webhook_url:
            _logger.error("n8n.new_lead_webhook_url not set. Skipping webhook.")
            return

        leads_to_send = self.search(
            [
                ("is_webhook_sent", "=", False),
            ],
            limit=100,
        )

        if not leads_to_send:
            _logger.info("No new leads to send to n8n webhook")
            return
        batch_payload = []
        for lead in leads_to_send:
            prop = lead.property_base_id
            prop_id = False
            prop_tag = False
            prop_bhk = False
            prop_location = False
            prop_city = False
            prop_link = False

            if prop:
                prop_id = prop.id
                prop_tag = prop.property_tag
                prop_bhk = prop.bhk
                prop_location = prop.location
                prop_city = prop.city
                prop_link = prop.property_link

            rm_name = lead.user_id.name if lead.user_id else False

            lead_data = {
                # Lead Info
                "lead_id": lead.id,
                "name": lead.name,
                "phone": lead.phone,
                "source": lead.source_id.name,
                "portal_property_id": lead.portal_property_id,
                "rm_name": rm_name,
                # Property Info
                "property_id": prop_id,
                "property_tag": prop_tag,
                "property_bhk": prop_bhk,
                "property_location": prop_location,
                "property_city": prop_city,
                "property_link": prop_link,
            }
            batch_payload.append(lead_data)

        if not batch_payload:
            _logger.info("No leads to send after processing.")
            return

        _logger.info("Sending %s new leads to n8n webhook...", len(batch_payload))
        try:
            headers = {"Content-Type": "application/json"}
            response = requests.post(
                webhook_url,
                data=json.dumps(batch_payload),
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
            leads_to_send.write({"is_webhook_sent": True})
            _logger.info(
                "Successfully sent %s leads to n8n webhook.",
                len(batch_payload),
            )

        except requests.exceptions.RequestException as e:
            _logger.error("Failed to send leads to n8n webhook: %s", e)
