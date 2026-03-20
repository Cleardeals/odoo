"""
Tests for PATCH /api/v1/properties/<identifier> (update endpoint).

Covers:
  - Authentication guard (wrong key → 403, missing key → 401)
  - Update a single scalar field
  - Update multiple fields in one request
  - service_expiry_date update triggers is_active auto-sync via write() override
  - Explicit is_active in PATCH payload overrides auto-sync
  - 'name' can be updated
  - 'pricing' and 'pricing_unit' can be updated
  - 'rm_user_id' (FK) can be reassigned
  - 'for_sell' boolean can be toggled
  - Identifier resolution: update via id, uuid, prop_id, owner_phone
  - 404 when identifier matches nothing
  - Wrong Content-Type → 415
  - Malformed JSON → 400
  - Empty JSON object (no recognised fields) → 422
  - Unknown fields ignored, surfaced in _ignored_fields
  - Response body contains the updated values (not stale)
  - Only the supplied fields are modified; omitted fields keep their values
"""

from datetime import date, timedelta
from unittest.mock import patch

from odoo.tests import tagged

from ..controllers.controllers import PropertyApiController
from .test_property_common import PropertyApiTestCase

_CONTROLLER_REQUEST = "odoo.addons.properties.controllers.controllers.request"


@tagged("post_install", "-at_install")
class TestPropertyApiUpdate(PropertyApiTestCase):
    """Tests for ``PropertyApiController.update_property``."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = PropertyApiController()

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _call_update(
        self,
        identifier,
        *,
        api_key=None,
        body=None,
        content_type="application/json",
    ):
        key = api_key if api_key is not None else "test-api-key-abc123"
        req = self.make_mock_request(
            api_key=key,
            method="PATCH",
            content_type=content_type,
            body=body,
        )
        with patch(_CONTROLLER_REQUEST, req):
            return self.controller.update_property(identifier=identifier)

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def test_01_wrong_api_key_returns_403(self):
        """Update endpoint must reject bad API key."""
        prop = self.make_property()
        resp = self._call_update(
            str(prop.id),
            api_key="wrong-key",
            body={"city": "Delhi"},
        )
        self.assertErrorResponse(resp, 403)

    def test_02_missing_api_key_returns_401(self):
        """Update endpoint must return 401 when the header is absent."""
        prop = self.make_property()
        resp = self._call_update(str(prop.id), api_key="", body={"city": "Delhi"})
        self.assertErrorResponse(resp, 401)

    # ------------------------------------------------------------------
    # 404 — identifier not found
    # ------------------------------------------------------------------

    def test_03_unknown_identifier_returns_404(self):
        """PATCH to an identifier that matches nothing must return 404."""
        resp = self._call_update("NOSUCHIDENTIFIER9999", body={"city": "Delhi"})
        self.assertErrorResponse(resp, 404)

    # ------------------------------------------------------------------
    # Content-Type enforcement
    # ------------------------------------------------------------------

    def test_04_wrong_content_type_returns_415(self):
        """Non-JSON Content-Type must return 415."""
        prop = self.make_property()
        resp = self._call_update(
            str(prop.id),
            content_type="text/plain",
            body={"city": "Delhi"},
        )
        self.assertErrorResponse(resp, 415)

    # ------------------------------------------------------------------
    # Malformed / empty body
    # ------------------------------------------------------------------

    def test_05_malformed_json_returns_400(self):
        """Invalid JSON body must return 400."""
        prop = self.make_property()
        req = self.make_mock_request(api_key="test-api-key-abc123", method="PATCH")
        req.httprequest.content_type = "application/json"
        req.httprequest.data = b"not-json!!!"
        with patch(_CONTROLLER_REQUEST, req):
            resp = self.controller.update_property(identifier=str(prop.id))
        self.assertErrorResponse(resp, 400)

    def test_06_empty_json_object_returns_422(self):
        """Empty JSON object (all fields unknown) must return 422."""
        prop = self.make_property()
        resp = self._call_update(str(prop.id), body={})
        self.assertErrorResponse(resp, 422)

    def test_07_payload_with_only_unknown_fields_returns_422(self):
        """Payload containing only unknown keys must return 422."""
        prop = self.make_property()
        resp = self._call_update(str(prop.id), body={"totally_fake": "value"})
        self.assertErrorResponse(resp, 422)

    # ------------------------------------------------------------------
    # Single-field update
    # ------------------------------------------------------------------

    def test_08_update_city(self):
        """PATCH with city must persist the new city value."""
        prop = self.make_property(city="Mumbai")
        resp = self._call_update(str(prop.id), body={"city": "Delhi"})
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["city"], "Delhi")
        prop.invalidate_recordset()
        self.assertEqual(prop.city, "Delhi")

    def test_09_update_name(self):
        """PATCH with name must persist the new name value."""
        prop = self.make_property(name="Original Name")
        new_name = "Updated Name via API"
        resp = self._call_update(str(prop.id), body={"name": new_name})
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["name"], new_name)

    def test_10_update_pricing_and_unit(self):
        """PATCH with pricing + pricing_unit must update both fields."""
        prop = self.make_property(pricing=45.0, pricing_unit="lakh")
        resp = self._call_update(
            str(prop.id),
            body={"pricing": 120.0, "pricing_unit": "cr"},
        )
        data = self.assertSuccessResponse(resp)
        self.assertAlmostEqual(data["pricing"], 120.0)
        self.assertEqual(data["pricing_unit"], "cr")

    def test_11_update_for_sell_toggle(self):
        """PATCH can toggle for_sell from True to False."""
        prop = self.make_property(for_sell=True)
        resp = self._call_update(str(prop.id), body={"for_sell": False})
        data = self.assertSuccessResponse(resp)
        self.assertFalse(data["for_sell"])

    # ------------------------------------------------------------------
    # is_active auto-sync via write() override
    # ------------------------------------------------------------------

    def test_12_future_service_expiry_sets_is_active_true(self):
        """Updating service_expiry_date to a future date must auto-set is_active=True."""
        prop = self.make_property(is_active=False, service_expiry_date=False)
        future = (date.today() + timedelta(days=60)).isoformat()
        self._call_update(str(prop.id), body={"service_expiry_date": future})
        prop.invalidate_recordset()
        self.assertTrue(prop.is_active)

    def test_13_past_service_expiry_sets_is_active_false(self):
        """Updating service_expiry_date to a past date must auto-set is_active=False."""
        prop = self.make_property(is_active=True)
        past = (date.today() - timedelta(days=1)).isoformat()
        self._call_update(str(prop.id), body={"service_expiry_date": past})
        prop.invalidate_recordset()
        self.assertFalse(prop.is_active)

    def test_14_explicit_is_active_true_overrides_past_expiry_autosync(self):
        """Explicit is_active=True in PATCH payload wins even when expiry is in the past."""
        prop = self.make_property(is_active=True)
        past = (date.today() - timedelta(days=5)).isoformat()
        resp = self._call_update(
            str(prop.id),
            body={"service_expiry_date": past, "is_active": True},
        )
        data = self.assertSuccessResponse(resp)
        self.assertTrue(data["is_active"])

    def test_15_explicit_is_active_false_overrides_future_expiry_autosync(self):
        """Explicit is_active=False in PATCH payload wins even when expiry is in the future."""
        prop = self.make_property(is_active=True)
        future = (date.today() + timedelta(days=60)).isoformat()
        resp = self._call_update(
            str(prop.id),
            body={"service_expiry_date": future, "is_active": False},
        )
        data = self.assertSuccessResponse(resp)
        self.assertFalse(data["is_active"])

    # ------------------------------------------------------------------
    # RM reassignment
    # ------------------------------------------------------------------

    def test_16_rm_user_id_reassigned(self):
        """PATCH with rm_user_id must reassign the relationship manager."""
        prop = self.make_property(rm_user_id=self.rm_user.id)
        resp = self._call_update(str(prop.id), body={"rm_user_id": self.rm_user2.id})
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["rm_user"]["id"], self.rm_user2.id)

    # ------------------------------------------------------------------
    # Unknown fields handling
    # ------------------------------------------------------------------

    def test_17_unknown_fields_ignored_and_reported(self):
        """Unknown fields must not raise an error and must appear in '_ignored_fields'."""
        prop = self.make_property()
        resp = self._call_update(
            str(prop.id),
            body={"city": "Kolkata", "ghost_field": "boo"},
        )
        data = self.assertSuccessResponse(resp)
        self.assertIn("_ignored_fields", data)
        self.assertIn("ghost_field", data["_ignored_fields"])

    def test_18_unknown_fields_do_not_affect_valid_field_update(self):
        """Valid fields must be updated even when unknown fields are present."""
        prop = self.make_property()
        resp = self._call_update(
            str(prop.id),
            body={"city": "Kolkata", "ghost_field": "boo"},
        )
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["city"], "Kolkata")

    # ------------------------------------------------------------------
    # Identifier-resolution strategies for update
    # ------------------------------------------------------------------

    def test_19_update_by_uuid_resolves_correctly(self):
        """PATCH using uuid as identifier must update the correct record."""
        prop = self.make_property(uuid=f"update-by-uuid-{self.suffix}")
        resp = self._call_update(prop.uuid, body={"city": "Chennai"})
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["id"], prop.id)
        self.assertEqual(data["city"], "Chennai")

    def test_20_update_by_prop_id_resolves_correctly(self):
        """PATCH using prop_id as identifier must update the correct record."""
        prop = self.make_property()
        resp = self._call_update(prop.prop_id, body={"state": "Tamil Nadu"})
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["id"], prop.id)
        self.assertEqual(data["state"], "Tamil Nadu")

    def test_21_update_by_owner_phone_resolves_correctly(self):
        """PATCH using owner_phone as identifier must update the correct record."""
        prop = self.make_property(owner_phone="9550000001")
        resp = self._call_update("9550000001", body={"location": "Whitefield"})
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["id"], prop.id)
        self.assertEqual(data["location"], "Whitefield")

    # ------------------------------------------------------------------
    # Non-patched fields remain unchanged
    # ------------------------------------------------------------------

    def test_22_omitted_fields_retain_original_values(self):
        """Fields not included in the PATCH payload must keep their original values."""
        prop = self.make_property(city="Jaipur", state="Rajasthan")
        resp = self._call_update(str(prop.id), body={"city": "Ajmer"})
        data = self.assertSuccessResponse(resp)
        # state was NOT in payload, must be unchanged
        self.assertEqual(data["state"], "Rajasthan")
        self.assertEqual(data["city"], "Ajmer")

    # ------------------------------------------------------------------
    # Response sanity checks
    # ------------------------------------------------------------------

    def test_23_response_returns_200(self):
        """Successful update must return HTTP 200."""
        prop = self.make_property()
        resp = self._call_update(str(prop.id), body={"city": "Surat"})
        self.assertEqual(resp.status_code, 200)

    def test_24_response_has_correct_content_type(self):
        """Response must have Content-Type application/json."""
        prop = self.make_property()
        resp = self._call_update(str(prop.id), body={"city": "Surat"})
        self.assertIn("application/json", resp.content_type)

    def test_25_response_body_is_updated_record(self):
        """Response body must reflect the newly updated state, not stale data."""
        prop = self.make_property(city="OldCity")
        resp = self._call_update(str(prop.id), body={"city": "NewCity"})
        data = self.assertSuccessResponse(resp)
        # Response must reflect the change immediately
        self.assertEqual(data["city"], "NewCity")
