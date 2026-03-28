# Lead Scoring and Automation Engine

> Centralized lead ingestion, source normalization, assignment automation, and RM execution workflows for Cleardeals.

**Module name:** `leads`  
**Version:** `1.1.0`  
**Odoo version:** `19.0`  
**License:** `LGPL-3`  
**Last updated:** `2026-03-28`  
**Owner:** Cleardeals Tech

---

## What this module does

The leads module ingests buyer inquiries from webhooks, cron pulls, and manual channels, standardizes source metadata, resolves property links, and routes leads to RMs. It keeps two operational layers in sync:

- `leads.new`: ingestion and assignment layer
- `lead.score`: scored and follow-up layer

The module owns lead-source normalization (`lead.source`), duplicate control, assignment fallback behavior, WhatsApp response workflows, and seller/buyer lead analytics endpoints.

---

## Key models

| Model | Purpose |
|---|---|
| `leads.new` | Canonical lead ingestion and assignment record |
| `lead.score` | Scored lead lifecycle and follow-up workflow |
| `lead.source.category` | Source classification (`portal` vs `manual`) |
| `lead.source` | Source registry including portal code and fallback RM routing |
| `lead.property.interest` | Recommended property links and visit tracking |
| `whatsapp.response` | WhatsApp response tracking and RM processing |

---

## Lead source architecture (current)

1. `source_id` is required during lead creation.
2. `portal_name` input is normalized through `_get_or_create_source()`.
3. Known portal aliases resolve through `_canonical_portal_code()`.
4. If portal property resolution fails, assignment uses source-level `Fallback RM`.
5. If no fallback RM is configured, system assigns Administrator and records clear process notes.

### Canonical portal mapping

| Input aliases | Canonical code |
|---|---|
| `99acres` | `99acres` |
| `housing`, `housing.com` | `Housing.com` |
| `magicbricks`, `magicbricks.com` | `MagicBricks` |
| `olx` | `OLX` |

---

## Navigation map (backend)

Current user-facing paths in this module:

- `Leads > Lead Operations > Leads`
- `Leads > Lead Operations > All Scored Leads`
- `Leads > Lead Operations > My Actionable Leads`
- `Leads > Lead Operations > Import Scored Leads (BQ)`
- `Leads > Lead Operations > Import Leads File`
- `Leads > Lead Operations > Settings > Sources`
- `Leads > Lead Operations > Settings > Source Categories`
- `Leads > Lead Operations > WhatsApp Replies > Inbox`
- `Leads > Lead Operations > WhatsApp Replies > Positive Replies`

---

## Ingestion and processing flow

```text
Portal webhook / Housing cron / CSV import
    -> create_lead_if_not_duplicate()
    -> leads.new.create() with normalized source
    -> _process_lead_logic()
       -> resolve property from source + listing ID
       -> assign property RM OR source fallback RM
       -> if none configured, assign Administrator
    -> optional webhook dispatch / analytics consumption
```

---

## Configuration

### System parameters

| Key | Description |
|---|---|
| `google.bq.project_id` | BigQuery project for lead-score imports |
| `magicbricks.api.key` | API key for MagicBricks webhook validation |
| `99acres.webhook.api.key` | API key for 99acres webhook validation |
| `housing.api.key` | Housing.com API key |
| `housing.api.id` | Housing.com profile ID |
| `n8n.new_lead_webhook_url` | Outbound webhook endpoint |

### Source routing setup

For portal sources, configure `Fallback RM` in:

- `Leads > Lead Operations > Settings > Sources`

Use the `Needs Fallback RM` search filter in Sources to find incomplete setup.

---

## Testing

Run module tests (fresh DB recommended):

```bash
python odoo-bin -d <db_name> --addons-path=addons,custom_addons -i leads --test-enable --stop-after-init
```

Run only source-focused tests:

```bash
python odoo-bin -d <db_name> --addons-path=addons,custom_addons -i leads --test-enable --test-file=custom_addons/leads/tests/test_lead_source.py --stop-after-init
```

Detailed suite documentation: `custom_addons/leads/tests/README.md`

---

## Changes completed on 2026-03-28

- Added dedicated source test suite (`test_lead_source.py`) and test registration.
- Improved source configuration UX with filters, guidance text, and explicit fallback RM naming.
- Standardized fallback assignment logs and process notes for unmatched portal listings.
- Cleaned and aligned leads module menus and actions.
- Reworked WhatsApp menu hierarchy so Inbox and Positive Replies are children of `WhatsApp Replies`.
- Added module changelog at `custom_addons/leads/CHANGELOG.md`.

---

## Related documents

- `custom_addons/leads/CHANGELOG.md`
- `custom_addons/leads/tests/README.md`