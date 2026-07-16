"""Tests for the ``nudge.initial`` trigger event (initial-nudge workflows).

The event must fire exactly once per lead, at the settled decision point of each
creation path, carrying ``payload.has_property`` (``'yes'``/``'no'``) and an
enriched ``payload.actor.property`` snapshot the templates render from:

* manual leads  → emitted from ``create`` (already ``state='assigned'``),
* portal leads  → emitted from the ``write`` that sets ``state='assigned'``
                  (after ``_process_lead_logic`` resolves the property),
* never twice.
"""

from odoo.tests import tagged

from .common import WaTransactionCase


@tagged("post_install", "-at_install")
class TestInitialNudge(WaTransactionCase):
    # ── helpers ───────────────────────────────────────────────────────────────

    def _make_property(self, **vals):
        base = {
            "name": self._uniq("Umiyatirth Apartment "),
            "uuid": self._uniq("uuid-"),
            "prop_id": self._uniq("PID-"),
            "property_tag": self._uniq("TAG-"),
            "location": "Ghatlodia",
            "prop_sub_type": "Apartment",
            "bedroom_count": 3,
            "primary_image_url": "http://img/main.jpg",
            "property_size": "187 sq. yard",
            "furnishing_type": "Semi-Furnished",
            "tour_360_url": "http://tour/x",
        }
        base.update(vals)
        return self.env["property.base"].sudo().create(base)

    def _manual_lead(self, **vals):
        """Non-automated create path (settles at create, state='assigned')."""
        source = self.env["leads.new"]._get_or_create_source(
            self._uniq("ManualSrc "), source_type="manual"
        )
        base = {
            "name": self._uniq("Lead "),
            "phone": self._uniq_phone(),
            "source_id": source.id,
        }
        base.update(vals)
        return self.env["leads.new"].create(base)

    def _portal_lead(self, **vals):
        """Automated/portal create path (settles later, at the assign write)."""
        source = self.env["leads.new"]._get_or_create_source(
            self._uniq("Portal "), source_type="portal"
        )
        base = {
            "name": self._uniq("Lead "),
            "phone": self._uniq_phone(),
            "source_id": source.id,
        }
        base.update(vals)
        return self.env["leads.new"].with_context(
            automated_lead_creation=True
        ).create(base)

    @staticmethod
    def _nudges(published):
        return [
            p for p in published
            if p.payload.get("event_type") == "nudge.initial"
        ]

    # ── manual path ───────────────────────────────────────────────────────────

    def test_manual_lead_with_property_emits_yes(self):
        prop = self._make_property()
        with self.mock_pubsub() as published:
            lead = self._manual_lead(property_base_id=prop.id)

        nudges = self._nudges(published)
        self.assertEqual(len(nudges), 1)
        self.assertEqual(nudges[0].topic, "cd-prod-nudge-events")
        payload = nudges[0].payload["payload"]
        self.assertEqual(payload["has_property"], "yes")
        prop_snap = payload["actor"]["property"]
        self.assertEqual(prop_snap["id"], prop.id)
        # Enriched snapshot carries everything the templates need.
        self.assertEqual(prop_snap["type_label"], "3 BHK Apartment")
        self.assertEqual(prop_snap["size"], "187 sq. yard")
        self.assertEqual(prop_snap["furnishing"], "Semi-Furnished")
        self.assertEqual(prop_snap["image_url"], "http://img/main.jpg")
        self.assertEqual(prop_snap["tour_360_url"], "http://tour/x")
        self.assertTrue(lead.wa_nudge_emitted)

    def test_manual_lead_without_property_emits_no(self):
        with self.mock_pubsub() as published:
            self._manual_lead()

        nudges = self._nudges(published)
        self.assertEqual(len(nudges), 1)
        self.assertEqual(nudges[0].payload["payload"]["has_property"], "no")

    def test_type_label_without_bhk_is_sub_type_only(self):
        prop = self._make_property(bedroom_count=0, prop_sub_type="Shop")
        with self.mock_pubsub() as published:
            self._manual_lead(property_base_id=prop.id)
        prop_snap = self._nudges(published)[0].payload["payload"]["actor"]["property"]
        self.assertEqual(prop_snap["type_label"], "Shop")

    def test_project_name_strips_bracket_tag(self):
        prop = self._make_property(name="Umiyatirth Apartment [C-102-tag]")
        with self.mock_pubsub() as published:
            self._manual_lead(property_base_id=prop.id)
        prop_snap = self._nudges(published)[0].payload["payload"]["actor"]["property"]
        self.assertEqual(prop_snap["name"], "Umiyatirth Apartment")

    # ── portal path ───────────────────────────────────────────────────────────

    def test_portal_lead_emits_on_assign_not_create(self):
        prop = self._make_property()

        # Create alone (automated) must NOT emit a nudge yet.
        with self.mock_pubsub() as published:
            lead = self._portal_lead()
        self.assertFalse(self._nudges(published))
        self.assertFalse(lead.wa_nudge_emitted)

        # _process_lead_logic settling the property → nudge fires once, 'yes'.
        with self.mock_pubsub() as published:
            lead.write({"property_base_id": prop.id, "state": "assigned"})
        nudges = self._nudges(published)
        self.assertEqual(len(nudges), 1)
        self.assertEqual(nudges[0].payload["payload"]["has_property"], "yes")
        self.assertTrue(lead.wa_nudge_emitted)

    def test_portal_lead_no_property_emits_no_on_assign(self):
        with self.mock_pubsub() as published:
            lead = self._portal_lead()
        with self.mock_pubsub() as published:
            lead.write({"state": "assigned"})  # no property found
        nudges = self._nudges(published)
        self.assertEqual(len(nudges), 1)
        self.assertEqual(nudges[0].payload["payload"]["has_property"], "no")

    # ── idempotency ───────────────────────────────────────────────────────────

    def test_nudge_emitted_only_once(self):
        # Wrap create in its own capture so its deferred publish is flushed here
        # (postcommit is otherwise flushed by whatever mock_pubsub runs next).
        with self.mock_pubsub() as published_create:
            lead = self._manual_lead()  # emits once at create
        self.assertEqual(len(self._nudges(published_create)), 1)
        self.assertTrue(lead.wa_nudge_emitted)
        # A later assign write must not re-emit.
        with self.mock_pubsub() as published:
            lead.write({"state": "assigned"})
        self.assertFalse(self._nudges(published))
