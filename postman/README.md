# Square Yards Webhook — Postman Suite

Edge-case tests for the inbound Square Yards lead webhook:
`POST /api/v1/squareyards_webhook`.

## Files

- `SquareYards_Integration.postman_collection.json` — 13 requests with assertions.
- `SquareYards.postman_environment.json` — environment variables.

## Setup

1. **Import** both files into Postman and select the **SquareYards - Staging** environment.
2. Set the environment variables:
   | Variable | Meaning |
   |---|---|
   | `base_url` | Host of the target deploy, e.g. `https://staging.cleardeals.example` (no trailing slash). |
   | `squareyards_api_key` | The value of the Odoo system parameter `squareyards.webhook.api.key`. Requests fail with **503** until this is set on the server, and with **401** if this Postman value is wrong. |
   | `valid_property_id` | A Square Yards listing ID that **is** registered on a property in Odoo (`property.portal.listing`, portal = SquareYards). Drives the matched-property + duplicate tests. |
   | `unmatched_property_id` | A listing ID that is **not** registered, to exercise the fallback-RM path. |
3. In Odoo, make sure one property has a SquareYards portal listing whose ID equals `valid_property_id`.

## Running

Use the **Collection Runner** and run the collection top-to-bottom. Order matters:
request **04** creates a lead and request **05** resends it to prove de-duplication.
Each run generates fresh random phone numbers, so the suite is safe to run repeatedly
without tripping duplicate suppression.

## What each request asserts

| # | Request | Expect |
|---|---|---|
| 01 | Missing `apikey` | 401 |
| 02 | Wrong `apikey` | 401 |
| 03 | `X-API-KEY` fallback header | 200 |
| 04 | Happy path, matched property | 200 + "Success" |
| 05 | Duplicate resend of 04 | 200 (no second lead in Odoo) |
| 06 | WhatsApp flow (`mobile`+`propertyId` only, no name) | 200 (name → "SquareYards Lead") |
| 07 | Unmatched `propertyId` | 200 (fallback RM, no property link) |
| 08 | `+91`-prefixed mobile | 200 (stored as 10 digits) |
| 09 | Extra / unknown fields | 200 (ignored, kept in `raw_data`) |
| 10 | Missing `mobile` | 400 |
| 11 | Missing `propertyId` | 400 |
| 12 | Malformed JSON body | 400 |
| 13 | `GET` instead of `POST` | 405 |

## Notes

- The webhook returns **200 for de-duplicated leads** (a resend is acknowledged, not an
  error). Requests 05 verifies the HTTP status; confirm "no second lead" in Odoo.
- Only `mobile` and `propertyId` are required. `propertyId` is Square Yards' internal
  listing ID and the single property-match key (the "Unique PID" is not used).
