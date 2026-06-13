# -*- coding: utf-8 -*-
import json
from unittest.mock import MagicMock, patch

from odoo.tests import tagged

from odoo.addons.leads.controllers.portal_lead_controller import (
    PortalWebhookController,
)

from .test_portal_common import PortalLeadTestCase

_API_KEY_PARAM = "cleardeals.website.api.key"
_TEST_API_KEY = "website-test-key-123"


@tagged("post_install", "-at_install", "leads")
class TestWebsiteLead(PortalLeadTestCase):
    """Cleardeals website lead intake: model helpers + /api/v1/website_lead route.

    Unlike the portal webhooks, the website sends our own property short-code,
    which maps directly to property.base.prop_id (no portal-listing lookup).
    """

    def setUp(self):
        super().setUp()
        # The "Website Inquiry" (website) and "App Inquiry" (mobile app) sources
        # ship in lead_source_data.xml. Both share portal_code "Cleardeals" so
        # deduplication treats them as one channel. Ensure they exist with a
        # known fallback RM regardless of the seed RM presence.
        self.website_source = self.env["leads.new"]._get_or_create_source(
            "Website Inquiry",
            source_type="portal",
        )
        self.app_source = self.env["leads.new"]._get_or_create_source(
            "App Inquiry",
            source_type="portal",
        )
        self.website_source.sudo().write({"default_rm_user_id": self.naresh_user.id})
        self.app_source.sudo().write({"default_rm_user_id": self.naresh_user.id})

        self.prop_code = self.test_property.prop_id  # set by the common fixture
        self.env["ir.config_parameter"].sudo().set_param(_API_KEY_PARAM, _TEST_API_KEY)

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def _sample_payload(self, **overrides):
        payload = {
            "inquiry_type": "primary",
            "inquiry_source": "website",
            "name": "Ramesh Iyer",
            "phone": "+919876543210",
            "email": "ramesh.iyer@example.com",
            "message": "Interested in a 2BHK — site visit this weekend.",
            "property_id": self.prop_code,
            "executive_name": "Bhoomika Prajapati",
            "executive_email": "bhoomika.p@cleardeals.co.in",
            "executive_phone": "+919123456789",
            "client_submission_id": "9b1f0c2e-7d3a-4e21-90ab-2f6c1d8e4f53",
            "submitted_at": "2026-06-08T11:42:30+05:30",
        }
        payload.update(overrides)
        return payload

    def _post(self, payload, api_key=_TEST_API_KEY):
        """Invoke the controller method with a mocked ``request`` object.

        Mirrors the properties-module unit-test approach (no live HTTP server):
        the controller only touches request.env and request.httprequest, so a
        MagicMock bound to the test env is sufficient and fast.
        """
        mock_req = MagicMock()
        mock_req.env = self.env
        headers = {}
        if api_key:
            headers["X-API-KEY"] = api_key
        mock_req.httprequest.headers = headers
        mock_req.httprequest.data = json.dumps(payload).encode()

        with patch(
            "odoo.addons.leads.controllers.portal_lead_controller.request",
            mock_req,
        ):
            return PortalWebhookController().handle_website_lead()

    def _website_lead(self, **vals):
        defaults = {
            "name": "Website Lead",
            "phone": "9876543210",
            "source_id": self.website_source.id,
            "portal_property_id": self.prop_code,
            "state": "new",
        }
        defaults.update(vals)
        return (
            self.env["leads.new"]
            .with_context(automated_lead_creation=True)
            .create(defaults)
        )

    # ------------------------------------------------------------------
    # _resolve_property_by_prop_id
    # ------------------------------------------------------------------

    def test_01_resolve_property_by_prop_id_found(self):
        rec = self.env["leads.new"]._resolve_property_by_prop_id(self.prop_code)
        self.assertEqual(rec, self.test_property)

    def test_02_resolve_property_by_prop_id_not_found(self):
        rec = self.env["leads.new"]._resolve_property_by_prop_id("NO_SUCH_CODE")
        self.assertFalse(rec)

    def test_03_resolve_property_by_prop_id_blank(self):
        self.assertFalse(self.env["leads.new"]._resolve_property_by_prop_id(""))
        self.assertFalse(self.env["leads.new"]._resolve_property_by_prop_id(None))

    # ------------------------------------------------------------------
    # _process_website_lead
    # ------------------------------------------------------------------

    def test_04_process_assigns_property_and_its_rm(self):
        lead = self._website_lead()
        lead._process_website_lead()
        self.assertEqual(lead.property_base_id, self.test_property)
        self.assertEqual(lead.user_id, self.rm_user)  # test_property.rm_user_id
        self.assertEqual(lead.state, "assigned")
        self.assertIn("assigned to RM", lead.process_notes)

    def test_05_process_fallback_rm_when_no_property(self):
        lead = self._website_lead(portal_property_id="NON_EXISTENT_CODE")
        lead._process_website_lead()
        self.assertFalse(lead.property_base_id)
        self.assertEqual(lead.user_id, self.naresh_user)  # source default RM
        self.assertEqual(lead.state, "assigned")
        self.assertIn(self.naresh_user.name, lead.process_notes)

    def test_06_process_fallback_rm_when_property_has_no_rm(self):
        prop_no_rm = self.env["property.base"].create({
            "name": f"No-RM Property {self.suffix}",
            "prop_id": f"NORM{self.suffix}",
            "rm_user_id": False,
            "is_active": True,
        })
        lead = self._website_lead(portal_property_id=prop_no_rm.prop_id)
        lead._process_website_lead()
        # Property is matched but, lacking an RM, assignment falls back.
        self.assertEqual(lead.property_base_id, prop_no_rm)
        self.assertEqual(lead.user_id, self.naresh_user)
        self.assertEqual(lead.state, "assigned")

    def test_07_process_skips_non_new_lead(self):
        lead = self._website_lead(state="assigned", user_id=self.rm_user.id)
        original_user = lead.user_id
        lead._process_website_lead()
        self.assertFalse(lead.property_base_id)
        self.assertEqual(lead.user_id, original_user)
        self.assertEqual(lead.state, "assigned")

    # ------------------------------------------------------------------
    # /api/v1/website_lead route
    # ------------------------------------------------------------------

    def test_08_endpoint_invalid_api_key_returns_401(self):
        resp = self._post(self._sample_payload(), api_key="wrong-key")
        self.assertEqual(resp.status_code, 401)

    def test_09_endpoint_missing_api_key_returns_401(self):
        resp = self._post(self._sample_payload(), api_key=None)
        self.assertEqual(resp.status_code, 401)

    def test_10_endpoint_missing_required_field_returns_400(self):
        payload = self._sample_payload()
        del payload["property_id"]
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 400)

    def test_11_endpoint_creates_lead_and_assigns_property_rm(self):
        # inquiry_source "website" (the sample default) -> Website Inquiry source.
        resp = self._post(self._sample_payload(name=f"Endpoint Lead {self.suffix}"))
        self.assertEqual(resp.status_code, 200)

        lead = self.env["leads.new"].search(
            [("name", "=", f"Endpoint Lead {self.suffix}")], limit=1,
        )
        self.assertTrue(lead, "Endpoint should have created the lead")
        self.assertEqual(lead.source_id, self.website_source)
        self.assertEqual(lead.property_base_id, self.test_property)
        self.assertEqual(lead.user_id, self.rm_user)
        self.assertEqual(lead.state, "assigned")
        self.assertEqual(lead.phone, "9876543210")  # standardized from +91...
        self.assertEqual(lead.inquiry_type, "primary")
        self.assertEqual(
            lead.remarks,
            "Interested in a 2BHK — site visit this weekend.",
        )

    def test_12_endpoint_fallback_rm_when_no_property(self):
        resp = self._post(self._sample_payload(
            name=f"Unmatched Lead {self.suffix}",
            property_id="NON_EXISTENT_CODE",
        ))
        self.assertEqual(resp.status_code, 200)

        lead = self.env["leads.new"].search(
            [("name", "=", f"Unmatched Lead {self.suffix}")], limit=1,
        )
        self.assertTrue(lead)
        self.assertFalse(lead.property_base_id)
        self.assertEqual(lead.user_id, self.naresh_user)

    def test_13_endpoint_stores_full_payload_in_raw_data(self):
        resp = self._post(self._sample_payload(name=f"Raw Data Lead {self.suffix}"))
        self.assertEqual(resp.status_code, 200)

        lead = self.env["leads.new"].search(
            [("name", "=", f"Raw Data Lead {self.suffix}")], limit=1,
        )
        raw = json.loads(lead.raw_data)
        self.assertEqual(raw["executive_email"], "bhoomika.p@cleardeals.co.in")
        self.assertEqual(
            raw["client_submission_id"],
            "9b1f0c2e-7d3a-4e21-90ab-2f6c1d8e4f53",
        )
        self.assertEqual(raw["inquiry_source"], "website")

    def test_14_endpoint_suppresses_duplicate(self):
        phone = "9811122233"
        first = self._post(self._sample_payload(
            name=f"Dup Lead A {self.suffix}", phone=phone,
        ))
        self.assertEqual(first.status_code, 200)
        second = self._post(self._sample_payload(
            name=f"Dup Lead B {self.suffix}", phone=phone,
        ))
        self.assertEqual(second.status_code, 200)

        leads = self.env["leads.new"].search([
            ("phone", "=", phone),
            ("property_base_id", "=", self.test_property.id),
        ])
        self.assertEqual(
            len(leads), 1,
            "Second submission for same phone+property must be suppressed",
        )

    # ------------------------------------------------------------------
    # Source bifurcation: website vs mobile app
    # ------------------------------------------------------------------

    def test_15_endpoint_mobile_app_uses_app_source(self):
        resp = self._post(self._sample_payload(
            name=f"App Lead {self.suffix}",
            inquiry_source="mobile_app",
        ))
        self.assertEqual(resp.status_code, 200)
        lead = self.env["leads.new"].search(
            [("name", "=", f"App Lead {self.suffix}")], limit=1,
        )
        self.assertEqual(lead.source_id, self.app_source)
        # Property match + assignment still works identically for the app source.
        self.assertEqual(lead.property_base_id, self.test_property)
        self.assertEqual(lead.user_id, self.rm_user)

    def test_16_endpoint_missing_inquiry_source_defaults_to_website(self):
        payload = self._sample_payload(name=f"NoSource Lead {self.suffix}")
        del payload["inquiry_source"]
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 200)
        lead = self.env["leads.new"].search(
            [("name", "=", f"NoSource Lead {self.suffix}")], limit=1,
        )
        self.assertEqual(lead.source_id, self.website_source)

    # ------------------------------------------------------------------
    # Cross-source deduplication (website lead == app lead)
    # ------------------------------------------------------------------

    def test_17_cross_source_dedup_matched_property(self):
        # A website lead and an app lead, same phone + same (matched) property,
        # must be treated as one. Dedup here keys on phone + property_base_id,
        # which is independent of source.
        phone = "9700000011"
        web = self._post(self._sample_payload(
            name=f"Web Match {self.suffix}", phone=phone, inquiry_source="website",
        ))
        self.assertEqual(web.status_code, 200)
        app = self._post(self._sample_payload(
            name=f"App Match {self.suffix}", phone=phone, inquiry_source="mobile_app",
        ))
        self.assertEqual(app.status_code, 200)

        leads = self.env["leads.new"].search([
            ("phone", "=", phone),
            ("property_base_id", "=", self.test_property.id),
        ])
        self.assertEqual(
            len(leads), 1,
            "Website + app lead for same phone+property must dedup to one",
        )

    def test_18_cross_source_dedup_unmatched_property(self):
        # Same phone + same (unmatched) prop_id arriving on the website then the
        # app must still dedup. With no property to key on, dedup falls back to
        # phone + portal_property_id across sources sharing portal_code
        # "Cleardeals" (Website Inquiry + App Inquiry).
        phone = "9700000022"
        bad_code = "NO_SUCH_PROP_XYZ"
        web = self._post(self._sample_payload(
            name=f"Web Unmatched {self.suffix}", phone=phone,
            inquiry_source="website", property_id=bad_code,
        ))
        self.assertEqual(web.status_code, 200)
        app = self._post(self._sample_payload(
            name=f"App Unmatched {self.suffix}", phone=phone,
            inquiry_source="mobile_app", property_id=bad_code,
        ))
        self.assertEqual(app.status_code, 200)

        leads = self.env["leads.new"].search([
            ("phone", "=", phone),
            ("portal_property_id", "=", bad_code),
            ("source_id", "in", (self.website_source + self.app_source).ids),
        ])
        self.assertEqual(
            len(leads), 1,
            "Unmatched website + app lead for same phone+prop_id must dedup to one",
        )
