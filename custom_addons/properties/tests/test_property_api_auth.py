"""
Tests for the API authentication layer (``controllers/auth.py``).

``validate_api_key(request)`` is the single gateway that every controller
calls before touching the database.  It must:

  - Return (True, None) when the correct key is presented.
  - Return (False, 401 Response) when the header is absent.
  - Return (False, 403 Response) when a wrong key is presented.
  - Return (False, 503 Response) when the system parameter is not configured.
  - Use constant-time comparison (hmac.compare_digest) — verified indirectly
    by confirming that a key that differs only slightly is still rejected.

All tests mock the ``request`` object so no real HTTP server is required.
"""

import json

from odoo.tests import tagged

from ..controllers.auth import validate_api_key
from .test_property_common import PropertyApiTestCase


@tagged("post_install", "-at_install")
class TestPropertyApiAuth(PropertyApiTestCase):
    """Unit tests for validate_api_key()."""

    # ------------------------------------------------------------------ #
    # Happy path                                                           #
    # ------------------------------------------------------------------ #

    def test_01_valid_key_returns_true_none(self):
        """Correct X-API-Key header must return (True, None)."""
        req = self.make_mock_request(api_key="test-api-key-abc123")
        ok, err = validate_api_key(req)
        self.assertTrue(ok)
        self.assertIsNone(err)

    # ------------------------------------------------------------------ #
    # Missing header → 401                                                 #
    # ------------------------------------------------------------------ #

    def test_02_missing_header_returns_401(self):
        """Absent X-API-Key header must produce a 401 response."""
        req = self.make_mock_request(api_key="")  # empty string → header not set
        ok, err = validate_api_key(req)
        self.assertFalse(ok)
        self.assertIsNotNone(err)
        self.assertEqual(err.status_code, 401)

    def test_03_missing_header_body_has_expected_message(self):
        """401 response body should mention the missing header name."""
        req = self.make_mock_request(api_key="")
        _, err = validate_api_key(req)
        body = json.loads(err.get_data(as_text=True))
        self.assertIn("X-API-Key", body["error"]["message"])

    # ------------------------------------------------------------------ #
    # Wrong key → 403                                                      #
    # ------------------------------------------------------------------ #

    def test_04_wrong_key_returns_403(self):
        """A header with an invalid key must produce a 403 response."""
        req = self.make_mock_request(api_key="completely-wrong-key")
        ok, err = validate_api_key(req)
        self.assertFalse(ok)
        self.assertEqual(err.status_code, 403)

    def test_05_key_with_leading_space_rejected(self):
        """Key with an extra leading space must not match (no implicit stripping)."""
        req = self.make_mock_request(api_key=" test-api-key-abc123")
        ok, _ = validate_api_key(req)
        self.assertFalse(ok)

    def test_06_key_with_trailing_space_rejected(self):
        """Key with an extra trailing space must not match."""
        req = self.make_mock_request(api_key="test-api-key-abc123 ")
        ok, _ = validate_api_key(req)
        self.assertFalse(ok)

    def test_07_key_wrong_by_one_char_rejected(self):
        """A key that differs from the valid key by a single character must be rejected.
        This also acts as a proxy check for constant-time comparison usage."""
        req = self.make_mock_request(api_key="test-api-key-abc124")  # last char changed
        ok, err = validate_api_key(req)
        self.assertFalse(ok)
        self.assertEqual(err.status_code, 403)

    def test_08_empty_string_key_rejected(self):
        """Header present but with an empty string value must be rejected (treated as missing)."""
        # Prime headers dict with the real key first, then overwrite with empty string.
        req = self.make_mock_request(api_key="placeholder")
        # req.httprequest.headers is our plain dict — mutate it directly.
        req.httprequest.headers["X-API-Key"] = ""
        ok, err = validate_api_key(req)
        self.assertFalse(ok)
        # Empty value is treated the same as absent → 401
        self.assertEqual(err.status_code, 401)

    def test_09_wrong_key_body_mentions_message(self):
        """403 response body should include an error message."""
        req = self.make_mock_request(api_key="bad-key")
        _, err = validate_api_key(req)
        body = json.loads(err.get_data(as_text=True))
        self.assertFalse(body["success"])
        self.assertIn("message", body["error"])

    # ------------------------------------------------------------------ #
    # System parameter not configured → 503                               #
    # ------------------------------------------------------------------ #

    def test_10_unconfigured_system_param_returns_503(self):
        """Absent system parameter must produce a 503 response."""
        self.clear_api_key()
        try:
            req = self.make_mock_request(api_key="any-key")
            ok, err = validate_api_key(req)
            self.assertFalse(ok)
            self.assertEqual(err.status_code, 503)
        finally:
            # Restore so subsequent tests are not broken
            self.set_api_key("test-api-key-abc123")

    def test_11_unconfigured_system_param_body_is_correct(self):
        """503 error body should indicate configuration is missing."""
        self.clear_api_key()
        try:
            req = self.make_mock_request(api_key="any-key")
            _, err = validate_api_key(req)
            body = json.loads(err.get_data(as_text=True))
            self.assertEqual(body["error"]["status"], 503)
            self.assertFalse(body["success"])
        finally:
            self.set_api_key("test-api-key-abc123")

    # ------------------------------------------------------------------ #
    # Response format                                                      #
    # ------------------------------------------------------------------ #

    def test_12_error_responses_are_json(self):
        """All error responses must have Content-Type application/json."""
        req = self.make_mock_request(api_key="wrong")
        _, err = validate_api_key(req)
        self.assertIn("application/json", err.content_type)

    def test_13_error_response_has_standard_envelope(self):
        """Error body must conform to the standard {success, error: {status, message}} shape."""
        req = self.make_mock_request(api_key="wrong")
        _, err = validate_api_key(req)
        body = json.loads(err.get_data(as_text=True))

        self.assertIn("success", body)
        self.assertIn("error", body)
        self.assertIn("status", body["error"])
        self.assertIn("message", body["error"])

    # ------------------------------------------------------------------ #
    # Key rotation                                                         #
    # ------------------------------------------------------------------ #

    def test_14_accepts_newly_rotated_key(self):
        """After rotating the system parameter, the new key must be accepted."""
        new_key = "rotated-key-xyz-9876"
        self.set_api_key(new_key)
        try:
            req = self.make_mock_request(api_key=new_key)
            ok, err = validate_api_key(req)
            self.assertTrue(ok)
            self.assertIsNone(err)
        finally:
            self.set_api_key("test-api-key-abc123")

    def test_15_old_key_rejected_after_rotation(self):
        """After rotating the key, the previous key must be rejected."""
        new_key = "rotated-key-xyz-9876"
        self.set_api_key(new_key)
        try:
            req = self.make_mock_request(api_key="test-api-key-abc123")
            ok, _ = validate_api_key(req)
            self.assertFalse(ok)
        finally:
            self.set_api_key("test-api-key-abc123")
