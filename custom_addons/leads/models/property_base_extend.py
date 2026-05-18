import logging

from odoo import api, models
from odoo.fields import Domain

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module : leads
# Model  : property.base (extension)  +  property.portal.listing (extension)
# Purpose: (1) Restricts property list view to own records for RMs while
#              allowing cross-record reads on lead forms.
#          (2) Retroactively links and reassigns leads.new records whenever
#              a portal listing is created or its ID / property changes.
# Owner  : Cleardeals Tech
# ---------------------------------------------------------------------------

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
            domain = Domain(domain) & [('rm_user_id', '=', self.env.user.id)]
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


def _relink_leads_for_listing(env, property_rec, portal_name, portal_listing_id):
    """
    Find all unlinked leads.new that match portal_name + portal_listing_id
    and link them to property_rec, reassigning the RM.

    Called from PropertyPortalListingLeadRelink on create/write.
    """
    if not portal_name or not portal_listing_id or not property_rec:
        return

    unlinked_leads = env["leads.new"].search(
        [
            ("portal_name", "=", portal_name),
            ("portal_property_id", "=", str(portal_listing_id).strip()),
            ("property_base_id", "=", False),
        ]
    )

    if not unlinked_leads:
        return

    rm_user = property_rec.rm_user_id or env.ref("base.user_admin")

    _logger.info(
        "property.portal.listing: portal '%s' / ID '%s' linked to property '%s' — "
        "relinking %d unlinked lead(s), reassigning RM to %s.",
        portal_name,
        portal_listing_id,
        property_rec.property_tag or property_rec.id,
        len(unlinked_leads),
        rm_user.name,
    )

    for lead in unlinked_leads:
        lead.write(
            {
                "property_base_id": property_rec.id,
                "user_id": rm_user.id,
                "process_notes": (
                    (lead.process_notes or "")
                    + f"\nAuto-relinked: property '{property_rec.property_tag}' "
                    f"updated with {portal_name} ID '{portal_listing_id}'. "
                    f"RM reassigned to {rm_user.name}.\n"
                ),
            }
        )


class PropertyPortalListingLeadRelink(models.Model):
    """
    Extends property.portal.listing to trigger lead relinking whenever
    a portal listing is created or its portal_listing_id / property_base_id changes.

    This is the primary trigger for the "late ID" scenario: a lead arrives
    before the property has a portal listing, lands with default RM, then later
    the listing is added — at that point all matching unlinked leads get
    retroactively linked and reassigned.
    """

    _inherit = "property.portal.listing"

    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.property_base_id and rec.portal_name and rec.portal_listing_id:
                _relink_leads_for_listing(
                    self.env,
                    rec.property_base_id,
                    rec.portal_name,
                    rec.portal_listing_id,
                )
        return records

    def write(self, vals):
        # Capture state before the write to detect meaningful changes.
        old_state = {
            rec.id: (rec.portal_name, rec.portal_listing_id, rec.property_base_id)
            for rec in self
        }
        result = super().write(vals)
        relevant_keys = {"portal_listing_id", "portal_name", "property_base_id"}
        if not relevant_keys.intersection(vals):
            return result
        for rec in self:
            old_name, old_lid, old_prop = old_state[rec.id]
            changed = (
                rec.portal_name != old_name
                or rec.portal_listing_id != old_lid
                or rec.property_base_id != old_prop
            )
            if changed and rec.property_base_id and rec.portal_name and rec.portal_listing_id:
                _relink_leads_for_listing(
                    self.env,
                    rec.property_base_id,
                    rec.portal_name,
                    rec.portal_listing_id,
                )
        return result
