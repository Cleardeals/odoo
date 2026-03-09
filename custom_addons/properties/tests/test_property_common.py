"""
Shared test infrastructure for the Properties module test suite.

Provides:
  PropertyBaseTestCase   — TransactionCase subclass with model fixtures and
                           factory helpers used by every model-level test file.
  PropertyApiTestCase    — Extends PropertyBaseTestCase with helpers that build
                           mock Odoo HTTP request objects, used by all API
                           controller test files.

Design goals
------------
* Every test file imports its base class from here — no duplicated setup code.
* Factory helpers (`make_property`, `make_mock_request`) accept **kwargs so
  callers only specify what matters for their scenario.
* API key management is centralised: set_api_key() and clear_api_key() keep
  system-parameter state predictable across tests.
"""

import json
import time
from datetime import date, timedelta
from unittest.mock import MagicMock

from odoo.tests.common import TransactionCase

# The system parameter key used by auth.py
_API_KEY_PARAM = "properties.api_key"
_DEFAULT_TEST_KEY = "test-api-key-abc123"


# ---------------------------------------------------------------------------
# Model-level base
# ---------------------------------------------------------------------------


class PropertyBaseTestCase(TransactionCase):
    """
    Base test case for all ``property.base`` model tests.

    Class-level fixtures (created once per test class):
        cls.rm_user   — primary Relationship Manager
        cls.rm_user2  — secondary RM for reassignment tests
        cls.suffix    — unique string for this test run; prevents collisions

    Instance helpers:
        make_property(**kwargs) — creates a property.base with safe defaults
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.suffix = str(int(time.time() * 1000))

        cls.rm_user = cls.env["res.users"].create(
            {
                "name": f"Primary RM {cls.suffix}",
                "login": f"rm1_{cls.suffix}",
                "email": f"rm1_{cls.suffix}@test.internal",
            },
        )
        cls.rm_user2 = cls.env["res.users"].create(
            {
                "name": f"Secondary RM {cls.suffix}",
                "login": f"rm2_{cls.suffix}",
                "email": f"rm2_{cls.suffix}@test.internal",
            },
        )

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    _prop_counter = 0

    @classmethod
    def make_property(cls, **kwargs):
        """
        Create a ``property.base`` record with production-representative
        defaults.  Every call generates a unique ``uuid`` and ``prop_id`` so
        tests can run in parallel without uniqueness-constraint failures.

        Override any field by passing it as a keyword argument.
        """
        PropertyBaseTestCase._prop_counter += 1
        n = PropertyBaseTestCase._prop_counter
        uid = f"{cls.suffix}_{n}"

        defaults = {
            "name": f"Test Property {uid}",
            "uuid": f"uuid-{uid}",
            "prop_id": f"TP{uid[-6:]}",
            "form_no": f"FORM-{uid}",
            "prop_type": "Residential",
            "prop_sub_type": "Apartment",
            "for_sell": True,
            "city": "Mumbai",
            "state": "Maharashtra",
            "location": "Andheri West",
            "pricing": 45.0,
            "pricing_unit": "lakh",
            "bedroom_count": 2,
            "owner_name": "Test Owner",
            "owner_phone": f"98765{uid[-5:]}",
            "owner_email": f"owner{uid}@example.com",
            "rm_user_id": cls.rm_user.id,
            "is_active": True,
            "service_expiry_date": date.today() + timedelta(days=30),
            "welcome_call_date": date.today(),
            "reg_date": date.today(),
        }
        defaults.update(kwargs)
        return cls.env["property.base"].create(defaults)


# ---------------------------------------------------------------------------
# API-level base
# ---------------------------------------------------------------------------


class PropertyApiTestCase(PropertyBaseTestCase):
    """
    Extends ``PropertyBaseTestCase`` with helpers for testing HTTP controller
    methods without spinning up a real web server.

    The ``make_mock_request`` factory produces a MagicMock object that
    satisfies every attribute access the controller code makes on
    ``odoo.http.request``.

    API key helpers:
        set_api_key(key)  — writes key to ir.config_parameter
        clear_api_key()   — removes the key (simulates unconfigured state)
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Prime a default API key so every test starts authenticated.
        cls.env["ir.config_parameter"].sudo().set_param(
            _API_KEY_PARAM,
            _DEFAULT_TEST_KEY,
        )

    # ------------------------------------------------------------------
    # API key helpers
    # ------------------------------------------------------------------

    def set_api_key(self, key: str):
        """Overwrite the API key system parameter for the current test."""
        self.env["ir.config_parameter"].sudo().set_param(_API_KEY_PARAM, key)

    def clear_api_key(self):
        """Remove the API key system parameter (simulates unconfigured server)."""
        param = (
            self.env["ir.config_parameter"]
            .sudo()
            .search(
                [("key", "=", _API_KEY_PARAM)],
            )
        )
        if param:
            param.unlink()

    # ------------------------------------------------------------------
    # Mock request factory
    # ------------------------------------------------------------------

    def make_mock_request(
        self,
        *,
        api_key: str = _DEFAULT_TEST_KEY,
        method: str = "GET",
        content_type: str = "application/json",
        body: dict | None = None,
        query_params: dict | None = None,
    ) -> MagicMock:
        """
        Build a MagicMock that mimics ``odoo.http.request`` for the
        properties controllers.

        Parameters
        ----------
        api_key:
            Value placed in the ``X-API-Key`` header.  Pass ``""`` to
            simulate a missing header.
        method:
            HTTP verb (informational only in unit tests).
        content_type:
            Value for the ``Content-Type`` header.
        body:
            Python dict that will be JSON-serialised as the request body.
            Pass ``None`` for requests with no body (GET, DELETE).
        query_params:
            Dict of query-string parameters exposed via
            ``request.httprequest.args``.

        Returns
        -------
        MagicMock
            Drop-in replacement for ``odoo.http.request``.
        """
        mock_req = MagicMock()

        # Bind real environment so ORM calls work
        mock_req.env = self.env

        # Headers
        headers = {}
        if api_key:
            headers["X-API-Key"] = api_key
        mock_req.httprequest.headers = headers

        # Content-Type & body
        mock_req.httprequest.content_type = content_type
        raw_body = json.dumps(body).encode() if body is not None else b""
        mock_req.httprequest.data = raw_body

        # Query string — stored as a plain dict; controllers call qs.get() which is
        # the built-in dict.get(), so no override is needed.
        qs = query_params or {}
        mock_req.httprequest.args = qs

        # Remote address (used in auth warning logs)
        mock_req.httprequest.remote_addr = "127.0.0.1"
        mock_req.httprequest.path = "/api/v1/properties"
        mock_req.httprequest.method = method

        return mock_req

    # ------------------------------------------------------------------
    # Response assertion helpers
    # ------------------------------------------------------------------

    def assertSuccessResponse(self, response, expected_status: int = 200):
        """Assert the werkzeug Response is a success envelope with expected status."""
        self.assertEqual(
            response.status_code,
            expected_status,
            response.get_data(as_text=True),
        )
        body = json.loads(response.get_data(as_text=True))
        self.assertTrue(body.get("success"), f"Expected success=true, got: {body}")
        return body["data"]

    def assertErrorResponse(self, response, expected_status: int):
        """Assert the werkzeug Response is an error envelope with expected status."""
        self.assertEqual(
            response.status_code,
            expected_status,
            response.get_data(as_text=True),
        )
        body = json.loads(response.get_data(as_text=True))
        self.assertFalse(body.get("success"), f"Expected success=false, got: {body}")
        return body["error"]
