"""``is_auto_created`` and the "every lead starts at Lead" rule.

``is_auto_created`` decides whether the WhatsApp initial-nudge workflow fires.
The distinction it draws is *who created the lead*, and the subtlety worth
pinning is that ``automated_lead_creation`` alone cannot answer that: the
Recommend Property wizard, the CSV import and ``create_lead_if_not_duplicate``
all pass that flag while being human acts.  ``lead_manual_origin`` is what
separates them.

The gate on the WhatsApp side lives in wa_communication; these tests only cover
the classification and the create-time status, which belong to ``leads``.
"""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "leads")
class TestLeadAutoCreated(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Lead = cls.env["leads.new"]
        cls.portal_source = cls.Lead._get_or_create_source(
            "AutoFlagPortal", source_type="portal")
        cls.manual_source = cls.Lead._get_or_create_source(
            "AutoFlagManual", source_type="manual")

    def _vals(self, **over):
        base = {
            "name": "Auto Flag Buyer",
            "phone": "9876500123",
            "source_id": self.portal_source.id,
        }
        base.update(over)
        return base

    # ── Classification ───────────────────────────────────────────────────────

    def test_portal_ingestion_is_auto_created(self):
        lead = self.Lead.with_context(
            automated_lead_creation=True).create(self._vals())
        self.assertTrue(lead.is_auto_created)

    def test_manual_form_creation_is_not_auto_created(self):
        lead = self.Lead.create(self._vals(
            phone="9876500124", source_id=self.manual_source.id))
        self.assertFalse(lead.is_auto_created)

    def test_manual_origin_beats_the_automated_flag(self):
        """The case that decides the whole design.

        A wizard passing ``automated_lead_creation`` is still a human act, and
        must not be treated as system ingestion.
        """
        lead = self.Lead.with_context(
            automated_lead_creation=True,
            lead_manual_origin=True,
        ).create(self._vals(phone="9876500125"))
        self.assertFalse(lead.is_auto_created)

    def test_flag_is_readonly(self):
        """Nothing should be able to talk itself into the workflow later."""
        self.assertTrue(self.Lead._fields["is_auto_created"].readonly)

    # ── Every lead starts at "Lead" ──────────────────────────────────────────

    def test_create_forces_lead_status(self):
        lead = self.Lead.with_context(automated_lead_creation=True).create(
            self._vals(phone="9876500126", current_status="requirement_closed"))
        self.assertEqual(lead.current_status, "lead")

    def test_create_forces_lead_status_for_manual_leads_too(self):
        lead = self.Lead.create(self._vals(
            phone="9876500127",
            source_id=self.manual_source.id,
            current_status="site_visit_done"))
        self.assertEqual(lead.current_status, "lead")

    def test_status_is_still_writable_after_creation(self):
        """Creation is pinned; the funnel afterwards is not (see the WA gate)."""
        lead = self.Lead.with_context(automated_lead_creation=True).create(
            self._vals(phone="9876500128"))
        lead.write({"current_status": "busy"})
        self.assertEqual(lead.current_status, "busy")

    # ── The backfill discriminator ───────────────────────────────────────────

    def test_portal_property_id_is_what_ingestion_fills(self):
        """The migration classifies history on source_type + portal_property_id.

        Pins the assumption behind that: a lead created through the form has no
        portal listing id even when its source is a portal, which is exactly why
        source_type alone was not good enough.
        """
        by_hand = self.Lead.create(self._vals(
            phone="9876500129", source_id=self.portal_source.id))
        self.assertFalse(by_hand.portal_property_id)
