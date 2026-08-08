import hashlib
import hmac
import json
import logging
import re
import time
from datetime import date, timedelta

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
    is_portal_source = fields.Boolean(
        string="Is Portal Source",
        compute="_compute_is_portal_source",
        store=False,
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

    bde_id = fields.Many2one(
        "leads.bde",
        string="BDE",
        copy=False,
        index=True,
        tracking=True,
        help="Business Development Executive handling this ops sale lead.",
    )

    bde_allowed_ids = fields.Many2many(
        "leads.bde",
        compute="_compute_bde_allowed_ids",
        store=False,
        help="BDEs selectable by the current user (manager: all; RM: only their allowed ones).",
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

    last_reassignment_batch_id = fields.Many2one(
        "lead.reassignment.log",
        string="Last Reassignment Batch",
        readonly=True,
        copy=False,
        index=True,
        help="The most recent bulk reassignment operation that moved this lead.",
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
        compute_sudo=True,
    )

    base_property_bhk = fields.Char(
        related="property_base_id.bhk",
        string="Property BHK",
        readonly=True,
        store=True,
        compute_sudo=True,
    )

    base_property_location = fields.Char(
        related="property_base_id.location",
        string="Property Location",
        readonly=True,
        store=True,
        compute_sudo=True,
    )

    base_property_city = fields.Char(
        related="property_base_id.city",
        string="Property City",
        readonly=True,
        store=True,
        compute_sudo=True,
    )

    base_property_owner_name = fields.Char(
        related="property_base_id.owner_name",
        string="Property Owner",
        readonly=True,
        store=True,
        compute_sudo=True,
    )

    base_property_link = fields.Char(
        related="property_base_id.property_link",
        string="Property Link",
        readonly=True,
        store=True,
        compute_sudo=True,
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

    # --- Constraints ---

    @api.constrains("phone")
    def _check_phone_number(self):
        """Reject a missing or malformed phone on manually entered leads.

        Scope is deliberate.  Every automated path (portal webhooks, the CSV
        import wizard, the SquareYards/OLX pulls, WhatsApp triage, the recommend
        wizard) sets ``automated_lead_creation``; the lead form is the only
        creator that does not.  Enforcing there and only there means an RM can
        no longer save a lead nobody can call, while a portal sending a bad
        number still lands the lead instead of being rejected at the door —
        losing a real inbound enquiry is worse than storing a number an RM will
        have to correct.

        Because Odoo only runs a constraint when one of its trigger fields is
        written, existing rows with bad numbers stay editable: the check bites
        when someone touches ``phone``, not when they edit anything else.
        """
        if self.env.context.get("automated_lead_creation"):
            return
        for rec in self:
            error = self._phone_validation_error(rec.phone)
            if error:
                raise ValidationError(error)

    @api.model
    def _phone_validation_error(self, phone):
        """Return a human error for *phone*, or ``''`` when it is acceptable.

        Split out from the constraint so the same rule can be reused (and
        tested) without needing a record.
        """
        digits = re.sub(r"\D", "", phone or "")
        if not digits:
            return (
                "A phone number is required. Enter the buyer's 10-digit mobile "
                "number so the team can call or WhatsApp them."
            )
        # Accept exactly what _standardize_phone stores: a bare 10-digit number,
        # or one carrying the 91 country code, however the RM spaced or
        # punctuated it.  Deliberately NOT accepting an 11-digit '0'-prefixed
        # number: '08012345678' is a Bangalore landline, and trimming the zero
        # would turn it into '8012345678', which merely looks like a mobile.
        # Rejecting it makes the RM retype the real number instead of silently
        # storing an unreachable one.
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        if len(digits) != 10:
            return (
                "'%s' is not a valid phone number. Enter a 10-digit Indian "
                "mobile number (the +91 country code is optional)." % phone
            )
        if digits[0] not in "6789":
            return (
                "'%s' is not a valid mobile number. Indian mobile numbers start "
                "with 6, 7, 8 or 9 — please check the number." % phone
            )
        return ""

    @api.constrains("is_ops_sale_lead", "bde_id")
    def _check_bde_required_for_ops_sale(self):
        for rec in self:
            if rec.is_ops_sale_lead and not rec.bde_id:
                raise ValidationError(
                    "A BDE must be selected when a lead is marked as an Ops Sale Lead."
                )

    @api.constrains("bde_id", "user_id", "is_ops_sale_lead")
    def _check_bde_allowed_for_rm(self):
        for rec in self:
            if not rec.is_ops_sale_lead or not rec.bde_id or not rec.user_id:
                continue
            # Empty allowed_rm_ids means the BDE is open to all RMs.
            if rec.bde_id.allowed_rm_ids and rec.user_id not in rec.bde_id.allowed_rm_ids:
                raise ValidationError(
                    f"RM '{rec.user_id.name}' is not authorised to refer leads to "
                    f"BDE '{rec.bde_id.name}'. Contact a manager to update the BDE configuration."
                )

    # --- BDE reassignment helpers (shared by bulk wizard & auto-relink) ---

    @api.model
    def _bde_candidates_for_rm(self, rm):
        """Active BDEs ``rm`` may receive OPS-sale leads for.

        A BDE is usable by an RM when it is open to everyone (empty
        allowed_rm_ids) or explicitly lists that RM — mirrors
        _check_bde_allowed_for_rm.
        """
        bdes = self.env["leads.bde"].search([("active", "=", True)])
        return bdes.filtered(lambda b: not b.allowed_rm_ids or rm in b.allowed_rm_ids)

    def _resolve_bde_for_rm(self, rm, candidates=None):
        """Pick the BDE for this OPS-sale lead when it is reassigned to ``rm``.

        Returns a leads.bde recordset:
          * the current BDE if it is still valid for ``rm`` (keep),
          * otherwise a valid BDE — preferring one that explicitly lists ``rm``
            over an open one, chosen deterministically by name (swap),
          * an empty recordset if ``rm`` is authorised for no BDE (the caller
            must then not reassign the RM).

        Call only for OPS-sale leads.
        """
        self.ensure_one()
        if candidates is None:
            candidates = self._bde_candidates_for_rm(rm)
        if self.bde_id and self.bde_id in candidates:
            return self.bde_id
        explicit = candidates.filtered(lambda b: rm in b.allowed_rm_ids)
        pool = explicit or candidates
        return pool.sorted(lambda b: (b.name or "").lower())[:1]

    # --- Compute Methods ---

    @api.depends_context("uid")
    def _compute_bde_allowed_ids(self):
        user = self.env.user
        all_bdes = self.env["leads.bde"].search([("active", "=", True)])
        if not user.has_group("leads.group_lead_score_manager"):
            # Managers see all BDEs; RMs see open BDEs + those they are approved for.
            all_bdes = all_bdes.filtered(
                lambda b: not b.allowed_rm_ids or user in b.allowed_rm_ids
            )
        for rec in self:
            rec.bde_allowed_ids = all_bdes

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

    @api.depends("source_id", "source_id.category_id", "source_id.category_id.source_type")
    def _compute_is_portal_source(self):
        """Use source category type directly so migrated rows with stale stored related fields still behave correctly."""
        for rec in self:
            rec.is_portal_source = (
                rec.source_id.category_id.source_type == "portal"
                if rec.source_id and rec.source_id.category_id
                else False
            )

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
                            f"Duplicate lead detected in last {self.DUPLICATE_WINDOW_DAYS} days "
                            "for the same phone/property criteria.\n"
                            f"Lead: {existing_lead.name}\n"
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
            "website inquiry": "Cleardeals",
            "app inquiry": "Cleardeals",
            "cleardeals website": "Cleardeals",
            "cleardeals": "Cleardeals",
            "squareyards": "SquareYards",
            "square yards": "SquareYards",
            "square_yards": "SquareYards",
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

    # Duplicate-detection window, in days.  A buyer re-enquiring about the same
    # property after this long is treated as a genuinely new inquiry.
    DUPLICATE_WINDOW_DAYS = 180

    @api.model
    def _find_duplicate_lead(self, phone, property_id, exclude_ids=None):
        """
        Return an existing lead with the same phone + property, or an empty
        recordset.

        This is the single source of truth for the "same buyer, same property"
        rule.  Every inflow (webhook processing, manual edit, Recommend wizard)
        must go through here so the criteria cannot drift between paths.

        The same phone on a *different* property is legitimate — a buyer may
        enquire about several properties — so the property is always part of
        the key, and no check is possible without one.
        """
        phone_clean = self._standardize_phone(phone)
        if not phone_clean or not property_id:
            return self.browse()

        domain = [
            ("phone", "=", phone_clean),
            ("property_base_id", "=", property_id),
            (
                "create_date",
                ">=",
                fields.Datetime.now() - timedelta(days=self.DUPLICATE_WINDOW_DAYS),
            ),
        ]
        if exclude_ids:
            domain.append(("id", "not in", list(exclude_ids)))
        return self.sudo().search(domain, limit=1)

    def _reject_if_duplicate(self, property_rec):
        """
        Guard the moment an automated inflow links a property to this lead.

        Portal/website leads are created before their property is resolved, so
        the create-time duplicate check may have had no property to key on.  By
        the time we link one, an inquiry for the same buyer + property can
        already exist — that is exactly how duplicates used to slip through.

        Automated inflows must never raise here (an exception would abort
        ingestion and strand the lead), so a duplicate is *rejected*: the
        property is left unlinked, the lead is marked ``failed`` with a note
        pointing at the original, and the event is logged — mirroring how
        :meth:`create_lead_if_not_duplicate` logs and skips.

        Returns True when the lead was rejected and the caller must stop.
        """
        self.ensure_one()
        duplicate = self._find_duplicate_lead(
            self.phone,
            property_rec.id,
            exclude_ids=self.ids,
        )
        if not duplicate:
            return False

        _logger.info(
            "Duplicate lead detected on property link. Phone: %s, Property: %s. "
            "Rejecting lead %s (original: %s).",
            self.phone,
            property_rec.property_tag or property_rec.id,
            self.id,
            duplicate.id,
        )
        self.write(
            {
                "state": "failed",
                "process_notes": (
                    "Rejected as a duplicate inquiry — the same phone already "
                    f"has an inquiry for this property.\nOriginal lead: "
                    f"{duplicate.name} (ID {duplicate.id})\n"
                    f"Assigned RM: {duplicate.user_id.name or 'Unassigned'}\n"
                ),
            },
        )
        return True

    def _duplicate_error_message(self, duplicate, phone):
        """Human-readable duplicate description, shared by every error path."""
        status_selection = dict(self._fields["current_status"].selection)
        status_label = status_selection.get(
            duplicate.current_status,
            duplicate.current_status or "Unknown",
        )
        return (
            f"Phone number {phone} is already assigned to another inquiry "
            "for the same property.\n"
            f"Lead: {duplicate.name}\n"
            f"Assigned RM: {duplicate.user_id.name or 'Unassigned'}\n"
            f"Current Status: {status_label}"
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

        time_limit = fields.Datetime.now() - timedelta(days=self.DUPLICATE_WINDOW_DAYS)
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
            # Dedup across all sources sharing the same portal_code, so leads
            # that arrive on different sources for the same channel are treated
            # as one (e.g. the Cleardeals website and the Cleardeals app both
            # use portal_code "Cleardeals"). For single-source portals the
            # sibling set is just the source itself, preserving prior behaviour.
            sibling_source_ids = [source_id]
            if source and source.portal_code:
                siblings = (
                    self.env["lead.source"]
                    .sudo()
                    .search([("portal_code", "=", source.portal_code)])
                )
                if siblings:
                    sibling_source_ids = siblings.ids
            domain = [
                ("phone", "=", phone_clean),
                ("source_id", "in", sibling_source_ids),
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
        in last 180 days (so multiple portal IDs on the same property don't
        create duplicates).

        Fallback (when no portal-listing mapping exists yet):
        same phone + same portal source + same portal_property_id in the same
        window.
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

        if "phone" in vals:
            vals = dict(vals)
            vals["phone"] = self._standardize_phone(vals.get("phone"))

        # Re-check for duplicates whenever *either* half of the duplicate key
        # changes.  Linking a property is just as capable of creating a
        # phone+property duplicate as changing the phone — before this, a lead
        # created without a property could silently acquire one that already
        # belonged to another inquiry.
        #
        # Automated inflows are skipped here: they reject-and-log upstream
        # (see _process_lead_logic / _process_website_lead), because raising
        # inside their own property-linking write would abort ingestion.
        checks_duplicates = ("phone" in vals or "property_base_id" in vals) and not (
            self.env.context.get("automated_lead_creation")
        )
        if checks_duplicates:
            for rec in self:
                effective_phone = vals.get("phone", rec.phone)
                # Determine the effective property after this write completes.
                # Same phone is allowed for different properties (a buyer can
                # inquire about multiple properties); only the same phone +
                # same property combination is a duplicate.
                effective_property_id = (
                    vals["property_base_id"]
                    if "property_base_id" in vals
                    else rec.property_base_id.id
                )
                duplicate = self._find_duplicate_lead(
                    effective_phone,
                    effective_property_id,
                    exclude_ids=self.ids,
                )
                if duplicate:
                    raise ValidationError(
                        self._duplicate_error_message(
                            duplicate,
                            self._standardize_phone(effective_phone),
                        ),
                    )

        leads_to_stamp = self.env["leads.new"]
        first_contact_time = False
        if "current_status" in vals and vals["current_status"] != "lead":
            leads_to_stamp = self.filtered(lambda r: not r.first_contact_datetime)
            if leads_to_stamp:
                first_contact_time = fields.Datetime.now()

        res = super().write(vals)

        if leads_to_stamp and first_contact_time:
            # Bypass the override so this silent internal write does not
            # fire a second bus notification, which would trigger a second
            # grouped list reload on every connected client and cause an
            # OWL "Component is destroyed" race condition.
            super(NewPortalLead, leads_to_stamp).write(
                {"first_contact_datetime": first_contact_time}
            )

        # Skip bus notification for internal-only field updates that have
        # no visible effect on the list/form (webhook flag, process notes).
        _SILENT_FIELDS = frozenset({"first_contact_datetime", "is_webhook_sent", "process_notes"})
        if set(vals.keys()) - _SILENT_FIELDS:
            channel = "leads.new"
            notification_type = "bus_notification"
            message = {
                "ids": self.ids,
                "model": "leads.new",
                "event": "write",
            }
            self.env["bus.bus"]._sendone(channel, notification_type, message)

        return res

    def web_save(self, vals, specification, next_id=None):
        """
        Override web_save to handle lead reassignment.

        When user_id is being changed (RM reassigns the lead to another RM),
        the write succeeds because the record rule is evaluated against the
        pre-write value (still the current user). However the immediate
        read-back that web_save performs after the write would fail because
        user_id now points to the new RM, violating the 'RM See Own' rule.

        Using sudo() only for this one-time confirmation read keeps the strict
        read rule intact everywhere else — the reassigning RM loses access the
        moment they navigate away from the record.
        """
        reassigning = "user_id" in vals and vals["user_id"] != self.env.uid
        if reassigning:
            if self:
                self.write(vals)
            else:
                self = self.create(vals)
            # next_id is intentionally ignored here. Applying it and then reading
            # with sudo() would allow the caller to read any leads.new record by
            # supplying an arbitrary client-controlled ID, bypassing "RM See Own".
            # sudo() scope is limited strictly to the one record that was just
            # written (whose user_id no longer matches the current user).
            return self.sudo().with_context(bin_size=True).web_read(specification)
        return super().web_save(vals, specification, next_id=next_id)

    def action_open_bulk_reassign(self):
        """Open the Bulk Reassign wizard for the selected leads.

        Triggered by the manager-only header button on the list view. ``self``
        is the current selection; its ids are forwarded to the wizard via the
        standard active_ids context that its default_get reads.
        """
        return (
            self.env["lead.bulk.reassign.wizard"]
            .with_context(active_model="leads.new", active_ids=self.ids)
            .create({})
            .action_open()
        )

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
                fallback_hint = (
                    "Set a Fallback RM in Leads > Lead Operations > Settings > Sources "
                    "to route unmatched portal leads."
                )

                if not rm_user:
                    _logger.error(
                        "No fallback RM configured for source '%s'. Assigning to Administrator.",
                        source_name,
                    )
                    rm_user = self.env.ref("base.user_admin")
                    notes = (
                        f"{msg}\n"
                        f"Assigned to Administrator because no Fallback RM is configured.\n"
                        f"{fallback_hint}\n"
                    )
                else:
                    notes = f"{msg}\nAssigned to Fallback RM: {rm_user.name}.\n"

            if property_rec and self._reject_if_duplicate(property_rec):
                return

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

    @api.model
    def _resolve_property_by_prop_id(self, prop_id):
        """Resolve a property.base directly from its short-code (prop_id).

        Used by the Cleardeals website intake, where the payload carries our own
        internal property short-code, so no portal-listing lookup is needed.
        """
        code = (prop_id or "").strip()
        if not code:
            return self.env["property.base"]
        return (
            self.env["property.base"]
            .sudo()
            .search([("prop_id", "=", code)], limit=1)
        )

    def _process_website_lead(self):
        """Assign a Cleardeals website lead.

        Property is matched directly on prop_id (stored in portal_property_id).
        Assignment always uses the property's RM; falls back to the source's
        default RM, then Administrator.
        """
        self.ensure_one()
        _logger.info(
            "🔄 Processing website lead %s: %s (state: %s)",
            self.id,
            self.name,
            self.state,
        )

        if self.state != "new":
            _logger.info("⏭️ Skipping website lead %s, state is %s", self.id, self.state)
            return

        try:
            property_rec = self._resolve_property_by_prop_id(self.portal_property_id)

            if property_rec and property_rec.rm_user_id:
                rm_user = property_rec.rm_user_id
                notes = (
                    f"Website lead assigned to RM {rm_user.name} "
                    f"for property {property_rec.property_tag}.\n"
                )
            else:
                if not property_rec:
                    msg = f"Property not found for prop_id: {self.portal_property_id}"
                else:
                    msg = f"Property {property_rec.property_tag} has no RM"
                _logger.warning(
                    "⚠️ Website lead %s: %s. Falling back to default RM.",
                    self.id,
                    msg,
                )
                rm_user = self.source_id.default_rm_user_id
                if not rm_user:
                    rm_user = self.env.ref("base.user_admin")
                    notes = (
                        f"{msg}\n"
                        f"Assigned to Administrator because no Fallback RM is configured.\n"
                    )
                else:
                    notes = f"{msg}\nAssigned to Fallback RM: {rm_user.name}.\n"

            if property_rec and self._reject_if_duplicate(property_rec):
                return

            self.write(
                {
                    "property_base_id": property_rec.id if property_rec else False,
                    "user_id": rm_user.id,
                    "state": "assigned",
                    "process_notes": notes,
                },
            )

            _logger.info(
                "🎉 Website lead %s: Successfully assigned to %s for property %s",
                self.id,
                rm_user.name,
                property_rec.property_tag if property_rec else "N/A",
            )

        except Exception as e:
            _logger.exception("❌ Failed to process website lead %s", self.id)
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
                "email": lead.email or False,
                "source": lead.source_id.name,
                "portal_property_id": lead.portal_property_id,
                "project_name": lead.project_name or False,
                "rm_name": rm_name,
                # Property Info (property.base — the new canonical model)
                "property_base_id": prop_id,
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

    # --- OLX API PULL METHODS ---

    def _api_fetch_olx(self, account):
        """
        Authenticate against the OLX Business API and fetch leads for the given account.

        Returns a list of normalised lead dicts ready for create_lead_if_not_duplicate,
        or an empty list on any error (error already recorded on the account).

        Authentication tokens are held only in local variables for the duration of this
        call and are never persisted to the database.
        """
        OLX_BASE = "https://business.olx.in"
        OLX_AUTH_URL = f"{OLX_BASE}/api/v1/auth/login"
        OLX_LEADS_URL = f"{OLX_BASE}/api/v1/leads"
        OLX_HEADERS = {
            "Content-Type": "application/json",
            "client-language": "en-in",
            "api-version": "134",
            # Remove x-origin-panamera — we found it causes issues
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
        PAGE_SIZE = 100

        # Read optional SOCKS5 proxy from system parameters (dev/testing only).
        # Leave olx.socks_proxy empty in production.
        proxy_url = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("olx.socks_proxy", default="")
            .strip()
        )
        proxies = {"https": proxy_url, "http": proxy_url} if proxy_url else None

        password = self.env["lead.olx.account"]._get_olx_password(account.login)
        if not password:
            raise ValueError(
                f"No password configured for OLX account '{account.login}'. "
                "Set it via Settings → OLX Accounts."
            )

        # --- Step 1: Authenticate ---
        auth_payload = {"login": account.login, "password": password}
        _logger.debug("OLX auth: using proxy=%s", proxies)
        _logger.debug("OLX auth: headers=%s", OLX_HEADERS)
        try:
            auth_resp = requests.post(
                OLX_AUTH_URL,
                json=auth_payload,
                headers=OLX_HEADERS,
                proxies=proxies,
                timeout=30,
            )
            auth_resp.raise_for_status()
            auth_data = auth_resp.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"OLX auth failed for account '{account.login}': {e}") from e
        except ValueError as e:
            raise RuntimeError(
                f"OLX auth response could not be parsed for account '{account.login}': {e}"
            ) from e

        access_token = auth_data.get("access_token")
        user_id = auth_data.get("user_id")

        if not access_token or not user_id:
            raise RuntimeError(
                f"OLX auth succeeded but response missing access_token or user_id "
                f"for account '{account.login}'. Response keys: {list(auth_data.keys())}"
            )

        # --- Step 2: Determine date range ---
        if account.last_fetch_at:
            start_date = account.last_fetch_at.date() - timedelta(days=1)
        else:
            start_date = date.today() - timedelta(days=1)
        end_date = date.today()

        leads_headers = {
            **OLX_HEADERS,
            "Authorization": f"Bearer {access_token}",
        }

        # --- Step 3: Paginate through leads ---
        all_leads = []
        page = 1
        total_pages = 1  # Updated from first response

        while page <= total_pages:
            # Build URL manually — requests.get(params=...) URL-encodes '/' as '%2F'
            # but the OLX API requires literal slashes in the date format DD/MM/YY.
            start_str = start_date.strftime("%d/%m/%y")
            end_str = end_date.strftime("%d/%m/%y")
            leads_url = (
                f"{OLX_LEADS_URL}?startDate={start_str}&endDate={end_str}"
                f"&userId={user_id}&page={page}&pageSize={PAGE_SIZE}"
            )
            try:
                leads_resp = requests.get(
                    leads_url,
                    headers=leads_headers,
                    proxies=proxies,
                    timeout=30,
                )
                # OLX returns 500 when there are no leads for the date range —
                # treat it as an empty result, not an error.
                if leads_resp.status_code == 500:
                    _logger.info(
                        "OLX leads API returned 500 for account '%s' (no leads in range). "
                        "Treating as empty.",
                        account.login,
                    )
                    break
                leads_resp.raise_for_status()
                resp_data = leads_resp.json()
            except requests.exceptions.RequestException as e:
                raise RuntimeError(
                    f"OLX leads API failed on page {page} for account '{account.login}': {e}"
                ) from e
            except ValueError as e:
                raise RuntimeError(
                    f"OLX leads API response could not be parsed (page {page}) "
                    f"for account '{account.login}': {e}"
                ) from e

            data = resp_data.get("data", {})
            raw_leads = data.get("leads", [])
            raw_ads = data.get("ads", [])
            pagination = resp_data.get("pagination", {})
            total_pages = int(pagination.get("totalPages", 1))

            if not raw_leads:
                break

            # Build adId → ad object lookup for project_name and raw_data enrichment
            ad_by_id = {str(ad.get("id")): ad for ad in raw_ads if ad.get("id")}

            for lead in raw_leads:
                parsed = self._parse_olx_lead(lead, ad_by_id)
                if parsed:
                    all_leads.append(parsed)

            page += 1

        _logger.info(
            "OLX account '%s': fetched %d leads (date range: %s → %s).",
            account.login,
            len(all_leads),
            start_date,
            end_date,
        )
        return all_leads

    def _parse_olx_lead(self, lead, ad_by_id):
        """
        Translate a single OLX lead object into the standard lead_vals dict.

        Returns the dict, or None if the lead has no usable phone number.
        """
        raw_phone = lead.get("phoneNumber", "") or ""
        phone_clean = self._standardize_phone(raw_phone)

        if not phone_clean:
            _logger.warning(
                "OLX lead skipped — no phone number. adId: %s",
                lead.get("adId"),
            )
            return None

        ad_id = str(lead.get("adId") or "").strip()
        matched_ad = ad_by_id.get(ad_id, {})
        project_name = (matched_ad.get("title") or "").strip() or None

        raw_data = json.dumps(
            {
                "lead": lead,
                "ad": matched_ad,
            },
            ensure_ascii=False,
            indent=2,
        )

        return {
            "name": (lead.get("name") or "OLX Lead").strip(),
            "phone": phone_clean,
            "email": lead.get("emailId") or False,
            "portal_property_id": ad_id or False,
            "project_name": project_name,
            "raw_data": raw_data,
            "state": "new",
        }

    @api.model
    def _cron_rotate_olx_accounts(self):
        """
        Called every 12 minutes. Processes the next OLX account in rotation.

        Rotation order: active accounts ordered by last_fetch_at ASC NULLS FIRST,
        then sequence ASC. One account per cron run → all 15 accounts covered
        within a 3-hour window.
        """
        _logger.info("CRON: OLX account rotation starting...")

        account = self.env["lead.olx.account"]._get_next_account()
        if not account:
            _logger.warning("CRON: No active OLX accounts configured. Skipping.")
            return

        _logger.info(
            "CRON: Processing OLX account '%s' (login: %s).",
            account.name,
            account.login,
        )

        source = self._get_or_create_source("OLX", source_type="portal")

        try:
            olx_leads = self._api_fetch_olx(account)
        except Exception as e:
            _logger.error(
                "CRON: OLX account '%s' failed during fetch: %s",
                account.login,
                e,
            )
            account._record_failure(str(e))
            return

        created_count = 0
        for lead_dict in olx_leads:
            try:
                lead_vals = {
                    **lead_dict,
                    "source_id": source.id,
                }
                new_lead = self.with_context(
                    automated_lead_creation=True,
                ).create_lead_if_not_duplicate(lead_vals)

                if new_lead:
                    _logger.info(
                        "CRON: OLX lead %s created, processing...",
                        new_lead.id,
                    )
                    new_lead._process_lead_logic()
                    created_count += 1

            except Exception:
                _logger.exception(
                    "CRON: Failed to create/process OLX lead (adId: %s) for account '%s'.",
                    lead_dict.get("portal_property_id"),
                    account.login,
                )

        account._record_success()

        _logger.info(
            "CRON: OLX account '%s' done. %d new leads created from %d fetched.",
            account.login,
            created_count,
            len(olx_leads),
        )
