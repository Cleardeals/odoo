from odoo.tests import tagged
from odoo.tests.common import new_test_user

from .test_portal_common import PortalLeadTestCase

# ---------------------------------------------------------------------------
# Module : leads
# Tests  : OPS-sale BDE safety on the auto-relink path (property_base_extend).
#
# When a portal listing / portal ID is added to a property, matching unlinked
# leads are relinked and reassigned to the property's RM. An OPS-sale lead in
# that batch must not trip the BDE authorisation constraint: its BDE is swapped
# for one the new RM is allowed for, or — if the new RM is allowed for no BDE —
# the property is still linked but the RM is left unchanged (logged), never
# raising a ValidationError.
# ---------------------------------------------------------------------------


@tagged("post_install", "-at_install")
class TestRelinkBde(PortalLeadTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bde_only_a = cls.env["leads.bde"].sudo().create(
            {
                "name": f"Relink BDE Only A {cls.suffix}",
                "allowed_rm_ids": [(6, 0, [cls.test_rm_a.id])],
            }
        )
        cls.rm_c = new_test_user(
            cls.env,
            login=f"relink_rm_c_{cls.suffix}",
            name="Relink RM C",
            groups="base.group_user,leads.group_lead_score_rm",
        )

    def _unlinked_ops_lead(self, portal_id, phone):
        """An OPS-sale lead with no property link, owned by test_rm_a."""
        return (
            self.env["leads.new"]
            .with_context(automated_lead_creation=True)
            .create(
                {
                    "name": "Relink Ops",
                    "phone": phone,
                    "source_id": self.source_magicbricks.id,
                    "portal_property_id": portal_id,
                    "user_id": self.test_rm_a.id,
                    "state": "assigned",
                    "is_ops_sale_lead": True,
                    "bde_id": self.bde_only_a.id,
                }
            )
        )

    def _property_with_rm(self, rm, tag):
        return self.env["property.base"].create(
            {
                "property_tag": tag,
                "name": tag,
                "prop_id": tag.replace("-", "")[:12],
                "bedroom_count": 2,
                "location": "L",
                "city": "C",
                "rm_user_id": rm.id,
                "is_active": True,
            }
        )

    def _add_listing(self, prop, portal_id):
        """Creating the listing triggers the relink path."""
        return self.env["property.portal.listing"].create(
            {
                "property_base_id": prop.id,
                "portal_name": "MagicBricks",
                "portal_listing_id": portal_id,
                "listing_label": f"MagicBricks | {portal_id}",
                "active": True,
            }
        )

    def test_relink_swaps_bde_for_new_rm(self):
        """New RM not allowed for the lead's BDE, but has an explicit BDE →
        relink reassigns RM and swaps the BDE (no ValidationError)."""
        pid = f"RLNK1{self.suffix[-5:]}"
        lead = self._unlinked_ops_lead(pid, f"9730{self.suffix[-6:]}")
        prop = self._property_with_rm(self.test_rm_b, f"RLNK-B-{self.suffix}")

        self._add_listing(prop, pid)  # must not raise

        self.assertEqual(lead.property_base_id, prop)
        self.assertEqual(lead.user_id, self.test_rm_b)
        self.assertEqual(lead.bde_id, self.test_bde_restricted)
        self.assertIn("BDE re-assigned", lead.process_notes)

    def test_relink_keeps_rm_when_no_valid_bde(self):
        """New RM allowed for no BDE → property linked, RM kept, logged."""
        self.test_bde_open.sudo().active = False  # remove the open fallback
        pid = f"RLNK2{self.suffix[-5:]}"
        lead = self._unlinked_ops_lead(pid, f"9731{self.suffix[-6:]}")
        prop = self._property_with_rm(self.rm_c, f"RLNK-C-{self.suffix}")

        self._add_listing(prop, pid)  # must not raise

        self.assertEqual(lead.property_base_id, prop, "Property still linked.")
        self.assertEqual(lead.user_id, self.test_rm_a, "RM kept (no valid BDE).")
        self.assertEqual(lead.bde_id, self.bde_only_a, "BDE unchanged.")
        self.assertIn("RM NOT reassigned", lead.process_notes)

    def test_relink_non_ops_lead_unaffected(self):
        """A normal (non-OPS) lead still relinks and reassigns as before."""
        pid = f"RLNK3{self.suffix[-5:]}"
        lead = (
            self.env["leads.new"]
            .with_context(automated_lead_creation=True)
            .create(
                {
                    "name": "Relink Normal",
                    "phone": f"9732{self.suffix[-6:]}",
                    "source_id": self.source_magicbricks.id,
                    "portal_property_id": pid,
                    "user_id": self.test_rm_a.id,
                    "state": "assigned",
                }
            )
        )
        prop = self._property_with_rm(self.test_rm_b, f"RLNK-N-{self.suffix}")
        self._add_listing(prop, pid)
        self.assertEqual(lead.property_base_id, prop)
        self.assertEqual(lead.user_id, self.test_rm_b)

    def test_relink_multiple_unlinked_leads_in_one_listing_create(self):
        """Creating one listing relinks EVERY matching unlinked lead and reassigns
        them all to the property's RM.

        This pins the batch behaviour of the canonical property.portal.listing
        trigger — the path the system relies on after the redundant legacy-column
        trigger on property.base is removed.
        """
        pid = f"RLNKM{self.suffix[-5:]}"
        leads = self.env["leads.new"]
        for i in range(3):
            leads |= (
                self.env["leads.new"]
                .with_context(automated_lead_creation=True)
                .create(
                    {
                        "name": f"Relink Multi {i}",
                        "phone": f"973{i}{self.suffix[-6:]}",
                        "source_id": self.source_magicbricks.id,
                        "portal_property_id": pid,
                        "user_id": self.test_rm_a.id,
                        "state": "assigned",
                    }
                )
            )

        prop = self._property_with_rm(self.test_rm_b, f"RLNK-M-{self.suffix}")
        self._add_listing(prop, pid)  # single create, must relink all three

        for lead in leads:
            self.assertEqual(lead.property_base_id, prop)
            self.assertEqual(lead.user_id, self.test_rm_b)
