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

    def _open_wizard(self, leads, user=None):
        """Open the wizard the way the bound server action does."""
        return (
            self.env["lead.bulk.reassign.wizard"]
            .with_user(user or self.manager)
            .with_context(active_model="leads.new", active_ids=leads.ids)
            .create({})
        )

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
