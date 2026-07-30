"""
Regression tests for the duplicate hole that let two leads share a phone +
property in production.

Background
----------
The duplicate key is phone + property.  Leads can be created *without* a
property (portal/website leads resolve theirs during processing; a manual lead
can simply be saved with the field blank), and the old ``write()`` only
re-checked for duplicates when ``phone`` changed.  So a lead could be created
unchecked and then silently acquire a property that already belonged to another
inquiry — producing exactly the observed duplicate pair.

Expected behaviour now:
  * Manual property linking  -> ValidationError (popup for the user).
  * Automated inflows        -> reject + log, never raise (raising would abort
    ingestion); the lead is marked ``failed`` and the property is left unlinked.
"""

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .test_portal_common import PortalLeadTestCase


@tagged("post_install", "-at_install")
class TestLeadPropertyLinkDuplicate(PortalLeadTestCase):
    """Duplicate detection at the moment a property gets linked."""

    PHONE = "9925695645"

    def _make_lead_with_property(self, **kwargs):
        """An existing inquiry that already owns phone + test_property."""
        values = {
            "name": "Original Inquiry",
            "phone": self.PHONE,
            "source_id": self.source_magicbricks.id,
            "property_base_id": self.test_property.id,
            "state": "assigned",
        }
        values.update(kwargs)
        return (
            self.env["leads.new"]
            .with_context(automated_lead_creation=True)
            .create(values)
        )

    def _as_user_edit(self, lead):
        """
        Model a UI edit.

        A recordset returned by an automated ``create()`` still carries
        ``automated_lead_creation`` in its context, which suppresses the
        duplicate check.  A real user edit arrives on a fresh recordset, so
        re-browse without that flag.
        """
        return lead.with_context(automated_lead_creation=False)

    # ------------------------------------------------------------------
    # Manual path — popup
    # ------------------------------------------------------------------

    def test_01_manual_property_link_on_duplicate_raises(self):
        """Linking a property that already has this phone must raise (popup)."""
        self._make_lead_with_property()

        # A second lead created WITHOUT a property — dedup cannot key on
        # anything at create time, so it is allowed through.
        second = self._make_lead_with_property(
            name="Instagram Inquiry",
            property_base_id=False,
            source_id=self.source_unknown.id,
        )
        self.assertFalse(second.property_base_id)

        # Now a user links the same property in the UI -> must be blocked.
        with self.assertRaises(ValidationError) as ctx:
            self._as_user_edit(second).write(
                {"property_base_id": self.test_property.id},
            )

        message = str(ctx.exception)
        self.assertIn(self.PHONE, message)
        self.assertIn("Original Inquiry", message)

    def test_02_manual_phone_change_onto_duplicate_still_raises(self):
        """The pre-existing phone-change guard must keep working."""
        self._make_lead_with_property()
        other = self._make_lead_with_property(
            name="Other Buyer",
            phone="9000000001",
        )
        with self.assertRaises(ValidationError):
            self._as_user_edit(other).write({"phone": self.PHONE})

    def test_03_same_phone_different_property_is_allowed(self):
        """A buyer may enquire about several properties."""
        self._make_lead_with_property()
        other_property = self.env["property.base"].create(
            {
                "name": f"Second Property {self.suffix}",
                "prop_id": f"SP{self.suffix}",
                "rm_user_id": self.rm_user.id,
                "is_active": True,
            },
        )
        second = self._make_lead_with_property(
            name="Same Buyer Other Property",
            property_base_id=False,
        )
        # Must NOT raise.
        self._as_user_edit(second).write({"property_base_id": other_property.id})
        self.assertEqual(second.property_base_id, other_property)

    def test_04_unrelated_write_is_unaffected(self):
        """Writes that touch neither half of the key must not be checked."""
        lead = self._make_lead_with_property()
        self._as_user_edit(lead).write({"name": "Renamed"})
        self.assertEqual(lead.name, "Renamed")

    # ------------------------------------------------------------------
    # Automated path — reject + log, never raise
    # ------------------------------------------------------------------

    @mute_logger("odoo.addons.leads.models.new_portal_leads")
    def test_05_automated_processing_rejects_duplicate_without_raising(self):
        """
        A portal lead whose property resolves to one that already has this
        phone must be rejected, not raised on, and must not get the property.
        """
        self._make_lead_with_property()

        # Incoming portal lead for the SAME phone and the same listing.
        incoming = self.create_portal_lead(
            name="Portal Duplicate",
            phone=self.PHONE,
            portal_property_id=self.mb_id,
        )

        # Must not raise — ingestion has to survive.
        incoming._process_lead_logic()

        self.assertFalse(
            incoming.property_base_id,
            "Duplicate must not acquire the property.",
        )
        self.assertEqual(incoming.state, "failed")
        self.assertIn("duplicate", (incoming.process_notes or "").lower())

    @mute_logger("odoo.addons.leads.models.new_portal_leads")
    def test_06_automated_processing_links_when_not_duplicate(self):
        """The happy path must still link the property and assign an RM."""
        incoming = self.create_portal_lead(
            name="Portal Fresh",
            phone="9000000002",
            portal_property_id=self.mb_id,
        )
        incoming._process_lead_logic()

        self.assertEqual(incoming.property_base_id, self.test_property)
        self.assertEqual(incoming.state, "assigned")

    # ------------------------------------------------------------------
    # Shared helper
    # ------------------------------------------------------------------

    def test_07_find_duplicate_lead_requires_both_halves(self):
        """No phone or no property => no duplicate check is possible."""
        self._make_lead_with_property()
        Leads = self.env["leads.new"]

        self.assertFalse(
            Leads._find_duplicate_lead("", self.test_property.id),
            "Missing phone must yield no match.",
        )
        self.assertFalse(
            Leads._find_duplicate_lead(self.PHONE, False),
            "Missing property must yield no match.",
        )
        self.assertTrue(
            Leads._find_duplicate_lead(self.PHONE, self.test_property.id),
            "Both halves present must find the existing inquiry.",
        )

    def test_08_find_duplicate_lead_normalises_phone(self):
        """+91 / formatted numbers must match the stored 10-digit form."""
        self._make_lead_with_property()
        self.assertTrue(
            self.env["leads.new"]._find_duplicate_lead(
                f"+91 {self.PHONE}",
                self.test_property.id,
            ),
        )
