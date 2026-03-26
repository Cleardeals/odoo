# Properties Module — REST API Documentation

**Version:** 1.1.0
**Base URL:** `https://odoo.cleardeals.xyz/api/v1/properties`
**Data Format:** `application/json` (request and response)
**Authentication:** API Key via HTTP header

---

## Table of Contents

1. [Overview](#1-overview)
2. [Authentication](#2-authentication)
3. [Request & Response Format](#3-request--response-format)
4. [Identifier Resolution](#4-identifier-resolution)
5. [Field Reference](#5-field-reference)
6. [Endpoints](#6-endpoints)
   - [GET /api/v1/properties](#61-get-apiv1properties--list-properties)
   - [GET /api/v1/properties/`<identifier>`](#62-get-apiv1propertiesidentifier--get-single-property)
   - [PUT /api/v1/properties](#63-put-apiv1properties--create-property)
   - [PATCH /api/v1/properties/`<identifier>`](#64-patch-apiv1propertiesidentifier--update-property)
   - [DELETE /api/v1/properties/`<identifier>`](#65-delete-apiv1propertiesidentifier--delete-property)
7. [Error Reference](#7-error-reference)
8. [Setup & Configuration](#8-setup--configuration)
9. [Quick-Reference curl Examples](#9-quick-reference-curl-examples)

---

## 1. Overview

The Properties REST API provides full CRUD access to the `property.base` model — the single source of truth for all Cleardeals property inventory.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/properties` | Paginated, filterable property list |
| `GET` | `/api/v1/properties/<identifier>` | Retrieve a single property |
| `PUT` | `/api/v1/properties` | Create a new property record |
| `PATCH` | `/api/v1/properties/<identifier>` | Partially update a property |
| `DELETE` | `/api/v1/properties/<identifier>` | Permanently delete a property |

All endpoints:
- Require a valid `X-API-Key` header on every request.
- Return `Content-Type: application/json`.
- Follow a consistent `{"success": true/false, "data"/"error": …}` envelope.

---

## 2. Authentication

Authentication is performed via a **static API key** passed as an HTTP request header.

### Header

```
X-API-Key: <your-api-key>
```

### How it works

1. The server reads the expected key from the Odoo system parameter `properties.api_key`.
2. The supplied header value is compared using a **constant-time comparison** (`hmac.compare_digest`) to prevent timing-oracle attacks.
3. If the key is missing or incorrect the request is rejected immediately — no database operation is performed.

### Authentication error responses

| Scenario | HTTP Status | Message |
|----------|-------------|---------|
| `X-API-Key` header absent | `401` | `Missing 'X-API-Key' header.` |
| Key does not match | `403` | `Invalid API key.` |
| System parameter not configured | `503` | `API authentication is not configured on this server.` |

### Configuring the API key

Set the system parameter via **Settings → Technical → System Parameters** or from the Odoo shell:

```python
env['ir.config_parameter'].sudo().set_param('properties.api_key', 'your-secret-key')
env.cr.commit()
```

> **Security note:** Use a long, randomly generated key (minimum 32 characters). Treat it as a password — do not commit it to source control.

---

## 3. Request & Response Format

### Success envelope

```json
{
  "success": true,
  "data": { ... }
}
```

### Error envelope

```json
{
  "success": false,
  "error": {
    "status": 404,
    "message": "No property found for identifier 'XYZ'."
  }
}
```

### Request body (write operations)

All write operations (`PUT`, `PATCH`) must send a JSON object body with the header:

```
Content-Type: application/json
```

Supplying an unrecognised field does **not** cause a validation error — it is silently ignored and the key name is returned in `_ignored_fields` within the response body.

---

## 4. Identifier Resolution

The `<identifier>` path segment used by `GET`, `PATCH`, and `DELETE` is resolved using a **four-strategy waterfall** — the first strategy that returns a match wins:

| Priority | Strategy | Description |
|----------|----------|-------------|
| 1 | **Odoo ID** | If the identifier is a pure integer, it is looked up as the database primary key (`id`). |
| 2 | **UUID** | Matched against the `uuid` field (exact match). |
| 3 | **Short code** | Matched against the `prop_id` field (exact match). |
| 4 | **Owner phone** | If the identifier contains only digits, `+`, `-`, or spaces, a substring search (`LIKE`) is performed against `owner_phone`. This handles records where multiple phone numbers are stored in a single string (e.g. `"9033870424 8735999816"`). |

If no strategy produces a match, the API returns `404`.

---

## 5. Field Reference

### Response object — `property` resource

All endpoints that return a property return the following JSON object shape.

#### Identifiers

| Field | Type | Description |
|-------|------|-------------|
| `id` | `integer` | Odoo database primary key. Stable, auto-assigned. |
| `uuid` | `string \| null` | UUID assigned by the Cleardeals website API. |
| `prop_id` | `string \| null` | 6–8 character alphanumeric short-code (e.g. `GBH75X0K`). |
| `form_no` | `string \| null` | Unique form number from the Cleardeals platform. Cross-model join key. |

#### Core descriptors

| Field | Type | Description |
|-------|------|-------------|
| `name` | `string \| null` | Full marketing name of the property. |
| `reg_date` | `string \| null` | ISO-8601 date (`YYYY-MM-DD`). Date onboarded to the platform. |
| `prop_type` | `string \| null` | Broad classification — e.g. `Residential`, `Commercial`. |
| `prop_sub_type` | `string \| null` | Detailed classification — e.g. `Apartment`, `Villa`, `Office`. |
| `for_sell` | `boolean` | `true` = listed for sale; `false` = listed for rent. |
| `state` | `string \| null` | State where the property is located. |
| `city` | `string \| null` | City where the property is located. |
| `location` | `string \| null` | Micro-location or locality within the city. |

#### Pricing

| Field | Type | Description |
|-------|------|-------------|
| `pricing` | `number \| null` | Numeric price value. |
| `pricing_unit` | `string \| null` | Unit of the price — e.g. `lakh`, `crore`, `thousand`. |
| `pricing_display` | `string \| null` | Human-readable combined string — e.g. `48 Lakh`, `2.5 Crore/month`. Read-only computed field. |

#### Owner information

| Field | Type | Description |
|-------|------|-------------|
| `owner_name` | `string \| null` | Full name of the property owner. |
| `owner_phone` | `string \| null` | Owner contact number(s). May contain multiple numbers separated by spaces. |
| `owner_email` | `string \| null` | Owner email address. |

#### Assignment

| Field | Type | Description |
|-------|------|-------------|
| `rm_user` | `object \| null` | Assigned Relationship Manager. Shape: `{"id": integer, "name": string}`. |

#### Physical attributes

| Field | Type | Description |
|-------|------|-------------|
| `bedroom_count` | `integer \| null` | Number of bedrooms (raw count). |
| `bhk` | `string \| null` | Human-readable label — e.g. `2 BHK`. Computed from `bedroom_count`. Read-only. |

#### Links & media

| Field | Type | Description |
|-------|------|-------------|
| `property_link` | `string \| null` | Canonical Cleardeals URL. Computed from `name` + `prop_id`. Read-only. |
| `gmaps_url` | `string \| null` | Google Maps embed URL. |

#### Portal / listing IDs

| Field | Type | Description |
|-------|------|-------------|
| `property_tag` | `string \| null` | Short display tag used in the lead-suggestor pipeline. |
| `portal_listings` | `array<object>` | Canonical multi-listing structure from `property.portal.listing`. Each item has `id`, `portal_name`, `portal_listing_id`, `listing_label`, `active`. |
| `legacy_portal_ids` | `object` | Backward-visibility only. Contains old fields `ninety_nine_acres_id`, `housing_id`, `magicbricks_id`, `olx_id`. |

#### Dates

| Field | Type | Description |
|-------|------|-------------|
| `service_expiry_date` | `string \| null` | ISO-8601 date. Date when the Cleardeals service contract expires. |
| `welcome_call_date` | `string \| null` | ISO-8601 date. Date of the welcome call with the owner. |

#### Status & system

| Field | Type | Description |
|-------|------|-------------|
| `is_active` | `boolean` | `true` = property is live/active. `false` = deactivated (e.g. post-expiry). |
| `inventory_migrated` | `boolean` | Internal flag. `true` once legacy `property.inventory` data has been migrated into this record. |

#### Computed display helpers (read-only)

| Field | Type | Description |
|-------|------|-------------|
| `listing_type` | `string \| null` | `"Sell"` or `"Rent"`. Derived from `for_sell`. |
| `prop_type_display` | `string \| null` | Capitalised property type label. |
| `is_new` | `boolean` | `true` when `reg_date` is within the last 3 days. |

---

### Writable fields (PUT / PATCH)

The following fields are accepted in request bodies. All fields are optional for `PATCH`; only `name` is required for `PUT`.

| Field | Type | Notes |
|-------|------|-------|
| `name` | `string` | **Required on create.** Property display name. |
| `uuid` | `string` | Must be unique across all records. |
| `prop_id` | `string` | Must be unique across all records. |
| `form_no` | `string` | Cross-model join key. |
| `reg_date` | `string` | ISO-8601 date (`YYYY-MM-DD`). |
| `prop_type` | `string` | e.g. `Residential`, `Commercial`. |
| `prop_sub_type` | `string` | e.g. `Apartment`, `Villa`. |
| `for_sell` | `boolean` | `true` = sale, `false` = rent. |
| `state` | `string` | State name. |
| `city` | `string` | City name. |
| `location` | `string` | Micro-location / area. |
| `pricing` | `number` | Numeric price. |
| `pricing_unit` | `string` | e.g. `lakh`, `crore`. |
| `owner_name` | `string` | Owner full name. |
| `owner_phone` | `string` | Phone number(s). |
| `owner_email` | `string` | Email address. |
| `rm_user_id` | `integer` | Odoo `res.users` database ID of the assigned RM. |
| `bedroom_count` | `integer` | Number of bedrooms. |
| `gmaps_url` | `string` | Google Maps embed URL. |
| `property_tag` | `string` | Short display tag. |
| `portal_listings` | `array<object>` | Canonical relation payload. Replaces legacy single portal-id fields for writes. |
| `service_expiry_date` | `string` | ISO-8601 date. Updates `is_active` automatically. |
| `welcome_call_date` | `string` | ISO-8601 date. |
| `is_active` | `boolean` | Manually override active/inactive status. |

#### portal_listings payload shape

```json
[
  {
    "portal_name": "99acres",
    "portal_listing_id": "T89400543",
    "listing_label": "W36TK04R | 99acres | T89400543",
    "active": true
  },
  {
    "portal_name": "Housing.com",
    "portal_listing_id": "19684263",
    "listing_label": "W36TK04R | Housing.com | 19684263",
    "active": true
  }
]
```

Allowed values for `portal_name`: `99acres`, `Housing.com`, `MagicBricks`, `OLX`.

On `PATCH`, if `portal_listings` is supplied, the API **replaces** all existing portal listings on that property with the provided array.

> Any field not in the table above is silently discarded and reported in `_ignored_fields`.

---

## 6. Endpoints

---

### 6.1 GET /api/v1/properties — List Properties

Retrieve a paginated, optionally filtered list of properties, ordered by `reg_date desc, id desc`.

#### Request

```
GET /api/v1/properties
X-API-Key: <key>
```

#### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | `integer` | `1` | Page number (1-based). |
| `page_size` | `integer` | `20` | Records per page. Min: `1`, Max: `200`. |
| `is_active` | `boolean` | — | Filter by active status. Accepts: `true`, `false`, `1`, `0`, `yes`, `no`. |
| `for_sell` | `boolean` | — | Filter by listing type. `true` = for sale, `false` = for rent. |
| `city` | `string` | — | Exact city match (case-sensitive). |
| `state` | `string` | — | Exact state match (case-sensitive). |
| `prop_type` | `string` | — | Exact property type match. |
| `prop_id` | `string` | — | Exact short-code match. |
| `form_no` | `string` | — | Exact form number match. |
| `owner_phone` | `string` | — | Substring match against owner phone field. |
| `portal_name` | `string` | — | Portal source filter via relation (`99acres`, `Housing.com`, `MagicBricks`, `OLX`). |
| `portal_listing_id` | `string` | — | Exact portal listing ID filter via relation table. |
| `search` | `string` | — | Case-insensitive substring search against property `name`. |

Multiple filters are combined with logical `AND`.

#### Response — `200 OK`

```json
{
  "success": true,
  "data": {
    "total": 342,
    "page": 1,
    "page_size": 20,
    "pages": 18,
    "results": [
      {
        "id": 101,
        "uuid": "550e8400-e29b-41d4-a716-446655440000",
        "prop_id": "GBH75X0K",
        "form_no": "FORM-001",
        "name": "Aaryan City",
        "reg_date": "2025-11-20",
        "prop_type": "Residential",
        "prop_sub_type": "Apartment",
        "for_sell": true,
        "state": "Maharashtra",
        "city": "Mumbai",
        "location": "Andheri West",
        "pricing": 48.0,
        "pricing_unit": "lakh",
        "pricing_display": "48 Lakh",
        "owner_name": "Mr. Raghuvendra Rao",
        "owner_phone": "9033870424 8735999816",
        "owner_email": "raghuvendrarao379@gmail.com",
        "rm_user": { "id": 7, "name": "Chetna Solanki" },
        "bedroom_count": 2,
        "bhk": "2 BHK",
        "property_link": "https://www.cleardeals.in/property/aaryan-city-GBH75X0K",
        "gmaps_url": "https://maps.google.com/embed?...",
        "property_tag": "Premium",
        "portal_listings": [
          {
            "id": 11,
            "portal_name": "99acres",
            "portal_listing_id": "T89400543",
            "listing_label": "W36TK04R | 99acres | T89400543",
            "active": true
          },
          {
            "id": 12,
            "portal_name": "Housing.com",
            "portal_listing_id": "19684263",
            "listing_label": "W36TK04R | Housing.com | 19684263",
            "active": true
          }
        ],
        "legacy_portal_ids": {
          "ninety_nine_acres_id": null,
          "housing_id": null,
          "magicbricks_id": null,
          "olx_id": null
        },
        "service_expiry_date": "2026-12-31",
        "welcome_call_date": "2025-11-22",
        "is_active": true,
        "inventory_migrated": true,
        "listing_type": "Sell",
        "prop_type_display": "Residential",
        "is_new": false
      }
    ]
  }
}
```

#### Pagination notes

- `total` — absolute count of records matching the current filters.
- `pages` — total number of pages (`ceil(total / page_size)`).
- When `page` exceeds `pages`, `results` will be an empty array — not an error.

---

### 6.2 GET /api/v1/properties/`<identifier>` — Get Single Property

Retrieve a single property record. The `<identifier>` is resolved using the [four-strategy waterfall](#4-identifier-resolution).

#### Request

```
GET /api/v1/properties/<identifier>
X-API-Key: <key>
```

#### Path Parameter

| Parameter | Description |
|-----------|-------------|
| `identifier` | Odoo `id`, `uuid`, `prop_id` (short code), or owner phone number. |

#### Response — `200 OK`

```json
{
  "success": true,
  "data": {
    "id": 101,
    "uuid": "550e8400-e29b-41d4-a716-446655440000",
    "prop_id": "GBH75X0K",
    ...
  }
}
```

#### Response — `404 Not Found`

```json
{
  "success": false,
  "error": {
    "status": 404,
    "message": "No property found for identifier 'XYZ'."
  }
}
```

---

### 6.3 PUT /api/v1/properties — Create Property

Create a new `property.base` record. Returns the full serialised record on success.

#### Request

```
PUT /api/v1/properties
X-API-Key: <key>
Content-Type: application/json

{
  "name": "Aaryan City",
  "uuid": "550e8400-e29b-41d4-a716-446655440000",
  "prop_id": "GBH75X0K",
  "form_no": "FORM-001",
  "prop_type": "Residential",
  "prop_sub_type": "Apartment",
  "for_sell": true,
  "city": "Mumbai",
  "state": "Maharashtra",
  "location": "Andheri West",
  "pricing": 48.0,
  "pricing_unit": "lakh",
  "bedroom_count": 2,
  "owner_name": "Mr. Raghuvendra Rao",
  "owner_phone": "9033870424 8735999816",
  "owner_email": "raghuvendrarao379@gmail.com",
  "rm_user_id": 7,
  "portal_listings": [
    {
      "portal_name": "99acres",
      "portal_listing_id": "T89400543",
      "listing_label": "W36TK04R | 99acres | T89400543",
      "active": true
    },
    {
      "portal_name": "Housing.com",
      "portal_listing_id": "19684263",
      "listing_label": "W36TK04R | Housing.com | 19684263",
      "active": true
    }
  ],
  "service_expiry_date": "2026-12-31",
  "is_active": true
}
```

#### Required fields

| Field | Validation |
|-------|-----------|
| `name` | Must be present and non-empty. |

All other writable fields are optional.

#### Response — `201 Created`

Returns the full property object (same shape as GET single property).

If unknown fields were supplied they are reported in `_ignored_fields`:

```json
{
  "success": true,
  "data": {
    "id": 102,
    "name": "Aaryan City",
    ...
    "_ignored_fields": ["unknown_key", "another_bad_field"]
  }
}
```

#### Uniqueness constraints

The following fields must be unique across all records:

| Field | Constraint |
|-------|-----------|
| `uuid` | Globally unique |
| `prop_id` | Globally unique |

Violating either constraint returns `500` with the database error detail.

---

### 6.4 PATCH /api/v1/properties/`<identifier>` — Update Property

Partially update an existing property. Only the fields supplied in the request body are changed — all other fields remain untouched. The `<identifier>` is resolved via the [four-strategy waterfall](#4-identifier-resolution).

#### Request

```
PATCH /api/v1/properties/<identifier>
X-API-Key: <key>
Content-Type: application/json

{
  "pricing": 52.5,
  "pricing_unit": "lakh",
  "service_expiry_date": "2026-12-31",
  "portal_listings": [
    {
      "portal_name": "99acres",
      "portal_listing_id": "T89400543",
      "listing_label": "W36TK04R | 99acres | T89400543",
      "active": true
    },
    {
      "portal_name": "MagicBricks",
      "portal_listing_id": "MB-667788",
      "listing_label": "W36TK04R | MagicBricks | MB-667788",
      "active": true
    }
  ]
}
```

#### Path Parameter

| Parameter | Description |
|-----------|-------------|
| `identifier` | Odoo `id`, `uuid`, `prop_id`, or owner phone number. |

#### Automatic side-effects

| Written field | Side-effect |
|---------------|-------------|
| `service_expiry_date` | `is_active` is automatically set to `true` if the new date is ≥ today, `false` if it is in the past. |

#### Response — `200 OK`

Returns the full updated property object.

```json
{
  "success": true,
  "data": {
    "id": 101,
    "pricing": 52.5,
    "pricing_unit": "lakh",
    "pricing_display": "52.5 Lakh",
    ...
  }
}
```

#### Response — `404 Not Found`

```json
{
  "success": false,
  "error": {
    "status": 404,
    "message": "No property found for identifier 'XYZ'."
  }
}
```

---

### 6.5 DELETE /api/v1/properties/`<identifier>` — Delete Property

Permanently and irreversibly delete a `property.base` record from the database. This is a **hard delete** — the record cannot be recovered after this operation.

#### Request

```
DELETE /api/v1/properties/<identifier>
X-API-Key: <key>
```

#### Path Parameter

| Parameter | Description |
|-----------|-------------|
| `identifier` | Odoo `id`, `uuid`, `prop_id`, or owner phone number. |

#### Response — `200 OK`

Returns the identifiers of the deleted record for confirmation.

```json
{
  "success": true,
  "data": {
    "message": "Property permanently deleted.",
    "deleted": {
      "id": 101,
      "uuid": "550e8400-e29b-41d4-a716-446655440000",
      "prop_id": "GBH75X0K",
      "name": "Aaryan City"
    }
  }
}
```

#### Response — `404 Not Found`

```json
{
  "success": false,
  "error": {
    "status": 404,
    "message": "No property found for identifier 'XYZ'."
  }
}
```

> **Warning:** There is no soft-delete or recycle bin. This operation removes the database row permanently. Prefer setting `is_active: false` via `PATCH` when you only want to deactivate a listing.

---

## 7. Error Reference

All error responses follow the same JSON envelope:

```json
{
  "success": false,
  "error": {
    "status": <http_status_code>,
    "message": "<human-readable description>"
  }
}
```

### HTTP status codes

| Code | Name | When it occurs |
|------|------|----------------|
| `400` | Bad Request | Malformed JSON, invalid `page` / `page_size` values, non-JSON Content-Type on write. |
| `401` | Unauthorized | `X-API-Key` header is absent. |
| `403` | Forbidden | `X-API-Key` header is present but the value does not match the configured key. |
| `404` | Not Found | No `property.base` record matched the supplied identifier. |
| `415` | Unsupported Media Type | `PUT` or `PATCH` request body sent without `Content-Type: application/json`. |
| `422` | Unprocessable Entity | Request body is valid JSON but contains no accepted fields, or `name` is missing on `PUT`. |
| `500` | Internal Server Error | Unexpected Odoo / database error (e.g. unique constraint violation). The `message` includes the exception detail. |
| `503` | Service Unavailable | The `properties.api_key` system parameter has not been set on the server. |

---

## 8. Setup & Configuration

### Step 1 — Enable the module

Install the `properties` module from **Apps** in Odoo, or via the command line:

```bash
./odoo-bin -d <database> -i properties
```

### Step 2 — Set the API key

Navigate to **Settings → Technical → System Parameters** and create:

| Key | Value |
|-----|-------|
| `properties.api_key` | `<your-secret-key>` |

Or from the Odoo shell:

```bash
./odoo-bin shell -d <database> -c odoo.conf
```

```python
env['ir.config_parameter'].sudo().set_param('properties.api_key', 'your-secret-key-here')
env.cr.commit()
```

### Step 3 — Verify

```bash
curl -X GET "https://<host>/api/v1/properties?page_size=1" \
  -H "X-API-Key: your-secret-key-here"
```

A `200 OK` response with a `"success": true` body confirms the API is operational.

---

## 9. Quick-Reference curl Examples

Replace `<HOST>` with your Odoo base URL (e.g. `http://localhost:8069`) and `<KEY>` with your API key.

### List — first page, 10 results

```bash
curl -X GET "<HOST>/api/v1/properties?page=1&page_size=10" \
  -H "X-API-Key: <KEY>"
```

### List — active sale properties in Mumbai

```bash
curl -X GET "<HOST>/api/v1/properties?is_active=true&for_sell=true&city=Mumbai" \
  -H "X-API-Key: <KEY>"
```

### List — search by property name

```bash
curl -X GET "<HOST>/api/v1/properties?search=Aaryan" \
  -H "X-API-Key: <KEY>"
```

### List — filter by portal source + listing ID

```bash
curl -X GET "<HOST>/api/v1/properties?portal_name=99acres&portal_listing_id=T89400543" \
  -H "X-API-Key: <KEY>"
```

### List — filter by owner phone (partial match)

```bash
curl -X GET "<HOST>/api/v1/properties?owner_phone=9879572586" \
  -H "X-API-Key: <KEY>"
```

### Get — by Odoo ID

```bash
curl -X GET "<HOST>/api/v1/properties/101" \
  -H "X-API-Key: <KEY>"
```

### Get — by UUID

```bash
curl -X GET "<HOST>/api/v1/properties/550e8400-e29b-41d4-a716-446655440000" \
  -H "X-API-Key: <KEY>"
```

### Get — by short code (prop_id)

```bash
curl -X GET "<HOST>/api/v1/properties/GBH75X0K" \
  -H "X-API-Key: <KEY>"
```

### Get — by owner phone number

```bash
curl -X GET "<HOST>/api/v1/properties/9879572586" \
  -H "X-API-Key: <KEY>"
```

### Create (PUT)

```bash
curl -X PUT "<HOST>/api/v1/properties" \
  -H "X-API-Key: <KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Aaryan City",
    "uuid": "550e8400-e29b-41d4-a716-446655440000",
    "prop_id": "GBH75X0K",
    "prop_type": "Residential",
    "prop_sub_type": "Apartment",
    "for_sell": true,
    "city": "Mumbai",
    "state": "Maharashtra",
    "location": "Andheri West",
    "pricing": 48.0,
    "pricing_unit": "lakh",
    "bedroom_count": 2,
    "owner_name": "Mr. Raghuvendra Rao",
    "owner_phone": "9033870424 8735999816",
    "owner_email": "raghuvendrarao379@gmail.com",
    "rm_user_id": 7,
    "portal_listings": [
      {
        "portal_name": "99acres",
        "portal_listing_id": "T89400543",
        "listing_label": "W36TK04R | 99acres | T89400543",
        "active": true
      },
      {
        "portal_name": "Housing.com",
        "portal_listing_id": "19684263",
        "listing_label": "W36TK04R | Housing.com | 19684263",
        "active": true
      }
    ],
    "service_expiry_date": "2026-12-31",
    "is_active": true
  }'
```

### Update pricing and portal listings (PATCH by prop_id)

```bash
curl -X PATCH "<HOST>/api/v1/properties/GBH75X0K" \
  -H "X-API-Key: <KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "pricing": 52.5,
    "pricing_unit": "lakh",
    "portal_listings": [
      {
        "portal_name": "99acres",
        "portal_listing_id": "T89400543",
        "listing_label": "W36TK04R | 99acres | T89400543",
        "active": true
      },
      {
        "portal_name": "MagicBricks",
        "portal_listing_id": "MB-667788",
        "listing_label": "W36TK04R | MagicBricks | MB-667788",
        "active": true
      }
    ]
  }'
```

### Deactivate a property (PATCH — soft approach)

```bash
curl -X PATCH "<HOST>/api/v1/properties/GBH75X0K" \
  -H "X-API-Key: <KEY>" \
  -H "Content-Type: application/json" \
  -d '{"is_active": false}'
```

### Update expiry date (PATCH — auto-updates is_active)

```bash
curl -X PATCH "<HOST>/api/v1/properties/101" \
  -H "X-API-Key: <KEY>" \
  -H "Content-Type: application/json" \
  -d '{"service_expiry_date": "2027-06-30"}'
```

### Hard delete (DELETE by prop_id)

```bash
curl -X DELETE "<HOST>/api/v1/properties/GBH75X0K" \
  -H "X-API-Key: <KEY>"
```

### Hard delete (DELETE by Odoo ID)

```bash
curl -X DELETE "<HOST>/api/v1/properties/101" \
  -H "X-API-Key: <KEY>"
```

---

*Documentation generated for Properties module v1.1.0 — Cleardeals Tech*
