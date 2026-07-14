from markupsafe import Markup

from odoo import api, fields, models
from odoo.tools import html_escape


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
            ("SquareYards", "Square Yards"),
        ],
        string="Portal",
        default=lambda self: self.env.context.get("default_portal_name"),
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
        help="Example: GBH75X0K | B-505, Green Heights | 19684263",
    )
    active = fields.Boolean(
        string="Active",
        default=True,
        index=True,
    )

    @api.depends("portal_name", "portal_listing_id", "listing_label")
    def _compute_display_name(self):
        for rec in self:
            base = f"{rec.portal_name or ''} - {rec.portal_listing_id or ''}".strip(
                " -"
            )
            if rec.listing_label:
                rec.display_name = f"{base} ({rec.listing_label})"
            else:
                rec.display_name = base

    def _build_default_listing_label(
        self, property_rec, portal_name, portal_listing_id
    ):
        short_code = (property_rec.prop_id or "").strip()
        portal = (portal_name or "").strip()
        listing_id = (portal_listing_id or "").strip()
        parts = [part for part in [short_code, portal, listing_id] if part]
        return " | ".join(parts)

    def _post_chatter(self, property_rec, title, details=None):
        if not property_rec:
            return
        details = details or []
        heading = Markup("<strong>%s</strong>") % html_escape(title)
        lines = [heading] + [html_escape(line) for line in details]
        body = Markup("<br/>").join(lines)
        property_rec.message_post(body=body, subtype_xmlid="mail.mt_note")

    @api.model_create_multi
    def create(self, vals_list):
        default_portal = self.env.context.get("default_portal_name")

        property_ids = {
            vals.get("property_base_id")
            for vals in vals_list
            if vals.get("property_base_id")
        }
        properties = {
            rec.id: rec for rec in self.env["property.base"].browse(list(property_ids))
        }

        for vals in vals_list:
            if not vals.get("portal_name") and default_portal:
                vals["portal_name"] = default_portal

            if not vals.get("listing_label") and vals.get("property_base_id"):
                prop = properties.get(vals["property_base_id"])
                if prop:
                    vals["listing_label"] = self._build_default_listing_label(
                        prop,
                        vals.get("portal_name"),
                        vals.get("portal_listing_id"),
                    )

        records = super().create(vals_list)
        for rec in records:
            rec._post_chatter(
                rec.property_base_id,
                "Portal listing added",
                [
                    f"Portal: {rec.portal_name or '-'}",
                    f"Portal Listing ID: {rec.portal_listing_id or '-'}",
                    f"Listing Label: {rec.listing_label or '-'}",
                ],
            )
        return records

    def write(self, vals):
        before = {
            rec.id: {
                "property": rec.property_base_id,
                "portal_name": rec.portal_name,
                "portal_listing_id": rec.portal_listing_id,
                "listing_label": rec.listing_label,
                "active": rec.active,
            }
            for rec in self
        }

        result = super().write(vals)

        for rec in self:
            old = before[rec.id]
            details = []

            if old["portal_name"] != rec.portal_name:
                details.append(
                    f"Portal: {old['portal_name'] or '-'} → {rec.portal_name or '-'}"
                )
            if old["portal_listing_id"] != rec.portal_listing_id:
                old_listing_id = old["portal_listing_id"] or "-"
                new_listing_id = rec.portal_listing_id or "-"
                details.append(
                    f"Portal Listing ID: {old_listing_id} → {new_listing_id}"
                )
            if old["listing_label"] != rec.listing_label:
                details.append(
                    f"Listing Label: {old['listing_label'] or '-'} → {rec.listing_label or '-'}"
                )
            if old["active"] != rec.active:
                details.append(f"Active: {old['active']} → {rec.active}")

            old_property = old["property"]
            if old_property != rec.property_base_id:
                if old_property:
                    rec._post_chatter(
                        old_property,
                        "Portal listing moved out",
                        [
                            f"Portal: {old['portal_name'] or '-'}",
                            f"Portal Listing ID: {old['portal_listing_id'] or '-'}",
                            f"Moved to Property: {rec.property_base_id.display_name or '-'}",
                        ],
                    )
                rec._post_chatter(
                    rec.property_base_id,
                    "Portal listing moved in",
                    [
                        f"Portal: {rec.portal_name or '-'}",
                        f"Portal Listing ID: {rec.portal_listing_id or '-'}",
                        f"From Property: {old_property.display_name if old_property else '-'}",
                    ],
                )
            elif details:
                rec._post_chatter(
                    rec.property_base_id, "Portal listing updated", details
                )

        return result

    def unlink(self):
        snapshots = [
            {
                "property": rec.property_base_id,
                "portal_name": rec.portal_name,
                "portal_listing_id": rec.portal_listing_id,
                "listing_label": rec.listing_label,
            }
            for rec in self
        ]
        result = super().unlink()
        for snap in snapshots:
            self._post_chatter(
                snap["property"],
                "Portal listing removed",
                [
                    f"Portal: {snap['portal_name'] or '-'}",
                    f"Portal Listing ID: {snap['portal_listing_id'] or '-'}",
                    f"Listing Label: {snap['listing_label'] or '-'}",
                ],
            )
        return result


class PropertyBase(models.Model):
    _inherit = "property.base"

    portal_listing_ids = fields.One2many(
        "property.portal.listing",
        "property_base_id",
        string="Portal Listings",
        copy=False,
        help="All portal listing IDs linked to this property.",
    )
    portal_listing_99acres_ids = fields.One2many(
        "property.portal.listing",
        "property_base_id",
        string="99acres Listings",
        domain=[("portal_name", "=", "99acres")],
        copy=False,
    )
    portal_listing_housing_ids = fields.One2many(
        "property.portal.listing",
        "property_base_id",
        string="Housing.com Listings",
        domain=[("portal_name", "=", "Housing.com")],
        copy=False,
    )
    portal_listing_magicbricks_ids = fields.One2many(
        "property.portal.listing",
        "property_base_id",
        string="MagicBricks Listings",
        domain=[("portal_name", "=", "MagicBricks")],
        copy=False,
    )
    portal_listing_olx_ids = fields.One2many(
        "property.portal.listing",
        "property_base_id",
        string="OLX Listings",
        domain=[("portal_name", "=", "OLX")],
        copy=False,
    )
    portal_listing_squareyards_ids = fields.One2many(
        "property.portal.listing",
        "property_base_id",
        string="Square Yards Listings",
        domain=[("portal_name", "=", "SquareYards")],
        copy=False,
    )
