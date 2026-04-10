# Lead Scoring and Automation Engine

> Centralized lead ingestion, source normalization, assignment automation, RM execution workflows, and site visit lifecycle management for Cleardeals.

**Module name:** `leads`  
**Version:** `1.5.0`  
**Odoo version:** `19.0`  
**License:** `LGPL-3`  
**Last updated:** `2026-04-10`  
**Owner:** Cleardeals Tech

---

## What this module does

The leads module ingests buyer inquiries from webhooks, cron pulls, and manual channels, standardizes source metadata, resolves property links, and routes leads to RMs. It keeps two operational layers in sync:

- `leads.new`: ingestion, assignment, and inquiry-level timeline
- `lead.score`: scored and follow-up layer

The module also owns the complete **site visit lifecycle**: creating, rescheduling, cancelling, and tracking visit appointments per inquiry, with a visual timeline rendered directly on the lead and inquiry forms.

---

## Key models

| Model | Purpose |
|---|---|
| `leads.new` | Canonical lead ingestion, assignment, and inquiry record |
| `lead.score` | Scored lead lifecycle and follow-up workflow |
| `lead.source.category` | Source classification (`portal` vs `manual`) |
| `lead.source` | Source registry including portal code and fallback RM routing |
| `lead.property.interest` | Recommended property links and visit tracking |
| `lead.site.visit` | Individual site visit appointment (scheduled, completed, cancelled, etc.) |
| `lead.site.visit.status` | Configurable status taxonomy with semantic flags |
| `lead.site.visit.feedback.option` | Feedback options tied to specific statuses |
| `lead.olx.account` | OLX dealer account credentials and polling state |
| `whatsapp.response` | WhatsApp response tracking and RM processing |

---

## Site visit lifecycle

### Status flags

Each `lead.site.visit.status` record carries boolean semantic flags:

| Flag | Meaning |
|---|---|
| `is_scheduled_status` | Visit is upcoming and active |
| `is_reschedule_status` | Triggers the reschedule write flow (creates new visit, closes old) |
| `is_completed_status` | Visit happened — hard terminal, chain closes |
| `is_cancelled_status` | Visit did not happen — hard terminal (except `code='superseded'`) |
| `is_no_show_status` | Buyer did not appear — hard terminal, chain closes |
| `is_terminal` | Any status that locks the record from further edits |

The special status `code='superseded'` carries `is_cancelled_status=True` (to prevent edit) but is treated as a **chain midpoint**, not a dead end. It is written only by the internal reschedule `write()` flow and must never be set directly by an RM.

### Status `code='cancelling'`

The "CANCELLING" status is a non-terminal in-progress state used when a cancellation is being processed (e.g. buyer called to cancel, RM is confirming). It renders in grey. It must not be confused with the terminal `cancelled` status.

### Reschedule flow

When a visit's status is set to one with `is_reschedule_status=True`:

1. A new `lead.site.visit` is created for the same inquiry with `status=scheduled`, carrying `previous_visit_id → old visit`.
2. The old visit is atomically closed with `status=superseded` and the reschedule feedback stored on it.
3. The old visit's `root_visit_id` is inherited so the chain graph remains intact.

The `skip_active_visit_check` and `skip_terminal_write` context flags exist solely to allow this atomic two-step without triggering guards.

### Chain detection in timelines

Timelines use `previous_visit_id` graph traversal — **not** `root_visit_id` — because `root_visit_id` may be `NULL` on visits created before it was introduced. The graph walk:

1. Builds `successor_of[old_id] = newer_visit` from `previous_visit_id` edges.
2. Identifies chain starts (visits with no predecessor in the current set).
3. Walks oldest→newest; splits at hard terminals (`is_completed_status`, `is_no_show_status`, or `is_cancelled_status AND code != 'superseded'`).
4. Reverses each sub-chain for display (newest first) and sorts by most-recent date.

A new visit created after a genuine cancellation (or completion) starts a fresh chain, regardless of wizard pre-fill, because the wizard no longer sets `previous_visit_id` when the latest visit is terminal.

### Add Visit wizard behaviour

The wizard (`lead.add.site.visit.wizard`) pre-fills:
- `property_base_id` and `assigned_rm_id` from the inquiry defaults.
- `status_id` defaulting to `code='scheduled'`.
- `previous_visit_id` = the latest visit **only if it is non-terminal** (active visit being supplemented, not a fresh start after cancellation or completion).

---

## Visual timeline

Both the Inquiry Timeline and the Overall Lead Timeline are computed HTML fields rendered on the lead/inquiry form via `sanitize="0"` to allow full CSS.

### What each element means

| Element | Meaning |
|---|---|
| `#N` column | Chronological visit number — `#1` = first ever visit, `#N` = most recent |
| Coloured vertical line | These visits belong to the same appointment thread (rescheduled from each other) |
| Dot colour | Visit outcome: green=completed, orange=scheduled, blue=rescheduled, red=no show, grey=cancelled |
| `↻ moved` badge | This visit's date was moved forward; the new date is in the row above |
| Chain banner | "Rescheduled once · Originally booked for {date}" — appears only for multi-visit chains |

**Singletons** (a visit with no reschedule chain) show no banner and no coloured line — their status pill and dot colour are sufficient.

### Rendering technique

The connector column uses `linear-gradient` on the `<td>` background to draw the vertical spine:
- Top row of a chain → `transparent 50% / lane_color 50%`
- Middle rows → solid `lane_color`
- Bottom row → `lane_color 50% / transparent 50%`

This avoids `height:100%` flexbox issues inside `<table>` cells.

### Overall Lead Timeline (multi-inquiry)

Each inquiry's reschedule chain is isolated by the `_check_reschedule_lineage` constraint — `previous_visit_id` cannot cross inquiry boundaries. So two parallel chains (e.g. Property A inquiry and Property B inquiry) are always detected as separate threads, each given a distinct lane colour. The "Inquiry" column labels every row.

---

## Lead source architecture

1. `source_id` is required during lead creation.
2. `portal_name` input is normalized through `_get_or_create_source()`.
3. Known portal aliases resolve through `_canonical_portal_code()`.
4. If portal property resolution fails, assignment uses the source-level `Fallback RM`.
5. If no fallback RM is configured, the system assigns Administrator and records clear process notes.

### Canonical portal mapping

| Input aliases | Canonical code |
|---|---|
| `99acres` | `99acres` |
| `housing`, `housing.com` | `Housing.com` |
| `magicbricks`, `magicbricks.com` | `MagicBricks` |
| `olx` | `OLX` |

---

## Navigation map (backend)

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
Portal webhook / Housing cron / OLX cron / CSV import
    -> create_lead_if_not_duplicate()
    -> leads.new.create() with normalized source
    -> _process_lead_logic()
       -> resolve property from source + listing ID
       -> assign property RM OR source fallback RM
       -> if none configured, assign Administrator
    -> optional webhook dispatch / analytics consumption
```

---

## OLX lead integration

Leads are polled from the OLX Business API (`https://business.olx.in`) using
a rotating cron. Up to 15 dealer accounts are cycled. One account is processed
per cron tick to stay within a 3-hour coverage window.

### Authentication flow

```
POST /api/v1/auth/login  { login, password }
    → { access_token, user_id }

GET /api/v1/leads?startDate=DD/MM/YY&endDate=DD/MM/YY&userId=...&page=1&pageSize=100
    → { data: { leads: [...], ads: [...] }, pagination: { totalPages: N } }
```

Required headers on every request: `api-version: 134`, `client-language: en-in`.

### Account records (`lead.olx.account`)

- Manage via `Leads > Lead Operations > OLX Accounts`.
- Passwords are **write-only** in the UI — typed once and stored in
  `ir.config_parameter` under `olx.account.<login>.password`. They are never
  stored in a DB column and never exported.
- An account is auto-disabled after **5 consecutive failures**. Re-enable it
  manually once credentials are fixed; the `process_notes` field explains why
  it was disabled.

### OLX 500 = no leads

The OLX API returns HTTP 500 (not 404) when an account has no leads in the
requested date range. The cron treats a 500 from the leads endpoint as an
empty result — it does **not** count as a failure.

### Property matching

Each OLX lead carries an `adId`. The cron sets this as `portal_property_id`
and the standard `_resolve_property_from_source()` function looks up a
`property.portal.listing` record with `portal_name='OLX'` and a matching
`portal_listing_id`. If found, the lead is linked to the property and assigned
to its RM; otherwise it goes to the OLX source's fallback RM.

### Retroactive relink

`PropertyPortalListingLeadRelink` (in `models/property_base_extend.py`) hooks
`property.portal.listing.create` and `write`. Whenever a listing is added or
its ID is corrected, all unlinked leads (`property_base_id=False`) matching
that portal+ID are retroactively linked and their RM is updated. Leads that
already have a `property_base_id` are never touched.

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
| `olx.socks_proxy` | SOCKS5 proxy URL for OLX API calls (dev only). Set to `socks5h://127.0.0.1:9090` in dev; leave **empty** in production — the prod server IP is whitelisted with OLX directly. |
| `olx.account.<login>.password` | OLX account password (one key per account). Written via the `lead.olx.account` form; never stored in a DB column. |

### Source routing setup

For portal sources, configure `Fallback RM` in:

- `Leads > Lead Operations > Settings > Sources`

Use the `Needs Fallback RM` search filter in Sources to find incomplete setup.

---

## Testing

Run the full module test suite:

```bash
source .venv/bin/activate && python3 odoo-bin \
  --addons-path=addons,custom_addons \
  -d cleardeals_19_dev \
  --test-enable --test-tags /leads \
  -u leads,properties \
  --no-http --stop-after-init
```

Current test count: **351 tests, 0 failures**.

Detailed suite documentation: `custom_addons/leads/tests/README.md`

---

## Changelog summary

| Version | Date | Summary |
|---|---|---|
| `1.4.0` | 2026-04-03 | Fixed post-cancellation chain linkage; fixed CANCELLING colour rendering; changed visit numbering to chronological (#1=first). Rewrote timeline chain detection to use `previous_visit_id` graph instead of `root_visit_id`. |
| `1.3.x` | 2026-03 | Site visit timeline visual connector lines; chain banner; `_CHAIN_LANE_COLORS` palette; `sanitize="0"` on HTML timeline fields. |
| `1.2.x` | 2026-03 | Site visit lifecycle with reschedule write flow, chain metadata (`root_visit_id`, `previous_visit_id`, `reschedule_iteration`), concurrent visit guard, US-08 enforcement. |
| `1.1.0` | 2026-03-28 | Source test suite; source configuration UX; WhatsApp menu hierarchy; module CHANGELOG. |

Full detail: `custom_addons/leads/CHANGELOG.md`

---

## Related documents

- `custom_addons/leads/CHANGELOG.md`
- `custom_addons/leads/tests/README.md`