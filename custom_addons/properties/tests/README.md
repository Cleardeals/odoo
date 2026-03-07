# Properties Module — Test Suite Documentation

> **Module**: `properties` (Odoo 19.0)
> **Author**: Cleardeals Tech
> **Total Tests**: 186 across 11 test files and 16 test classes
> **Framework**: Odoo `TransactionCase` (each test runs in a rolled-back transaction)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Test Infrastructure](#2-test-infrastructure)
3. [Running the Tests](#3-running-the-tests)
4. [Test Files](#4-test-files)
   - [test_property_api_auth.py](#41-test_property_api_authpy--15-tests)
   - [test_property_api_list.py](#42-test_property_api_listpy--33-tests)
   - [test_property_api_get.py](#43-test_property_api_getpy--25-tests)
   - [test_property_api_create.py](#44-test_property_api_createpy--25-tests)
   - [test_property_api_update.py](#45-test_property_api_updatepy--25-tests)
   - [test_property_api_delete.py](#46-test_property_api_deletepy--20-tests)
   - [test_property_base_computed.py](#47-test_property_base_computedpy--42-tests)
   - [test_property_base_crud.py](#48-test_property_base_crudpy--21-tests)
   - [test_property_base_dates.py](#49-test_property_base_datespy--15-tests)
   - [test_property_base_write.py](#410-test_property_base_writepy--12-tests)
   - [test_property_base_cron.py](#411-test_property_base_cronpy--11-tests)
5. [Test Coverage Summary](#5-test-coverage-summary)
6. [Design Decisions](#6-design-decisions)

---

## 1. Overview

The `properties` module test suite provides comprehensive coverage for the `property.base` Odoo model and its associated REST API controllers. Tests are split into two layers:

| Layer | Prefix | What it tests |
|---|---|---|
| **Model layer** | `test_property_base_*` | ORM operations, computed fields, write overrides, cron jobs |
| **API layer** | `test_property_api_*` | HTTP controller logic, authentication, serialisation, error handling |

All API tests call controller methods **directly** without spinning up a real HTTP server, using `unittest.mock.patch` to substitute the live `odoo.http.request` object with a controlled `MagicMock`. This gives fast, deterministic tests while exercising the full controller code path.

---

## 2. Test Infrastructure

### `test_property_common.py`

Shared base classes used by every test file. No test cases live here directly.

#### `PropertyBaseTestCase(TransactionCase)`

Base for all model-level tests. Provides:

| Attribute | Description |
|---|---|
| `cls.rm_user` | Primary Relationship Manager (`res.users`) created once per class |
| `cls.rm_user2` | Secondary RM for reassignment tests |
| `cls.suffix` | Millisecond-precision timestamp string — prevents uniqueness-constraint collisions across parallel runs |

**`make_property(**kwargs)`** — Class-level factory method. Creates a `property.base` record with production-representative defaults. Every call auto-increments an internal counter so `uuid` and `prop_id` are always unique. Any field can be overridden by passing it as a keyword argument.

Default values applied by the factory:

| Field | Default |
|---|---|
| `name` | `"Test Property <uid>"` |
| `uuid` | `"uuid-<uid>"` |
| `prop_id` | `"TP<last-6-digits>"` |
| `prop_type` | `"Residential"` |
| `prop_sub_type` | `"Apartment"` |
| `for_sell` | `True` |
| `city` | `"Mumbai"` |
| `state` | `"Maharashtra"` |
| `pricing` | `45.0` |
| `pricing_unit` | `"lakh"` |
| `bedroom_count` | `2` |
| `is_active` | `True` |
| `service_expiry_date` | `today + 30 days` |
| `rm_user_id` | `cls.rm_user` |

#### `PropertyApiTestCase(PropertyBaseTestCase)`

Extends the base with helpers for API controller tests.

**API key helpers:**

| Method | Description |
|---|---|
| `set_api_key(key)` | Overwrites `ir.config_parameter` key `properties.api_key` |
| `clear_api_key()` | Removes the system parameter entirely (simulates unconfigured server) |

**`make_mock_request(**kwargs)`** — Builds a `MagicMock` that satisfies every attribute the controllers access on `odoo.http.request`. Parameters:

| Parameter | Default | Description |
|---|---|---|
| `api_key` | `"test-api-key-abc123"` | Value placed in `X-API-Key` header. Pass `""` to simulate absent header. |
| `method` | `"GET"` | HTTP verb (informational) |
| `content_type` | `"application/json"` | Value for `Content-Type` header |
| `body` | `None` | Dict serialised as JSON request body |
| `query_params` | `None` | Dict for `request.httprequest.args` |

**Assertion helpers** (defined in `PropertyApiTestCase`):

| Method | Description |
|---|---|
| `assertSuccessResponse(resp, expected_status=200)` | Asserts `resp.status_code == expected_status` and returns the decoded `data` dict from `{"success": true, "data": {...}}` |
| `assertErrorResponse(resp, expected_status)` | Asserts status code and `"success": false` in body |

---

## 3. Running the Tests

Run the full properties test suite with:

```powershell
python odoo-bin -r odoo -w odoo \
  --addons-path=addons,custom_addons,hrms_addons \
  -d odoo_19_db \
  --test-enable \
  --test-tags=properties \
  -u properties \
  --stop-after-init
```

All test classes are tagged `@tagged("post_install", "-at_install")`, so they run after module installation is complete.

---

## 4. Test Files

---

### 4.1 `test_property_api_auth.py` — 15 Tests

**Class**: `TestPropertyApiAuth`
**Subject**: `controllers/auth.py` → `validate_api_key(request)`

The authentication gateway called by every API controller before any database access. Tests verify that the function correctly distinguishes between valid, missing, wrong, and unconfigured keys using constant-time comparison.

| # | Test Name | Description |
|---|---|---|
| 01 | `test_01_valid_key_returns_true_none` | Correct `X-API-Key` returns `(True, None)` |
| 02 | `test_02_missing_header_returns_401` | Absent header returns `(False, 401 Response)` |
| 03 | `test_03_missing_header_body_has_expected_message` | 401 body mentions `"X-API-Key"` in the error message |
| 04 | `test_04_wrong_key_returns_403` | Wrong key returns `(False, 403 Response)` |
| 05 | `test_05_key_with_leading_space_rejected` | Key with a leading space is rejected (no implicit stripping) |
| 06 | `test_06_key_with_trailing_space_rejected` | Key with a trailing space is rejected |
| 07 | `test_07_key_wrong_by_one_char_rejected` | Key differing by a single character returns 403; acts as a proxy test for constant-time comparison |
| 08 | `test_08_empty_string_key_rejected` | Header present but value is `""` — treated as absent → 401 |
| 09 | `test_09_wrong_key_body_mentions_message` | 403 body is `{success: false, error: {message: ...}}` |
| 10 | `test_10_unconfigured_system_param_returns_503` | Missing `ir.config_parameter` returns 503 Service Unavailable |
| 11 | `test_11_unconfigured_system_param_body_is_correct` | 503 body has `{error: {status: 503}, success: false}` |
| 12 | `test_12_error_responses_are_json` | All error responses have `Content-Type: application/json` |
| 13 | `test_13_error_response_has_standard_envelope` | Every error body conforms to `{success, error: {status, message}}` |
| 14 | `test_14_accepts_newly_rotated_key` | After rotating the API key, the new key is accepted |
| 15 | `test_15_old_key_rejected_after_rotation` | After key rotation, the old key is rejected |

---

### 4.2 `test_property_api_list.py` — 33 Tests

**Class**: `TestPropertyApiList`
**Subject**: `GET /api/v1/properties` — paginated property list

**Fixture data** created in `setUpClass`:
- 10 active properties — `city=Mumbai`, `for_sell=True`, `is_active=True`
- 3 inactive properties — `city=Pune`, `for_sell=False`, `is_active=False`
- 2 rental properties — `city=Mumbai`, `for_sell=False`, `is_active=True`

#### Authentication (2 tests)

| # | Test Name | Description |
|---|---|---|
| 01 | `test_01_unauthenticated_request_rejected` | Wrong API key returns 403 |
| 02 | `test_02_missing_api_key_returns_401` | Absent header returns 401 |

#### Response Envelope (3 tests)

| # | Test Name | Description |
|---|---|---|
| 03 | `test_03_default_pagination_metadata` | Default response has `page=1`, `page_size=20` |
| 04 | `test_04_response_has_all_required_keys` | Envelope contains `total`, `page`, `page_size`, `pages`, `results` |
| 05 | `test_05_results_is_a_list` | `results` field is a JSON array |

#### Pagination (6 tests)

| # | Test Name | Description |
|---|---|---|
| 06 | `test_06_page_size_limits_results` | `page_size=2` returns at most 2 records |
| 07 | `test_07_page_two_returns_next_records` | Page 1 and page 2 result sets are disjoint |
| 08 | `test_08_page_size_capped_at_200` | `page_size=9999` is silently capped at 200 |
| 09 | `test_09_page_beyond_last_page_returns_empty_results` | Page past the end returns `results=[]`, not an error |
| 10 | `test_10_invalid_page_returns_400` | Non-integer `page` parameter returns 400 |
| 11 | `test_11_invalid_page_size_returns_400` | Non-integer `page_size` parameter returns 400 |

#### `is_active` Filter (4 tests)

| # | Test Name | Description |
|---|---|---|
| 12 | `test_12_is_active_true_returns_only_active` | `is_active=true` includes only active records |
| 13 | `test_13_is_active_false_returns_only_inactive` | `is_active=false` includes only inactive records |
| 14 | `test_14_is_active_zero_treated_as_false` | `is_active=0` is equivalent to `is_active=false` |
| 15 | `test_15_is_active_no_treated_as_false` | `is_active=no` is treated as falsy |

#### `for_sell` Filter (2 tests)

| # | Test Name | Description |
|---|---|---|
| 16 | `test_16_for_sell_true_returns_only_sell_listings` | `for_sell=true` returns only sale properties |
| 17 | `test_17_for_sell_false_returns_only_rent_listings` | `for_sell=false` returns only rental properties |

#### Exact Field Filters (6 tests)

| # | Test Name | Description |
|---|---|---|
| 18 | `test_18_city_filter_exact_match` | `city=Mumbai` returns only Mumbai records |
| 19 | `test_19_city_filter_excludes_non_matching` | `city=Mumbai` does not include Pune records |
| 20 | `test_20_state_filter_exact_match` | `state` filter performs exact match |
| 21 | `test_21_prop_type_filter` | `prop_type=Commercial` returns only commercial properties |
| 22 | `test_22_prop_id_filter_single_result` | `prop_id` (exact) returns exactly one record |
| 23 | `test_23_form_no_filter` | `form_no` filter returns only the matching property |

#### `owner_phone` LIKE Filter (2 tests)

| # | Test Name | Description |
|---|---|---|
| 24 | `test_24_owner_phone_like_exact_number` | Exact number matches the property |
| 25 | `test_25_owner_phone_like_partial_in_combined_field` | Partial match within a space-separated multi-number field |

#### `search` ilike Filter (2 tests)

| # | Test Name | Description |
|---|---|---|
| 26 | `test_26_search_ilike_finds_matching_name` | `search=` term matches name case-insensitively |
| 27 | `test_27_search_ilike_excludes_non_matches` | Unmatched term returns `total=0` |

#### Multiple Combined Filters (2 tests)

| # | Test Name | Description |
|---|---|---|
| 28 | `test_28_multiple_filters_combined_as_and` | Two filters apply simultaneously (AND logic) |
| 29 | `test_29_combined_filters_exclude_non_matching` | Records matching only one of two filters are excluded |

#### Empty Results (2 tests)

| # | Test Name | Description |
|---|---|---|
| 30 | `test_30_no_match_returns_zero_total` | Unmatched domain returns `total=0`, `results=[]` |
| 31 | `test_31_no_match_pages_is_zero` | When `total=0`, `pages` is also `0` |

#### Serialisation Sanity (2 tests)

| # | Test Name | Description |
|---|---|---|
| 32 | `test_32_each_result_has_id_and_name` | Every result object contains at minimum `id` and `name` |
| 33 | `test_33_pages_calculated_correctly` | `pages` equals `ceil(total / page_size)` |

---

### 4.3 `test_property_api_get.py` — 25 Tests

Covers two classes in one file.

#### Class: `TestPropertyApiGet` (19 tests)

**Subject**: `GET /api/v1/properties/<identifier>` — single record lookup

**Fixture**: One property with `uuid="get-test-uuid-001"`, `prop_id="GETPROP001"`, `owner_phone="9876543210"`.

The controller resolves `<identifier>` through a priority chain: integer id → uuid → prop_id → owner_phone (LIKE).

| # | Test Name | Description |
|---|---|---|
| 01 | `test_01_unauthenticated_returns_403` | Wrong key → 403 |
| 02 | `test_02_missing_api_key_returns_401` | Absent header → 401 |
| 03 | `test_03_lookup_by_integer_id` | Digit string matching Odoo id returns the record |
| 04 | `test_04_integer_id_response_has_name` | Record retrieved by id contains correct `name` |
| 05 | `test_05_nonexistent_integer_id_returns_404` | Non-existent integer id → 404 after all strategies exhausted |
| 06 | `test_06_lookup_by_uuid` | Identifier matching `uuid` returns the record |
| 07 | `test_07_lookup_by_uuid_case_sensitive` | UUID lookup is exact/case-sensitive; wrong case → 404 |
| 08 | `test_08_lookup_by_prop_id` | Identifier matching `prop_id` returns the record |
| 09 | `test_09_prop_id_nonexistent_returns_404` | Non-existent `prop_id` → 404 |
| 10 | `test_10_lookup_by_exact_owner_phone` | Digit string matching `owner_phone` returns the record |
| 11 | `test_11_lookup_by_phone_substring_in_combined_field` | Phone lookup works when the number is one of N space-separated numbers |
| 12 | `test_12_phone_lookup_nonexistent_returns_404` | Digit string matching no phone → 404 |
| 13 | `test_13_integer_id_takes_priority_over_uuid` | When identifier is a digit, Odoo id is tried before uuid |
| 14 | `test_14_uuid_takes_priority_over_prop_id` | When uuid matches, a coincidental prop_id match on another record is ignored |
| 15 | `test_15_identifier_leading_trailing_whitespace_trimmed` | Controller strips whitespace from `<identifier>` |
| 16 | `test_16_random_string_identifier_returns_404` | Random string matching nothing → 404 |
| 17 | `test_17_404_error_body_includes_identifier_in_message` | 404 message echoes back the identifier that was not found |
| 18 | `test_18_response_includes_core_fields` | Success response contains `id`, `name`, `uuid`, `prop_id`, `city`, `state`, `is_active` |
| 19 | `test_19_response_is_json_content_type` | Response has `Content-Type: application/json` |

#### Class: `TestResolveIdentifier` (6 tests)

**Subject**: `_resolve_identifier(env, identifier)` — module-level resolver function tested in isolation

| # | Test Name | Description |
|---|---|---|
| 20 | `test_20_resolves_by_integer_id` | Returns record when passed its integer id as a string |
| 21 | `test_21_resolves_by_uuid` | Returns record by uuid |
| 22 | `test_22_resolves_by_prop_id` | Returns record by prop_id |
| 23 | `test_23_resolves_by_owner_phone` | Returns record by owner_phone |
| 24 | `test_24_returns_empty_recordset_for_unknown` | Returns falsy empty recordset for unknown identifier |
| 25 | `test_25_nonexistent_integer_id_falls_through_to_empty` | Nonexistent integer id falls through all strategies → empty |

---

### 4.4 `test_property_api_create.py` — 25 Tests

**Class**: `TestPropertyApiCreate`
**Subject**: `PUT /api/v1/properties` — property creation endpoint
**Expected success status**: `201 Created`

| # | Test Name | Description |
|---|---|---|
| 01 | `test_01_wrong_api_key_returns_403` | Bad key → 403 |
| 02 | `test_02_missing_api_key_returns_401` | Absent header → 401 |
| 03 | `test_03_wrong_content_type_returns_415` | `application/x-www-form-urlencoded` → 415 Unsupported Media Type |
| 04 | `test_04_missing_content_type_returns_415` | Empty Content-Type → 415 |
| 05 | `test_05_malformed_json_returns_400` | Body that is not valid JSON → 400 |
| 06 | `test_06_empty_body_bytes_returns_400` | Completely empty body → 400 |
| 07 | `test_07_missing_name_returns_422` | Payload without `name` → 422 Unprocessable Entity |
| 08 | `test_08_null_name_returns_422` | Explicit `null` for `name` → 422 |
| 09 | `test_09_empty_string_name_returns_422` | Empty string for `name` → 422 |
| 10 | `test_10_create_with_name_only_returns_201` | Payload with only `name` creates a record and returns 201 |
| 11 | `test_11_created_record_exists_in_db` | Record is persisted in the database after successful creation |
| 12 | `test_12_response_status_is_201` | HTTP status code is 201 on success |
| 13 | `test_13_all_scalar_fields_accepted_and_stored` | All scalar allowed-create fields are persisted correctly |
| 14 | `test_14_rm_user_id_accepted_as_integer_fk` | `rm_user_id` as integer FK is accepted and linked |
| 15 | `test_15_boolean_fields_accepted` | `for_sell` and `is_active` booleans round-trip correctly |
| 16 | `test_16_date_fields_accepted_as_iso_strings` | ISO date strings for `service_expiry_date` / `welcome_call_date` are stored |
| 17 | `test_17_portal_id_fields_accepted` | Portal ID fields (`ninety_nine_acres_id`, `housing_id`, `magicbricks_id`, `olx_id`) are stored |
| 18 | `test_18_unknown_fields_ignored_and_reported` | Fields not in the allow-list do not cause errors; appear in `_ignored_fields` |
| 19 | `test_19_valid_and_unknown_fields_mixed` | Mix of valid and unknown: valid ones saved, unknown ones reported |
| 20 | `test_20_payload_with_only_unknown_fields_returns_422` | Payload whose every field is unknown → 422 |
| 21 | `test_21_duplicate_uuid_returns_500` | Second record with an existing `uuid` → 500 (DB constraint) |
| 22 | `test_22_duplicate_prop_id_returns_500` | Second record with an existing `prop_id` → 500 (DB constraint) |
| 23 | `test_23_response_includes_id` | Response contains `id` as a positive integer |
| 24 | `test_24_response_body_round_trips_uuid` | UUID supplied in payload appears in the success response |
| 25 | `test_25_response_is_json_content_type` | Response has `Content-Type: application/json` |

---

### 4.5 `test_property_api_update.py` — 25 Tests

**Class**: `TestPropertyApiUpdate`
**Subject**: `PATCH /api/v1/properties/<identifier>` — partial update endpoint
**Expected success status**: `200 OK`

| # | Test Name | Description |
|---|---|---|
| 01 | `test_01_wrong_api_key_returns_403` | Bad key → 403 |
| 02 | `test_02_missing_api_key_returns_401` | Absent header → 401 |
| 03 | `test_03_unknown_identifier_returns_404` | Identifier matching no record → 404 |
| 04 | `test_04_wrong_content_type_returns_415` | Non-JSON Content-Type → 415 |
| 05 | `test_05_malformed_json_returns_400` | Invalid JSON body → 400 |
| 06 | `test_06_empty_json_object_returns_422` | Empty `{}` payload → 422 |
| 07 | `test_07_payload_with_only_unknown_fields_returns_422` | Only unknown keys → 422 |
| 08 | `test_08_update_city` | PATCH `city` persists the new city value |
| 09 | `test_09_update_name` | PATCH `name` updates the property name |
| 10 | `test_10_update_pricing_and_unit` | PATCH `pricing` and `pricing_unit` updates both atomically |
| 11 | `test_11_update_for_sell_toggle` | PATCH toggles `for_sell` from `True` to `False` |
| 12 | `test_12_future_service_expiry_sets_is_active_true` | PATCH with future `service_expiry_date` auto-sets `is_active=True` via `write()` override |
| 13 | `test_13_past_service_expiry_sets_is_active_false` | PATCH with past `service_expiry_date` auto-sets `is_active=False` |
| 14 | `test_14_explicit_is_active_true_overrides_past_expiry_autosync` | Explicit `is_active=True` in payload wins over auto-sync even with past expiry |
| 15 | `test_15_explicit_is_active_false_overrides_future_expiry_autosync` | Explicit `is_active=False` wins over auto-sync even with future expiry |
| 16 | `test_16_rm_user_id_reassigned` | PATCH `rm_user_id` reassigns the RM; response contains `rm_user.id` |
| 17 | `test_17_unknown_fields_ignored_and_reported` | Unknown fields do not raise errors; appear in `_ignored_fields` |
| 18 | `test_18_unknown_fields_do_not_affect_valid_field_update` | Valid fields update even when unknown fields are present |
| 19 | `test_19_update_by_uuid_resolves_correctly` | PATCH using `uuid` as identifier updates the correct record |
| 20 | `test_20_update_by_prop_id_resolves_correctly` | PATCH using `prop_id` as identifier updates the correct record |
| 21 | `test_21_update_by_owner_phone_resolves_correctly` | PATCH using `owner_phone` as identifier updates the correct record |
| 22 | `test_22_omitted_fields_retain_original_values` | Fields not in the PATCH payload keep their original values |
| 23 | `test_23_response_returns_200` | Successful update returns HTTP 200 |
| 24 | `test_24_response_has_correct_content_type` | Response has `Content-Type: application/json` |
| 25 | `test_25_response_body_is_updated_record` | Response body immediately reflects the new state, not stale data |

---

### 4.6 `test_property_api_delete.py` — 20 Tests

**Class**: `TestPropertyApiDelete`
**Subject**: `DELETE /api/v1/properties/<identifier>` — hard-delete endpoint
**Expected success status**: `200 OK`

Each delete test creates a fresh property record via `make_property()` so tests are completely independent of one another.

#### Authentication (2 tests)

| # | Test Name | Description |
|---|---|---|
| 01 | `test_01_wrong_api_key_returns_403` | Wrong key → 403; record is not deleted |
| 02 | `test_02_missing_api_key_returns_401` | Absent header → 401; record is not deleted |

#### 404 — Identifier Not Found (2 tests)

| # | Test Name | Description |
|---|---|---|
| 03 | `test_03_unknown_identifier_returns_404` | String matching no record → 404 |
| 04 | `test_04_nonexistent_integer_id_returns_404` | Large digit string that is not a real id → 404 |

#### Delete by Integer id (3 tests)

| # | Test Name | Description |
|---|---|---|
| 05 | `test_05_delete_by_integer_id_returns_200` | Successful delete by id returns 200 |
| 06 | `test_06_delete_by_integer_id_removes_record` | After delete, `search()` returns empty for the former id |
| 07 | `test_07_delete_by_integer_id_browse_returns_empty` | After delete, `browse().exists()` returns `False` |

#### Delete by UUID (2 tests)

| # | Test Name | Description |
|---|---|---|
| 08 | `test_08_delete_by_uuid_removes_record` | Deleting by `uuid` permanently removes the record |
| 09 | `test_09_delete_by_uuid_response_has_correct_ids` | Response body `deleted` object contains the correct `id` and `uuid` (captured before deletion) |

#### Delete by prop_id (2 tests)

| # | Test Name | Description |
|---|---|---|
| 10 | `test_10_delete_by_prop_id_removes_record` | Deleting by `prop_id` permanently removes the record |
| 11 | `test_11_delete_by_prop_id_response_shows_prop_id` | Response body `deleted.prop_id` matches the deleted property's prop_id (captured before deletion) |

#### Delete by owner_phone (2 tests)

| # | Test Name | Description |
|---|---|---|
| 12 | `test_12_delete_by_owner_phone_removes_record` | Deleting by exact `owner_phone` removes the record |
| 13 | `test_13_delete_by_phone_in_combined_field` | Deleting by one number from a space-separated multi-number field works |

#### Response Body Structure (3 tests)

| # | Test Name | Description |
|---|---|---|
| 14 | `test_14_response_body_has_message_key` | Success body includes a `message` key |
| 15 | `test_15_response_body_deleted_has_all_identity_fields` | `deleted` sub-object contains `id`, `uuid`, `prop_id`, and `name` |
| 16 | `test_16_response_body_reflects_deleted_record_name` | `deleted.name` matches the record's actual name |

#### No Side-Effects (1 test)

| # | Test Name | Description |
|---|---|---|
| 17 | `test_17_delete_does_not_affect_unrelated_record` | Deleting one property does not cascade to any other record |

#### Idempotency / Double-Delete (1 test)

| # | Test Name | Description |
|---|---|---|
| 18 | `test_18_second_delete_returns_404` | Second DELETE on the same (now-deleted) identifier returns 404 |

#### Response Metadata (2 tests)

| # | Test Name | Description |
|---|---|---|
| 19 | `test_19_response_status_code_is_200` | HTTP status code is 200 on success |
| 20 | `test_20_response_content_type_is_json` | Response has `Content-Type: application/json` |

---

### 4.7 `test_property_base_computed.py` — 42 Tests

Five test classes covering every computed field on `property.base`.

---

#### Class: `TestBuildPropertyLink` — 10 tests

**Subject**: `build_property_link(name, prop_id)` — module-level helper function
Generates the canonical Cleardeals property URL.

| # | Test Name | Description |
|---|---|---|
| 01 | `test_01_normal_ascii_name` | Standard ASCII name produces the correct URL slug |
| 02 | `test_02_name_with_special_characters` | Parentheses are stripped; dots in the name do not appear in the slug portion |
| 03 | `test_03_name_with_multiple_spaces` | Multiple consecutive spaces collapse to a single hyphen |
| 04 | `test_04_name_with_mixed_case` | Name is lowercased in the slug |
| 05 | `test_05_empty_name_returns_empty` | Empty name produces empty string |
| 06 | `test_06_empty_prop_id_returns_empty` | Empty `prop_id` produces empty string |
| 07 | `test_07_both_empty_returns_empty` | Both empty → empty string |
| 08 | `test_08_name_with_leading_trailing_spaces` | Leading/trailing whitespace stripped before slugification |
| 09 | `test_09_slug_no_leading_trailing_hyphens` | Generated slug does not start or end with a hyphen |
| 10 | `test_10_returns_cleardeals_base_url` | Result starts with `https://www.cleardeals.in/property/` |

---

#### Class: `TestComputePropertyLink` — 5 tests

**Subject**: `property_link` — stored computed field (depends on `name`, `prop_id`)

| # | Test Name | Description |
|---|---|---|
| 01 | `test_01_link_computed_on_create` | `property_link` is populated immediately after `create()` |
| 02 | `test_02_link_updates_when_name_changes` | `property_link` recomputes when `name` is updated via `write()` |
| 03 | `test_03_link_updates_when_prop_id_changes` | `property_link` recomputes when `prop_id` is updated |
| 04 | `test_04_link_empty_when_name_missing` | `property_link` is `""` when `name` is falsy |
| 05 | `test_05_link_empty_when_prop_id_missing` | `property_link` is `""` when `prop_id` is falsy |

---

#### Class: `TestComputeBhk` — 7 tests

**Subject**: `bhk` — stored computed field (depends on `bedroom_count`)
Format: `"N BHK"` for N > 0; `""` for N ≤ 0.

| # | Test Name | Description |
|---|---|---|
| 01 | `test_01_one_bedroom` | `bedroom_count=1` → `"1 BHK"` |
| 02 | `test_02_two_bedrooms` | `bedroom_count=2` → `"2 BHK"` |
| 03 | `test_03_three_bedrooms` | `bedroom_count=3` → `"3 BHK"` |
| 04 | `test_04_zero_bedrooms` | `bedroom_count=0` → `""` (commercial / studio) |
| 05 | `test_05_negative_bedroom_count` | Negative count → `""` |
| 06 | `test_06_bhk_recomputes_on_write` | `bhk` updates immediately when `bedroom_count` changes via `write()` |
| 07 | `test_07_large_bedroom_count` | `bedroom_count=10` → `"10 BHK"` |

---

#### Class: `TestComputeDisplayFields` — 15 tests

**Subject**: `_compute_display_fields` — non-stored batch compute (updates `prop_type_display`, `listing_type`, `pricing_display`, `is_new`)

**`prop_type_display`** (3 tests)

| # | Test Name | Description |
|---|---|---|
| 01 | `test_01_prop_type_display_capitalised` | Lowercase `prop_type` is title-cased |
| 02 | `test_02_prop_type_display_already_capitalised` | Already-capitalised value passes through unchanged |
| 03 | `test_03_prop_type_display_empty_when_type_falsy` | Falsy `prop_type` → `""` |

**`listing_type`** (2 tests)

| # | Test Name | Description |
|---|---|---|
| 04 | `test_04_listing_type_sell_when_for_sell_true` | `for_sell=True` → `"Sell"` |
| 05 | `test_05_listing_type_rent_when_for_sell_false` | `for_sell=False` → `"Rent"` |

**`pricing_display`** (5 tests)

| # | Test Name | Description |
|---|---|---|
| 06 | `test_06_pricing_display_with_unit_sell` | `48 lakh` sale → `"48 Lakh"` |
| 07 | `test_07_pricing_display_with_unit_rent` | `15 thousand` rental → `"15 Thousand/month"` |
| 08 | `test_08_pricing_display_without_unit` | No `pricing_unit` → displays the raw number |
| 09 | `test_09_pricing_display_empty_when_no_pricing` | `pricing=0.0` → `""` |
| 10 | `test_10_pricing_display_strips_trailing_decimals` | `48.0` displays as `"48"`, not `"48.0"` (`:g` format) |

**`is_new`** (5 tests)

| # | Test Name | Description |
|---|---|---|
| 11 | `test_11_is_new_true_when_reg_date_today` | `reg_date=today` → `is_new=True` |
| 12 | `test_12_is_new_true_when_reg_date_2_days_ago` | `reg_date` 2 days ago → `is_new=True` |
| 13 | `test_13_is_new_false_when_reg_date_4_days_ago` | `reg_date` 4 days ago → `is_new=False` |
| 14 | `test_14_is_new_false_when_reg_date_missing` | Falsy `reg_date` → `is_new=False` |
| 15 | `test_15_is_new_boundary_exactly_3_days_ago` | Exactly 3 days ago is still `is_new=True` (boundary: `>= three_days_ago`) |

---

#### Class: `TestComputeGmapsEmbedHtml` — 5 tests

**Subject**: `gmaps_embed_html` — non-stored computed HTML field (depends on `gmaps_url`)

| # | Test Name | Description |
|---|---|---|
| 01 | `test_01_iframe_generated_when_url_present` | When `gmaps_url` is set, output contains `<iframe>` with the URL embedded |
| 02 | `test_02_fallback_paragraph_when_url_missing` | When `gmaps_url` is falsy, output contains "No Google Maps URL" message |
| 03 | `test_03_iframe_sets_full_width` | `<iframe>` has `width="100%"` |
| 04 | `test_04_iframe_has_allowfullscreen` | `<iframe>` has `allowfullscreen` attribute |
| 05 | `test_05_html_recomputes_when_url_changes` | Field recomputes when `gmaps_url` changes via `write()` |

---

### 4.8 `test_property_base_crud.py` — 21 Tests

**Class**: `TestPropertyBaseCRUD`
**Subject**: Core ORM operations on `property.base`

#### Creation (6 tests)

| # | Test Name | Description |
|---|---|---|
| 01 | `test_01_create_with_minimum_fields` | Record created with only `name` gets a database id |
| 02 | `test_02_create_with_all_api_sourced_fields` | All API-sourced fields (PROP-2.1) are stored verbatim |
| 03 | `test_03_create_with_manager_editable_fields` | Portal ID and tag fields (PROP-2.3/2.4) are stored correctly |
| 04 | `test_04_create_assigns_rm_user` | Many2one `rm_user_id` is correctly linked |
| 05 | `test_05_default_is_active_true` | Default value for `is_active` is `True` |
| 06 | `test_06_default_inventory_migrated_false` | Default value for `inventory_migrated` is `False` |

#### Unique Constraints (4 tests)

| # | Test Name | Description |
|---|---|---|
| 07 | `test_07_uuid_unique_constraint` | Duplicate `uuid` raises `psycopg2.IntegrityError` |
| 08 | `test_08_prop_id_unique_constraint` | Duplicate `prop_id` raises `psycopg2.IntegrityError` |
| 09 | `test_09_null_uuid_does_not_violate_unique_constraint` | Multiple records with `uuid=False` are allowed |
| 10 | `test_10_null_prop_id_does_not_violate_unique_constraint` | Multiple records with `prop_id=False` are allowed |

#### Search & Filter (6 tests)

| # | Test Name | Description |
|---|---|---|
| 11 | `test_11_search_by_city` | Domain filter on `city` returns only matching records |
| 12 | `test_12_search_by_is_active` | `is_active` filter correctly partitions active and inactive records |
| 13 | `test_13_search_by_for_sell` | `for_sell` filter distinguishes sale from rental |
| 14 | `test_14_search_name_ilike` | Case-insensitive partial `name` search returns matches |
| 15 | `test_15_default_ordering_reg_date_desc` | Default order is `reg_date` descending, then `id` descending |
| 16 | `test_16_search_count_matches_search` | `search_count()` cardinality matches `len(search())` |

#### Update (3 tests)

| # | Test Name | Description |
|---|---|---|
| 17 | `test_17_write_single_field` | `write()` updates one field without touching others |
| 18 | `test_18_write_multiple_fields` | `write()` updates multiple fields atomically |
| 19 | `test_19_write_rm_reassignment` | `rm_user_id` reassignment via `write()` updates the relation |

#### Delete (2 tests)

| # | Test Name | Description |
|---|---|---|
| 20 | `test_20_unlink_removes_record` | `unlink()` permanently removes the record |
| 21 | `test_21_unlink_does_not_affect_other_records` | Deleting one record does not cascade to unrelated records |

---

### 4.9 `test_property_base_dates.py` — 15 Tests

**Class**: `TestPropertyBaseDates`
**Subject**: Date field storage and `DD/MM/YYYY` display formatting

#### Storage (3 tests)

| # | Test Name | Description |
|---|---|---|
| 01 | `test_01_service_expiry_date_stored_correctly` | `service_expiry_date` stores and retrieves as a Python `date` object |
| 02 | `test_02_welcome_call_date_stored_correctly` | `welcome_call_date` stores and retrieves as a Python `date` object |
| 03 | `test_03_both_date_fields_stored_independently` | Both fields hold different values simultaneously without interference |

#### Display Format (8 tests)

| # | Test Name | Description |
|---|---|---|
| 04 | `test_04_service_expiry_display_format` | Display is `"DD/MM/YYYY"` |
| 05 | `test_05_welcome_call_display_format` | Display is `"DD/MM/YYYY"` |
| 06 | `test_06_display_leading_zeros_day` | Single-digit day is zero-padded (e.g., `03`) |
| 07 | `test_07_display_leading_zeros_month` | Single-digit month is zero-padded (e.g., `02`) |
| 08 | `test_08_display_leading_zeros_both_day_and_month` | Both day and month zero-padded when single-digit |
| 09 | `test_09_display_format_is_slash_separated` | Separator is `/` not `-` or `.` |
| 10 | `test_10_display_order_is_day_month_year` | Order is `DD/MM/YYYY`, not `YYYY/MM/DD` or `MM/DD/YYYY` |

#### Empty / Falsy Dates (2 tests)

| # | Test Name | Description |
|---|---|---|
| 11 | `test_11_empty_service_expiry_display_is_empty_string` | `service_expiry_date=False` displays as `""` |
| 12 | `test_12_empty_welcome_call_display_is_empty_string` | `welcome_call_date=False` displays as `""` |

#### Recomputation (3 tests)

| # | Test Name | Description |
|---|---|---|
| 13 | `test_13_service_expiry_display_recomputes_on_change` | Display field updates when underlying date changes |
| 14 | `test_14_welcome_call_display_recomputes_on_change` | Display field updates when `welcome_call_date` changes |
| 15 | `test_15_display_clears_when_date_set_to_false` | Display becomes `""` when date is cleared to `False` |

---

### 4.10 `test_property_base_write.py` — 12 Tests

**Class**: `TestPropertyBaseWrite`
**Subject**: `write()` override that automatically synchronises `is_active` when `service_expiry_date` changes

#### Future Expiry → Active (2 tests)

| # | Test Name | Description |
|---|---|---|
| 01 | `test_01_future_expiry_activates_record` | Future `service_expiry_date` sets `is_active=True` |
| 02 | `test_02_far_future_expiry_activates_record` | Year 2099 expiry also activates the record |

#### Past Expiry → Inactive (2 tests)

| # | Test Name | Description |
|---|---|---|
| 03 | `test_03_past_expiry_deactivates_record` | Yesterday's expiry sets `is_active=False` |
| 04 | `test_04_older_past_expiry_deactivates_record` | Long-past expiry (e.g., 2020) also deactivates |

#### Boundary (1 test)

| # | Test Name | Description |
|---|---|---|
| 05 | `test_05_today_expiry_keeps_active` | Expiry on today's date is treated as active (`>= today`) |

#### Explicit `is_active` Wins (2 tests)

| # | Test Name | Description |
|---|---|---|
| 06 | `test_06_explicit_is_active_true_overrides_past_expiry` | Caller-supplied `is_active=True` wins over auto-sync even with past expiry |
| 07 | `test_07_explicit_is_active_false_overrides_future_expiry` | Caller-supplied `is_active=False` wins over auto-sync even with future expiry |

#### No Expiry Change → `is_active` Untouched (2 tests)

| # | Test Name | Description |
|---|---|---|
| 08 | `test_08_write_other_field_does_not_change_is_active` | Writing `city` does not change `is_active` |
| 09 | `test_09_write_pricing_does_not_change_is_active` | Writing `pricing` does not change `is_active` |

#### Clearing the Expiry Date (1 test)

| # | Test Name | Description |
|---|---|---|
| 10 | `test_10_clearing_expiry_date_leaves_is_active_unchanged` | Setting `service_expiry_date=False` does not trigger auto-sync |

#### Batch Write (2 tests)

| # | Test Name | Description |
|---|---|---|
| 11 | `test_11_batch_write_with_future_expiry_activates_all` | `write()` on a multi-record recordset activates every record |
| 12 | `test_12_batch_write_with_past_expiry_deactivates_all` | `write()` on a multi-record recordset deactivates every record |

---

### 4.11 `test_property_base_cron.py` — 11 Tests

**Class**: `TestPropertyBaseCron`
**Subject**: `_cron_cleanup_expired_properties()` — nightly scheduled action

The cron marks properties inactive when their `service_expiry_date < today`. Tests use `invalidate_recordset()` after the cron runs to ensure fresh data is read from the database.

#### Core Deactivation (2 tests)

| # | Test Name | Description |
|---|---|---|
| 01 | `test_01_expired_yesterday_becomes_inactive` | Property expiring yesterday is deactivated |
| 02 | `test_02_expired_long_ago_becomes_inactive` | Property expired months/years ago is also deactivated |

#### Active Records Untouched (2 tests)

| # | Test Name | Description |
|---|---|---|
| 03 | `test_03_future_expiry_stays_active` | Future expiry (30 days out) is not touched |
| 04 | `test_04_far_future_expiry_stays_active` | Year 2099 expiry is not touched |

#### Boundary Condition (1 test)

| # | Test Name | Description |
|---|---|---|
| 05 | `test_05_expiry_today_remains_active` | Strict `< today` comparison: expiry on today's date is NOT deactivated |

#### Batch Handling (2 tests)

| # | Test Name | Description |
|---|---|---|
| 06 | `test_06_batch_multiple_expired_all_deactivated` | All 5 records with varying past expiry dates are deactivated in one run |
| 07 | `test_07_mixed_expiry_only_expired_deactivated` | Only expired records are deactivated; active ones remain untouched |

#### Idempotency (2 tests)

| # | Test Name | Description |
|---|---|---|
| 08 | `test_08_already_inactive_not_modified` | Running cron on an already-inactive property is a no-op |
| 09 | `test_09_cron_idempotent_second_run` | Running cron twice produces the same result without raising |

#### Records Without Expiry (1 test)

| # | Test Name | Description |
|---|---|---|
| 10 | `test_10_no_expiry_date_record_not_deactivated` | Properties with no `service_expiry_date` are not affected |

#### Resilience (1 test)

| # | Test Name | Description |
|---|---|---|
| 11 | `test_11_cron_does_not_propagate_internal_errors` | Cron catches internal exceptions and does not let them bubble up (verified via `unittest.mock.patch`) |

---

## 5. Test Coverage Summary

| File | Class(es) | Tests | Areas Covered |
|---|---|---|---|
| `test_property_api_auth.py` | `TestPropertyApiAuth` | 15 | Authentication, key validation, response shape |
| `test_property_api_list.py` | `TestPropertyApiList` | 33 | Pagination, all filters, serialisation |
| `test_property_api_get.py` | `TestPropertyApiGet`, `TestResolveIdentifier` | 25 | Identifier resolution, 404 handling, field serialisation |
| `test_property_api_create.py` | `TestPropertyApiCreate` | 25 | Input validation, field persistence, error codes |
| `test_property_api_update.py` | `TestPropertyApiUpdate` | 25 | Partial updates, auto-sync `is_active`, identifier routing |
| `test_property_api_delete.py` | `TestPropertyApiDelete` | 20 | Hard delete, idempotency, response body |
| `test_property_base_computed.py` | `TestBuildPropertyLink`, `TestComputePropertyLink`, `TestComputeBhk`, `TestComputeDisplayFields`, `TestComputeGmapsEmbedHtml` | 42 | All computed fields |
| `test_property_base_crud.py` | `TestPropertyBaseCRUD` | 21 | ORM CRUD, constraints, search |
| `test_property_base_dates.py` | `TestPropertyBaseDates` | 15 | Date storage, display formatting (`DD/MM/YYYY`) |
| `test_property_base_write.py` | `TestPropertyBaseWrite` | 12 | `write()` override, `is_active` auto-sync |
| `test_property_base_cron.py` | `TestPropertyBaseCron` | 11 | Scheduled action, boundary logic, resilience |
| **Total** | **16 classes** | **186** | |

---

## 6. Design Decisions

### No Real HTTP Server Required
All API tests mock `odoo.http.request` using `unittest.mock.patch`. Controller methods are called directly as Python functions. This avoids the significant overhead of spinning up an HTTP server while still exercising the full request handling pipeline including authentication, JSON parsing, ORM calls, and response serialisation.

### `TransactionCase` Isolation
Each individual test runs inside a database transaction that is automatically rolled back after the test completes. This means:
- Tests are fully isolated from one another.
- `setUpClass` fixture data is created once per class and shared, but individual test writes are rolled back.
- No cleanup code is needed in individual tests.

### Class-Level Fixtures via `setUpClass`
Expensive fixture setup (creating RM users, bulk property records for list tests) is done once in `setUpClass` rather than `setUp`, keeping the test run fast. Factory-created records within individual tests are rolled back automatically.

### `make_property()` Factory Pattern
The shared `make_property()` classmethod in `PropertyBaseTestCase` ensures:
- Every test specifies only the fields relevant to its scenario.
- Auto-incremented counters prevent uniqueness constraint violations across tests within the same class.
- Sensible production-representative defaults mean tests assert on real-world behaviour.

### Identifier Priority Chain (`_resolve_identifier`)
The `<identifier>` path parameter in GET, PATCH, and DELETE endpoints is resolved through a deterministic priority chain:

1. **Integer id** — if the string is all digits, attempt `browse(int(identifier)).exists()`
2. **UUID** — exact match on `uuid` field
3. **prop_id** — exact match on `prop_id` field
4. **owner_phone** — LIKE match within the `owner_phone` field (supports space-separated multi-number values)

This is tested both at the controller level (integration) and at the `_resolve_identifier` unit level, giving confidence from both directions.

### API Key Security
`validate_api_key()` uses `hmac.compare_digest` for constant-time string comparison, preventing timing-based side-channel attacks. The test suite verifies rejection of keys differing by a single character (`test_07`) as a proxy check for this behaviour.
