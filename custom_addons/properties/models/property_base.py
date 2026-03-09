import logging
import re
from datetime import timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# Base URL used to build the canonical property link
PROPERTY_BASE_URL = "https://www.cleardeals.in/property/"


def build_property_link(property_name: str, prop_id: str) -> str:
    """
    Build a canonical Cleardeals property URL from the property name and its
    short-code ID.

    Example:
        property_name = "Aaryan City", prop_id = "GBH75X0K"
        -> "https://www.cleardeals.in/property/aaryan-city-GBH75X0K"

    Steps:
        1. Strip leading/trailing whitespace and lowercase the name.
        2. Remove every character that is not a-z, 0-9, a space, or a hyphen.
        3. Collapse runs of whitespace into a single hyphen.
        4. Collapse consecutive hyphens and strip edge hyphens.
        5. Append the prop_id with a hyphen separator.
    """
    if not property_name or not prop_id:
        return ""
    slug = property_name.strip().lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return f"{PROPERTY_BASE_URL}{slug}-{prop_id}"


class PropertyBase(models.Model):
    """
    Central property model for the Cleardeals system.

    This is the single source of truth for all property data.  Other modules
    (lead_suggestor, leads) reference this model instead of the legacy
    property.inventory which lives inside lead_suggestor.

    Field groups
    ============
    API-sourced (PROP-2.1)
        Written by _cron_sync_from_api() only.  Never edited in the UI.
        Displayed as readonly on the form.

    Computed (PROP-2.2)
        property_link and bhk are derived from stored fields; no manual input.

    Manager-editable / migration-origin (PROP-2.3 + PROP-2.4)
        Initially populated once by _cron_sync_from_inventory() from the legacy
        property.inventory records.  After that, only Managers can edit them in
        the UI.  The API cron never overwrites these.

    System / status (PROP-2.5)
        is_active  : set False by expiry-cleanup cron.
        inventory_migrated : flipped True after migration cron populates the
                             manager-editable fields for a given record.
    """

    _name = "property.base"
    _description = "Cleardeals Property"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "reg_date desc, name"
    _rec_name = "name"

    # -------------------------------------------------------------------------
    # SQL Constraints  (Odoo 19 declarative style)
    # -------------------------------------------------------------------------
    _uuid_uniq = models.Constraint(
        "UNIQUE(uuid)",
        message="A property with this UUID already exists.",
    )
    _prop_id_uniq = models.Constraint(
        "UNIQUE(prop_id)",
        message="A property with this short-code (prop_id) already exists.",
    )

    # =========================================================================
    # PROP-2.1 — API-sourced fields  (readonly in UI, written by cron only)
    # =========================================================================

    uuid = fields.Char(
        string="Property UUID",
        index=True,
        readonly=True,
        copy=False,
        help="UUID assigned by the Cleardeals website API. "
        "Different from Odoo's internal database ID.",
    )
    prop_id = fields.Char(
        string="Property Short Code",
        index=True,
        readonly=True,
        copy=False,
        help="6-character alphanumeric short-code used by the website and "
        "certain API endpoints (e.g. GBH75X0K).",
    )
    form_no = fields.Char(
        string="Form Number",
        index=True,
        readonly=True,
        copy=False,
        help="Unique form number from the Cleardeals website API (form_no field).  "
        "Matches Form_Number in the BigQuery Customer_Data table and is used as "
        "the stable cross-model key for migrating data from property.inventory.",
    )
    name = fields.Char(
        string="Property Name",
        readonly=True,
        tracking=True,
        help="Full marketing name of the property as shown on the website.",
    )
    reg_date = fields.Date(
        string="Registration Date",
        readonly=True,
        index=True,
        help="Date the property was onboarded onto the Cleardeals platform. "
        "Use as a filter to surface newly added properties.",
    )
    prop_type = fields.Char(
        string="Property Type",
        readonly=True,
        help="Broad classification, e.g. Residential or Commercial.",
    )
    for_sell = fields.Boolean(
        string="For Sale",
        readonly=True,
        index=True,
        help="True → property is listed for sale.  False → listed for rent.",
    )
    prop_sub_type = fields.Char(
        string="Property Sub-Type",
        readonly=True,
        help="Detailed classification, e.g. Apartment, Villa, Office.",
    )
    state = fields.Char(
        string="State",
        readonly=True,
        help="State where the property is located (plain text, not relational).",
    )
    city = fields.Char(
        string="City",
        readonly=True,
        help="City where the property is located.",
    )
    location = fields.Char(
        string="Location / Area",
        readonly=True,
        help="Micro-location or locality within the city.",
    )
    rm_user_id = fields.Many2one(
        "res.users",
        string="Assigned RM",
        readonly=True,
        index=True,
        help="Odoo user record of the Relationship Manager assigned on the website.",
    )
    owner_name = fields.Char(
        string="Owner Name",
        readonly=True,
        tracking=True,
    )
    owner_phone = fields.Char(
        string="Owner Phone",
        readonly=True,
    )
    owner_email = fields.Char(
        string="Owner Email",
        readonly=True,
    )
    pricing = fields.Float(
        string="Price",
        readonly=True,
        digits=(16, 2),
        help="Sell price when for_sale=True; rent price when for_sale=False.",
    )
    pricing_unit = fields.Char(
        string="Price Unit",
        readonly=True,
        help="Unit of the pricing value (e.g. 'lakh', 'crore', 'thousand').",
    )
    gmaps_url = fields.Char(
        string="Google Maps URL",
        readonly=True,
    )
    bedroom_count = fields.Integer(
        string="Bedrooms",
        readonly=True,
        help="Number of bedrooms (BHK count) from the API.",
    )

    # =========================================================================
    # PROP-2.2 — Computed fields  (no manual input)
    # =========================================================================

    property_link = fields.Char(
        string="Property Link",
        compute="_compute_property_link",
        store=True,
        readonly=True,
        help="Canonical Cleardeals URL built from property name + prop_id.  "
        "Used as the matching key when cross-referencing BigQuery data.",
    )
    bhk = fields.Char(
        string="BHK",
        compute="_compute_bhk",
        store=True,
        readonly=True,
        help="Human-readable bedroom label, e.g. '2 BHK'.  Derived from bedroom_count.",
    )
    # Display-only computed fields (not stored — rendered fresh on every read)
    prop_type_display = fields.Char(
        string="Type",
        compute="_compute_display_fields",
        help="Capitalised property type label (e.g. 'Residential').",
    )
    listing_type = fields.Char(
        string="Listing",
        compute="_compute_display_fields",
        help="'Sell' when for_sell is True, 'Rent' otherwise.",
    )
    pricing_display = fields.Char(
        string="Price",
        compute="_compute_display_fields",
        help="Pricing value combined with its unit (e.g. '48 Lakh').",
    )
    is_new = fields.Boolean(
        string="New",
        compute="_compute_display_fields",
        help="True when registration date is within the last 3 days.",
    )
    gmaps_embed_html = fields.Html(
        string="Google Maps",
        compute="_compute_gmaps_embed_html",
        sanitize=False,
        help="Embedded Google Maps iframe rendered from the gmaps_url.",
    )

    # Display-formatted dates (DD/MM/YYYY) for the UI
    service_expiry_date_display = fields.Char(
        string="Expiry (DD/MM/YYYY)",
        compute="_compute_date_displays",
    )
    welcome_call_date_display = fields.Char(
        string="Welcome Call (DD/MM/YYYY)",
        compute="_compute_date_displays",
    )

    # =========================================================================
    # PROP-2.3 + PROP-2.4 — Manager-editable / migration-origin fields
    #   • Populated once by _cron_sync_from_inventory()
    #   • Only managers may edit afterwards (enforced in the view via `groups`)
    #   • The API cron NEVER writes to these fields
    # =========================================================================

    property_tag = fields.Char(
        string="Property Tag",
        index=True,
        tracking=True,
        help="Short display tag used in the lead-suggestor pipeline.  "
        "Migrated from property.inventory; editable by managers.",
    )
    ninety_nine_acres_id = fields.Char(
        string="99acres ID",
        index=True,
        help="Property listing ID on 99acres portal.",
    )
    housing_id = fields.Char(
        string="Housing.com ID",
        index=True,
        help="Property listing ID on Housing.com portal.",
    )
    magicbricks_id = fields.Char(
        string="Magicbricks ID",
        index=True,
        help="Property listing ID on Magicbricks portal.",
    )
    olx_id = fields.Char(
        string="OLX ID",
        index=True,
        help="Property listing ID on OLX portal.",
    )
    service_expiry_date = fields.Date(
        string="Service Expiry Date",
        index=True,
        tracking=True,
        help="Date the Cleardeals service contract expires.  "
        "Pre-filled from property.inventory migration; editable by managers.",
    )
    welcome_call_date = fields.Date(
        string="Welcome Call Date",
        tracking=True,
        help="Date of the welcome call with the owner.  "
        "Not sourced from the API; set manually by managers.",
    )

    # =========================================================================
    # PROP-2.5 — System / status fields
    # =========================================================================

    is_active = fields.Boolean(
        string="Active",
        default=True,
        index=True,
        tracking=True,
        help="Set to False automatically by the expiry-cleanup cron when "
        "service_expiry_date passes today.",
    )
    inventory_migrated = fields.Boolean(
        string="Migrated from Inventory",
        default=False,
        readonly=True,
        index=True,
        copy=False,
        help="Internal flag.  Set to True by _cron_sync_from_inventory() once "
        "the manager-editable fields have been populated from the legacy "
        "property.inventory record.  Prevents repeated re-migration.",
    )

    # =========================================================================
    # Compute methods
    # =========================================================================

    @api.depends("name", "prop_id")
    def _compute_property_link(self):
        for rec in self:
            if rec.name and rec.prop_id:
                rec.property_link = build_property_link(rec.name, rec.prop_id)
            else:
                rec.property_link = ""

    @api.depends("bedroom_count")
    def _compute_bhk(self):
        for rec in self:
            if rec.bedroom_count and rec.bedroom_count > 0:
                rec.bhk = f"{rec.bedroom_count} BHK"
            else:
                rec.bhk = ""

    @api.depends("prop_type", "for_sell", "pricing", "pricing_unit", "reg_date")
    def _compute_display_fields(self):
        """Computes all lightweight UI-display fields in one pass."""
        today = fields.Date.today()
        three_days_ago = today - timedelta(days=3)
        for rec in self:
            # Capitalised type label
            rec.prop_type_display = (rec.prop_type or "").capitalize()
            # Sell / Rent text label
            rec.listing_type = "Sell" if rec.for_sell else "Rent"
            # Combined pricing display
            if rec.pricing:
                unit = (rec.pricing_unit or "").capitalize()
                suffix = "/month" if not rec.for_sell else ""
                rec.pricing_display = (
                    f"{rec.pricing:g} {unit}{suffix}".strip()
                    if unit
                    else f"{rec.pricing:g}"
                )
            else:
                rec.pricing_display = ""
            # New flag — registration within last 3 days
            rec.is_new = bool(
                rec.reg_date and rec.reg_date >= three_days_ago,
            )

    @api.depends("gmaps_url")
    def _compute_gmaps_embed_html(self):
        """Builds an iframe HTML block from the stored Google Maps embed URL."""
        for rec in self:
            if rec.gmaps_url:
                rec.gmaps_embed_html = (
                    f'<iframe src="{rec.gmaps_url}" '
                    'width="100%" height="420" style="border:0;" '
                    'allowfullscreen="" loading="lazy" '
                    'referrerpolicy="no-referrer-when-downgrade"></iframe>'
                )
            else:
                rec.gmaps_embed_html = '<p class="text-muted">No Google Maps URL available for this property.</p>'

    @api.depends("service_expiry_date", "welcome_call_date")
    def _compute_date_displays(self):
        """Formats dates strictly as DD/MM/YYYY for display."""
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

    # =========================================================================
    # Write override — auto-update is_active when service_expiry_date changes
    # =========================================================================

    def write(self, vals):
        """
        When service_expiry_date is explicitly updated, automatically keeps
        is_active in sync: active if expiry >= today, inactive if past.
        This mirrors what the nightly cleanup cron does, but fires immediately
        on save so the status is correct without waiting for the next cron run.
        """
        if "service_expiry_date" in vals and "is_active" not in vals:
            expiry_val = vals["service_expiry_date"]
            if expiry_val:
                expiry_date = fields.Date.to_date(expiry_val)
                vals["is_active"] = expiry_date >= fields.Date.today()
        return super().write(vals)

    # =========================================================================
    # Cron — Expiry cleanup
    # =========================================================================

    @api.model
    def _cron_cleanup_expired_properties(self):
        """
        Scheduled action: marks properties inactive when their service contract
        has expired.

        Runs daily at 00:30 UTC.  Only touches is_active; never modifies any
        financial or manager-editable field.
        """
        _logger.info("Starting cleanup of expired properties...")
        try:
            today = fields.Date.today()
            expired = self.search(
                [
                    ("service_expiry_date", "<", today),
                    ("is_active", "=", True),
                ],
            )
            if expired:
                expired.write({"is_active": False})
                _logger.info(
                    "Marked %d properties as inactive (service expired).",
                    len(expired),
                )
            else:
                _logger.info("No expired properties found.")
        except Exception as e:  # noqa: BLE001
            _logger.error("Error during expired properties cleanup: %s", e)

    # =========================================================================
    # Manual sync trigger (Managers only — button in list view)
    # =========================================================================

    def action_manual_sync(self):
        """
        Manually triggers the API sync cron.  Only visible/accessible to users
        in the properties.group_property_manager security group (enforced in
        the view with groups= attribute on the button).

        Returns a sticky display_notification so the user gets feedback without
        leaving the list view.
        """
        try:
            self._cron_sync_from_api()
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Sync Complete"),
                    "message": _("Properties have been synchronised from the API."),
                    "sticky": False,
                    "type": "success",
                },
            }
        except Exception as e:  # noqa: BLE001
            _logger.error("Manual API sync failed: %s", e)
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Sync Failed"),
                    "message": _("API sync encountered an error. Check the logs."),
                    "sticky": True,
                    "type": "danger",
                },
            }
