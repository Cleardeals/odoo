import logging

from odoo import api, models
from odoo.osv.expression import AND

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

    Cross-RM read access
    --------------------
    Leads RMs need to read any property record to display it on a lead form
    (e.g. a recommended property owned by a different RM).  This is handled
    by an ir.rule (rule_property_base_leads_rm_read_all in
    leads/security/security.xml) that ORs [(1,'=',1)] for the
    ``leads.group_lead_score_rm`` group.  Odoo ORs rules across groups, so
    the combined SQL domain becomes TRUE for leads RMs, letting _search()
    return any property record.

    To keep the Properties module list view showing only an RM's own
    properties, the module's actions set the context key
    ``properties_module_view=True``.  The _search override below detects
    that key and injects [('rm_user_id','=',user.id)] back into the domain,
    restoring the "own properties only" list while leaving cross-RM reads
    unrestricted everywhere else.
    """

    _name = "property.base"
    _inherit = "property.base"

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None,
                *, active_test=True, bypass_access=False):
        """Restrict Properties module list view to own properties for RMs.

        When the ``properties_module_view`` context key is set (injected by
        every Properties module action), non-manager RM users only see their
        own properties.  Outside that context (e.g. when Odoo fetches a
        property record to display it on a lead form) the restriction is not
        applied, so leads RMs can read any property record freely.
        """
        if (
            not self.env.su
            and not bypass_access
            and self.env.context.get('properties_module_view')
            and self.env.user.has_group('properties.group_property_rm')
            and not self.env.user.has_group('properties.group_property_manager')
        ):
            domain = AND([list(domain), [('rm_user_id', '=', self.env.user.id)]])
        return super()._search(
            domain, offset=offset, limit=limit, order=order,
            active_test=active_test, bypass_access=bypass_access,
        )

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
