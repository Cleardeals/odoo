# Square Yards → Cleardeals Lead Webhook — Integration Guide

**Audience:** Square Yards engineering team
**Purpose:** Push real-time buyer leads from Square Yards into the Cleardeals CRM.
**Status:** Ready for integration. The endpoint is live once Cleardeals provisions your API key.

---

## 1. Overview

When a buyer submits an enquiry on a Cleardeals property listed on Square Yards,
Square Yards sends that lead to Cleardeals via a single HTTPS `POST` request.
Cleardeals creates the lead, matches it to the property, and assigns it to the
right Relationship Manager (RM) automatically.

```
Buyer enquiry on Square Yards
        │
        ▼
POST /api/v1/squareyards_webhook   (this document)
        │
        ▼
Cleardeals CRM: create lead → match property by propertyId → assign RM
```

---

## 2. Endpoint

| | |
|---|---|
| **Method** | `POST` |
| **Production URL** | `https://<PROD_HOST>/api/v1/squareyards_webhook` |
| **Content-Type** | `application/json` |

> The exact `PROD_HOST` values are shared with you separately
> by the Cleardeals team along with your API key.

---

## 3. Authentication

Every request must include a shared secret in the **`apikey`** HTTP header:

```
apikey: <YOUR_SHARED_SECRET>
```

- The secret is provisioned by Cleardeals and delivered to you out-of-band
  (not in this document). Treat it as a credential.
- Requests with a missing or wrong key are rejected with **`401`**.
- If Cleardeals has not yet configured the integration on their side, requests
  return **`503`** — in that case, retry later or contact Cleardeals.
- Key rotation: contact your Cleardeals technical contact (Section 9). A rotated
  key takes effect immediately; coordinate the switch to avoid a gap.

---

## 4. Request schema

Two kinds of leads are supported. **Only `mobile` and `propertyId` are required**
in both; everything else is optional.

| Field | Type | Required | Notes |
|---|---|:---:|---|
| `mobile` | string | **Yes** | Buyer's mobile number. 10-digit Indian, or `+91`-prefixed — both accepted. |
| `propertyId` | string | **Yes** | **Square Yards' internal listing ID.** This is the key Cleardeals uses to match the lead to the property. See Section 5. |
| `name` | string | No | Buyer's name. Absent for WhatsApp-button leads — Cleardeals stores a default name in that case. |
| `email` | string | No | Buyer's email. |
| `source` | string | No | Constant `"SquareYards"`. Informational; Cleardeals tags the source regardless. |
| `projectName` | string | No | Project / society name. |
| `cityName` | string | No | Stored for reference. |
| `sublocalityName` | string | No | Stored for reference. |
| `propertyTypeName` | string | No | e.g. `Apartment`. Stored for reference. |
| `unitType` | string | No | e.g. `3bhk`. Stored for reference. |
| `availArea` | number | No | Stored for reference. |
| `totalPrice` | number | No | Stored for reference. |
| `listingType` | string | No | `rent` or `sale`. Stored for reference. |

**Two lead flows (for context):**

- **Standard form lead** — includes `name`, `mobile`, `email`, `propertyId`.
- **WhatsApp-button lead** — includes only `mobile` and `propertyId` (no name/email).

All fields not explicitly consumed are stored verbatim by Cleardeals for reference,
so sending extra/unknown fields is safe (they are ignored, never rejected).

> **Note — which ID to send.** Your upload API lets a partner store their own
> property identifier (a "Unique PID", e.g. the Cleardeals website's ID) against
> a listing. Cleardeals currently onboards its Square Yards listings **manually**,
> so **no Cleardeals Unique PID is stored** against them — the only identifier
> that exists is **Square Yards' own listing ID**. Send that Square Yards listing
> ID in `propertyId`; that is the value Cleardeals registers and matches on. Do
> **not** send a Unique PID. (If Cleardeals moves to API-based uploads later and a
> Unique PID is stored, we will revisit this guidance.)

---

## 5. How property matching works

`propertyId` must be the **same listing ID Cleardeals has registered for that
property under the "SquareYards" portal.** When it matches, the lead is linked to
the property and assigned to that property's RM. When it does not match (or the
property has not been registered yet), the lead is still accepted and routed to a
default fallback RM — no lead is ever dropped.

---

## 6. Sample requests

**Standard form lead:**

```bash
curl -X POST "https://<PROD_HOST>/api/v1/squareyards_webhook" \
  -H "Content-Type: application/json" \
  -H "apikey: <YOUR_SHARED_SECRET>" \
  -d '{
    "name": "Sy User",
    "mobile": "9876543210",
    "email": "sy.user@example.com",
    "source": "SquareYards",
    "projectName": "DLF",
    "cityName": "Gurgaon",
    "sublocalityName": "Sector 55",
    "propertyTypeName": "Apartment",
    "unitType": "3bhk",
    "availArea": 100,
    "totalPrice": 50000,
    "listingType": "rent",
    "propertyId": "123456"
  }'
```

**WhatsApp-button lead (minimal):**

```bash
curl -X POST "https://<PROD_HOST>/api/v1/squareyards_webhook" \
  -H "Content-Type: application/json" \
  -H "apikey: <YOUR_SHARED_SECRET>" \
  -d '{
    "mobile": "9876543210",
    "propertyId": "123456",
    "source": "SquareYards"
  }'
```

---

## 7. Responses

The response body is plain text; **rely on the HTTP status code**.

| Status | Meaning | Your action |
|---|---|---|
| `200` | Lead accepted. Also returned for a **duplicate** lead (silently de-duplicated). | Treat as success. |
| `400` | Missing a required field (`mobile` / `propertyId`) or malformed JSON. | Fix the payload; do not retry unchanged. |
| `401` | Missing or wrong `apikey`. | Check the credential; do not retry unchanged. |
| `405` | Wrong HTTP method (must be `POST`). | Use `POST`. |
| `503` | Integration not yet configured on the Cleardeals side. | Retry later / contact Cleardeals. |
| `5xx` | Temporary server error. | Retry with backoff (Section 8). |

**Sample success (`200`):**

```
Success: Lead punched in the CRM
```

**Sample validation error (`400`):**

```
Failed to push lead: Missing required fields.
```

---

## 8. Idempotency & retries

- **Duplicates are safe.** If you resend the same lead (same mobile + same
  property within the suppression window), Cleardeals de-duplicates it and still
  returns `200`. Re-sending never creates a duplicate lead.
- **Retry only on `5xx` and network errors,** using exponential backoff
  (e.g. 1s, 5s, 30s). Because duplicates are de-duplicated, a retry after an
  uncertain outcome is safe.
- **Do not retry `400` / `401`** without changing the request — the outcome will
  be identical.

---

## 9. Contacts & change log

**Cleardeals technical contact:** _Nirat Patel / tech@cleardeals.in_

**Change log**

| Date | Version | Change |
|---|---|---|
| _2026-07-01_ | 1.0 | Initial integration guide. |
