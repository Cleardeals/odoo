"""
Tests for the GET /api/v1/properties list endpoint.

Covers:
  - Authentication guard (unauthenticated requests rejected)
  - Default pagination (page=1, page_size=20)
  - Custom page and page_size query parameters
  - page_size capped at 200
  - is_active boolean filter (truthy and falsy values)
  - for_sell boolean filter
  - Exact filters: city, state, prop_type, prop_id, form_no
  - owner_phone 'like' filter (matches substring in a space-separated number string)
  - 'search' ilike filter on property name
  - Multiple filters combined (AND logic)
  - Empty result set returns correct envelope with total=0
  - Pagination metadata (total, page, page_size, pages)
  - Results beyond last page return empty list, not an error
  - Invalid page / page_size non-integer returns 400

All tests call the controller method directly with a mocked ``request``
object; no real HTTP server is required.
"""

import math
from unittest.mock import patch

from odoo.tests import tagged

from ..controllers.controllers import PropertyApiController
from .test_property_common import PropertyApiTestCase

_CONTROLLER_REQUEST = "odoo.addons.properties.controllers.controllers.request"


@tagged("post_install", "-at_install")
class TestPropertyApiList(PropertyApiTestCase):
    """Tests for ``PropertyApiController.list_properties``."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.controller = PropertyApiController()

        # Create a consistent set of properties to query against.
        #   active_properties   - 10 records, is_active=True, for_sell=True,  city=Mumbai
        #   inactive_properties - 3 records,  is_active=False, for_sell=False, city=Pune
        #   rent_properties     - 2 records,  is_active=True,  for_sell=False, city=Mumbai
        cls.active_props = [
            cls.make_property(
                city="Mumbai",
                state="Maharashtra",
                prop_type="Residential",
                for_sell=True,
                is_active=True,
                owner_phone=f"900000000{i}",
            )
            for i in range(10)
        ]
        cls.inactive_props = [
            cls.make_property(
                city="Pune",
                state="Maharashtra",
                prop_type="Commercial",
                for_sell=False,
                is_active=False,
                owner_phone=f"800000000{i}",
            )
            for i in range(3)
        ]
        cls.rent_props = [
            cls.make_property(
                city="Mumbai",
                state="Maharashtra",
                prop_type="Residential",
                for_sell=False,
                is_active=True,
                owner_phone=f"700000000{i}",
            )
            for i in range(2)
        ]

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _call_list(self, *, api_key=None, query_params=None):
        """Call list_properties() with the given query params under a patched request."""
        key = api_key if api_key is not None else "test-api-key-abc123"
        req = self.make_mock_request(api_key=key, query_params=query_params or {})
        with patch(_CONTROLLER_REQUEST, req):
            return self.controller.list_properties()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def test_01_unauthenticated_request_rejected(self):
        """List endpoint must reject requests without a valid API key."""
        resp = self._call_list(api_key="bad-key-xyz")
        self.assertErrorResponse(resp, 403)

    def test_02_missing_api_key_returns_401(self):
        """List endpoint must return 401 when X-API-Key header is absent."""
        resp = self._call_list(api_key="")
        self.assertErrorResponse(resp, 401)

    # ------------------------------------------------------------------
    # Default pagination
    # ------------------------------------------------------------------

    def test_03_default_pagination_metadata(self):
        """Default call returns page=1, page_size=20 in metadata."""
        resp = self._call_list()
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 20)

    def test_04_response_has_all_required_keys(self):
        """Response envelope must include total, page, page_size, pages, results."""
        resp = self._call_list()
        data = self.assertSuccessResponse(resp)
        for key in ("total", "page", "page_size", "pages", "results"):
            self.assertIn(key, data, msg=f"Missing key: {key}")

    def test_05_results_is_a_list(self):
        """The 'results' key must be a list."""
        resp = self._call_list()
        data = self.assertSuccessResponse(resp)
        self.assertIsInstance(data["results"], list)

    # ------------------------------------------------------------------
    # Pagination with is_active filter to keep result set small
    # ------------------------------------------------------------------

    def test_06_page_size_limits_results(self):
        """page_size=2 must return at most 2 results."""
        resp = self._call_list(query_params={"page_size": "2", "is_active": "true"})
        data = self.assertSuccessResponse(resp)
        self.assertLessEqual(len(data["results"]), 2)

    def test_07_page_two_returns_next_records(self):
        """page=2 returns results distinct from page=1."""
        params1 = {"page": "1", "page_size": "3", "is_active": "true"}
        params2 = {"page": "2", "page_size": "3", "is_active": "true"}
        ids1 = {
            r["id"]
            for r in self.assertSuccessResponse(self._call_list(query_params=params1))[
                "results"
            ]
        }
        ids2 = {
            r["id"]
            for r in self.assertSuccessResponse(self._call_list(query_params=params2))[
                "results"
            ]
        }
        self.assertTrue(ids1.isdisjoint(ids2), "Page 1 and page 2 must not overlap")

    def test_08_page_size_capped_at_200(self):
        """page_size > 200 must be silently capped at 200."""
        resp = self._call_list(query_params={"page_size": "9999"})
        data = self.assertSuccessResponse(resp)
        self.assertLessEqual(data["page_size"], 200)

    def test_09_page_beyond_last_page_returns_empty_results(self):
        """Requesting a page past the last one must return results=[] without error."""
        resp = self._call_list(query_params={"page": "9999", "is_active": "true"})
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["results"], [])

    def test_10_invalid_page_returns_400(self):
        """Non-integer 'page' parameter must produce a 400 error."""
        resp = self._call_list(query_params={"page": "abc"})
        self.assertErrorResponse(resp, 400)

    def test_11_invalid_page_size_returns_400(self):
        """Non-integer 'page_size' parameter must produce a 400 error."""
        resp = self._call_list(query_params={"page_size": "xyz"})
        self.assertErrorResponse(resp, 400)

    # ------------------------------------------------------------------
    # is_active filter
    # ------------------------------------------------------------------

    def test_12_is_active_true_returns_only_active(self):
        """is_active=true must only return active properties."""
        resp = self._call_list(query_params={"is_active": "true"})
        data = self.assertSuccessResponse(resp)
        for record in data["results"]:
            self.assertTrue(
                record["is_active"],
                f"Inactive record in results: {record['id']}",
            )

    def test_13_is_active_false_returns_only_inactive(self):
        """is_active=false must only return inactive properties."""
        resp = self._call_list(query_params={"is_active": "false"})
        data = self.assertSuccessResponse(resp)
        for record in data["results"]:
            self.assertFalse(
                record["is_active"],
                f"Active record in results: {record['id']}",
            )

    def test_14_is_active_zero_treated_as_false(self):
        """is_active=0 must be treated the same as is_active=false."""
        resp_zero = self._call_list(query_params={"is_active": "0"})
        resp_false = self._call_list(query_params={"is_active": "false"})
        ids_zero = {r["id"] for r in self.assertSuccessResponse(resp_zero)["results"]}
        ids_false = {r["id"] for r in self.assertSuccessResponse(resp_false)["results"]}
        self.assertEqual(ids_zero, ids_false)

    def test_15_is_active_no_treated_as_false(self):
        """is_active=no must be treated as falsy."""
        resp = self._call_list(query_params={"is_active": "no"})
        data = self.assertSuccessResponse(resp)
        for record in data["results"]:
            self.assertFalse(record["is_active"])

    # ------------------------------------------------------------------
    # for_sell filter
    # ------------------------------------------------------------------

    def test_16_for_sell_true_returns_only_sell_listings(self):
        """for_sell=true must only return properties with for_sell=True."""
        resp = self._call_list(query_params={"for_sell": "true", "is_active": "true"})
        data = self.assertSuccessResponse(resp)
        for record in data["results"]:
            self.assertTrue(record["for_sell"])

    def test_17_for_sell_false_returns_only_rent_listings(self):
        """for_sell=false must only return properties with for_sell=False."""
        resp = self._call_list(query_params={"for_sell": "false", "is_active": "true"})
        data = self.assertSuccessResponse(resp)
        for record in data["results"]:
            self.assertFalse(record["for_sell"])

    # ------------------------------------------------------------------
    # Exact field filters
    # ------------------------------------------------------------------

    def test_18_city_filter_exact_match(self):
        """city filter must match exact city name only."""
        resp = self._call_list(query_params={"city": "Mumbai", "is_active": "true"})
        data = self.assertSuccessResponse(resp)
        for record in data["results"]:
            self.assertEqual(record["city"], "Mumbai")

    def test_19_city_filter_excludes_non_matching(self):
        """city=Mumbai must not include Pune records."""
        resp = self._call_list(query_params={"city": "Mumbai", "is_active": "true"})
        data = self.assertSuccessResponse(resp)
        ids_set = {r["id"] for r in data["results"]}
        for prop in self.inactive_props:  # inactive Pune records
            self.assertNotIn(prop.id, ids_set)

    def test_20_state_filter_exact_match(self):
        """state filter must return only properties with that exact state."""
        target_state = self.active_props[0].state
        resp = self._call_list(query_params={"state": target_state})
        data = self.assertSuccessResponse(resp)
        for record in data["results"]:
            self.assertEqual(record["state"], target_state)

    def test_21_prop_type_filter(self):
        """prop_type=Commercial must only return Commercial properties."""
        resp = self._call_list(query_params={"prop_type": "Commercial"})
        data = self.assertSuccessResponse(resp)
        for record in data["results"]:
            self.assertEqual(record["prop_type"], "Commercial")

    def test_22_prop_id_filter_single_result(self):
        """prop_id filter (exact) must return exactly one matching property."""
        target = self.active_props[0]
        resp = self._call_list(query_params={"prop_id": target.prop_id})
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["results"][0]["id"], target.id)

    def test_23_form_no_filter(self):
        """form_no filter must return only the property with that form number."""
        target = self.active_props[0]
        resp = self._call_list(query_params={"form_no": target.form_no})
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["results"][0]["form_no"], target.form_no)

    # ------------------------------------------------------------------
    # owner_phone LIKE filter
    # ------------------------------------------------------------------

    def test_24_owner_phone_like_exact_number(self):
        """owner_phone filter must match a property with that exact number."""
        target = self.active_props[0]
        resp = self._call_list(query_params={"owner_phone": target.owner_phone})
        data = self.assertSuccessResponse(resp)
        ids = [r["id"] for r in data["results"]]
        self.assertIn(target.id, ids)

    def test_25_owner_phone_like_partial_in_combined_field(self):
        """owner_phone filter must match a property where the number is one of several in the field."""
        # Create a property with two phone numbers in the field
        first_num = "9111111111"
        second_num = "9222222222"
        combined = f"{first_num} {second_num}"
        prop = self.make_property(owner_phone=combined, is_active=True)
        # Filtering by just the second number should still find this property
        resp = self._call_list(query_params={"owner_phone": second_num})
        data = self.assertSuccessResponse(resp)
        ids = [r["id"] for r in data["results"]]
        self.assertIn(prop.id, ids)

    # ------------------------------------------------------------------
    # 'search' ilike filter
    # ------------------------------------------------------------------

    def test_26_search_ilike_finds_matching_name(self):
        """search= filter must return properties whose name contains the term (case-insensitive)."""
        unique_suffix = "UniqueTestNameXYZ987"
        prop = self.make_property(name=f"Premium Plot {unique_suffix}", is_active=True)
        resp = self._call_list(query_params={"search": unique_suffix.lower()})
        data = self.assertSuccessResponse(resp)
        ids = [r["id"] for r in data["results"]]
        self.assertIn(prop.id, ids)

    def test_27_search_ilike_excludes_non_matches(self):
        """search= filter must not return properties that don't match the term."""
        resp = self._call_list(
            query_params={"search": "ZZZNOMATCHZZZSPECIALTERM"},
        )
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["total"], 0)

    # ------------------------------------------------------------------
    # Multiple filters (AND)
    # ------------------------------------------------------------------

    def test_28_multiple_filters_combined_as_and(self):
        """city + for_sell filters must both apply (AND logic)."""
        resp = self._call_list(
            query_params={"city": "Mumbai", "for_sell": "true", "is_active": "true"},
        )
        data = self.assertSuccessResponse(resp)
        for record in data["results"]:
            self.assertEqual(record["city"], "Mumbai")
            self.assertTrue(record["for_sell"])

    def test_29_combined_filters_exclude_non_matching(self):
        """Filters combined must not include records that only match one criterion."""
        resp = self._call_list(
            query_params={"city": "Pune", "for_sell": "true"},
        )
        data = self.assertSuccessResponse(resp)
        # self.inactive_props are in Pune with for_sell=False → should not appear
        ids = [r["id"] for r in data["results"]]
        for prop in self.inactive_props:
            self.assertNotIn(prop.id, ids)

    # ------------------------------------------------------------------
    # Empty results
    # ------------------------------------------------------------------

    def test_30_no_match_returns_zero_total(self):
        """A domain that matches nothing must return total=0 and empty results."""
        resp = self._call_list(query_params={"city": "ZZZNOCITYMATCH"})
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["results"], [])

    def test_31_no_match_pages_is_zero(self):
        """When total=0 the pages count should be 0."""
        resp = self._call_list(query_params={"city": "ZZZNOCITYMATCH"})
        data = self.assertSuccessResponse(resp)
        self.assertEqual(data["pages"], 0)

    # ------------------------------------------------------------------
    # Result serialisation sanity check
    # ------------------------------------------------------------------

    def test_32_each_result_has_id_and_name(self):
        """Every result in the list must include at minimum 'id' and 'name'."""
        resp = self._call_list(query_params={"page_size": "5", "is_active": "true"})
        data = self.assertSuccessResponse(resp)
        for record in data["results"]:
            self.assertIn("id", record)
            self.assertIn("name", record)

    def test_33_pages_calculation_is_ceiling_division(self):
        """pages = ceil(total / page_size) — verified with page_size=3 and known total."""
        resp = self._call_list(
            query_params={"is_active": "true", "page_size": "3"},
        )
        data = self.assertSuccessResponse(resp)
        expected_pages = math.ceil(data["total"] / 3)
        self.assertEqual(data["pages"], expected_pages)
