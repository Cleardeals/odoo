# Module README Template

Save as: `custom_addons/{module}/README.md`

Based on the internal README format used by Google, Stripe, and Shopify
engineering teams for internal service documentation. The goal: a developer
who has never seen this module should be productive in 15 minutes.

---

## Template

```markdown
# {Module Display Name}

> {One sentence. What this module does. Why it exists.}

**Module name:** `{technical_module_name}`
**Version:** `{manifest_version}`
**Last updated:** {date}
**Owner:** Cleardeals Tech

---

## What this module does

{3–5 sentences. Expand on the one-liner above. What is the module's
single responsibility? What does it own that nothing else should touch?
What does it explicitly NOT do?}

---

## Key models

| Model | Table | Purpose |
|---|---|---|
| `property.base` | `property_base` | Canonical property record — single source of truth for all property data |
| `property.portal.listing` | `property_portal_listing` | One-to-many portal listing IDs per property |

---

## Dependencies

| Depends on | Why |
|---|---|
| `base` | Standard Odoo base |
| `mail` | Chatter and activity tracking on property records |
| `leads` | Properties are linked to leads via leads.new.property_base_id |

**Important:** This module is a dependency of `leads` and `lead_suggestor`.
Changes to `property.base` fields or the REST API affect both.

---

## Data flow

{A short description or ASCII diagram of how data enters, moves through,
and leaves this module.}

```
BigQuery (source of truth)
    ↓  property_sync.py — every 3 hours
property_base (Odoo DB)
    ↓  property_portal_listing — linked many-to-one
Portal listing IDs (99acres, Housing.com, MagicBricks, OLX)
    ↓  resolve_property() — called by leads module
Matched to incoming portal leads
    ↓  REST API — /api/v1/properties
Consumed by mobile app, n8n, and external integrations
```

---

## Configuration

| Parameter | Location | Default | Description |
|---|---|---|---|
| BQ project ID | `ir.config_parameter` `bigquery.project_id` | — | Google Cloud project for BQ sync |
| Sync interval | `data/property_cron.xml` | 3 hours | How often property_sync.py runs |

---

## Security model

| Group | Read | Write | Create | Delete | Notes |
|---|---|---|---|---|---|
| `group_property_manager` | ✓ all | ✓ | ✓ | ✓ | Full access to all properties |
| `group_property_rm` | ✓ own only | ✗ | ✗ | ✗ | Own = rm_user_id = current user |
| RM (lead form context) | ✓ all active | ✗ | ✗ | ✗ | Via search_all_properties_for_lead context |

See `security/property_security.xml` for the exact ir.rule definitions.

---

## REST API

Base URL: `/api/v1/properties`

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/properties` | List properties with filters |
| `GET` | `/api/v1/properties/:id` | Get single property by ID |
| `POST` | `/api/v1/properties` | Create property (manager only) |
| `PUT` | `/api/v1/properties/:id` | Update property (manager only) |

Full API reference: `docs/api.md`

---

## Migration history

| Version | Migration file | Summary |
|---|---|---|
| `19.0.1.1.0` | `pre-seed_portal_listings.py` | Backfilled portal_portal_listing from flat fields |
| `19.0.1.2.0` | `pre-normalise_listing_labels.py` | Normalised label format |
| `19.0.1.3.0` | `pre-finalise_listing_labels.py` | Final label format: prop_id | portal | listing_id |

Planned:
| `19.0.1.4.0` | `post-drop_legacy_portal_columns.py` | Drop ninety_nine_acres_id etc. (CDLS-112) |

---

## Common operations

### Trigger a manual property sync
```python
env["property.base"].action_sync_from_bigquery()
```

### Find a property by portal listing ID
```python
prop = env["property.portal.listing"].resolve_property(
    portal="MagicBricks",
    portal_listing_id="MB9871234",
)
```

### Check which properties have no active portal listings
```sql
SELECT pb.prop_id, pb.name
FROM property_base pb
WHERE NOT EXISTS (
    SELECT 1 FROM property_portal_listing ppl
    WHERE ppl.property_base_id = pb.id AND ppl.active = TRUE
)
AND pb.active = TRUE;
```

---

## Known issues and limitations

- Portal listing IDs synced from BigQuery are overwritten on every sync cycle.
  Manual changes to listing IDs are preserved only if the field is not in
  `SYNC_FIELDS`. See `property_sync.py` for the current field list.

- `property_inventory.py` in `lead_suggestor` does a parallel BQ sync for
  the suggestor model. Changes to the sync logic must be applied in both files.

---

## Where to go for more

| Question | Where to look |
|---|---|
| How does lead-to-property matching work? | `leads/models/new_portal_leads.py` → `_find_property()` |
| Why does an RM see all properties on the lead form? | `security/property_security.xml` → `property_base_rule_rm` |
| What does the API return? | `controllers/serializers.py` → `serialize_property()` |
| Why was the portal listing model introduced? | `docs/decisions/ADR-001-portal-listing-model.md` |
```