"""Tests for the ``nudge.initial`` trigger event (initial-nudge workflows).

Lead *creation* is the trigger, so the event fires from ``create`` and only from
``create`` — which is what makes it exactly-once, with no bookkeeping column:
``create`` runs exactly once per record.

The subtlety these tests pin down is *when the envelope is built*. A lead is not
settled at creation: a portal lead is created ``state='new'`` with no property,
and ``_process_lead_logic`` resolves and writes ``property_base_id`` later in the
same transaction. So the envelope — and the eligibility check — are resolved at
publish time (post-commit), not when the hook fires. Building them eagerly would
route every portal lead to the no-property variant.

``mock_pubsub`` runs ``cr.postcommit`` when its ``with`` block exits, so "later in
the same transaction" is modelled by writing inside the same block.
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
        """Non-automated create path (manual/wizard leads settle at create)."""
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
        """Automated/portal create path (property resolved by a later write)."""
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
            self._manual_lead(property_base_id=prop.id)

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

    # ── portal path: the envelope must describe the *settled* lead ────────────

    def test_portal_lead_property_resolved_after_create_still_emits_yes(self):
        """The reason the payload is built late.

        The lead is created with no property (as portal leads are), and
        ``_process_lead_logic`` attaches one later in the same transaction. The
        single create-triggered event must still say ``'yes'`` — an envelope
        built at create time would say ``'no'`` and route to the wrong workflow.
        """
        prop = self._make_property()
        with self.mock_pubsub() as published:
            lead = self._portal_lead()
            self.assertFalse(lead.property_base_id)  # not settled yet
            lead.write({"property_base_id": prop.id, "state": "assigned"})

        nudges = self._nudges(published)
        self.assertEqual(len(nudges), 1)
        payload = nudges[0].payload["payload"]
        self.assertEqual(payload["has_property"], "yes")
        self.assertEqual(payload["actor"]["property"]["id"], prop.id)

    def test_portal_lead_with_no_property_found_emits_no(self):
        with self.mock_pubsub() as published:
            lead = self._portal_lead()
            lead.write({"state": "assigned"})  # no property matched

        nudges = self._nudges(published)
        self.assertEqual(len(nudges), 1)
        self.assertEqual(nudges[0].payload["payload"]["has_property"], "no")

    # ── exactly once, without a guard column ─────────────────────────────────

    def test_create_emits_once_and_later_assign_does_not_re_emit(self):
        """``create`` is the only trigger — the assign write is no longer one."""
        with self.mock_pubsub() as published_create:
            lead = self._manual_lead()
        self.assertEqual(len(self._nudges(published_create)), 1)

        with self.mock_pubsub() as published_write:
            lead.write({"state": "assigned"})
        self.assertFalse(self._nudges(published_write))

    def test_repeated_assign_writes_never_emit(self):
        """The old level-check re-fired on every save mentioning state=assigned."""
        with self.mock_pubsub():
            lead = self._manual_lead()

        with self.mock_pubsub() as published:
            lead.write({"state": "assigned"})
            lead.write({"state": "assigned"})
            lead.write({"phone": self._uniq_phone(), "state": "assigned"})
        self.assertFalse(self._nudges(published))

    # ── eligibility is judged at publish time, like the payload ──────────────

    def test_lead_moved_off_lead_status_before_commit_does_not_emit(self):
        """Status is read from the settled lead, not from creation."""
        with self.mock_pubsub() as published:
            lead = self._manual_lead()
            lead.current_status = "requirement_closed"
        self.assertFalse(self._nudges(published))

    def test_lead_without_phone_does_not_emit(self):
        """No phone → no nudge; there is nobody to message.

        Uses the portal path because a *manual* lead can no longer be saved
        without a phone (leads.new._check_phone_number).  Portal and webhook
        creates stay exempt, so a phoneless lead is still reachable there — and
        this is the case that must not emit.
        """
        with self.mock_pubsub() as published:
            self._portal_lead(phone=False)
        self.assertFalse(self._nudges(published))

    # ── behaviour deltas vs the old assign-triggered hook ─────────────────────
    # These pin down leads that never reach state='assigned'. Under the old hook
    # they were silently never nudged; creation is now the trigger, so they are.

    def test_lead_whose_processing_failed_still_emits(self):
        """_process_lead_logic's except branch writes state='failed' and leaves
        current_status='lead' — so a failed lead IS nudged now (it was not before).
        """
        with self.mock_pubsub() as published:
            lead = self._portal_lead()
            lead.write({"state": "failed"})  # mirrors the except branch
        nudges = self._nudges(published)
        self.assertEqual(len(nudges), 1)
        self.assertEqual(nudges[0].payload["payload"]["has_property"], "no")

    def test_lead_left_unassigned_in_new_state_still_emits(self):
        """Property lag: the lead stays state='new' until the 4h reprocess cron.
        Creation is the trigger, so it is nudged immediately, with 'no'.
        """
        with self.mock_pubsub() as published:
            self._portal_lead()  # never processed; stays state='new'
        nudges = self._nudges(published)
        self.assertEqual(len(nudges), 1)
        self.assertEqual(nudges[0].payload["payload"]["has_property"], "no")
