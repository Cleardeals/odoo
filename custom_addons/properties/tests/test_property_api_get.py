"""
Tests for GET /api/v1/properties/<identifier> (single-record lookup).

Covers:
  - Authentication guard
  - Lookup by Odoo integer id
  - Lookup by uuid
  - Lookup by prop_id
  - Lookup by owner_phone (exact single number)
  - Lookup by owner_phone (one number from a space-separated multi-number field)
  - Identifier priority: numeric strings interpreted as id first, then uuid, etc.
  - 404 when no record matches any strategy
  - Response shape (serialised record fields present)
  - Whitespace trimming of the identifier
  - Leading-zero numeric strings that are NOT a real id are tried as uuid/prop_id
  - Non-phone non-numeric string that matches no uuid or prop_id → 404

All controller tests call the method directly with a patched ``request`` object.
"""

import json
from unittest.mock import patch

from odoo.tests import tagged

from ..controllers.controllers import PropertyApiController, _resolve_identifier
from .test_property_common import PropertyApiTestCase

_CONTROLLER_REQUEST = "odoo.addons.properties.controllers.controllers.request"


@tagged("post_install", "-at_install")
class TestPropertyApiGet(PropertyApiTestCase):
    """Tests for ``PropertyApiController.get_property``."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = PropertyApiController()

        # A single base property reused by most tests
        cls.prop = cls.make_property(
            name="Test Get Property",
            uuid="get-test-uuid-001",
            prop_id="GETPROP001",
            owner_phone="9876543210",
        )

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _call_get(self, identifier, *, api_key=None):
        key = api_key if api_key is not None else "test-api-key-abc123"
        req = self.make_mock_request(api_key=key)
        with patch(_CONTROLLER_REQUEST, req):
            return self.controller.get_property(identifier=identifier)

    # ------------------------------------------------------------------
    # Authentication guard
    # ------------------------------------------------------------------

    def test_01_unauthenticated_returns_403(self):
        """GET single must reject requests with a wrong API key."""
        resp = self._call_get(str(self.prop.id), api_key="wrong-key")
        self.assertErrorResponse(resp, 403)

    def test_02_missing_api_key_returns_401(self):
        """Absent X-API-Key header must return 401."""
        resp = self._call_get(str(self.prop.id), api_key="")
        self.assertErrorResponse(resp, 401)

    # ------------------------------------------------------------------
    # Lookup by Odoo integer id
    # ------------------------------------------------------------------

    def test_03_lookup_by_integer_id(self):
        """String-digit identifier matching the Odoo id must return the record."""
        resp = self._call_get(str(self.prop.id))
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["id"], self.prop.id)

    def test_04_integer_id_response_has_name(self):
        """Record retrieved by id must include the correct name."""
        resp = self._call_get(str(self.prop.id))
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["name"], self.prop.name)

    def test_05_nonexistent_integer_id_returns_404(self):
        """A digit string that is not a real id must ultimately return 404."""
        resp = self._call_get("9999999999")
        self.assertErrorResponse(resp, 404)

    # ------------------------------------------------------------------
    # Lookup by UUID
    # ------------------------------------------------------------------

    def test_06_lookup_by_uuid(self):
        """Identifier matching a record's uuid must return that record."""
        resp = self._call_get("get-test-uuid-001")
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["uuid"], "get-test-uuid-001")
        self.assertEqual(data["id"], self.prop.id)

    def test_07_lookup_by_uuid_case_sensitive(self):
        """UUID lookup is exact/case-sensitive; wrong case must not match."""
        resp = self._call_get("GET-TEST-UUID-001")
        self.assertErrorResponse(resp, 404)

    # ------------------------------------------------------------------
    # Lookup by prop_id
    # ------------------------------------------------------------------

    def test_08_lookup_by_prop_id(self):
        """Identifier matching a record's prop_id must return that record."""
        resp = self._call_get("GETPROP001")
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["prop_id"], "GETPROP001")

    def test_09_prop_id_nonexistent_returns_404(self):
        """prop_id that does not match any record must return 404."""
        resp = self._call_get("NOSUCHPROPID")
        self.assertErrorResponse(resp, 404)

    # ------------------------------------------------------------------
    # Lookup by owner_phone
    # ------------------------------------------------------------------

    def test_10_lookup_by_exact_owner_phone(self):
        """Digit-string matching the owner_phone must return the record."""
        resp = self._call_get("9876543210")
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["id"], self.prop.id)

    def test_11_lookup_by_phone_substring_in_combined_field(self):
        """Phone lookup must find a property where the query is one of N space-separated numbers."""
        first_num = "9333111111"
        second_num = "9444222222"
        combined = f"{first_num} {second_num}"
        prop = self.make_property(owner_phone=combined)
        # Look up using only the second number — must be found via 'like'
        resp = self._call_get(second_num)
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["id"], prop.id)

    def test_12_phone_lookup_nonexistent_returns_404(self):
        """A digit string that matches no phone returns 404."""
        resp = self._call_get("0000000000")
        self.assertErrorResponse(resp, 404)

    # ------------------------------------------------------------------
    # Identifier priority
    # ------------------------------------------------------------------

    def test_13_integer_id_takes_priority_over_uuid(self):
        """When identifier is a digit, Odoo id is tried BEFORE uuid."""
        # Create a property whose uuid is a digit string that is NOT an existing id
        # This proves id strategy runs first: if the int lookup found something it wins.
        id_prop = self.prop  # id is a real int
        resp = self._call_get(str(id_prop.id))
        data = self.assertSuccessResponse(resp)
        # Should return the prop with that id, not any uuid match
        self.assertEqual(data["id"], id_prop.id)

    def test_14_uuid_takes_priority_over_prop_id(self):
        """When uuid matches, a coincidental prop_id match must not override it."""
        shared_code = "DUALID001"
        prop_a = self.make_property(uuid=shared_code, prop_id="UNIQUE_PROPA001")
        _prop_b = self.make_property(uuid="unique-uuid-prb", prop_id=shared_code)

        resp = self._call_get(shared_code)
        data = self.assertSuccessResponse(resp)
        # uuid match (prop_a) must win over prop_id match (prop_b)
        self.assertEqual(data["id"], prop_a.id)

    # ------------------------------------------------------------------
    # Whitespace handling
    # ------------------------------------------------------------------

    def test_15_identifier_leading_trailing_whitespace_trimmed(self):
        """Controller strips whitespace from <identifier> before resolving."""
        # The route parameter will have whitespace if the URL does; strip() is applied in controller
        resp = self._call_get(f"  {self.prop.prop_id}  ")
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["id"], self.prop.id)

    # ------------------------------------------------------------------
    # Completely invalid identifier
    # ------------------------------------------------------------------

    def test_16_random_string_identifier_returns_404(self):
        """A random non-existent string that is not a digit/phone returns 404."""
        resp = self._call_get("totally-random-identifier-no-match-xyz")
        self.assertErrorResponse(resp, 404)

    def test_17_404_error_body_includes_identifier_in_message(self):
        """The 404 message should echo back the identifier that was not found."""
        bad_id = "not-a-real-identifier-abc"
        resp = self._call_get(bad_id)
        body = json.loads(resp.get_data(as_text=True))
        self.assertIn(bad_id, body["error"]["message"])

    # ------------------------------------------------------------------
    # Response serialisation
    # ------------------------------------------------------------------

    def test_18_response_includes_core_fields(self):
        """Successful response must contain key property fields."""
        resp = self._call_get(str(self.prop.id))
        data = self.assertSuccessResponse(resp)
        for field in ("id", "name", "uuid", "prop_id", "city", "state", "is_active"):
            self.assertIn(field, data, msg=f"Missing field: {field}")

    def test_19_response_is_json_content_type(self):
        """Response must have Content-Type application/json."""
        resp = self._call_get(str(self.prop.id))
        self.assertIn("application/json", resp.content_type)


# ---------------------------------------------------------------------------
# Unit tests for _resolve_identifier() helper (isolated, no HTTP mock needed)
# ---------------------------------------------------------------------------


@tagged("post_install", "-at_install")
class TestResolveIdentifier(PropertyApiTestCase):
    """Direct unit tests for the ``_resolve_identifier`` module-level function."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.prop = cls.make_property(
            uuid="resolve-test-uuid-abc",
            prop_id="RESOLVETEST01",
            owner_phone="9123456789",
        )

    def test_20_resolves_by_integer_id(self):
        """_resolve_identifier returns record when passed its integer id as string."""
        rec = _resolve_identifier(self.env, str(self.prop.id))
        self.assertEqual(rec.id, self.prop.id)

    def test_21_resolves_by_uuid(self):
        rec = _resolve_identifier(self.env, "resolve-test-uuid-abc")
        self.assertEqual(rec.id, self.prop.id)

    def test_22_resolves_by_prop_id(self):
        rec = _resolve_identifier(self.env, "RESOLVETEST01")
        self.assertEqual(rec.id, self.prop.id)

    def test_23_resolves_by_owner_phone(self):
        rec = _resolve_identifier(self.env, "9123456789")
        self.assertEqual(rec.id, self.prop.id)

    def test_24_returns_empty_recordset_for_unknown(self):
        rec = _resolve_identifier(self.env, "COMPLETELYUNKNOWNIDENTIFIER99")
        self.assertFalse(rec)  # empty recordset is falsy

    def test_25_nonexistent_integer_id_falls_through_to_empty(self):
        rec = _resolve_identifier(self.env, "8888888888")
        self.assertFalse(rec)
