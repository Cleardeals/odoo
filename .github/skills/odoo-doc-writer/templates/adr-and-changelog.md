# ADR and CHANGELOG Templates

---

## Architecture Decision Record (ADR)

ADRs answer the question future developers will always ask:
"Why did they do it this way?"

Based on Michael Nygard's ADR format, used at Google, GitHub, and Shopify.

**Key rules:**
- ADRs are immutable once accepted. Never edit an ADR to change a decision.
  Write a new ADR that supersedes the old one.
- ADRs record the context at the time of the decision — the constraints,
  the options considered, the tradeoffs. Not the final answer alone.
- An ADR with only the decision and no context is useless. The decision
  is already in the code. The context is what only this document captures.

**Save at:** `custom_addons/{module}/docs/decisions/ADR-{NNN}-{slug}.md`

### Template

```markdown
# ADR-001: Use a unified property.portal.listing model instead of per-portal models

**Date:** 2024-XX-XX
**Status:** Accepted
**Deciders:** Cleardeals Tech
**Epic:** CDLS-100

---

## Context

Each property currently stores one portal listing ID per portal as a flat
Char field on property.base: ninety_nine_acres_id, housing_id, magicbricks_id,
olx_id. This model assumes one listing ID per property per portal.

The business requirement changed: a single property can now be listed at
multiple price points or under different agent accounts on the same portal.
Each listing generates its own leads with its own portal ID. The flat field
model cannot represent this.

Two architectural options were considered:

**Option A — One model per portal**
Four separate models: `property.99acres.listing`, `property.housing.listing`,
`property.magicbricks.listing`, `property.olx.listing`.

Pros:
- Type safety — impossible to create a Housing.com listing with an OLX ID
- Each model can have portal-specific fields without polluting others

Cons:
- Four models, four access CSV rows, four views, four ORM registrations
- Adding a fifth portal (e.g. NoBroker) requires a new model
- Lead webhook resolution requires branching on portal name to choose model
- No single query across all portal IDs for a property

**Option B — Single unified model with portal as a Selection field**
One model: `property.portal.listing` with portal_name as a Selection field.

Pros:
- One model, one access CSV section, one view
- Adding a fifth portal requires only a new Selection option + migration
- `resolve_property(portal, listing_id)` is a single clean method
- Can query "all listings for this property" in one ORM call

Cons:
- No compile-time enforcement that the portal value is valid
  (mitigated by Selection field constraint + unique constraint)
- Portal-specific fields would require nullable columns for non-applicable portals
  (currently no portal-specific fields exist, so this is a hypothetical concern)

---

## Decision

Option B — single unified `property.portal.listing` model.

The primary driver was the lead resolution path: `_find_property()` needed to
resolve any incoming portal ID to a property. With Option A, this would require
four separate searches. With Option B, it is one `resolve_property()` call.

The addition of a fifth portal (which is planned for NoBroker) requires only
a new Selection value in Option B. In Option A it would require a new model,
new migrations, new security rows, and view changes.

---

## Consequences

**Positive:**
- Lead resolution is a single method: `resolve_property(portal, listing_id)`
- Adding new portals is a configuration change, not a model change
- The Portal Listings tab in the property form can show all portals in one view

**Negative / watch points:**
- The portal_name field is a string Selection — its values must match exactly
  between the model, the webhook handler's PORTAL_NAME_MAP, and the migration
  scripts. A typo in one place causes silent lookup failures.
- If portals ever need portal-specific fields, the unified model becomes awkward.
  At that point, reconsider Option A (supersede this ADR).

**Supersedes:** Nothing
**Superseded by:** (if this decision is ever reversed, link the new ADR here)
```

---

## CHANGELOG template

Based on the Keep a Changelog format (keepachangelog.com), used by
Stripe, GitHub, and most major open source projects.

**Key rules:**
- Newest version at the top
- Changes grouped by type: Added, Changed, Deprecated, Removed, Fixed, Security
- Each entry is one bullet: what changed and why (not how)
- Breaking changes are marked `[BREAKING]` — always include migration path
- API changes get their own sub-section under the version

**Save at:** `custom_addons/{module}/CHANGELOG.md`

### Template

```markdown
# Changelog — {module_display_name}

All notable changes to this module are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)

---

## [19.0.1.3.0] — 2024-XX-XX

### Added
- `property.portal.listing` model: supports multiple portal listing IDs
  per property across 99acres, Housing.com, MagicBricks, and OLX (CDLS-100)
- Portal Listings tab on property form view: grouped by portal, editable
  by managers
- `resolve_property(portal, listing_id)` classmethod: single entry point
  for lead-to-property resolution across all portals

### Changed
- `_find_property()` in leads module now uses `resolve_property()` instead
  of searching flat portal ID fields directly (CDLS-131)
- Properties API response: portal IDs now returned as `portal_listings[]`
  array instead of four flat fields. See API changelog below.

### Deprecated
- `ninety_nine_acres_id`, `housing_id`, `magicbricks_id`, `olx_id` fields
  on `property.base` are deprecated. Still present in DB and code until
  CDLS-112, but should not be used in new code. Use `portal_listing_ids`
  One2many instead.

### Migration
- `19.0.1.1.0/pre-seed_portal_listings.py`: backfills portal_portal_listing
- `19.0.1.2.0/pre-normalise_listing_labels.py`: normalises labels
- `19.0.1.3.0/pre-finalise_listing_labels.py`: finalises label format

### API changes (v1)

**[BREAKING] GET /api/v1/properties/:id**

Portal ID fields removed from response. Replaced with `portal_listings[]`:

Before:
```json
{
  "ninety_nine_acres_id": "99A-12345",
  "housing_id": null,
  "magicbricks_id": "MB9871234",
  "olx_id": null
}
```

After:
```json
{
  "portal_listings": [
    {"portal": "99acres", "listing_id": "99A-12345", "is_active": true},
    {"portal": "magicbricks", "listing_id": "MB9871234", "is_active": true}
  ]
}
```

Migration: update consumers to read `portal_listings[]` instead of flat fields.

---

## [19.0.1.0.0] — 2024-XX-XX

### Added
- Initial release of properties module
- `property.base` model with BQ sync via `property_sync.py`
- REST API at `/api/v1/properties`
- Manager and RM security groups
```

---

## When to write an ADR vs a comment vs a README section

| Situation | Write |
|---|---|
| "Why did we choose One model over four?" | ADR |
| "Why is this field readonly here?" | Inline comment |
| "Why does resolve_property prefer active listings?" | Method docstring Note: section |
| "What does this module do?" | README |
| "What changed in this version?" | CHANGELOG |
| "Why does sudo() appear here?" | Inline comment |
| "Why do we use HMAC for Housing.com auth?" | ADR or method docstring |
| "Why is the cron every 15 minutes not every hour?" | ADR (operational decision) |