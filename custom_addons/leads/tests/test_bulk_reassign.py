from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import new_test_user

from .test_portal_common import PortalLeadTestCase

# ---------------------------------------------------------------------------
# Module : leads
# Tests  : Bulk RM reassignment wizard (lead.bulk.reassign.wizard) + the
#          immutable audit log (lead.reassignment.log).
#
# Covers the manager-only bulk reassignment feature: moving many leads to a
# single new RM with a mandatory reason, cascading the new RM onto every site
# visit, recording a batch log, and enforcing the per-operation cap and access
# rules.
# Owner  : Cleardeals Tech
# ---------------------------------------------------------------------------


@tagged("post_install", "-at_install")
class TestBulkReassign(PortalLeadTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # A Lead Manager — the only role allowed to run the wizard.
        cls.manager = new_test_user(
            cls.env,
            login=f"test_mgr_{cls.suffix}",
            name="Test Manager",
            groups="base.group_user,leads.group_lead_score_manager",
        )

        cls.scheduled_status = cls.env["lead.site.visit.status"].search(
            [("code", "=", "scheduled")], limit=1
        )

        # BDE fixtures for OPS-sale handling. The base class already provides
        # cls.test_bde_open (open to all) and cls.test_bde_restricted (only
        # test_rm_b). Add one restricted to test_rm_a and a third RM allowed
        # for no restricted BDE.
        cls.bde_only_a = cls.env["leads.bde"].sudo().create(
            {
                "name": f"BDE Only A {cls.suffix}",
                "allowed_rm_ids": [(6, 0, [cls.test_rm_a.id])],
            }
        )
        cls.rm_c = new_test_user(
            cls.env,
            login=f"test_rm_c_{cls.suffix}",
            name="Test RM Gamma",
            groups="base.group_user,leads.group_lead_score_rm",
        )

    # -- helpers --------------------------------------------------------

    def _make_lead(self, rm_user, name="Bulk Lead", phone=None):
        """Create an assigned primary lead owned by rm_user."""
        return (
            self.env["leads.new"]
            .with_context(automated_lead_creation=True)
            .create(
                {
                    "name": name,
                    "phone": phone or f"98{self.suffix[-8:]}",
                    "source_id": self.source_magicbricks.id,
                    "property_base_id": self.test_property.id,
                    "user_id": rm_user.id,
                    "state": "assigned",
                    "inquiry_type": "primary",
                }
            )
        )

    def _make_ops_lead(self, rm_user, bde, name="Ops Lead", phone=None):
        """Create an OPS-sale lead (requires a BDE the owner RM is allowed for)."""
        return (
            self.env["leads.new"]
            .with_context(automated_lead_creation=True)
            .create(
                {
                    "name": name,
                    "phone": phone or f"97{self.suffix[-8:]}",
                    "source_id": self.source_magicbricks.id,
                    "property_base_id": self.test_property.id,
                    "user_id": rm_user.id,
                    "state": "assigned",
                    "inquiry_type": "primary",
                    "is_ops_sale_lead": True,
                    "bde_id": bde.id,
                }
            )
        )

    def _open_wizard(self, leads, user=None):
        """Open the wizard the way the bound server action does."""
        return (
            self.env["lead.bulk.reassign.wizard"]
            .with_user(user or self.manager)
            .with_context(active_model="leads.new", active_ids=leads.ids)
            .create({})
        )

    def _reassign(self, leads, new_rm, reason="bulk test"):
        wiz = self._open_wizard(leads)
        wiz.new_rm_id = new_rm
        wiz.reason = reason
        wiz.action_confirm_reassign()
        return wiz

    # -- preview / scope resolution ------------------------------------

    def test_01_default_get_resolves_selection(self):
        leads = self._make_lead(self.test_rm_a, "L1", "9810000001") | self._make_lead(
            self.test_rm_a, "L2", "9810000002"
        )
        wiz = self._open_wizard(leads)
        self.assertEqual(wiz.lead_count, 2)
        self.assertEqual(set(wiz.lead_ids.ids), set(leads.ids))
        self.assertFalse(wiz.over_limit)
        self.assertIn("(2)", wiz.source_rm_summary)

    def test_01b_header_button_opens_wizard_for_selection(self):
        """The list header button entry point (action_open_bulk_reassign)
        opens the wizard pre-loaded with the selected leads."""
        leads = self._make_lead(self.test_rm_a, "L1", "9810000003") | self._make_lead(
            self.test_rm_a, "L2", "9810000004"
        )
        action = leads.with_user(self.manager).action_open_bulk_reassign()
        self.assertEqual(action["res_model"], "lead.bulk.reassign.wizard")
        wiz = self.env["lead.bulk.reassign.wizard"].browse(action["res_id"])
        self.assertEqual(set(wiz.lead_ids.ids), set(leads.ids))
        self.assertEqual(wiz.lead_count, 2)

    # -- happy path -----------------------------------------------------

    def test_02_reassign_moves_user_and_creates_log(self):
        leads = self._make_lead(self.test_rm_a, "L1", "9810000011") | self._make_lead(
            self.test_rm_a, "L2", "9810000012"
        )
        wiz = self._open_wizard(leads)
        wiz.new_rm_id = self.test_rm_b
        wiz.reason = "RM Alpha is on long leave"
        wiz.action_confirm_reassign()

        # All leads moved to the new RM.
        for lead in leads:
            self.assertEqual(lead.user_id, self.test_rm_b)
            self.assertTrue(lead.last_reassignment_batch_id)
            self.assertIn("Bulk reassigned to", lead.process_notes)
            self.assertIn("on long leave", lead.process_notes)

        # A single shared batch log was created with correct figures.
        batch = leads[0].last_reassignment_batch_id
        self.assertEqual(leads[1].last_reassignment_batch_id, batch)
        self.assertEqual(batch.lead_count, 2)
        self.assertEqual(batch.new_rm_id, self.test_rm_b)
        self.assertEqual(batch.reason, "RM Alpha is on long leave")
        self.assertEqual(set(batch.lead_ids.ids), set(leads.ids))
        self.assertEqual(wiz.state, "done")
        self.assertEqual(wiz.reassigned_count, 2)

    def test_03_cascade_moves_all_site_visits(self):
        lead = self._make_lead(self.test_rm_a, "L", "9810000021")
        visit = (
            self.env["lead.site.visit"]
            .sudo()
            .create(
                {
                    "inquiry_id": lead.id,
                    "property_base_id": lead.property_base_id.id,
                    "assigned_rm_id": self.test_rm_a.id,
                    "scheduled_datetime": "2026-05-01 10:00:00",
                    "status_id": self.scheduled_status.id,
                }
            )
        )
        wiz = self._open_wizard(lead)
        wiz.new_rm_id = self.test_rm_b
        wiz.reason = "Reassign with visits"
        wiz.action_confirm_reassign()

        self.assertEqual(visit.assigned_rm_id, self.test_rm_b)
        self.assertEqual(wiz.site_visits_moved_count, 1)
        self.assertEqual(lead.last_reassignment_batch_id.site_visits_moved, 1)

    def test_04_no_cascade_when_disabled(self):
        lead = self._make_lead(self.test_rm_a, "L", "9810000031")
        visit = (
            self.env["lead.site.visit"]
            .sudo()
            .create(
                {
                    "inquiry_id": lead.id,
                    "property_base_id": lead.property_base_id.id,
                    "assigned_rm_id": self.test_rm_a.id,
                    "scheduled_datetime": "2026-05-01 10:00:00",
                    "status_id": self.scheduled_status.id,
                }
            )
        )
        wiz = self._open_wizard(lead)
        wiz.new_rm_id = self.test_rm_b
        wiz.reason = "Leads only"
        wiz.cascade_site_visits = False
        wiz.action_confirm_reassign()

        self.assertEqual(lead.user_id, self.test_rm_b)
        self.assertEqual(visit.assigned_rm_id, self.test_rm_a, "Visit must stay put.")
        self.assertEqual(wiz.site_visits_moved_count, 0)

    def test_05_already_owned_leads_are_skipped(self):
        moving = self._make_lead(self.test_rm_a, "L1", "9810000041")
        already = self._make_lead(self.test_rm_b, "L2", "9810000042")
        wiz = self._open_wizard(moving | already)
        wiz.new_rm_id = self.test_rm_b
        wiz.reason = "Mixed selection"
        wiz.action_confirm_reassign()

        self.assertEqual(wiz.reassigned_count, 1)
        self.assertEqual(wiz.skipped_count, 1)
        self.assertTrue(moving.last_reassignment_batch_id)
        self.assertFalse(
            already.last_reassignment_batch_id,
            "A lead already on the target RM must not be stamped.",
        )

    def test_06_all_already_owned_raises(self):
        lead = self._make_lead(self.test_rm_b, "L", "9810000051")
        wiz = self._open_wizard(lead)
        wiz.new_rm_id = self.test_rm_b
        wiz.reason = "Nothing to do"
        with self.assertRaises(UserError):
            wiz.action_confirm_reassign()

    # -- guard rails ----------------------------------------------------

    def test_07_reason_is_mandatory(self):
        lead = self._make_lead(self.test_rm_a, "L", "9810000061")
        wiz = self._open_wizard(lead)
        wiz.new_rm_id = self.test_rm_b
        wiz.reason = "   "
        with self.assertRaises(UserError):
            wiz.action_confirm_reassign()

    def test_08_new_rm_is_mandatory(self):
        lead = self._make_lead(self.test_rm_a, "L", "9810000071")
        wiz = self._open_wizard(lead)
        wiz.reason = "No target chosen"
        with self.assertRaises(UserError):
            wiz.action_confirm_reassign()

    def test_09_cap_enforced(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "leads.bulk_reassign_max", "1"
        )
        leads = self._make_lead(self.test_rm_a, "L1", "9810000081") | self._make_lead(
            self.test_rm_a, "L2", "9810000082"
        )
        wiz = self._open_wizard(leads)
        self.assertTrue(wiz.over_limit)
        wiz.new_rm_id = self.test_rm_b
        wiz.reason = "Too many"
        with self.assertRaises(UserError):
            wiz.action_confirm_reassign()

    # -- audit log immutability ----------------------------------------

    def test_10_log_is_append_only(self):
        lead = self._make_lead(self.test_rm_a, "L", "9810000091")
        wiz = self._open_wizard(lead)
        wiz.new_rm_id = self.test_rm_b
        wiz.reason = "Immutable check"
        wiz.action_confirm_reassign()
        batch = lead.last_reassignment_batch_id

        with self.assertRaises(UserError):
            batch.reason = "tampered"
        with self.assertRaises(UserError):
            batch.unlink()

    # -- access ---------------------------------------------------------

    def test_11_rm_cannot_use_wizard(self):
        lead = self._make_lead(self.test_rm_a, "L", "9810000101")
        with self.assertRaises(AccessError):
            self.env["lead.bulk.reassign.wizard"].with_user(self.test_rm_a).with_context(
                active_model="leads.new", active_ids=lead.ids
            ).create({})

    def test_12_rm_cannot_read_log(self):
        lead = self._make_lead(self.test_rm_a, "L", "9810000111")
        wiz = self._open_wizard(lead)
        wiz.new_rm_id = self.test_rm_b
        wiz.reason = "Log access check"
        wiz.action_confirm_reassign()
        batch = lead.last_reassignment_batch_id

        with self.assertRaises(AccessError):
            batch.with_user(self.test_rm_a).read(["reason"])

    # -- OPS-sale / BDE handling ---------------------------------------

    def test_20_ops_bde_kept_when_valid_for_new_rm(self):
        """An OPS-sale lead whose BDE is open (valid for any RM) keeps its BDE."""
        lead = self._make_ops_lead(self.test_rm_a, self.test_bde_open,
                                    "Ops open", "9720000001")
        wiz = self._reassign(lead, self.test_rm_b)
        self.assertEqual(lead.user_id, self.test_rm_b)
        self.assertTrue(lead.is_ops_sale_lead)
        self.assertEqual(lead.bde_id, self.test_bde_open, "Open BDE must be kept.")
        self.assertEqual(wiz.bde_reassigned_count, 0)
        self.assertEqual(wiz.failed_count, 0)
        self.assertEqual(wiz.reassigned_count, 1)

    def test_21_ops_bde_swapped_to_explicit_for_new_rm(self):
        """Regression for the reported error: moving an OPS-sale lead to an RM
        not authorised for its BDE no longer raises — the BDE is swapped to one
        that explicitly lists the new RM."""
        lead = self._make_ops_lead(self.test_rm_a, self.bde_only_a,
                                    "Ops swap", "9720000002")
        wiz = self._reassign(lead, self.test_rm_b)  # must not raise
        self.assertEqual(lead.user_id, self.test_rm_b)
        self.assertEqual(lead.bde_id, self.test_bde_restricted,
                         "BDE should swap to the one explicitly allowing test_rm_b.")
        self.assertEqual(wiz.bde_reassigned_count, 1)
        self.assertEqual(wiz.failed_count, 0)
        self.assertIn("BDE re-assigned", lead.process_notes)

    def test_22_ops_bde_swapped_to_open_when_no_explicit(self):
        """When the new RM has no explicitly-allowed BDE, fall back to an open one."""
        lead = self._make_ops_lead(self.test_rm_a, self.bde_only_a,
                                    "Ops open fallback", "9720000003")
        wiz = self._reassign(lead, self.rm_c)
        self.assertEqual(lead.user_id, self.rm_c)
        self.assertEqual(lead.bde_id, self.test_bde_open,
                         "Should fall back to the open BDE for rm_c.")
        self.assertEqual(wiz.bde_reassigned_count, 1)
        self.assertEqual(wiz.failed_count, 0)

    def test_23_ops_fails_when_new_rm_allowed_for_no_bde(self):
        """If the new RM is authorised for no BDE, the OPS-sale lead is left in
        place and reported, while other valid leads in the batch still move."""
        self.test_bde_open.sudo().active = False  # no open BDE remains
        normal = self._make_lead(self.test_rm_a, "Normal", "9720000004")
        ops = self._make_ops_lead(self.test_rm_a, self.bde_only_a,
                                  "Ops fail", "9720000005")
        wiz = self._reassign(normal | ops, self.rm_c)  # must not raise

        # Normal lead moved; ops lead untouched and reported.
        self.assertEqual(normal.user_id, self.rm_c)
        self.assertEqual(ops.user_id, self.test_rm_a, "Failing lead must stay put.")
        self.assertEqual(ops.bde_id, self.bde_only_a, "Its BDE is unchanged.")
        self.assertEqual(wiz.reassigned_count, 1)
        self.assertEqual(wiz.failed_count, 1)
        self.assertIn(ops, wiz.failed_lead_ids)
        # Recorded in the immutable log for management.
        self.assertEqual(wiz.batch_id.failed_count, 1)
        self.assertIn(ops, wiz.batch_id.failed_lead_ids)

    def test_24_all_fail_still_creates_log_without_error(self):
        """A batch where every movable lead fails BDE auth must not raise and
        must still record the failures in the log."""
        self.test_bde_open.sudo().active = False
        ops = self._make_ops_lead(self.test_rm_a, self.bde_only_a,
                                  "Ops only fail", "9720000006")
        wiz = self._reassign(ops, self.rm_c)
        self.assertEqual(ops.user_id, self.test_rm_a)
        self.assertEqual(wiz.reassigned_count, 0)
        self.assertEqual(wiz.failed_count, 1)
        self.assertTrue(wiz.batch_id)
        self.assertEqual(wiz.batch_id.failed_count, 1)

    def test_25_ops_count_shown_in_preview(self):
        """The preview reports how many OPS-sale leads are in the selection."""
        leads = self._make_lead(self.test_rm_a, "n", "9720000007") | \
            self._make_ops_lead(self.test_rm_a, self.test_bde_open, "o", "9720000008")
        wiz = self._open_wizard(leads)
        self.assertEqual(wiz.ops_sale_count, 1)
        self.assertEqual(wiz.lead_count, 2)
