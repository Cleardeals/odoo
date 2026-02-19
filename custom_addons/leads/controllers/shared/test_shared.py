# -*- coding: utf-8 -*-
"""
test_shared.py
--------------
Standalone tests for the three shared controller modules:
  - phone_utils.py
  - response_utils.py       (mocked — no real Odoo Response needed)
  - property_resolver.py    (mocked — no real Odoo ORM needed)

Run from any Python 3.10+ environment:
    python test_shared.py

No Odoo installation required. Odoo imports are patched via sys.modules
before any module is loaded.
"""

import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call


# ─────────────────────────────────────────────────────────────────────────────
# 1.  BOOTSTRAP: Fake the Odoo modules so imports don't blow up
# ─────────────────────────────────────────────────────────────────────────────

def _build_odoo_stubs():
    """
    Insert minimal stubs for `odoo` and `odoo.http` into sys.modules
    so that response_utils.py can be imported without a running Odoo server.
    """
    odoo_mod = types.ModuleType("odoo")
    odoo_http_mod = types.ModuleType("odoo.http")

    # Minimal Response stub — mirrors the real Odoo Response signature
    class FakeResponse:
        def __init__(self, body, status=200, mimetype="application/json"):
            self.body = body
            self.status = status
            self.mimetype = mimetype

        def get_json(self):
            return json.loads(self.body)

        def __repr__(self):
            return f"<FakeResponse status={self.status}>"

    odoo_http_mod.Response = FakeResponse

    sys.modules["odoo"] = odoo_mod
    sys.modules["odoo.http"] = odoo_http_mod


_build_odoo_stubs()


# ─────────────────────────────────────────────────────────────────────────────
# 2.  NOW import the modules under test
#     Adjust these paths to wherever the files live relative to this script.
# ─────────────────────────────────────────────────────────────────────────────

import importlib.util, pathlib

def _load(filename: str):
    """Load a .py file by path and return it as a module object."""
    path = pathlib.Path(__file__).parent / filename
    spec = importlib.util.spec_from_file_location(filename.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# Load each shared file directly
phone_utils      = _load(pathlib.Path("phone_utils.py"))
response_utils   = _load(pathlib.Path("response_utils.py"))
property_resolver = _load(pathlib.Path("property_resolver.py"))


# ─────────────────────────────────────────────────────────────────────────────
# 3.  phone_utils  TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizePhoneTo10Digit(unittest.TestCase):
    """Tests for normalize_phone_to_10_digit()"""

    fn = staticmethod(phone_utils.normalize_phone_to_10_digit)

    # ── Happy path ────────────────────────────────────────────────────────────

    def test_plain_10_digit(self):
        self.assertEqual(self.fn("9876543210"), "9876543210")

    def test_with_91_prefix(self):
        self.assertEqual(self.fn("919876543210"), "9876543210")

    def test_with_plus_91_prefix(self):
        self.assertEqual(self.fn("+919876543210"), "9876543210")

    def test_with_leading_zero(self):
        self.assertEqual(self.fn("09876543210"), "9876543210")

    def test_with_spaces(self):
        self.assertEqual(self.fn("  98765 43210 "), "9876543210")

    def test_with_dashes(self):
        self.assertEqual(self.fn("98765-43210"), "9876543210")

    def test_with_plus_and_spaces(self):
        self.assertEqual(self.fn("+91 98765 43210"), "9876543210")

    def test_leading_trailing_whitespace(self):
        self.assertEqual(self.fn("  9876543210  "), "9876543210")

    # ── Returns None cases ────────────────────────────────────────────────────

    def test_none_input(self):
        self.assertIsNone(self.fn(None))

    def test_empty_string(self):
        self.assertIsNone(self.fn(""))

    def test_whitespace_only(self):
        self.assertIsNone(self.fn("   "))

    def test_too_short(self):
        self.assertIsNone(self.fn("98765"))

    def test_too_long_not_91_prefix(self):
        # 13 digits, doesn't match any known format
        self.assertIsNone(self.fn("9876543210123"))

    def test_11_digits_not_starting_with_0(self):
        # 11 digits but starts with 9, not 0
        self.assertIsNone(self.fn("91234567890"))

    def test_alpha_only(self):
        self.assertIsNone(self.fn("abcdefghij"))

    def test_mixed_alpha_too_short(self):
        self.assertIsNone(self.fn("9876abc"))

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_number_as_integer_like_string(self):
        # Should work since we cast to str internally
        self.assertEqual(self.fn("9876543210"), "9876543210")

    def test_returns_string_not_int(self):
        result = self.fn("9876543210")
        self.assertIsInstance(result, str)

    def test_numbers_starting_with_0_after_91_strip(self):
        # +91 followed by a number starting with 0 — rare but valid to strip correctly
        self.assertEqual(self.fn("+910876543210"), "0876543210")


class TestExtractPhoneFromRequest(unittest.TestCase):
    """Tests for extract_phone_from_request()"""

    fn = staticmethod(phone_utils.extract_phone_from_request)

    def _make_request(self, phone_value):
        mock_req = MagicMock()
        mock_req.params.get.return_value = phone_value
        return mock_req

    def test_valid_10_digit_in_request(self):
        req = self._make_request("9876543210")
        self.assertEqual(self.fn(req), "9876543210")

    def test_91_prefix_in_request(self):
        req = self._make_request("919876543210")
        self.assertEqual(self.fn(req), "9876543210")

    def test_missing_phone_param_returns_none(self):
        mock_req = MagicMock()
        mock_req.params.get.return_value = ""
        self.assertIsNone(self.fn(mock_req))

    def test_invalid_phone_returns_none(self):
        req = self._make_request("123")
        self.assertIsNone(self.fn(req))

    def test_strips_whitespace_from_request_param(self):
        req = self._make_request("  9876543210  ")
        self.assertEqual(self.fn(req), "9876543210")

    def test_params_get_called_with_phone_key(self):
        req = self._make_request("9876543210")
        self.fn(req)
        req.params.get.assert_called_once_with("phone", "")


# ─────────────────────────────────────────────────────────────────────────────
# 4.  response_utils  TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestSuccessResponse(unittest.TestCase):
    """Tests for success_response()"""

    fn = staticmethod(response_utils.success_response)

    def _parse(self, resp):
        return resp.get_json()

    def test_envelope_shape(self):
        resp = self.fn({"key": "value"})
        body = self._parse(resp)
        self.assertIn("success", body)
        self.assertIn("data", body)
        self.assertIn("error", body)

    def test_success_is_true(self):
        body = self._parse(self.fn({}))
        self.assertTrue(body["success"])

    def test_error_is_null(self):
        body = self._parse(self.fn({}))
        self.assertIsNone(body["error"])

    def test_data_passthrough_dict(self):
        payload = {"foo": "bar", "count": 42}
        body = self._parse(self.fn(payload))
        self.assertEqual(body["data"], payload)

    def test_data_passthrough_list(self):
        payload = [1, 2, 3]
        body = self._parse(self.fn(payload))
        self.assertEqual(body["data"], payload)

    def test_default_http_status_200(self):
        resp = self.fn({})
        self.assertEqual(resp.status, 200)

    def test_custom_http_status(self):
        resp = self.fn({}, http_status=201)
        self.assertEqual(resp.status, 201)

    def test_mimetype_is_json(self):
        resp = self.fn({})
        self.assertEqual(resp.mimetype, "application/json")

    def test_date_serialization_does_not_crash(self):
        """default=str in json.dumps should handle date/datetime objects."""
        from datetime import date, datetime
        payload = {"d": date(2025, 1, 1), "dt": datetime(2025, 1, 1, 12, 0)}
        # Should not raise
        resp = self.fn(payload)
        body = self._parse(resp)
        self.assertIn("d", body["data"])

    def test_empty_dict(self):
        body = self._parse(self.fn({}))
        self.assertEqual(body["data"], {})

    def test_none_data(self):
        body = self._parse(self.fn(None))
        self.assertIsNone(body["data"])


class TestErrorResponse(unittest.TestCase):
    """Tests for error_response()"""

    fn = staticmethod(response_utils.error_response)

    def _parse(self, resp):
        return resp.get_json()

    def test_success_is_false(self):
        body = self._parse(self.fn(400, "bad input"))
        self.assertFalse(body["success"])

    def test_data_is_null(self):
        body = self._parse(self.fn(400, "bad input"))
        self.assertIsNone(body["data"])

    def test_error_block_present(self):
        body = self._parse(self.fn(400, "bad input"))
        self.assertIsNotNone(body["error"])

    def test_error_code_matches(self):
        body = self._parse(self.fn(404, "not found"))
        self.assertEqual(body["error"]["code"], 404)

    def test_error_message_matches(self):
        body = self._parse(self.fn(422, "validation failed"))
        self.assertEqual(body["error"]["message"], "validation failed")

    def test_http_status_set(self):
        resp = self.fn(404, "not found")
        self.assertEqual(resp.status, 404)

    def test_500_error(self):
        body = self._parse(self.fn(500, "internal error"))
        self.assertEqual(body["error"]["code"], 500)

    def test_mimetype_is_json(self):
        resp = self.fn(400, "bad")
        self.assertEqual(resp.mimetype, "application/json")


class TestPaginate(unittest.TestCase):
    """Tests for paginate()"""

    fn = staticmethod(response_utils.paginate)

    def test_basic_first_page(self):
        items = list(range(25))
        result = self.fn(items, page=1, page_size=10)
        self.assertEqual(result["items"], list(range(10)))

    def test_second_page(self):
        items = list(range(25))
        result = self.fn(items, page=2, page_size=10)
        self.assertEqual(result["items"], list(range(10, 20)))

    def test_last_partial_page(self):
        items = list(range(25))
        result = self.fn(items, page=3, page_size=10)
        self.assertEqual(result["items"], list(range(20, 25)))

    def test_page_beyond_total_returns_empty(self):
        items = list(range(5))
        result = self.fn(items, page=99, page_size=10)
        self.assertEqual(result["items"], [])

    def test_total_count(self):
        items = list(range(25))
        result = self.fn(items, page=1, page_size=10)
        self.assertEqual(result["pagination"]["total"], 25)

    def test_total_pages_exact_division(self):
        items = list(range(20))
        result = self.fn(items, page=1, page_size=10)
        self.assertEqual(result["pagination"]["total_pages"], 2)

    def test_total_pages_with_remainder(self):
        items = list(range(21))
        result = self.fn(items, page=1, page_size=10)
        self.assertEqual(result["pagination"]["total_pages"], 3)

    def test_page_size_in_meta(self):
        result = self.fn(list(range(10)), page=1, page_size=5)
        self.assertEqual(result["pagination"]["page_size"], 5)

    def test_page_in_meta(self):
        result = self.fn(list(range(10)), page=2, page_size=5)
        self.assertEqual(result["pagination"]["page"], 2)

    def test_empty_list(self):
        result = self.fn([], page=1, page_size=10)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["pagination"]["total"], 0)

    def test_page_zero_clamped_to_1(self):
        """page=0 should be treated as page=1"""
        items = list(range(10))
        result = self.fn(items, page=0, page_size=5)
        self.assertEqual(result["items"], list(range(5)))

    def test_page_size_zero_clamped_to_1(self):
        """page_size=0 should be clamped to minimum of 1"""
        items = list(range(5))
        result = self.fn(items, page=1, page_size=0)
        self.assertEqual(len(result["items"]), 1)

    def test_page_size_hard_cap_at_200(self):
        """page_size above 200 should be capped"""
        items = list(range(500))
        result = self.fn(items, page=1, page_size=999)
        self.assertLessEqual(len(result["items"]), 200)

    def test_single_item_list(self):
        result = self.fn(["only"], page=1, page_size=10)
        self.assertEqual(result["items"], ["only"])
        self.assertEqual(result["pagination"]["total"], 1)
        self.assertEqual(result["pagination"]["total_pages"], 1)


# ─────────────────────────────────────────────────────────────────────────────
# 5.  property_resolver  TESTS  (fully mocked — no Odoo ORM)
# ─────────────────────────────────────────────────────────────────────────────

def _make_env(search_returns=None):
    """
    Build a minimal fake Odoo `env` dict-like object.

    search_returns : a list of recordsets to return on successive search() calls.
                     Each call to env[model].sudo().search() pops from this list.
    """
    search_queue = list(search_returns or [])

    class FakeRecordset:
        def __init__(self, records=None, ids=None):
            self._records = records or []
            self.ids = ids or list(range(len(self._records)))

        def __len__(self):
            return len(self._records)

        def __bool__(self):
            return bool(self._records)

        def __iter__(self):
            return iter(self._records)

        def mapped(self, field):
            return [getattr(r, field, None) for r in self._records]

        def browse(self, ids):
            return FakeRecordset(ids=ids)

    class FakeModel:
        def __init__(self):
            self._sudo = self

        def sudo(self):
            return self

        def search(self, domain, **kwargs):
            if search_queue:
                return search_queue.pop(0)
            return FakeRecordset()

        def browse(self, ids):
            return FakeRecordset(ids=ids)

    class FakeEnv:
        def __getitem__(self, model_name):
            return FakeModel()

    return FakeEnv(), FakeRecordset


class TestGetPropertiesForPhone(unittest.TestCase):

    def test_returns_props_on_exact_match(self):
        env, RS = _make_env()
        found = RS([MagicMock(property_tag="TAG1")])
        not_needed = RS()

        # Patch: first search (10-digit) returns results → second never called
        with patch.object(env["property.inventory"].sudo().__class__, "search",
                          side_effect=[found]) as mock_search:
            result = property_resolver.get_properties_for_phone(env, "9876543210")
            self.assertEqual(mock_search.call_count, 1)

    def test_falls_back_to_91_prefix_when_first_empty(self):
        """
        When the exact 10-digit search returns nothing, it should
        try with the '91' prefix.
        """
        env, RS = _make_env()
        empty = RS()
        found_with_91 = RS([MagicMock(property_tag="TAG2")])

        call_count = {"n": 0}
        def fake_search(domain, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return empty          # first call: exact 10-digit → nothing
            return found_with_91      # second call: 91 prefix → found

        model = env["property.inventory"]
        with patch.object(model.__class__, "search", side_effect=fake_search):
            property_resolver.get_properties_for_phone(env, "9876543210")
            self.assertEqual(call_count["n"], 2)

    def test_uses_is_active_not_active_field(self):
        """
        ⚠️  KNOWN BUG CHECK: the model field is 'is_active', not 'active'.
        This test captures the domain actually passed to search() and
        asserts the correct field name is used.
        """
        captured_domains = []

        env, RS = _make_env()
        empty = RS()

        def fake_search(domain, **kwargs):
            captured_domains.append(domain)
            return empty

        model = env["property.inventory"]
        with patch.object(model.__class__, "search", side_effect=fake_search):
            property_resolver.get_properties_for_phone(env, "9876543210")

        # Check all domains used — none should reference 'active', they should use 'is_active'
        for domain in captured_domains:
            field_names = [clause[0] for clause in domain if isinstance(clause, (list, tuple))]
            self.assertNotIn(
                "active", field_names,
                msg=(
                    "BUG DETECTED: domain uses 'active' but the model field is 'is_active'. "
                    f"Full domain: {domain}"
                ),
            )
            self.assertIn(
                "is_active", field_names,
                msg=f"Expected 'is_active' in domain but got: {domain}",
            )

    def test_returns_empty_recordset_when_no_match(self):
        env, RS = _make_env()
        empty = RS()

        with patch.object(env["property.inventory"].__class__, "search",
                          return_value=empty):
            result = property_resolver.get_properties_for_phone(env, "9999999999")
            self.assertEqual(len(result), 0)


class TestGetPropertyTags(unittest.TestCase):

    def test_returns_list_of_tags(self):
        env, RS = _make_env()
        rec1 = MagicMock()
        rec1.property_tag = "TAG1"
        rec2 = MagicMock()
        rec2.property_tag = "TAG2"
        found = RS([rec1, rec2])

        with patch.object(env["property.inventory"].__class__, "search",
                          return_value=found):
            tags = property_resolver.get_property_tags(env, "9876543210")
            self.assertIn("TAG1", tags)
            self.assertIn("TAG2", tags)

    def test_returns_empty_list_when_no_properties(self):
        env, RS = _make_env()
        empty = RS()
        with patch.object(env["property.inventory"].__class__, "search",
                          return_value=empty):
            tags = property_resolver.get_property_tags(env, "9876543210")
            self.assertEqual(tags, [])


class TestGetPrimaryLeadsForTags(unittest.TestCase):

    def test_returns_empty_recordset_for_empty_tags(self):
        env, RS = _make_env()
        result = property_resolver.get_primary_leads_for_tags(env, [])
        # browse([]) → should be falsy / length 0
        self.assertFalse(bool(result.ids) if hasattr(result, "ids") else bool(result))

    def test_searches_leads_by_property_ids(self):
        env, RS = _make_env()
        prop_rs = RS([MagicMock()], ids=[10, 11])
        lead_rs = RS([MagicMock(), MagicMock()], ids=[101, 102])

        search_results = [prop_rs, lead_rs]

        def fake_search(domain, **kwargs):
            return search_results.pop(0)

        with patch.object(env["property.inventory"].__class__, "search",
                          side_effect=fake_search), \
             patch.object(env["leads.new"].__class__, "search",
                          return_value=lead_rs):
            result = property_resolver.get_primary_leads_for_tags(
                env, ["TAG1", "TAG2"]
            )
            self.assertEqual(len(result), 2)


class TestGetRecommendedLeadsForTags(unittest.TestCase):

    def test_returns_empty_recordset_for_empty_tags(self):
        env, RS = _make_env()
        result = property_resolver.get_recommended_leads_for_tags(env, [])
        self.assertFalse(bool(result.ids) if hasattr(result, "ids") else bool(result))

    def test_searches_interests_by_property_ids(self):
        env, RS = _make_env()
        prop_rs = RS([MagicMock()], ids=[10])
        interest_rs = RS([MagicMock()], ids=[55])

        def fake_prop_search(domain, **kwargs):
            return prop_rs

        def fake_interest_search(domain, **kwargs):
            return interest_rs

        with patch.object(env["property.inventory"].__class__, "search",
                          side_effect=fake_prop_search), \
             patch.object(env["lead.property.interest"].__class__, "search",
                          side_effect=fake_interest_search):
            result = property_resolver.get_recommended_leads_for_tags(env, ["TAG1"])
            self.assertEqual(len(result), 1)


# ─────────────────────────────────────────────────────────────────────────────
# 6.  RUN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Phone utils
    suite.addTests(loader.loadTestsFromTestCase(TestNormalizePhoneTo10Digit))
    suite.addTests(loader.loadTestsFromTestCase(TestExtractPhoneFromRequest))

    # Response utils
    suite.addTests(loader.loadTestsFromTestCase(TestSuccessResponse))
    suite.addTests(loader.loadTestsFromTestCase(TestErrorResponse))
    suite.addTests(loader.loadTestsFromTestCase(TestPaginate))

    # Property resolver
    suite.addTests(loader.loadTestsFromTestCase(TestGetPropertiesForPhone))
    suite.addTests(loader.loadTestsFromTestCase(TestGetPropertyTags))
    suite.addTests(loader.loadTestsFromTestCase(TestGetPrimaryLeadsForTags))
    suite.addTests(loader.loadTestsFromTestCase(TestGetRecommendedLeadsForTags))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
