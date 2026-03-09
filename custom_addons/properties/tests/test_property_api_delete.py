"""
Tests for DELETE /api/v1/properties/<identifier> (hard-delete endpoint).

Covers:
  - Authentication guard (wrong key → 403, missing key → 401)
  - Delete by Odoo integer id → record permanently removed
  - Delete by uuid → record permanently removed
  - Delete by prop_id → record permanently removed
  - Delete by owner_phone → record permanently removed
  - Response body contains deleted record's identifiers (id, uuid, prop_id, name)
  - 404 when identifier matches no record
  - Record is truly removed from the database (search and browse both return nothing)
  - Deleting one record does not affect other records (no cascade)
  - Response returns 200 on success
  - Response is application/json
  - Deleting already-deleted (repeated request) returns 404 on second call
"""

from unittest.mock import patch

from odoo.tests import tagged

from ..controllers.controllers import PropertyApiController
from .test_property_common import PropertyApiTestCase

_CONTROLLER_REQUEST = "odoo.addons.properties.controllers.controllers.request"


@tagged("post_install", "-at_install")
class TestPropertyApiDelete(PropertyApiTestCase):
    """Tests for ``PropertyApiController.delete_property``."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = PropertyApiController()

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _call_delete(self, identifier, *, api_key=None):
        key = api_key if api_key is not None else "test-api-key-abc123"
        req = self.make_mock_request(api_key=key, method="DELETE")
        with patch(_CONTROLLER_REQUEST, req):
            return self.controller.delete_property(identifier=identifier)

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def test_01_wrong_api_key_returns_403(self):
        """Delete endpoint must reject a wrong API key."""
        prop = self.make_property()
        resp = self._call_delete(str(prop.id), api_key="wrong-key-xyz")
        self.assertErrorResponse(resp, 403)
        # Record must still exist after rejected request
        self.assertTrue(prop.exists())

    def test_02_missing_api_key_returns_401(self):
        """Delete endpoint must return 401 when the X-API-Key header is absent."""
        prop = self.make_property()
        resp = self._call_delete(str(prop.id), api_key="")
        self.assertErrorResponse(resp, 401)
        self.assertTrue(prop.exists())

    # ------------------------------------------------------------------
    # 404 — identifier not found
    # ------------------------------------------------------------------

    def test_03_unknown_identifier_returns_404(self):
        """DELETE with an identifier that matches no record must return 404."""
        resp = self._call_delete("NOSUCHIDENTIFIER9999XYZ")
        self.assertErrorResponse(resp, 404)

    def test_04_nonexistent_integer_id_returns_404(self):
        """DELETE with a large digit string that is not a real id must return 404."""
        resp = self._call_delete("9999999998")
        self.assertErrorResponse(resp, 404)

    # ------------------------------------------------------------------
    # Delete by Odoo integer id
    # ------------------------------------------------------------------

    def test_05_delete_by_integer_id_returns_200(self):
        """DELETE by Odoo id must return 200."""
        prop = self.make_property()
        prop_id_val = prop.id
        resp = self._call_delete(str(prop_id_val))
        self.assertSuccessResponse(resp, expected_status=200)

    def test_06_delete_by_integer_id_removes_record(self):
        """After DELETE by id the record must not exist in the database."""
        prop = self.make_property()
        prop_id_val = prop.id
        self._call_delete(str(prop_id_val))
        remaining = self.env["property.base"].search([("id", "=", prop_id_val)])
        self.assertFalse(remaining)

    def test_07_delete_by_integer_id_browse_returns_empty(self):
        """After DELETE, browse() on the former id must return an empty recordset."""
        prop = self.make_property()
        prop_id_val = prop.id
        self._call_delete(str(prop_id_val))
        self.env["property.base"].invalidate_model()
        record = self.env["property.base"].browse(prop_id_val)
        self.assertFalse(record.exists())

    # ------------------------------------------------------------------
    # Delete by uuid
    # ------------------------------------------------------------------

    def test_08_delete_by_uuid_removes_record(self):
        """DELETE using the property's uuid must permanently remove the record."""
        prop = self.make_property(uuid=f"del-uuid-{self.suffix}")
        prop_id_val = prop.id
        resp = self._call_delete(prop.uuid)
        self.assertSuccessResponse(resp)
        self.assertFalse(self.env["property.base"].search([("id", "=", prop_id_val)]))

    def test_09_delete_by_uuid_response_has_correct_ids(self):
        """Response body for uuid-delete must include correct id and uuid."""
        prop = self.make_property(uuid=f"resp-uuid-{self.suffix}")
        expected_id = prop.id
        expected_uuid = prop.uuid
        resp = self._call_delete(expected_uuid)
        data = self.assertSuccessResponse(resp)
        self.assertIn("deleted", data)
        self.assertEqual(data["deleted"]["id"], expected_id)
        self.assertEqual(data["deleted"]["uuid"], expected_uuid)

    # ------------------------------------------------------------------
    # Delete by prop_id
    # ------------------------------------------------------------------

    def test_10_delete_by_prop_id_removes_record(self):
        """DELETE using the property's prop_id must permanently remove the record."""
        prop = self.make_property()
        prop_id_val = prop.id
        resp = self._call_delete(prop.prop_id)
        self.assertSuccessResponse(resp)
        self.assertFalse(self.env["property.base"].search([("id", "=", prop_id_val)]))

    def test_11_delete_by_prop_id_response_shows_prop_id(self):
        """Response body for prop_id-delete must include prop_id."""
        prop = self.make_property()
        expected_prop_id = prop.prop_id
        resp = self._call_delete(expected_prop_id)
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["deleted"]["prop_id"], expected_prop_id)

    # ------------------------------------------------------------------
    # Delete by owner_phone
    # ------------------------------------------------------------------

    def test_12_delete_by_owner_phone_removes_record(self):
        """DELETE using owner_phone must permanently remove the record."""
        prop = self.make_property(owner_phone="9660000001")
        prop_id_val = prop.id
        resp = self._call_delete("9660000001")
        self.assertSuccessResponse(resp)
        self.assertFalse(self.env["property.base"].search([("id", "=", prop_id_val)]))

    def test_13_delete_by_phone_in_combined_field(self):
        """Phone in a multi-number owner_phone field — DELETE via individual number must work."""
        first = "9770000001"
        second = "9880000002"
        prop = self.make_property(owner_phone=f"{first} {second}")
        prop_id_val = prop.id
        resp = self._call_delete(second)
        self.assertSuccessResponse(resp)
        self.assertFalse(self.env["property.base"].search([("id", "=", prop_id_val)]))

    # ------------------------------------------------------------------
    # Response body structure
    # ------------------------------------------------------------------

    def test_14_response_body_has_message_key(self):
        """Success response must include a 'message' key."""
        prop = self.make_property()
        resp = self._call_delete(str(prop.id))
        data = self.assertSuccessResponse(resp)
        self.assertIn("message", data)

    def test_15_response_body_deleted_has_all_identity_fields(self):
        """The 'deleted' sub-object must contain id, uuid, prop_id, and name."""
        prop = self.make_property()
        resp = self._call_delete(str(prop.id))
        data = self.assertSuccessResponse(resp)
        for field in ("id", "uuid", "prop_id", "name"):
            self.assertIn(
                field, data["deleted"], msg=f"Missing field in deleted: {field}"
            )

    def test_16_response_body_reflects_deleted_record_name(self):
        """The name in the 'deleted' sub-object must match the record's name."""
        prop = self.make_property(name="Delete Name Check Property")
        resp = self._call_delete(str(prop.id))
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["deleted"]["name"], "Delete Name Check Property")

    # ------------------------------------------------------------------
    # No side-effects on other records
    # ------------------------------------------------------------------

    def test_17_delete_does_not_affect_unrelated_record(self):
        """Deleting one property must not remove any other property."""
        prop_a = self.make_property(name="Property A - Keep")
        prop_b = self.make_property(name="Property B - Delete")
        self._call_delete(str(prop_b.id))
        self.assertTrue(
            prop_a.exists(), "prop_a must still exist after deleting prop_b"
        )

    # ------------------------------------------------------------------
    # Double-delete (idempotency)
    # ------------------------------------------------------------------

    def test_18_second_delete_returns_404(self):
        """A second DELETE call on the same (now gone) identifier must return 404."""
        prop = self.make_property()
        prop_id_val = str(prop.id)
        self._call_delete(prop_id_val)
        resp2 = self._call_delete(prop_id_val)
        self.assertErrorResponse(resp2, 404)

    # ------------------------------------------------------------------
    # Response metadata
    # ------------------------------------------------------------------

    def test_19_response_status_code_is_200(self):
        """HTTP status code of a successful delete must be 200."""
        prop = self.make_property()
        resp = self._call_delete(str(prop.id))
        self.assertEqual(resp.status_code, 200)

    def test_20_response_content_type_is_json(self):
        """Response Content-Type must be application/json."""
        prop = self.make_property()
        resp = self._call_delete(str(prop.id))
        self.assertIn("application/json", resp.content_type)
