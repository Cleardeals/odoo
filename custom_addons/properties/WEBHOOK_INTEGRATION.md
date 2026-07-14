# Property Webhooks — Website Integration Guide

**Audience:** Website / admin-panel backend team
**Version:** 1.0.0 (Odoo `properties` module 19.0.1.4.0)
**Base URL:** `https://odoo.cleardeals.xyz`
**Data Format:** `application/json` (request and response)
**Authentication:** API key via HTTP header

---

## Table of Contents

1. [What changed & why](#1-what-changed--why)
2. [Endpoints](#2-endpoints)
3. [Authentication](#3-authentication)
4. [Request format](#4-request-format)
5. [What you send vs. what we store (field mapping)](#5-what-you-send-vs-what-we-store-field-mapping)
6. [Response format](#6-response-format)
7. [Idempotency, retries & ordering](#7-idempotency-retries--ordering)
8. [Error reference](#8-error-reference)
9. [End-to-end examples (curl)](#9-end-to-end-examples-curl)
10. [Delivery requirements & best practices](#10-delivery-requirements--best-practices)
11. [FAQ](#11-faq)

---

## 1. What changed & why

Previously Odoo **polled** the website API every 3 hours to discover new and
changed properties. That meant data could be up to 3 hours stale and the whole
catalogue was re-fetched each cycle.

Going forward, **the website pushes changes to Odoo in real time** via two
webhooks:

- When a property is **created** in the admin panel → call the **create** webhook.
- When a property is **updated** in the admin panel → call the **update** webhook.

Odoo performs the matching create/update immediately. The polling job has been
retired (kept only as a manual backfill tool on our side).

**You do not need to change your payload.** The webhook body is the *exact same
structure* your existing property API already returns for a single property.

---

## 2. Endpoints

| Event | Method | URL |
|-------|--------|-----|
| Property created | `POST` | `https://odoo.cleardeals.xyz/api/v1/properties/webhook/create` |
| Property updated | `POST` | `https://odoo.cleardeals.xyz/api/v1/properties/webhook/update` |

Notes:
- Both are `POST` and accept the same body.
- Send the **single property** that changed — one property per request (not a list).
- Fire the event **after** the property (and its related rows) are committed on
  your side, so the payload reflects the final state.

---

## 3. Authentication

Every request must include a shared secret in the `X-API-Key` header:

```
X-API-Key: <your-api-key>
```

- The key is the same one used for the existing Properties REST API.
- It is provisioned and rotated by the Cleardeals Tech team — store it as a
  secret on your side, never commit it to source control.
- Always call over **HTTPS**.

Missing key → `401`. Wrong key → `403`. (See [§8](#8-error-reference).)

---

## 4. Request format

- **Method:** `POST`
- **Header:** `Content-Type: application/json` (required — a non-JSON content type is rejected with `415`)
- **Header:** `X-API-Key: <your-api-key>`
- **Body:** the property envelope, identical to your single-property API response:

```json
{
  "success": true,
  "property": {
    "id": "c68b54d6-ca00-4273-9a28-a722df42b02e",
    "property_name": "Parshwanath Society",
    "prop_id": "WZOO4IIQ",
    "...": "... all the usual nested fields ..."
  }
}
```

We also accept a **bare property object** (without the `{"success", "property"}`
wrapper) if that is simpler on your side:

```json
{ "id": "c68b54d6-...", "property_name": "Parshwanath Society", "...": "..." }
```

> **The single most important field is `property.id`** (the property UUID). It is
> the key we match on. A request without it is rejected (`422`). See
> [idempotency](#7-idempotency-retries--ordering).

You can send the **full payload** — including `details`, `furniture_details`,
`areas`, `sell_pricing`, `rent_pricing`, the nested `state`/`city`/`location_area`
objects, and the entire `media` array. Odoo reads the fields it needs and safely
ignores the rest; extra fields never cause an error.

---

## 5. What you send vs. what we store (field mapping)

Odoo currently consumes the following fields from each property object. Anything
not in this table is accepted but ignored (for now).

| Your field (website) | Stored in Odoo as | Notes |
|----------------------|-------------------|-------|
| `id` | `uuid` | **Required.** The match key. |
| `prop_id` | `prop_id` | Short code. Must be unique. |
| `form_no` | `form_no` | |
| `property_name` | `name` | |
| `reg_date` | `reg_date` | ISO datetime accepted; stored as date (`YYYY-MM-DD`). |
| `prop_type` | `prop_type` | e.g. `residential` / `commercial`. |
| `for_sell` | `for_sell` | Boolean. Selects which pricing block is read (below). |
| `prop_sub_type` | `prop_sub_type` | |
| `state.name` | `state` | Read from the nested object. |
| `city.name` | `city` | Read from the nested object. |
| `location_area.name` | `location` | Read from the nested object. |
| `exec_name` | `rm_user_id` | Resolved by **name** to an Odoo user (see note). |
| `owner_name` | `owner_name` | |
| `owner_contact_no` | `owner_phone` | Normalised to a 10-digit number (strips `+91`, spaces, hyphens). |
| `owner_email` | `owner_email` | |
| `gmaps_url` | `gmaps_url` | |
| `details.bedroom_count` | `bedroom_count` | Integer parsed from strings like `"5 BHK"` → `5`. |
| `sell_pricing.offer_price` | `pricing` | Used when `for_sell = true`. |
| `sell_pricing.offer_price_unit` | `pricing_unit` | e.g. `lakh`, `crore`. Used when `for_sell = true`. |
| `rent_pricing.rent_price` | `pricing` | Used when `for_sell = false`. |
| `rent_pricing.rent_price_unit` | `pricing_unit` | Used when `for_sell = false`. |

**Pricing rule:** if `for_sell` is `true`, we read `sell_pricing`; if `false`, we
read `rent_pricing`. Send the appropriate block (the other may be `null`).

**`exec_name` → RM:** we match the executive name against Odoo users (with light
normalisation: trims spaces, treats hyphens as spaces, case-insensitive). If no
user matches, the property is still saved with no RM assigned, and we log a
warning. To guarantee assignment, send the name exactly as it appears in Odoo.

**Manager-owned fields are never overwritten by webhooks:** portal IDs
(99acres/Housing/MagicBricks/OLX), `property_tag`, `service_expiry_date`, and
`welcome_call_date` are maintained inside Odoo. An update webhook will not clear
or change them.

**Media:** the `media` array is currently **accepted but not stored**. Keep
sending it; image handling may be added later without any change on your side.

---

## 6. Response format

All responses use a consistent envelope.

**Success:**

```json
{
  "success": true,
  "data": {
    "id": 191,
    "uuid": "c68b54d6-ca00-4273-9a28-a722df42b02e",
    "prop_id": "WZOO4IIQ",
    "name": "Parshwanath Society",
    "...": "... full serialized property ...",
    "_webhook_action": "created"
  }
}
```

- `data.id` — Odoo's internal numeric record id.
- `data._webhook_action` — what actually happened: `"created"`, `"updated"`, or
  `"unchanged"` (payload identical to what we already had).

**HTTP status codes returned on success:**

| Status | Meaning |
|--------|---------|
| `201 Created` | A new property record was created. |
| `200 OK` | An existing record was updated, or was unchanged. |

**Error:**

```json
{
  "success": false,
  "error": { "status": 422, "message": "Property payload is missing the required 'id' (uuid)." }
}
```

---

## 7. Idempotency, retries & ordering

Both endpoints perform an **idempotent upsert keyed on `property.id` (uuid)**.
This makes the integration robust to the realities of webhook delivery:

- **Create endpoint, uuid already exists** → we **update** that record (no
  duplicate is created). Response: `200`, `_webhook_action: "updated"`.
- **Update endpoint, uuid does not exist yet** → we **create** it. Response:
  `201`, `_webhook_action: "created"`.
- **Re-sending the exact same payload** → `200`, `_webhook_action: "unchanged"`.

Practical implications for you:
- **Safe to retry.** If you don't get a `2xx` (timeout, network error, `5xx`),
  just send the same request again. You will not create duplicates.
- **Out-of-order delivery is tolerated.** An update arriving before its create
  still results in a correct record.
- `uuid` and `prop_id` are both unique in Odoo. Keep them stable for the life of
  a property. Never reuse a `prop_id` for a different `uuid`.

---

## 8. Error reference

| Status | When it happens | What to do |
|--------|-----------------|------------|
| `200` | Updated or unchanged | Success. |
| `201` | Created | Success. |
| `400` | Body isn't valid JSON, or `property` is present but not an object | Fix the payload; do not blindly retry. |
| `401` | `X-API-Key` header missing | Add the header. |
| `403` | `X-API-Key` is wrong | Check the secret. |
| `415` | `Content-Type` is not `application/json` | Set the header. |
| `422` | `property.id` (uuid) missing, or the data failed to save | Fix the payload (usually a missing/invalid `id`). |
| `500` | Unexpected server error | Safe to retry; if it persists, contact Cleardeals Tech with the timestamp and `id`. |
| `503` | API key not configured on the server | Contact Cleardeals Tech. |

**Retry guidance:** retry on `408`/`429`/`5xx`/network failures with exponential
backoff (e.g. 1s, 5s, 30s, a few times). Do **not** auto-retry `400`/`401`/`403`/
`415`/`422` — those need a fix, not a resend.

---

## 9. End-to-end examples (curl)

### Create a property

```bash
curl -X POST "https://odoo.cleardeals.xyz/api/v1/properties/webhook/create" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $CLEARDEALS_API_KEY" \
  -d '{
    "success": true,
    "property": {
      "id": "c68b54d6-ca00-4273-9a28-a722df42b02e",
      "property_name": "Parshwanath Society",
      "prop_id": "WZOO4IIQ",
      "form_no": "CD007075",
      "reg_date": "2026-06-09T00:00:00.000Z",
      "prop_type": "residential",
      "for_sell": true,
      "prop_sub_type": "Twin Bunglow",
      "exec_name": "Purvi Desai",
      "owner_name": "Mr. Jinal Shah",
      "owner_contact_no": "+91 97377-48067",
      "owner_email": "jinalshah@example.com",
      "gmaps_url": "https://www.google.com/maps/embed?pb=!...",
      "state": { "name": "Gujarat" },
      "city": { "name": "Ahmedabad" },
      "location_area": { "name": "Naranpura" },
      "details": { "bedroom_count": "5 BHK" },
      "sell_pricing": { "offer_price": 2.75, "offer_price_unit": "crore" },
      "rent_pricing": null,
      "media": [ { "media_type": "image", "file_path": "https://.../main.jpeg" } ]
    }
  }'
```

Response:

```json
{ "success": true, "data": { "id": 191, "uuid": "c68b54d6-...", "name": "Parshwanath Society", "_webhook_action": "created", "...": "..." } }
```

### Update a property (e.g. price change)

```bash
curl -X POST "https://odoo.cleardeals.xyz/api/v1/properties/webhook/update" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $CLEARDEALS_API_KEY" \
  -d '{
    "success": true,
    "property": {
      "id": "c68b54d6-ca00-4273-9a28-a722df42b02e",
      "property_name": "Parshwanath Society",
      "prop_id": "WZOO4IIQ",
      "for_sell": true,
      "sell_pricing": { "offer_price": 2.60, "offer_price_unit": "crore" }
    }
  }'
```

Response:

```json
{ "success": true, "data": { "id": 191, "pricing": 2.6, "_webhook_action": "updated", "...": "..." } }
```

### A rent listing

```jsonc
// for_sell=false → pricing read from rent_pricing
{
  "success": true,
  "property": {
    "id": "…", "property_name": "2BHK on rent", "prop_id": "RENT001",
    "for_sell": false,
    "sell_pricing": null,
    "rent_pricing": { "rent_price": 25000, "rent_price_unit": "thousand" }
  }
}
```

---

## 10. Delivery requirements & best practices

- **One property per request.** Don't batch multiple properties in one call.
- **Always include `property.id`.** It's the match key.
- **Keep `id` and `prop_id` stable and unique** across a property's lifetime.
- **Fire after commit.** Send the webhook once your DB transaction is committed,
  so the payload is the final state.
- **Use HTTPS** and keep the API key secret.
- **Implement retries** with backoff for `5xx`/timeouts (the upsert is idempotent,
  so retries are safe).
- **Set a sensible client timeout** (e.g. 30s) and treat a timeout as "unknown —
  retry", not "failed".
- **Log our response** (`status` + `_webhook_action` + `data.id`) on your side for
  reconciliation/debugging.
- If a webhook is ever permanently lost, no data is corrupted — Cleardeals Tech
  can run a one-off reconciliation against your API on request.

---

## 11. FAQ

**Do we need separate payloads for create vs update?**
No. The body is identical; just POST to the matching URL. Because the upsert is
idempotent, even sending to the "wrong" one is safe — but please route by event
so logs/metrics stay meaningful.

**What if we send the same create twice?**
The second call updates the existing record (or returns `unchanged`). No
duplicate is created.

**What happens to images we send in `media`?**
They're accepted and ignored for now. Keep sending them; storage may be added
later with no change required on your side.

**The RM isn't getting assigned — why?**
`exec_name` must match an Odoo user's name. If it doesn't, the property still
saves but with no RM. Send the name exactly as configured in Odoo.

**Can we delete a property via webhook?**
Not currently. Deletion/deactivation is handled inside Odoo. Contact Cleardeals
Tech if you need a delete/unpublish flow.

**Who do we contact for the API key or issues?**
The Cleardeals Tech team. Include the timestamp, the property `id`, and our
response body when reporting a problem.
```
