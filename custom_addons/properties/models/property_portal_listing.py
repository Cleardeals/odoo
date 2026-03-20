from odoo import api, fields, models


class PropertyPortalListing(models.Model):
    _name = "property.portal.listing"
    _description = "Property Portal Listing"
    _order = "portal_name, portal_listing_id, id"

    _portal_listing_uniq = models.Constraint(
        "UNIQUE(portal_name, portal_listing_id)",
        message="This portal + listing ID is already linked to another property.",
    )

    property_base_id = fields.Many2one(
        "property.base",
        string="Property",
        required=True,
        ondelete="cascade",
        index=True,
    )
    portal_name = fields.Selection(
        [
            ("99acres", "99acres"),
            ("Housing.com", "Housing.com"),
            ("MagicBricks", "MagicBricks"),
            ("OLX", "OLX"),
        ],
        string="Portal",
        required=True,
        index=True,
        help="Portal/source name.",
    )
    portal_listing_id = fields.Char(
        string="Portal Listing ID",
        required=True,
        index=True,
        help="Listing identifier received from the portal for this property.",
    )
    listing_label = fields.Char(
        string="Listing Label",
        help="Free-text descriptor for identifying this listing quickly.",
    )
    active = fields.Boolean(
        string="Active",
        default=True,
        index=True,
    )

    @api.depends("portal_name", "portal_listing_id", "listing_label")
    def _compute_display_name(self):
        for rec in self:
            base = f"{rec.portal_name or ''} - {rec.portal_listing_id or ''}".strip(" -")
            if rec.listing_label:
                rec.display_name = f"{base} ({rec.listing_label})"
            else:
                rec.display_name = base


class PropertyBase(models.Model):
    _inherit = "property.base"

    portal_listing_ids = fields.One2many(
        "property.portal.listing",
        "property_base_id",
        string="Portal Listings",
        copy=False,
        help="All portal listing IDs linked to this property.",
    )
