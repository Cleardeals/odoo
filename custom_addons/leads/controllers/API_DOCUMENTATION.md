# Track API — Complete Reference

**Base URL:** `https://odoo.cleardeals.xyz`
**Protocol:** HTTPS only
**Format:** All requests and responses are JSON (`Content-Type: application/json`)
**Version:** No versioning prefix — routes are stable under `/api/track/`

---

## Table of Contents

1. [Response Envelope](#1-response-envelope)
2. [Authentication](#2-authentication)
3. [Common Parameters & Conventions](#3-common-parameters--conventions)
4. [Lead Status Reference](#4-lead-status-reference)
5. [Endpoints — Buyer](#5-endpoints--buyer)
   - [GET /api/track/lead/site-visits](#51-get-apitrackleadsite-visits)
   - [GET /api/track/lead/activity](#52-get-apitrackleadactivity)
6. [Endpoints — Seller](#6-endpoints--seller)
   - [GET /api/track/property/summary](#61-get-apitrackpropertysummary)
   - [GET /api/track/property/portal-performance](#62-get-apitrackpropertyportal-performance)
   - [GET /api/track/property/site-visits](#63-get-apitrackpropertysite-visits)
   - [GET /api/track/property/activity](#64-get-apitrackpropertyactivity)
   - [GET /api/track/property/funnel](#65-get-apitrackpropertyfunnel)
   - [GET /api/track/property/ai-suggestions](#66-get-apitrackpropertyai-suggestions)
7. [Error Reference](#7-error-reference)

---

## 1. Response Envelope

Every response — success or error — shares the same top-level envelope:

```json
{
  "success": true,
  "data":    { ... },
  "error":   null
}
```

```json
{
  "success": false,
  "data":    null,
  "error": {
    "code":    403,
    "message": "Invalid API key."
  }
}
```

| Field     | Type              | Description                                              |
|-----------|-------------------|----------------------------------------------------------|
| `success` | `boolean`         | `true` on 2xx, `false` on any error                      |
| `data`    | `object \| null`  | Payload on success; `null` on error                      |
| `error`   | `object \| null`  | `null` on success; `{code, message}` object on error     |

> **Note:** `null` fields in `data` objects indicate the value is absent or not set — they are never omitted from the response.

---

## 2. Authentication

### Protected endpoints
All endpoints require an API key.

### Header

```
X-API-Key: <your-api-key>
```

The key is validated server-side against the Odoo system parameter `track_api.secret_key`. Comparison is done with constant-time `hmac.compare_digest` to prevent timing attacks.

### Auth error responses

| HTTP Status | `error.message`                                  | Cause                                                |
|-------------|--------------------------------------------------|------------------------------------------------------|
| `401`       | `Missing API key in X-API-Key header.`           | Header entirely absent from the request              |
| `403`       | `Invalid API key.`                               | Header present but value does not match stored key   |
| `500`       | `API key not configured on server.`              | System parameter not set on the server               |
| `500`       | `Authentication configuration error.`            | Server failed to read the system parameter           |

### Example request

```bash
curl -H "X-API-Key: your-secret-key" \
     "https://odoo.cleardeals.xyz/api/track/property/summary?phone=9876543210"
```

---

## 3. Common Parameters & Conventions

### `phone` (all endpoints)

- **Required** on every endpoint.
- Accepts any of: `9876543210`, `+919876543210`, `919876543210`.
- The server strips leading `+91` or `91` automatically.
- The normalized 10-digit number is echoed back in the response as `buyer_phone` or `owner_phone`.

### `property_tag` (seller endpoints)

- **Optional** on seller endpoints that list it.
- When supplied, filters results to that single property. When absent, results span all properties owned by the phone number.
- The active filter value is echoed back as `tag_filter` in the response (`null` when no filter applied).

### Pagination (`page`, `page_size`)

Used on `/activity` and `/ai-suggestions` endpoints.

| Parameter   | Default | Min | Max |
|-------------|---------|-----|-----|
| `page`      | `1`     | `1` | —   |
| `page_size` | varies  | `1` | `200` (hard cap) |

Pagination metadata is always returned inside a `pagination` key:

```json
{
  "items": [ ... ],
  "pagination": {
    "page":        1,
    "page_size":   50,
    "total":       142,
    "total_pages": 3
  }
}
```

### Datetime format

All datetime strings are ISO 8601 (`YYYY-MM-DDTHH:MM:SS`). Date-only fields use `YYYY-MM-DD`. All values are in the server's configured timezone (IST).

### Inquiry types

| `inquiry_type` value | Model                    | Meaning                                                  |
|----------------------|--------------------------|----------------------------------------------------------|
| `"primary"`          | `leads.new`              | The buyer directly inquired about this property          |
| `"recommended"`      | `lead.property.interest` | The RM recommended this property to an existing buyer    |

---

## 4. Lead Status Reference

These values appear in `current_status` fields across all endpoints.

| Status value                                     | Display meaning                              |
|--------------------------------------------------|----------------------------------------------|
| `lead`                                           | New — not yet contacted                      |
| `busy`                                           | Line was busy                                |
| `ringing`                                        | Called, no answer                            |
| `call_back_later`                                | Requested callback Later                     |
| `details_shared_of_property`                     | Property details sent to buyer               |
| `detail_shared_and_interested_for_site_visit`    | Interested, site visit being arranged        |
| `option_not_matching_requirements`               | Property doesn't match buyer's needs         |
| `site_visit_scheduled`                           | Site visit confirmed                         |
| `rescheduled` *(legacy — not returned by API)*   | Rescheduled; superseded by new visit in v1.3 |
| `site_visit_done`                                | Site visit completed                         |
| `requirement_closed`                             | No More Requirement from Buyer end           |
| `no_requirements`                                | Buyer no longer looking                      |
| `property_sold_out`                              | Property no longer available                 |
| `budget_not_sufficient`                          | Budget mismatch                              |
| `switched_off`                                   | Phone switched off                           |
| `number_not_in_use_wrong_number`                 | Wrong/invalid phone number                   |
| `other`                                          | Fallback / uncategorized                     |

### Feedback fields

Site-visit endpoints populate feedback from the `lead.site.visit` model:

| Response field              | Source                                  | Description |
|-----------------------------|-----------------------------------------|-------------|
| `feedback_general`          | `visit.feedback_option_id.code`         | Feedback code for non-completed visits (cancelled / no-show reason) |
| `feedback_site_visit_done`  | `visit.feedback_option_id.code`         | Feedback code when the visit is completed |
| `remarks`                   | `visit.feedback_note`                   | Free-text note recorded by the RM |

Both `feedback_general` and `feedback_site_visit_done` are populated from the same underlying field (`feedback_option_id.code`) — the response key used depends on which bucket the visit is classified into. Values are feedback option codes (e.g. `"negotiation_started"`, `"buyer_cancelled_interest"`).

---

## 5. Endpoints — Buyer

### 5.1 `GET /api/track/lead/site-visits`

Returns all site visits for a buyer's phone number, classified into four timeline buckets.

Data is read directly from the `lead.site.visit` model (not from the snapshot fields on `leads.new`), so feedback, cancellation reasons, and no-show statuses are always accurate.

**Auth required:** Yes (`X-API-Key`)

#### Query Parameters

| Parameter | Type   | Required | Description                           |
|-----------|--------|----------|---------------------------------------|
| `phone`   | string | ✅ Yes   | Buyer phone number (any format)       |

#### Response — `data` shape

```json
{
  "buyer_phone": "9876543210",
  "upcoming":         [ <visit-object>, ... ],
  "pending_feedback": [ <visit-object>, ... ],
  "cancelled":        [ <visit-object>, ... ],
  "completed":        [ <visit-object>, ... ],
  "totals": {
    "upcoming":         2,
    "pending_feedback": 1,
    "cancelled":        3,
    "completed":        5
  }
}
```

#### Bucket classification logic

Classification is driven by the **status-type flags** on `lead.site.visit.status`, not by the `current_status` string snapshot on `leads.new`.

| Bucket             | Status condition                                         | Date condition                  | Sort order |
|--------------------|----------------------------------------------------------|---------------------------------|------------|
| `upcoming`         | `status.is_scheduled` OR `status.is_rescheduled`         | `site_visit_datetime` in future | ASC (soonest first) |
| `pending_feedback` | `status.is_scheduled` OR `status.is_rescheduled`         | `site_visit_datetime` in past   | ASC (oldest first) |
| `cancelled`        | `status.is_cancelled` OR `status.is_no_show`             | —                               | DESC (most recent first) |
| `completed`        | `status.is_completed`                                    | —                               | DESC       |

> **Reschedules:** When a visit is rescheduled, the original visit is superseded and a new `lead.site.visit` record is created with `status="scheduled"` and the new datetime. The new visit appears in `upcoming` if its date is in the future. The superseded visit is excluded from results.
>
> **No-show:** A visit marked as "Did Not Show Up" is classified as `cancelled`, not `pending_feedback`. This was not correctly handled before v2.0.

#### Visit object fields

All buckets include this base set:

| Field                  | Type              | Source                              | Description                                               |
|------------------------|-------------------|-------------------------------------|-----------------------------------------------------------|
| `inquiry_type`         | `string`          | `leads.new.inquiry_type`            | `"primary"` or `"recommended"`                            |
| `lead_id`              | `integer`         | `leads.new.id`                      | ID of the parent `leads.new` record                       |
| `lead_name`            | `string \| null`  | `leads.new.name`                    | Buyer name                                                |
| `source`               | `string \| null`  | `leads.new.source_id.name`          | Lead source of origin (e.g. `"MagicBricks"`, `"99acres"`) |
| `property_tag`         | `string \| null`  | `lead.site.visit.property_base_id`  | Unique property identifier tag                            |
| `property_bhk`         | `string \| null`  | `property_base.bhk`                 | Property size (e.g. `"2BHK"`)                             |
| `property_location`    | `string \| null`  | `property_base.location`            | Locality / micro-location                                 |
| `property_city`        | `string \| null`  | `property_base.city`                | City                                                      |
| `site_visit_datetime`  | `string \| null`  | `lead.site.visit.scheduled_datetime`| ISO 8601 datetime of the visit                            |
| `site_visit_date`      | `string \| null`  | `lead.site.visit.scheduled_date`    | Date-only string (`YYYY-MM-DD`)                           |
| `current_status`       | `string \| null`  | Derived from `status_id` flags      | `"site_visit_scheduled"` or `"site_visit_done"` (for display only — use bucket name for routing) |
| `remarks`              | `string \| null`  | `lead.site.visit.feedback_note`     | Free-text RM note                                         |

**Additional fields by bucket:**

| Bucket             | Extra fields                                                                                  |
|--------------------|-----------------------------------------------------------------------------------------------|
| `pending_feedback` | `note` — `"Visit date has passed — awaiting RM feedback"`                                    |
| `cancelled`        | `feedback_general` (`visit.feedback_option_id.code`), `note` — `"Visit did not occur due to buyer status"` |
| `completed`        | `feedback_site_visit_done` (`visit.feedback_option_id.code`)                                  |

#### Success example

```json
{
  "success": true,
  "data": {
    "buyer_phone": "9876543210",
    "upcoming": [
      {
        "inquiry_type": "primary",
        "lead_id": 101,
        "lead_name": "Ravi Shah",
        "source": "MagicBricks",
        "property_tag": "CLR-2BHK-MNG-001",
        "property_bhk": "2BHK",
        "property_location": "Maninagar",
        "property_city": "Ahmedabad",
        "site_visit_datetime": "2025-07-20T11:00:00",
        "site_visit_date": "2025-07-20",
        "current_status": "site_visit_scheduled",
        "remarks": "Client wants ground floor unit"
      }
    ],
    "pending_feedback": [],
    "cancelled": [],
    "completed": [],
    "totals": {
      "upcoming": 1,
      "pending_feedback": 0,
      "cancelled": 0,
      "completed": 0
    }
  },
  "error": null
}
```

#### Error responses

| HTTP | `error.message`                                         | Cause                      |
|------|---------------------------------------------------------|----------------------------|
| `400` | `Valid 'phone' query parameter is required.`           | `phone` param missing/invalid |
| `404` | `No inquiries found for phone {phone}.`                | No records for that buyer  |
| `401` | `Missing API key in X-API-Key header.`                 | Auth header absent         |
| `403` | `Invalid API key.`                                     | Wrong key                  |

---

### 5.2 `GET /api/track/lead/activity`

Returns a full activity overview for a buyer: summary counts and a list of all primary inquiries with their recommended properties nested inside.

**Auth required:** Yes (`X-API-Key`)

#### Query Parameters

| Parameter | Type   | Required | Description              |
|-----------|--------|----------|--------------------------|
| `phone`   | string | ✅ Yes   | Buyer phone number       |

#### Response — `data` shape

```json
{
  "buyer_phone": "9876543210",
  "summary": {
    "total_inquiries":      5,
    "total_properties":     3,
    "site_visits_scheduled": 2,
    "site_visits_done":      1
  },
  "primary_inquiries": [ <inquiry-object>, ... ]
}
```

#### Inquiry object

| Field                    | Type              | Description                                              |
|--------------------------|-------------------|----------------------------------------------------------|
| `lead_id`                | `integer`         | Odoo ID of the inquiry record                            |
| `lead_name`              | `string \| null`  | Buyer name on this inquiry                               |
| `source`                 | `string \| null`  | Source the inquiry came from                             |
| `inquiry_datetime`       | `string \| null`  | ISO 8601 datetime the inquiry was created                |
| `current_status`         | `string \| null`  | Current lead status                                      |
| `first_contacted_on`     | `string \| null`  | ISO 8601 datetime of first RM contact                    |
| `remarks`                | `string \| null`  | RM free-text note from the latest site visit             |
| `feedback_general`       | `string \| null`  | Feedback option code when visit is cancelled/no-show     |
| `feedback_site_visit_done` | `string \| null` | Feedback option code when visit is completed            |
| `has_property`           | `boolean`         | Whether a property is linked to this lead                |
| `property`               | `object \| null`  | Property details (see below)                             |
| `site_visit_datetime`    | `string \| null`  | ISO 8601 datetime of the scheduled/completed site visit  |
| `site_visit_date`        | `string \| null`  | Date-only string                                         |
| `recommended_properties` | `array`           | Recommended child inquiries for this lead                |

**`property` object (when `has_property: true`):**

| Field           | Type             | Description                        |
|-----------------|------------------|------------------------------------|
| `property_tag`  | `string \| null` | Property identifier tag            |
| `bhk`           | `string \| null` | e.g. `"3BHK"`                     |
| `location`      | `string \| null` | Locality                           |
| `city`          | `string \| null` | City                               |
| `property_link` | `string \| null` | URL to the property listing        |

**Each item in `recommended_properties`:**

| Field                 | Type             | Description                                              |
|-----------------------|------------------|----------------------------------------------------------|
| `interest_id`         | `integer`        | Odoo ID of the recommended inquiry record                |
| `property_tag`        | `string \| null` | Tag of the recommended property                          |
| `bhk`                 | `string \| null` | Size                                                     |
| `location`            | `string \| null` | Locality                                                 |
| `city`                | `string \| null` | City                                                     |
| `property_link`       | `string \| null` | URL to the property listing                              |
| `current_status`      | `string \| null` | Status snapshot of the recommended inquiry               |
| `site_visit_datetime` | `string \| null` | ISO 8601 datetime                                        |
| `site_visit_date`     | `string \| null` | Date-only string                                         |
| `remarks`             | `string \| null` | RM free-text note from the latest site visit             |

#### Success example

```json
{
  "success": true,
  "data": {
    "buyer_phone": "9876543210",
    "summary": {
      "total_inquiries": 2,
      "total_properties": 2,
      "site_visits_scheduled": 1,
      "site_visits_done": 0
    },
    "primary_inquiries": [
      {
        "lead_id": 12,
        "lead_name": "Priya Mehta",
        "source": "99acres",
        "inquiry_datetime": "2025-06-15T09:30:00",
        "current_status": "site_visit_scheduled",
        "first_contacted_on": "2025-06-15T11:00:00",
        "remarks": null,
        "feedback_general": null,
        "feedback_site_visit_done": null,
        "has_property": true,
        "property": {
          "property_tag": "CLR-3BHK-BOD-007",
          "bhk": "3BHK",
          "location": "Bodakdev",
          "city": "Ahmedabad",
          "property_link": "https://example.com/listing/007"
        },
        "site_visit_datetime": "2025-07-22T10:00:00",
        "site_visit_date": "2025-07-22",
        "recommended_properties": [
          {
            "interest_id": 55,
            "property_tag": "CLR-3BHK-PRH-012",
            "bhk": "3BHK",
            "location": "Prahladnagar",
            "city": "Ahmedabad",
            "property_link": "https://example.com/listing/012",
            "current_status": "details_shared_of_property",
            "site_visit_datetime": null,
            "site_visit_date": null,
            "remarks": null
          }
        ]
      }
    ]
  },
  "error": null
}
```

#### Error responses

| HTTP  | `error.message`                                       | Cause                         |
|-------|-------------------------------------------------------|-------------------------------|
| `400` | `Valid 'phone' query parameter is required.`          | `phone` param missing/invalid |
| `404` | `No Inquiries found for phone number {phone}.`        | No records for that buyer     |

---

## 6. Endpoints — Seller

All seller endpoints require the `X-API-Key` header.

---

### 6.1 `GET /api/track/property/summary`

High-level aggregated counts for all of a seller's properties, broken down by lead source and lead type.

**Auth required:** Yes

#### Query Parameters

| Parameter | Type   | Required | Description              |
|-----------|--------|----------|--------------------------|
| `phone`   | string | ✅ Yes   | Owner phone number       |
| `property_tag` | string | No       | Filter to a specific property      |

#### Response — `data` shape

```json
{
  "owner_phone": "9876543210",
  "properties":  ["TAG1", "TAG2"],
  "tag_filter":  null,
  "inquiries": {
    "total":       80,
    "primary":     55,
    "recommended": 25,
    "source_breakdown": {
      "MagicBricks":  { "primary": 20, "recommended": 10 },
      "99acres":      { "primary": 15, "recommended":  8 },
      "Housing.com":  { "primary": 12, "recommended":  5 },
      "OLX":          { "primary":  5, "recommended":  2 },
      "Unknown":      { "primary":  3, "recommended":  0 }
    }
  }
}
```

| Field                | Type            | Description                                               |
|----------------------|-----------------|-----------------------------------------------------------|
| `owner_phone`        | `string`        | Normalized 10-digit phone                                 |
| `properties`         | `string[]`      | All active property tags for this owner                   |
| `inquiries.total`    | `integer`       | Total leads (primary + recommended)                       |
| `inquiries.primary`  | `integer`       | Direct inquiry count                                      |
| `inquiries.recommended` | `integer`    | Recommended interest count                                |
| `inquiries.source_breakdown` | `object` | Per-source split keyed by source name (dynamic keys)      |

**Common source keys:** `MagicBricks`, `99acres`, `Housing.com`, `OLX`, `Unknown` (plus any custom source names)

#### Error responses

| HTTP  | `error.message`                                          | Cause                        |
|-------|----------------------------------------------------------|------------------------------|
| `400` | `Valid 'phone' query parameter is required.`             | Missing phone                |
| `404` | `No properties found for phone number {phone}.`          | No properties on file        |

---

### 6.2 `GET /api/track/property/portal-performance`

Per-source breakdown of lead statuses and key site-visit metrics. Optionally filtered to a single property.

**Auth required:** Yes

#### Query Parameters

| Parameter      | Type   | Required | Description                                       |
|----------------|--------|----------|---------------------------------------------------|
| `phone`        | string | ✅ Yes   | Owner phone number                                |
| `property_tag` | string | No       | Filter to a specific property tag                 |

#### Response — `data` shape

```json
{
  "owner_phone": "9876543210",
  "properties":  ["TAG1", "TAG2"],
  "tag_filter":  null,
  "sources": {
    "MagicBricks": {
      "total_leads":       30,
      "primary_leads":     20,
      "recommended_leads": 10,
      "statuses": {
        "lead":                  5,
        "site_visit_scheduled":  8,
        "site_visit_done":       4
      },
      "key_metrics": {
        "site_visit_scheduled": 8,
        "site_visit_done":      4
      }
    },
    "99acres":     { ... },
    "Housing.com": { ... },
    "OLX":         { ... },
    "Unknown":     { ... }
  }
}
```

| Field                                 | Type             | Description                                                  |
|---------------------------------------|------------------|--------------------------------------------------------------|
| `sources`                             | `object`         | Dynamic source map keyed by source name                      |
| `sources.<source>.total_leads`        | `integer`        | Sum of primary + recommended for this source                 |
| `sources.<source>.primary_leads`      | `integer`        | Direct inquiries attributed to this source                   |
| `sources.<source>.recommended_leads`  | `integer`        | Recommended interests (source inherited from parent lead)    |
| `sources.<source>.statuses`           | `object`         | Dynamic dict of `{status_value: count}` — only non-zero statuses appear |
| `sources.<source>.key_metrics`        | `object`         | Always present; `site_visit_scheduled` and `site_visit_done` counts |

> **Note:** `statuses` only includes statuses with count > 0. `key_metrics` is always present even if counts are 0.

#### Error responses

| HTTP  | `error.message`                                                                       |
|-------|---------------------------------------------------------------------------------------|
| `400` | `Valid 'phone' query parameter is required.`                                          |
| `404` | `No properties found for phone number {phone}.`                                       |
| `404` | `No properties found for phone number {phone} with tag '{property_tag}'.`             |

---

### 6.3 `GET /api/track/property/site-visits`

All site visits for a seller's properties, classified into four timeline buckets. Mirrors the buyer endpoint but from the seller's perspective (shows lead names/phones instead of lead IDs).

**Auth required:** Yes

#### Query Parameters

| Parameter      | Type   | Required | Description                   |
|----------------|--------|----------|-------------------------------|
| `phone`        | string | ✅ Yes   | Owner phone number            |
| `property_tag` | string | No       | Filter to a specific property |

#### Response — `data` shape

```json
{
  "owner_phone":      "9876543210",
  "properties":       ["TAG1", "TAG2"],
  "tag_filter":       null,
  "upcoming":         [ <visit-object>, ... ],
  "pending_feedback": [ <visit-object>, ... ],
  "cancelled":        [ <visit-object>, ... ],
  "completed":        [ <visit-object>, ... ],
  "totals": {
    "upcoming":         1,
    "pending_feedback": 2,
    "cancelled":        0,
    "completed":        4
  }
}
```

Bucket classification and sort order are identical to the [buyer site-visits endpoint](#51-get-apitrackleadsite-visits). Data is read directly from `lead.site.visit` — not from the snapshot fields on `leads.new`.

#### Visit object (seller perspective)

> Seller records expose `lead_name` and `lead_phone` instead of `lead_id`. The `source` field carries the inquiry type (`"primary"`/`"recommended"`). Both primary and recommended inquiries managed via `leads.new` + `lead.site.visit` are returned. Legacy `lead.property.interest` records (pre-visit-model) are returned on the legacy snapshot path if they have a visit date.

| Field                  | Type              | Source                                | Description                           |
|------------------------|-------------------|---------------------------------------|---------------------------------------|
| `source`               | `string`          | `leads.new.inquiry_type`              | `"primary"` or `"recommended"`        |
| `lead_name`            | `string \| null`  | `leads.new.name`                      | Buyer name                            |
| `lead_phone`           | `string \| null`  | `leads.new.phone`                     | Buyer phone number                    |
| `property_tag`         | `string \| null`  | `lead.site.visit.property_base_id`    | Property tag                          |
| `property_bhk`         | `string \| null`  | `property_base.bhk`                   | Property size                         |
| `property_location`    | `string \| null`  | `property_base.location`              | Locality                              |
| `site_visit_datetime`  | `string \| null`  | `lead.site.visit.scheduled_datetime`  | ISO 8601 datetime                     |
| `site_visit_date`      | `string \| null`  | `lead.site.visit.scheduled_date`      | Date-only string                      |
| `current_status`       | `string \| null`  | Derived from `status_id` flags        | `"site_visit_scheduled"` or `"site_visit_done"` |
| `remarks`              | `string \| null`  | `lead.site.visit.feedback_note`       | Free-text RM note                     |

Additional per-bucket fields are the same as the buyer endpoint (`note`, `feedback_general`, `feedback_site_visit_done`).

#### Error responses

Same error set as `/api/track/property/portal-performance`.

---

### 6.4 `GET /api/track/property/activity`

Paginated, chronologically-sorted list of every lead record (primary and recommended combined) for a seller's properties.

**Auth required:** Yes

#### Query Parameters

| Parameter      | Type    | Required | Default | Description                        |
|----------------|---------|----------|---------|------------------------------------|
| `phone`        | string  | ✅ Yes   | —       | Owner phone number                 |
| `property_tag` | string  | No       | —       | Filter to a specific property      |
| `page`         | integer | No       | `1`     | Page number (1-based)              |
| `page_size`    | integer | No       | `50`    | Records per page (max 200)         |

#### Response — `data` shape

```json
{
  "owner_phone": "9876543210",
  "properties":  ["TAG1", "TAG2"],
  "tag_filter":  null,
  "items": [ <activity-object>, ... ],
  "pagination": {
    "page":        1,
    "page_size":   50,
    "total":       142,
    "total_pages": 3
  }
}
```

#### Activity object

| Field                     | Type             | Description                                                    |
|---------------------------|------------------|----------------------------------------------------------------|
| `type`                    | `string`         | `"primary"` or `"recommended"`                                 |
| `lead_id`                 | `integer`        | Odoo ID of the inquiry record                                  |
| `lead_name`               | `string \| null` | Buyer name                                                     |
| `lead_phone`              | `string \| null` | Buyer phone                                                    |
| `source`                  | `string \| null` | Source of origin (from parent lead for recommended)            |
| `property_tag`            | `string \| null` | Property tag                                                   |
| `property_bhk`            | `string \| null` | Property size                                                  |
| `property_location`       | `string \| null` | Locality                                                       |
| `inquiry_datetime`        | `string \| null` | ISO 8601 — `create_date` of the inquiry record                 |
| `current_status`          | `string \| null` | Current status                                                 |
| `first_contacted_on`      | `string \| null` | ISO 8601 — first RM contact datetime (from parent lead for recommended) |
| `site_visit_datetime`     | `string \| null` | ISO 8601 datetime                                              |
| `site_visit_date`         | `string \| null` | Date-only string                                               |
| `remarks`                 | `string \| null` | RM free-text note from the latest site visit                   |
| `feedback_general`        | `string \| null` | Feedback option code when visit is cancelled/no-show           |
| `feedback_site_visit_done`| `string \| null` | Feedback option code when visit is completed                   |

> Results are sorted by `inquiry_datetime` descending (most recent first). Records with `null` datetime sort last.

#### Success example

```json
{
  "success": true,
  "data": {
    "owner_phone": "9876543210",
    "properties": ["CLR-2BHK-MNG-001"],
    "tag_filter": "CLR-2BHK-MNG-001",
    "items": [
      {
        "type": "primary",
        "lead_id": 42,
        "lead_name": "Kiran Patel",
        "lead_phone": "9000000001",
        "source": "Housing.com",
        "property_tag": "CLR-2BHK-MNG-001",
        "property_bhk": "2BHK",
        "property_location": "Maninagar",
        "inquiry_datetime": "2025-07-10T08:20:00",
        "current_status": "site_visit_done",
        "first_contacted_on": "2025-07-10T09:15:00",
        "site_visit_datetime": "2025-07-15T11:00:00",
        "site_visit_date": "2025-07-15",
        "remarks": "Liked the view from 3rd floor",
        "feedback_general": null,
        "feedback_site_visit_done": "buyer_liked_property"
      }
    ],
    "pagination": {
      "page": 1,
      "page_size": 50,
      "total": 1,
      "total_pages": 1
    }
  },
  "error": null
}
```

#### Error responses

| HTTP  | `error.message`                                                                  |
|-------|----------------------------------------------------------------------------------|
| `400` | `Valid 'phone' query parameter is required.`                                     |
| `400` | `'page' and 'page_size' must be integers.`                                       |
| `404` | `No properties found for phone number {phone}.`                           |
| `404` | `No properties found for phone number {phone} with tag '{property_tag}'.` |

---

### 6.5 `GET /api/track/property/funnel`

Aggregated conversion funnel across all of a seller's properties. Shows how many leads are at each stage and computes key performance metrics.

**Auth required:** Yes

#### Query Parameters

| Parameter | Type   | Required | Description              |
|-----------|--------|----------|--------------------------|
| `phone`   | string | ✅ Yes   | Owner phone number       |
| `property_tag` | string | No       | Filter to a specific property      |

#### Response — `data` shape

```json
{
  "owner_phone": "9876543210",
  "properties":  ["TAG1", "TAG2"],
  "tag_filter":  null,
  "funnel": {
    "total_inquiries": 42,
    "stages": {
      "lead":                                        { "count": 10, "pct_of_total": 23.8 },
      "busy":                                        { "count":  3, "pct_of_total":  7.1 },
      "ringing":                                     { "count":  2, "pct_of_total":  4.8 },
      "call_back_later":                             { "count":  1, "pct_of_total":  2.4 },
      "details_shared_of_property":                  { "count":  5, "pct_of_total": 11.9 },
      "detail_shared_and_interested_for_site_visit": { "count":  4, "pct_of_total":  9.5 },
      "option_not_matching_requirements":            { "count":  0, "pct_of_total":  0.0 },
      "site_visit_scheduled":                        { "count":  6, "pct_of_total": 14.3 },
      "rescheduled":                                 { "count":  1, "pct_of_total":  2.4 },
      "site_visit_done":                             { "count":  4, "pct_of_total":  9.5 },
      "requirement_closed":                          { "count":  3, "pct_of_total":  7.1 },
      "no_requirements":                             { "count":  2, "pct_of_total":  4.8 },
      "property_sold_out":                           { "count":  0, "pct_of_total":  0.0 },
      "budget_not_sufficient":                       { "count":  0, "pct_of_total":  0.0 },
      "switched_off":                                { "count":  0, "pct_of_total":  0.0 },
      "number_not_in_use_wrong_number":              { "count":  0, "pct_of_total":  0.0 },
      "other":                                       { "count":  1, "pct_of_total":  2.4 }
    },
    "key_metrics": {
      "contacted":            32,
      "site_visit_scheduled":  6,
      "site_visit_done":       4,
      "closed_or_lost":        5
    }
  }
}
```

#### Funnel field details

| Field                          | Type     | Description                                                    |
|--------------------------------|----------|----------------------------------------------------------------|
| `funnel.total_inquiries`       | `integer`| Total records (primary + recommended) for all properties       |
| `funnel.stages`                | `object` | All 17 stage keys always present, even at 0 count             |
| `funnel.stages.<stage>.count`  | `integer`| Number of leads at this stage                                  |
| `funnel.stages.<stage>.pct_of_total` | `float` | Rounded to one decimal place; 0.0 when total is 0         |
| `funnel.key_metrics.contacted` | `integer`| Leads that have been reached (all stages except `lead` and terminal ones) |
| `funnel.key_metrics.closed_or_lost` | `integer` | Sum of `requirement_closed + no_requirements + property_sold_out + budget_not_sufficient` |

#### Error responses

| HTTP  | `error.message`                                          |
|-------|----------------------------------------------------------|
| `400` | `Valid 'phone' query parameter is required.`             |
| `404` | `No properties found for phone number {phone}.`          |

---

### 6.6 `GET /api/track/property/ai-suggestions`

Returns AI-generated lead suggestions for a seller's properties, sourced from a BigQuery-synced model. Paginated; an empty `items` list is a valid response.

**Auth required:** Yes

#### Query Parameters

| Parameter      | Type    | Required | Default | Description                        |
|----------------|---------|----------|---------|------------------------------------|
| `phone`        | string  | ✅ Yes   | —       | Owner phone number                 |
| `property_tag` | string  | No       | —       | Filter to a specific property      |
| `page`         | integer | No       | `1`     | Page number (1-based)              |
| `page_size`    | integer | No       | `20`    | Records per page (max 200)         |

#### Response — `data` shape

```json
{
  "owner_phone": "9876543210",
  "properties":  ["TAG1"],
  "tag_filter":  null,
  "items": [ <suggestion-object>, ... ],
  "pagination": {
    "page":        1,
    "page_size":   20,
    "total":       5,
    "total_pages": 1
  }
}
```

#### Suggestion object

| Field                    | Type             | Description                                                     |
|--------------------------|------------------|-----------------------------------------------------------------|
| `property_tag`           | `string \| null` | The seller's property this suggestion is for                    |
| `suggested_lead_name`    | `string \| null` | Name of the suggested buyer                                     |
| `suggested_lead_phone`   | `string \| null` | Phone of the suggested buyer                                    |
| `original_property_tag`  | `string \| null` | Property the buyer originally inquired about (basis of match)   |
| `suggested_on`           | `string \| null` | ISO 8601 date when the suggestion was generated                 |
| `contact_type`           | `string \| null` | Type of interaction the suggested buyer has had                 |
| `rm_status`              | `string \| null` | RM's current status on this suggestion                          |
| `rm_feedback`            | `string \| null` | Free-text RM feedback on this suggestion                        |

> Suggestions are sorted by `suggested_on` descending.

#### Success example

```json
{
  "success": true,
  "data": {
    "owner_phone": "9876543210",
    "properties": ["CLR-3BHK-BOD-007"],
    "tag_filter": null,
    "items": [
      {
        "property_tag": "CLR-3BHK-BOD-007",
        "suggested_lead_name": "Amit Patel",
        "suggested_lead_phone": "9123456789",
        "original_property_tag": "CLR-3BHK-PRH-012",
        "suggested_on": "2025-07-10",
        "contact_type": "site_visit_done",
        "rm_status": "contacted",
        "rm_feedback": "Interested, will call back tomorrow"
      }
    ],
    "pagination": {
      "page": 1,
      "page_size": 20,
      "total": 1,
      "total_pages": 1
    }
  },
  "error": null
}
```

#### Error responses

| HTTP  | `error.message`                                                                  |
|-------|----------------------------------------------------------------------------------|
| `400` | `Valid 'phone' query parameter is required.`                                     |
| `400` | `Invalid 'page' or 'page_size' parameter. Must be integers.`                     |
| `404` | `No properties found for phone number {phone}.`                           |
| `404` | `No properties found for phone number {phone} with tag '{property_tag}'.` |

---

## 7. Error Reference

### Standard error codes

| HTTP Status | Meaning          | When to expect it                                              |
|-------------|------------------|----------------------------------------------------------------|
| `400`       | Bad Request      | Missing/invalid query parameters                               |
| `401`       | Unauthorized     | `X-API-Key` header is absent                                   |
| `403`       | Forbidden        | `X-API-Key` value is incorrect                                 |
| `404`       | Not Found        | No records found for the given phone / property tag            |
| `500`       | Server Error     | API key not configured on server, or unexpected server failure |

### Error response body

```json
{
  "success": false,
  "data":    null,
  "error": {
    "code":    404,
    "message": "No properties found for phone number 9876543210."
  }
}
```

### Endpoint auth summary

| Endpoint                                    | Auth Required |
|---------------------------------------------|:-------------:|
| `GET /api/track/lead/site-visits`           | ✅ Yes        |
| `GET /api/track/lead/activity`              | ✅ Yes        |
| `GET /api/track/property/summary`           | ✅ Yes        |
| `GET /api/track/property/portal-performance`| ✅ Yes        |
| `GET /api/track/property/site-visits`       | ✅ Yes        |
| `GET /api/track/property/activity`          | ✅ Yes        |
| `GET /api/track/property/funnel`            | ✅ Yes        |
| `GET /api/track/property/ai-suggestions`    | ✅ Yes        |

---

*Generated from source: `custom_addons/leads/controllers/`*
