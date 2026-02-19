# Track API — Quick Start

**Base URL:** `https://odoo.cleardeals.xyz`

All endpoints return JSON with the envelope `{ "success", "data", "error" }`.  
All endpoints accept `phone` in any format (`9876543210`, `+919876543210`, `919876543210`).

---

## Authentication

Add the header to every request **except** `GET /api/track/lead/activity`:

```
X-API-Key: your-secret-key
```

---

## Buyer endpoints

### Get buyer site visits (5 buckets)

```bash
curl -H "X-API-Key: your-key" \
  "https://odoo.cleardeals.xyz/api/track/lead/site-visits?phone=9876543210"
```

Returns: `upcoming`, `pending_feedback`, `cancelled`, `rescheduled`, `completed` arrays + `totals`.

---

### Get buyer full activity (no auth needed)

```bash
curl "https://odoo.cleardeals.xyz/api/track/lead/activity?phone=9876543210"
```

Returns: `summary` counts + `primary_inquiries[]` with `recommended_properties[]` nested inside each.

---

## Seller endpoints

All seller endpoints require `X-API-Key`.

### Portfolio summary (inquiry counts by portal)

```bash
curl -H "X-API-Key: your-key" \
  "https://odoo.cleardeals.xyz/api/track/property/summary?phone=9876543210"
```

### Portal performance breakdown

```bash
# All properties
curl -H "X-API-Key: your-key" \
  "https://odoo.cleardeals.xyz/api/track/property/portal-performance?phone=9876543210"

# Single property
curl -H "X-API-Key: your-key" \
  "https://odoo.cleardeals.xyz/api/track/property/portal-performance?phone=9876543210&property_tag=CLR-2BHK-MNG-001"
```

### Site visits (seller view)

```bash
curl -H "X-API-Key: your-key" \
  "https://odoo.cleardeals.xyz/api/track/property/site-visits?phone=9876543210"
```

### All lead activity (paginated)

```bash
# Page 1, 50 per page (defaults)
curl -H "X-API-Key: your-key" \
  "https://odoo.cleardeals.xyz/api/track/property/activity?phone=9876543210"

# Page 2, 25 per page, single property
curl -H "X-API-Key: your-key" \
  "https://odoo.cleardeals.xyz/api/track/property/activity?phone=9876543210&property_tag=TAG1&page=2&page_size=25"
```

### Conversion funnel

```bash
curl -H "X-API-Key: your-key" \
  "https://odoo.cleardeals.xyz/api/track/property/funnel?phone=9876543210"
```

### AI-generated lead suggestions (paginated)

```bash
curl -H "X-API-Key: your-key" \
  "https://odoo.cleardeals.xyz/api/track/property/ai-suggestions?phone=9876543210"
```

---

## Common error patterns

```js
// Check before using data
if (!response.success) {
  console.error(response.error.code, response.error.message);
  return;
}
const data = response.data;
```

| Status | Meaning                                   |
|--------|-------------------------------------------|
| `400`  | Missing or invalid `phone`/`page` params  |
| `401`  | `X-API-Key` header absent                 |
| `403`  | Wrong API key                             |
| `404`  | No records found for that phone/tag       |
| `500`  | Server misconfiguration                   |

---

See [API_DOCUMENTATION.md](./API_DOCUMENTATION.md) for complete schemas, all field descriptions, and full response examples.
