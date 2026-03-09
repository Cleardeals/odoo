import logging

from odoo import models

_logger = logging.getLogger(__name__)

# Portal field → portal_name value used in leads.new
PORTAL_FIELD_MAP = {
    "magicbricks_id": "MagicBricks",
    "ninety_nine_acres_id": "99acres",
    "housing_id": "Housing.com",
    "olx_id": "OLX",
}


class PropertyBaseLeadRelink(models.Model):
    """
    Extends property.base (defined in the 'properties' module) to automatically
    relink and reassign leads.new records when a portal ID field is updated.

    Scenario: A lead arrives with a portal_property_id that doesn't match any
    property yet (property_base_id stays False, lead goes to default RM). Later,
    someone adds/corrects that portal ID on the property. This write override
    detects the change and:
      1. Finds all unlinked leads.new with that portal_name + portal_property_id.
      2. Links property_base_id to this property.
      3. Reassigns user_id to the property's RM (if set).
    """

    _name = "property.base"
    _inherit = "property.base"

    def write(self, vals):
        # Collect which portal fields are being updated and their new values
        changed_portals = {
            field: vals[field] for field in PORTAL_FIELD_MAP if vals.get(field)
        }

        result = super().write(vals)

        if not changed_portals:
            return result

        for property_rec in self:
            for field, new_portal_id in changed_portals.items():
                portal_name = PORTAL_FIELD_MAP[field]

                # Find unlinked leads that match this portal + portal_property_id
                unlinked_leads = self.env["leads.new"].search(
                    [
                        ("portal_name", "=", portal_name),
                        ("portal_property_id", "=", new_portal_id),
                        ("property_base_id", "=", False),
                    ]
                )

                if not unlinked_leads:
                    continue

                _logger.info(
                    "property.base %s: portal field '%s' set to '%s' — "
                    "relinking %d unlinked lead(s) and reassigning RM.",
                    property_rec.property_tag or property_rec.id,
                    field,
                    new_portal_id,
                    len(unlinked_leads),
                )

                rm_user = property_rec.rm_user_id or self.env.ref("base.user_admin")

                for lead in unlinked_leads:
                    lead.write(
                        {
                            "property_base_id": property_rec.id,
                            "user_id": rm_user.id,
                            "process_notes": (
                                (lead.process_notes or "")
                                + f"\nAuto-relinked: property '{property_rec.property_tag}' "
                                f"updated with {portal_name} ID '{new_portal_id}'. "
                                f"RM reassigned to {rm_user.name}.\n"
                            ),
                        }
                    )

        return result
