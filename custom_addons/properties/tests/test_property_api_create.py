"""
Tests for PUT /api/v1/properties (create endpoint).

Covers:
  - Authentication guard (wrong key → 403, missing header → 401)
  - Successful creation with minimum required fields (name only)
  - Returns HTTP 201 on success
  - All allowed create fields are persisted correctly
  - Missing or null 'name' field → 422
  - Only JSON content-type accepted → wrong content-type returns 415
  - Malformed JSON body → 400
  - Empty JSON object body (no recognisable fields) → 422
  - Unknown fields in payload are ignored and listed in '_ignored_fields'
  - Duplicate uuid constraint violation handled → 500
  - Duplicate prop_id constraint violation handled → 500
  - Response body contains serialised new property data
  - 'rm_user_id' field accepted as integer foreign key
  - Boolean field 'is_active' and 'for_sell' accepted
  - Numeric field 'pricing' accepted as float
  - Integer field 'bedroom_count' accepted
  - A mix of valid and unknown fields → valid ones saved, unknowns reported
"""

from datetime import date, timedelta
from time import time_ns
from unittest.mock import patch

from odoo.tests import tagged

from ..controllers.controllers import PropertyApiController
from .test_property_common import PropertyApiTestCase

_CONTROLLER_REQUEST = "odoo.addons.properties.controllers.controllers.request"


@tagged("post_install", "-at_install")
class TestPropertyApiCreate(PropertyApiTestCase):
    """Tests for ``PropertyApiController.create_property``."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = PropertyApiController()

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _call_create(self, *, api_key=None, body=None, content_type="application/json"):
        key = api_key if api_key is not None else "test-api-key-abc123"
        req = self.make_mock_request(
            api_key=key,
            method="PUT",
            content_type=content_type,
            body=body,
        )
        with patch(_CONTROLLER_REQUEST, req):
            return self.controller.create_property()

    def _unique_vals(self, **extra):
        """Return a create payload with guaranteed-unique uuid and prop_id."""
        n = time_ns()
        defaults = {
            "name": f"API Created Property {n}",
            "uuid": f"api-uuid-{n}",
            "prop_id": f"APICR{str(n)[-6:]}",
        }
        defaults.update(extra)
        return defaults

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def test_01_wrong_api_key_returns_403(self):
        """Create endpoint must reject bad API key."""
        resp = self._call_create(api_key="bad-key", body={"name": "x"})
        self.assertErrorResponse(resp, 403)

    def test_02_missing_api_key_returns_401(self):
        """Create endpoint must return 401 when header is absent."""
        resp = self._call_create(api_key="", body={"name": "x"})
        self.assertErrorResponse(resp, 401)

    # ------------------------------------------------------------------
    # Content-Type enforcement
    # ------------------------------------------------------------------

    def test_03_wrong_content_type_returns_415(self):
        """Non-JSON Content-Type must return 415 Unsupported Media Type."""
        resp = self._call_create(
            content_type="application/x-www-form-urlencoded",
            body={"name": "test"},
        )
        self.assertErrorResponse(resp, 415)

    def test_04_missing_content_type_returns_415(self):
        """Empty Content-Type string must return 415."""
        resp = self._call_create(content_type="", body={"name": "test"})
        self.assertErrorResponse(resp, 415)

    # ------------------------------------------------------------------
    # Malformed request body
    # ------------------------------------------------------------------

    def test_05_malformed_json_returns_400(self):
        """A body that is not valid JSON must return 400."""
        req = self.make_mock_request(api_key="test-api-key-abc123", method="PUT")
        req.httprequest.content_type = "application/json"
        req.httprequest.data = b"{ this is not json }"
        with patch(_CONTROLLER_REQUEST, req):
            resp = self.controller.create_property()
        self.assertErrorResponse(resp, 400)

    def test_06_empty_body_bytes_returns_400(self):
        """Completely empty body must be rejected with 400."""
        req = self.make_mock_request(api_key="test-api-key-abc123", method="PUT")
        req.httprequest.content_type = "application/json"
        req.httprequest.data = b""
        with patch(_CONTROLLER_REQUEST, req):
            resp = self.controller.create_property()
        self.assertErrorResponse(resp, 400)

    # ------------------------------------------------------------------
    # Required fields
    # ------------------------------------------------------------------

    def test_07_missing_name_returns_422(self):
        """A payload without 'name' must return 422 Unprocessable Entity."""
        resp = self._call_create(body={"city": "Mumbai"})
        self.assertErrorResponse(resp, 422)

    def test_08_null_name_returns_422(self):
        """Explicit null for 'name' must be rejected with 422."""
        resp = self._call_create(body={"name": None})
        self.assertErrorResponse(resp, 422)

    def test_09_empty_string_name_returns_422(self):
        """Empty string for 'name' must be rejected with 422."""
        resp = self._call_create(body={"name": ""})
        self.assertErrorResponse(resp, 422)

    # ------------------------------------------------------------------
    # Minimum-field creation → 201
    # ------------------------------------------------------------------

    def test_10_create_with_name_only_returns_201(self):
        """A payload containing only 'name' must create a record and return 201."""
        resp = self._call_create(body={"name": f"Minimal Property {self.suffix}"})
        data = self.assertSuccessResponse(resp, expected_status=201)
        self.assertIsNotNone(data.get("id"))
        self.assertGreater(data["id"], 0)

    def test_11_created_record_exists_in_db(self):
        """Record created via API must be persisted in the database."""
        name = f"Persisted Property {self.suffix}"
        self._call_create(body={"name": name})
        count = self.env["property.base"].search_count([("name", "=", name)])
        self.assertEqual(count, 1)

    def test_12_response_status_is_201(self):
        """HTTP status code in response must be 201 on successful creation."""
        resp = self._call_create(body=self._unique_vals())
        self.assertEqual(resp.status_code, 201)

    # ------------------------------------------------------------------
    # All allowed create fields persisted
    # ------------------------------------------------------------------

    def test_13_all_scalar_fields_accepted_and_stored(self):
        """All scalar allowed-create fields supplied in the payload must be persisted."""
        vals = self._unique_vals(
            name="Full Fields Test",
            form_no=f"FRM-FULL-{self.suffix}",
            prop_type="Residential",
            prop_sub_type="Apartment",
            for_sell=True,
            state="Maharashtra",
            city="Pune",
            location="Kharadi",
            pricing=85.5,
            pricing_unit="lakh",
            owner_name="Jane Owner",
            owner_phone="9011223344",
            owner_email="jane@example.com",
            bedroom_count=3,
            gmaps_url="https://maps.google.com/?q=Pune",
            is_active=True,
        )
        resp = self._call_create(body=vals)
        data = self.assertSuccessResponse(resp, expected_status=201)
        record = self.env["property.base"].browse(data["id"])
        self.assertEqual(record.name, vals["name"])
        self.assertEqual(record.city, vals["city"])
        self.assertEqual(record.pricing, vals["pricing"])
        self.assertEqual(record.bedroom_count, vals["bedroom_count"])
        self.assertEqual(record.owner_email, vals["owner_email"])

    def test_14_rm_user_id_accepted_as_integer_fk(self):
        """rm_user_id as integer must be accepted and linked to the correct user."""
        vals = self._unique_vals(rm_user_id=self.rm_user.id)
        resp = self._call_create(body=vals)
        data = self.assertSuccessResponse(resp, expected_status=201)
        record = self.env["property.base"].browse(data["id"])
        self.assertEqual(record.rm_user_id.id, self.rm_user.id)

    def test_15_boolean_fields_accepted(self):
        """Boolean fields for_sell and is_active must be serialised correctly."""
        vals = self._unique_vals(for_sell=False, is_active=True)
        resp = self._call_create(body=vals)
        data = self.assertSuccessResponse(resp, expected_status=201)
        self.assertFalse(data["for_sell"])
        self.assertTrue(data["is_active"])

    def test_16_date_fields_accepted_as_iso_strings(self):
        """service_expiry_date and welcome_call_date supplied as ISO strings must be stored."""
        future_date = (date.today() + timedelta(days=60)).isoformat()
        today_str = date.today().isoformat()
        vals = self._unique_vals(
            service_expiry_date=future_date,
            welcome_call_date=today_str,
        )
        resp = self._call_create(body=vals)
        data = self.assertSuccessResponse(resp, expected_status=201)
        record = self.env["property.base"].browse(data["id"])
        self.assertIsNotNone(record.service_expiry_date)

    def test_17_portal_id_fields_accepted(self):
        """Portal ID fields must be stored correctly."""
        vals = self._unique_vals(
            ninety_nine_acres_id="99a-id-001",
            housing_id="hsng-id-001",
            magicbricks_id="mb-id-001",
            olx_id="olx-id-001",
        )
        resp = self._call_create(body=vals)
        data = self.assertSuccessResponse(resp, expected_status=201)
        record = self.env["property.base"].browse(data["id"])
        self.assertEqual(record.ninety_nine_acres_id, "99a-id-001")
        self.assertEqual(record.olx_id, "olx-id-001")

    # ------------------------------------------------------------------
    # Unknown fields → ignored, reported
    # ------------------------------------------------------------------

    def test_18_unknown_fields_ignored_and_reported(self):
        """Fields not in the allow-list must not cause an error; they must appear in '_ignored_fields'."""
        vals = self._unique_vals(
            nonexistent_field_xyz="should be ignored",
            another_random_field=42,
        )
        resp = self._call_create(body=vals)
        data = self.assertSuccessResponse(resp, expected_status=201)
        self.assertIn("_ignored_fields", data)
        self.assertIn("nonexistent_field_xyz", data["_ignored_fields"])
        self.assertIn("another_random_field", data["_ignored_fields"])

    def test_19_valid_and_unknown_fields_mixed(self):
        """Mix of valid + unknown: valid fields saved, unknown ones surfaced."""
        vals = self._unique_vals(
            city="Hyderabad",
            totally_fake_column="oops",
        )
        resp = self._call_create(body=vals)
        data = self.assertSuccessResponse(resp, expected_status=201)
        record = self.env["property.base"].browse(data["id"])
        self.assertEqual(record.city, "Hyderabad")
        self.assertIn("totally_fake_column", data.get("_ignored_fields", []))

    def test_20_payload_with_only_unknown_fields_returns_422(self):
        """Payload whose every field is unknown must return 422 (no valid fields to create)."""
        resp = self._call_create(body={"fake_a": 1, "fake_b": 2})
        self.assertErrorResponse(resp, 422)

    # ------------------------------------------------------------------
    # Uniqueness constraints
    # ------------------------------------------------------------------

    def test_21_duplicate_uuid_returns_500(self):
        """Creating a second property with a uuid that already exists must return 500."""
        fixed_uuid = f"dup-uuid-{self.suffix}"
        self._call_create(body=self._unique_vals(uuid=fixed_uuid))
        resp2 = self._call_create(body=self._unique_vals(uuid=fixed_uuid))
        self.assertErrorResponse(resp2, 500)

    def test_22_duplicate_prop_id_returns_500(self):
        """Creating a second property with a prop_id that already exists must return 500."""
        fixed_prop_id = f"DUP{self.suffix[-6:]}"
        self._call_create(body=self._unique_vals(prop_id=fixed_prop_id))
        resp2 = self._call_create(body=self._unique_vals(prop_id=fixed_prop_id))
        self.assertErrorResponse(resp2, 500)

    # ------------------------------------------------------------------
    # Response shape
    # ------------------------------------------------------------------

    def test_23_response_includes_id(self):
        """Response must include the 'id' of the newly created record."""
        resp = self._call_create(body=self._unique_vals())
        data = self.assertSuccessResponse(resp, expected_status=201)
        self.assertIn("id", data)
        self.assertIsInstance(data["id"], int)

    def test_24_response_body_round_trips_uuid(self):
        """UUID supplied in the payload must appear in the success response."""
        supplied_uuid = f"roundtrip-uuid-{self.suffix}"
        resp = self._call_create(body=self._unique_vals(uuid=supplied_uuid))
        data = self.assertSuccessResponse(resp, expected_status=201)
        self.assertEqual(data["uuid"], supplied_uuid)

    def test_25_response_is_json_content_type(self):
        """Response must be application/json."""
        resp = self._call_create(body=self._unique_vals())
        self.assertIn("application/json", resp.content_type)
