# API Documentation Standards

Based on Stripe's API documentation style — the gold standard for REST API docs.
Stripe's principle: every developer who reads your API docs should be able to
make their first successful call within 5 minutes without asking anyone.

---

## Structure of an API reference file

Every module that exposes a REST API must have a file at:
`custom_addons/{module}/docs/api.md`

### File structure

```markdown
# {Module} API Reference

**Base URL:** `https://{domain}/api/v1/{resource}`
**Authentication:** {method}
**Last updated:** {date} — version {module_version}

## Overview

[2–3 sentences: what this API does, who uses it, what it is NOT for]

## Authentication

[Exact steps to authenticate. Include the header name and format.
Include what happens on auth failure.]

## Endpoints

[One section per endpoint, in logical order — not alphabetical]

## Error reference

[All possible error codes and their meaning]

## Changelog

[API-level changes only — not code changes]
```

---

## Endpoint documentation format

Every endpoint gets this exact structure:

```markdown
### GET /api/v1/properties/:id

Returns a single property record by its Odoo database ID.

**Authentication required:** Yes — Bearer token or session cookie

**Path parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `id` | integer | Yes | The Odoo database ID of the property (`property.base.id`) |

**Query parameters:** None

**Request example:**

```bash
curl -X GET "https://odoo.cleardeals.cc/api/v1/properties/4521" \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json"
```

**Response — 200 OK:**

```json
{
  "id": 4521,
  "prop_id": "CD-4521",
  "name": "3 BHK Flat in Satellite",
  "bhk": "3 BHK",
  "city": "Ahmedabad",
  "location": "Satellite",
  "is_active": true,
  "portal_listings": [
    {
      "portal": "MagicBricks",
      "listing_id": "MB9871234",
      "label": "CD-4521 | MagicBricks | MB9871234",
      "is_active": true,
      "listed_on": "2024-01-15"
    },
    {
      "portal": "OLX",
      "listing_id": "OLX44556",
      "label": "CD-4521 | OLX | OLX44556",
      "is_active": false,
      "listed_on": "2023-08-01"
    }
  ]
}
```

**Response fields:**

| Field | Type | Nullable | Description |
|---|---|---|---|
| `id` | integer | No | Odoo database ID |
| `prop_id` | string | No | Short code, e.g. "CD-4521" |
| `portal_listings` | array | No | All portal listings. Empty array if none. |
| `portal_listings[].portal` | string | No | One of: "99acres", "Housing.com", "MagicBricks", "OLX" |
| `portal_listings[].is_active` | boolean | No | False = listing expired but ID still resolves |

**Error responses:**

| Status | Code | Description |
|---|---|---|
| 401 | `unauthorized` | Missing or invalid authentication |
| 404 | `not_found` | No property with this ID exists |
| 403 | `forbidden` | Authenticated user does not have access to this property |

**Notes:**
- `portal_listings` includes both active and inactive listings.
  Filter by `is_active: true` if you only want current listings.
- A property with no portal listings returns `"portal_listings": []`,
  not `null`.
```

---

## What makes Stripe-quality API docs

**1. Every parameter has an example value, not just a type**
Not `id (integer)` but `id (integer) — e.g. 4521`

**2. Every response shows real data, not placeholder JSON**
Not `{"name": "string"}` but `{"name": "3 BHK Flat in Satellite"}`

**3. Error cases are documented as prominently as success cases**
The happy path is obvious. What developers need is: what happens when
the ID doesn't exist, when auth fails, when the field is null.

**4. Nullable fields are always explicitly marked**
A developer should never have to test whether a field can be null.
Document it. Mark every field as nullable or not.

**5. The curl example is copy-pasteable**
Real URL, real headers, real auth format. A developer should be able
to paste it into their terminal and get a response.

**6. Breaking changes are marked prominently**
Any change that removes a field, changes a type, or changes a URL
must be in the CHANGELOG with a `BREAKING` label and a migration path.

---

## Documenting the Cleardeals properties API

### Current response shape documentation pattern

When documenting the serialiser in `controllers/serializers.py`,
add a docstring to the serialiser function:

```python
def serialize_property(record):
    """Serialise a property.base record to the API response shape.

    Returns a dict matching the documented API response for
    GET /api/v1/properties/:id.

    Fields included:
        Core identity: id, prop_id, uuid, name, property_tag
        Classification: prop_type, prop_sub_type, listing_type, bhk
        Location: state, city, location
        Pricing: pricing_display
        Ownership: owner_name, owner_phone, owner_email, rm_user_id
        Service: service_expiry_date_display, welcome_call_date_display
        Portal listings: portal_listings[] — see PortalListingSerializer

    Fields intentionally excluded:
        raw_data: internal field, not for external consumption
        gmaps_embed_html: HTML blob, not suitable for API response
        inventory_migrated: internal migration flag

    Returns:
        dict: Serialised property. Never None. Fields may be None if
            the source record has no value.
    """
```

---

## Controller method documentation

Every route handler in `controllers/controllers.py` must be documented:

```python
@http.route("/api/v1/properties/<int:property_id>", methods=["GET"], auth="user")
def get_property(self, property_id, **kwargs):
    """Return a single property by Odoo database ID.

    Args:
        property_id (int): The property.base record ID from the URL path.

    Returns:
        JSON response with the serialised property (HTTP 200), or:
            HTTP 404 if no property with this ID exists.
            HTTP 403 if the authenticated user cannot access this property.
            HTTP 401 if authentication is missing or invalid.

    Access control:
        Managers can access any property.
        RMs can only access properties where rm_user_id = current user,
        unless the search_all_properties_for_lead context is active.

    Example:
        GET /api/v1/properties/4521
        → 200 {"id": 4521, "prop_id": "CD-4521", ...}

        GET /api/v1/properties/99999
        → 404 {"error": "not_found", "message": "Property 99999 not found"}
    """
```