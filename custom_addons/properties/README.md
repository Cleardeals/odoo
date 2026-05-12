# Properties Module — Complete Model Reference

> Central property data store for the Cleardeals system. Single source of truth for all property records — synced from the Cleardeals website API, cross-referenced with BigQuery, and linked to leads and portal listings.

**Module name:** `properties`  
**Odoo version:** `19.0`  
**License:** `LGPL-3`  
**Last updated:** `2026-05-08`  
**Owner:** Cleardeals Tech

---

## Quick navigation

- [Module overview](#module-overview)
- [Model index](#model-index)
- [Model: `property.base`](#model-propertybase) — canonical property record
- [Model: `property.portal.listing`](#model-propertyportallisting) — portal listing per property
- [Cross-model relationships](#cross-model-relationships)
- [API sync architecture](#api-sync-architecture)
- [Field ownership groups](#field-ownership-groups)

---

## Module overview

The `properties` module owns the `property.base` model — the canonical representation of every property in the Cleardeals system. It also owns `property.portal.listing`, which maps a property to one or more listing IDs on external real-estate portals (99acres, Housing.com, MagicBricks, OLX).

Data flows from two sources:

1. **Cleardeals Website API** (`https://api.cleardeals.cc/api/v1/properties`) — synced by a daily cron job. Writes only the API-writable fields.
2. **Legacy `property.inventory`** (in `lead_suggestor`) — one-time migration cron populates the manager-editable fields (service expiry date, welcome call date, portal IDs, property tag) from the legacy table. The API cron never touches these.

The `leads` module extends `property.base` (in `leads/models/property_base_extend.py`) to add portal-ID-change hooks for lead relinking. The `lead_suggestor` module extends `property.base` (in `lead_suggestor/models/property_base_ext.py`) to add suggestion counts.

---

## Model index

| Model | DB table | Purpose |
|---|---|---|
| `property.base` | `property_base` | Canonical property record — single source of truth |
| `property.portal.listing` | `property_portal_listing` | Maps a property to a portal listing ID |

---

## Model: `property.base`

**DB table:** `property_base`  
**Description:** The single source of truth for all property data in the Cleardeals system. Fields are divided into ownership groups based on who (or what process) writes them.

**Inherits:** `mail.thread`, `mail.activity.mixin` (chatter + activity tracking)  
**Order:** `reg_date desc, name`  
**Record name:** `name`

### SQL constraints

| Constraint | Rule |
|---|---|
| `_uuid_uniq` | `uuid` must be globally unique |
| `_prop_id_uniq` | `prop_id` (short code) must be globally unique |

---

### Group PROP-2.1 — API-sourced fields

> **Written by:** `_cron_sync_from_api()` only (scheduled daily).  
> **Never edited** in the UI — displayed as readonly.  
> **API writable fields set:** `uuid`, `prop_id`, `form_no`, `name`, `reg_date`, `prop_type`, `for_sell`, `prop_sub_type`, `state`, `city`, `location`, `rm_user_id`, `owner_name`, `owner_phone`, `owner_email`, `pricing`, `pricing_unit`, `gmaps_url`, `bedroom_count`

| Field | Type | Stored | Description |
|---|---|---|---|
| `uuid` | `Char` | ✓ | UUID assigned by the Cleardeals website API. Not the same as Odoo's internal database ID. Readonly. Indexed. |
| `prop_id` | `Char` | ✓ | 6-character alphanumeric short-code (e.g. `GBH75X0K`). Used by the website and certain API endpoints. Readonly. Indexed. |
| `form_no` | `Char` | ✓ | Unique form number from the website API. Matches `Form_Number` in BigQuery `Customer_Data` table. Used as the stable cross-model key for migration from `property.inventory`. Readonly. Indexed. |
| `name` | `Char` | ✓ | Full marketing name of the property as shown on the website. Readonly. Tracking enabled. |
| `reg_date` | `Date` | ✓ | Date the property was onboarded onto the Cleardeals platform. Readonly. Indexed. |
| `prop_type` | `Char` | ✓ | Broad classification (e.g. `Residential`, `Commercial`). Readonly. |
| `for_sell` | `Boolean` | ✓ | `True` = listed for sale; `False` = listed for rent. Readonly. Indexed. |
| `prop_sub_type` | `Char` | ✓ | Detailed classification (e.g. `Apartment`, `Villa`, `Office`). Readonly. |
| `state` | `Char` | ✓ | State where the property is located (plain text, not relational). Readonly. |
| `city` | `Char` | ✓ | City where the property is located. Readonly. |
| `location` | `Char` | ✓ | Micro-location or locality within the city. Readonly. |
| `rm_user_id` | `Many2one → res.users` | ✓ | Relationship Manager assigned on the website. Readonly. Indexed. |
| `owner_name` | `Char` | ✓ | Property owner's full name. Readonly. Tracking enabled. |
| `owner_phone` | `Char` | ✓ | Property owner's phone number (10-digit normalized). Readonly. |
| `owner_email` | `Char` | ✓ | Property owner's email address. Readonly. |
| `pricing` | `Float` | ✓ | Sell price (`for_sell=True`) or rent price (`for_sell=False`). Precision: 16,2. Readonly. |
| `pricing_unit` | `Char` | ✓ | Unit of `pricing` (e.g. `lakh`, `crore`, `thousand`). Readonly. |
| `gmaps_url` | `Char` | ✓ | Google Maps embed URL for the property location. Readonly. |
| `bedroom_count` | `Integer` | ✓ | Number of bedrooms (BHK count) from the API. Readonly. |

---

### Group PROP-2.2 — Computed fields

> **Written by:** ORM compute methods only.  
> **No manual input.** Values derived from stored API fields.

| Field | Type | Stored | Description |
|---|---|---|---|
| `property_link` | `Char` | ✓ | Canonical Cleardeals URL built from `name` + `prop_id`. Format: `https://www.cleardeals.in/property/{slug}-{prop_id}`. Used as matching key in BigQuery cross-references. Readonly. |
| `bhk` | `Char` | ✓ | Human-readable bedroom label derived from `bedroom_count` (e.g. `2 BHK`). Empty string when `bedroom_count = 0`. Readonly. |
| `prop_type_display` | `Char` | ✗ | Capitalised `prop_type` label (e.g. `Residential`). Not stored — rendered on each read. |
| `listing_type` | `Char` | ✗ | `Sell` when `for_sell=True`, `Rent` otherwise. Not stored. |
| `pricing_display` | `Char` | ✗ | Combined pricing display (e.g. `48 Lakh` or `25 Thousand/month`). Not stored. |
| `is_new` | `Boolean` | ✗ | `True` when `reg_date` is within the last 3 days. Not stored. |
| `gmaps_embed_html` | `Html` | ✗ | Embedded Google Maps `<iframe>` HTML rendered from `gmaps_url`. `sanitize=False`. Not stored. |
| `service_expiry_date_display` | `Char` | ✗ | `service_expiry_date` formatted as `DD/MM/YYYY`. Not stored. |
| `welcome_call_date_display` | `Char` | ✗ | `welcome_call_date` formatted as `DD/MM/YYYY`. Not stored. |

---

### Group PROP-2.3 + PROP-2.4 — Manager-editable / migration-origin fields

> **Written by:** `_cron_sync_from_inventory()` once on migration, then only via the manager UI.  
> **The API cron NEVER writes to these fields.**  
> These fields were originally populated from `property.inventory` (BigQuery Customer_Data table) and are editable only by users with the `properties.group_property_manager` group.

| Field | Type | Stored | Description |
|---|---|---|---|
| `property_tag` | `Char` | ✓ | Short display tag used in the lead-suggestor pipeline (e.g. `B-505, Green Heights`). Migrated from `property.inventory`. Editable by managers. Indexed. Tracking enabled. |
| `ninety_nine_acres_id` | `Char` | ✓ | Property listing ID on the 99acres portal. Indexed. |
| `housing_id` | `Char` | ✓ | Property listing ID on the Housing.com portal. Indexed. |
| `magicbricks_id` | `Char` | ✓ | Property listing ID on the Magicbricks portal. Indexed. |
| `olx_id` | `Char` | ✓ | Property listing ID on the OLX portal. Indexed. |
| `service_expiry_date` | `Date` | ✓ | Date the Cleardeals service contract expires. Pre-filled from migration; editable by managers. Indexed. Tracking enabled. |
| `welcome_call_date` | `Date` | ✓ | Date of the welcome call with the owner. Not sourced from API; set manually by managers. Tracking enabled. |

---

### Group PROP-2.5 — System / status fields

| Field | Type | Stored | Default | Description |
|---|---|---|---|---|
| `is_active` | `Boolean` | ✓ | `True` | Set to `False` automatically by the expiry-cleanup cron when `service_expiry_date` passes today. Indexed. Tracking enabled. |
| `inventory_migrated` | `Boolean` | ✓ | `False` | Internal flag. Set to `True` by `_cron_sync_from_inventory()` once the manager-editable fields have been populated from the legacy record. Prevents repeated re-migration. Indexed. Readonly. |

---

### Extension fields added by other modules

These fields are added to `property.base` by other modules via `_inherit`. They live in `property_base` table.

**From `lead_suggestor` module** (`lead_suggestor/models/property_base_ext.py`):

| Field | Type | Stored | Description |
|---|---|---|---|
| `suggestion_ids` | `One2many → property.lead.suggestion` | ✗ | All lead suggestions linked to this property. |
| `suggestion_count` | `Integer` | ✓ (computed) | Total count of `suggestion_ids`. |
| `new_suggestion_count` | `Integer` | ✓ (computed) | Count of `suggestion_ids` where `status='new'`. |

---

## Model: `property.portal.listing`

**DB table:** `property_portal_listing`  
**Description:** Maps a `property.base` record to a specific listing ID on an external portal. A single property can have multiple portal listings (one per portal, or multiple per portal for different listing IDs). Used by the lead assignment engine to match incoming portal leads to the correct property.

**Order:** `portal_name, portal_listing_id, id`

| Field | Type | Required | Stored | Description |
|---|---|---|---|---|
| `property_base_id` | `Many2one → property.base` | ✓ | ✓ | Parent property. `ondelete=cascade`. Indexed. |
| `portal_name` | `Selection` | ✓ | ✓ | Portal identifier. Values: `99acres`, `Housing.com`, `MagicBricks`, `OLX`. Required. Indexed. Default: from `context['default_portal_name']` if set. |
| `portal_listing_id` | `Char` | ✓ | ✓ | The listing identifier as used by the portal (e.g. OLX `adId`, 99acres listing number). Required. Indexed. |
| `listing_label` | `Char` | — | ✓ | Human-readable label (e.g. `GBH75X0K \| B-505, Green Heights \| 19684263`). Auto-generated from `prop_id + portal_name + portal_listing_id` if not provided. |
| `active` | `Boolean` | — | ✓ | Soft-delete flag. Default: `True`. Indexed. |

**Constraint:** `_portal_listing_uniq` — `(portal_name, portal_listing_id)` must be globally unique.

**Chatter auditing:** `create`, `write`, and `unlink` all post formatted notes to the linked `property_base_id` chatter. If a listing is moved to a different property, both old and new properties receive chatter notes.

### How this connects to lead routing

When a portal lead arrives:

1. `leads.new._process_lead_logic()` reads `portal_name` and `portal_property_id` from the lead.
2. It searches `property.portal.listing` for a record matching `(portal_name, portal_listing_id)`.
3. If found → lead is linked to the listing's `property_base_id` and assigned to that property's `rm_user_id`.
4. If not found → lead stays unlinked and goes to the source-level fallback RM.

**Retroactive relinking:** When a `property.portal.listing` record is created or its `portal_listing_id` is updated, the `leads` module's `PropertyPortalListingLeadRelink` hook automatically finds all previously unlinked leads matching that portal+listing-ID and links them retroactively.

---

## Cross-model relationships

```
property.base (property_base)
 ├── rm_user_id               → res.users
 ├── portal_listings          ← property.portal.listing (one2many)
 ├── suggestion_ids           ← property.lead.suggestion (one2many, via lead_suggestor)
 └── (referenced by)
     ├── leads.new.property_base_id
     ├── lead.property.interest.property_base_id
     ├── lead.site.visit.property_base_id
     └── property.lead.suggestion.property_base_id

property.portal.listing (property_portal_listing)
 └── property_base_id         → property.base
```

---

## API sync architecture

### Cleardeals Website API

- **Endpoint:** `GET https://api.cleardeals.cc/api/v1/properties`
- **Pagination:** `limit=100` per page; iterates until no more pages.
- **Cron frequency:** Daily.
- **Matching key:** `uuid` field — if a record with this `uuid` already exists, it is updated; otherwise created.
- **Write scope:** Only `API_WRITABLE_FIELDS` — never touches `service_expiry_date`, `welcome_call_date`, `property_tag`, or any portal ID.

### BigQuery migration cron (`_cron_sync_from_inventory`)

- **Source:** `cleardeals-459513.cleardeals_dataset.Customer_Data`
- **Matching key:** `form_no` on `property.base` ↔ `Form_Number` in BigQuery.
- **Purpose:** One-time population of manager-editable fields from the legacy `property.inventory` table.
- **Idempotency:** Once `inventory_migrated=True` on a record, the cron skips it.

### Expiry cleanup cron

- Runs daily.
- Sets `is_active=False` on any `property.base` record where `service_expiry_date < today`.

---

## Field ownership groups

| Group | Fields | Writeable by |
|---|---|---|
| PROP-2.1 (API-sourced) | `uuid`, `prop_id`, `form_no`, `name`, `reg_date`, `prop_type`, `for_sell`, `prop_sub_type`, `state`, `city`, `location`, `rm_user_id`, `owner_name`, `owner_phone`, `owner_email`, `pricing`, `pricing_unit`, `gmaps_url`, `bedroom_count` | API cron only |
| PROP-2.2 (Computed) | `property_link`, `bhk`, `prop_type_display`, `listing_type`, `pricing_display`, `is_new`, `gmaps_embed_html`, `*_display` dates | ORM compute only |
| PROP-2.3 + 2.4 (Manager-editable) | `property_tag`, `ninety_nine_acres_id`, `housing_id`, `magicbricks_id`, `olx_id`, `service_expiry_date`, `welcome_call_date` | Migration cron (once) + managers via UI |
| PROP-2.5 (System) | `is_active`, `inventory_migrated` | Cron jobs only |
