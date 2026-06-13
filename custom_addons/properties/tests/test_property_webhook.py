"""
Tests for the inbound property webhooks
(POST /api/v1/properties/webhook/{create,update}).

Both routes are thin wrappers over ``property.base._upsert_one`` and share one
handler, so the suite exercises the shared behaviour through both entry points.

Covers:
  - Authentication guard (wrong key → 403, missing header → 401)
  - Create event with the full website envelope → 201, _webhook_action="created"
  - Website nested field names are mapped correctly (sell_pricing, details,
    state/city/location_area, owner phone normalisation, exec_name → rm_user_id)
  - Idempotency: create for an existing uuid → 200 "updated"
  - Idempotency: update for a missing uuid → 201 "created"
  - Update that changes nothing → 200 "unchanged"
  - Manager-editable MIGRATION_FIELDS are never clobbered by an update
  - Missing 'id' (uuid) → 422
  - Wrong Content-Type → 415
  - A bare property object (no envelope) is also accepted
  - The 'media' array is ignored (record still upserts cleanly)
"""

from datetime import date, timedelta
from time import time_ns
from unittest.mock import patch

from odoo.tests import tagged

from ..controllers.webhooks import PropertyWebhookController
from .test_property_common import PropertyApiTestCase

_WEBHOOK_REQUEST = "odoo.addons.properties.controllers.webhooks.request"


@tagged("post_install", "-at_install")
class TestPropertyWebhook(PropertyApiTestCase):
    """Tests for ``PropertyWebhookController``."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = PropertyWebhookController()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _payload(self, *, envelope=True, **overrides):
        """
        Build a website-shaped single-property payload with guaranteed-unique
        identifiers.  Field names mirror the live website API / webhook body.
        """
        n = time_ns()
        prop = {
            "id": f"wh-uuid-{n}",
            "property_name": f"Webhook Property {n}",
            "prop_id": f"WH{str(n)[-6:]}",
            "form_no": f"CD{str(n)[-6:]}",
            "reg_date": "2026-06-09T00:00:00.000Z",
            "prop_type": "residential",
            "for_sell": True,
            "prop_sub_type": "Twin Bunglow",
            "exec_name": self.rm_user.name,
            "owner_name": "Mr. Jinal Shah",
            "owner_contact_no": "+91 97377-48067",
            "owner_email": "jinalshah@example.com",
            "gmaps_url": "https://maps.example.com/embed",
            "state": {"name": "Gujarat"},
            "city": {"name": "Ahmedabad"},
            "location_area": {"name": "Naranpura"},
            "details": {"bedroom_count": "5 BHK"},
            "sell_pricing": {"offer_price": 2.75, "offer_price_unit": "crore"},
            "rent_pricing": None,
        }
        prop.update(overrides)
        if envelope:
            return {"success": True, "property": prop}
        return prop

    def _call(self, intent, *, api_key=None, body=None, content_type="application/json"):
        key = api_key if api_key is not None else "test-api-key-abc123"
        req = self.make_mock_request(
            api_key=key,
            method="POST",
            content_type=content_type,
            body=body,
        )
        with patch(_WEBHOOK_REQUEST, req):
            if intent == "create":
                return self.controller.webhook_create()
            return self.controller.webhook_update()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def test_01_wrong_api_key_returns_403(self):
        resp = self._call("create", api_key="bad-key", body=self._payload())
        self.assertErrorResponse(resp, 403)

    def test_02_missing_api_key_returns_401(self):
        resp = self._call("create", api_key="", body=self._payload())
        self.assertErrorResponse(resp, 401)

    # ------------------------------------------------------------------
    # Create event
    # ------------------------------------------------------------------

    def test_03_create_returns_201_and_created_action(self):
        body = self._payload()
        resp = self._call("create", body=body)
        data = self.assertSuccessResponse(resp, 201)
        self.assertEqual(data["_webhook_action"], "created")
        rec = self.env["property.base"].search(
            [("uuid", "=", body["property"]["id"])], limit=1
        )
        self.assertTrue(rec)
        self.assertEqual(rec.name, body["property"]["property_name"])

    def test_04_website_fields_are_mapped(self):
        body = self._payload()
        self._call("create", body=body)
        prop = body["property"]
        rec = self.env["property.base"].search([("uuid", "=", prop["id"])], limit=1)

        self.assertEqual(rec.prop_id, prop["prop_id"])
        self.assertEqual(rec.form_no, prop["form_no"])
        self.assertEqual(rec.prop_type, "residential")
        self.assertTrue(rec.for_sell)
        self.assertEqual(rec.state, "Gujarat")
        self.assertEqual(rec.city, "Ahmedabad")
        self.assertEqual(rec.location, "Naranpura")
        self.assertEqual(rec.bedroom_count, 5)            # parsed from "5 BHK"
        self.assertEqual(rec.pricing, 2.75)               # from sell_pricing
        self.assertEqual(rec.pricing_unit, "crore")
        self.assertEqual(rec.owner_phone, "9737748067")   # normalised 10-digit
        self.assertEqual(rec.rm_user_id, self.rm_user)    # exec_name resolved
        self.assertEqual(str(rec.reg_date), "2026-06-09")

    def test_05_bare_property_object_accepted(self):
        body = self._payload(envelope=False)
        resp = self._call("create", body=body)
        data = self.assertSuccessResponse(resp, 201)
        self.assertEqual(data["_webhook_action"], "created")
        self.assertTrue(
            self.env["property.base"].search([("uuid", "=", body["id"])], limit=1)
        )

    def test_06_media_array_is_ignored(self):
        body = self._payload(media=[{"id": "m1", "file_path": "http://x/y.jpg"}])
        resp = self._call("create", body=body)
        self.assertSuccessResponse(resp, 201)  # no crash; media simply dropped

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    def test_07_create_existing_uuid_updates(self):
        body = self._payload()
        self._call("create", body=body)
        # Same uuid, changed name → should update, not duplicate.
        body["property"]["property_name"] = "Renamed Property"
        resp = self._call("create", body=body)
        data = self.assertSuccessResponse(resp, 200)
        self.assertEqual(data["_webhook_action"], "updated")
        recs = self.env["property.base"].search([("uuid", "=", body["property"]["id"])])
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs.name, "Renamed Property")

    def test_08_update_missing_uuid_creates(self):
        body = self._payload()
        resp = self._call("update", body=body)
        data = self.assertSuccessResponse(resp, 201)
        self.assertEqual(data["_webhook_action"], "created")

    def test_09_update_no_change_is_unchanged(self):
        body = self._payload()
        self._call("create", body=body)
        resp = self._call("update", body=body)
        data = self.assertSuccessResponse(resp, 200)
        self.assertEqual(data["_webhook_action"], "unchanged")

    # ------------------------------------------------------------------
    # Manager-editable fields are protected
    # ------------------------------------------------------------------

    def test_10_update_does_not_clobber_migration_fields(self):
        body = self._payload()
        self._call("create", body=body)
        rec = self.env["property.base"].search(
            [("uuid", "=", body["property"]["id"])], limit=1
        )
        expiry = date.today() + timedelta(days=90)
        rec.write({"property_tag": "VIP", "service_expiry_date": expiry})

        # An update with new API data must leave manager fields untouched.
        body["property"]["property_name"] = "Updated Again"
        self._call("update", body=body)
        rec.invalidate_recordset()
        self.assertEqual(rec.name, "Updated Again")
        self.assertEqual(rec.property_tag, "VIP")
        self.assertEqual(rec.service_expiry_date, expiry)

    # ------------------------------------------------------------------
    # Validation / error paths
    # ------------------------------------------------------------------

    def test_11_missing_uuid_returns_422(self):
        body = self._payload()
        body["property"].pop("id")
        resp = self._call("create", body=body)
        self.assertErrorResponse(resp, 422)

    def test_12_wrong_content_type_returns_415(self):
        resp = self._call("create", body=self._payload(), content_type="text/plain")
        self.assertErrorResponse(resp, 415)
