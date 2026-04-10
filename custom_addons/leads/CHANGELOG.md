# Changelog - Lead Scoring (leads)

All notable changes to this module are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)

---

## [1.5.0] - 2026-04-10

### Added

- **OLX Business API integration** — automated lead polling for up to 15 dealer accounts.
  - New model `lead.olx.account` stores account credentials and polling state.
    Passwords are **write-only** — stored in `ir.config_parameter` under
    `olx.account.<login>.password`, never in a DB column.
  - Cron job `_cron_rotate_olx_accounts` (every 12 minutes) selects the next active
    account by `last_fetch_at ASC NULLS FIRST` and fetches the past day's leads.
  - Auto-disables an account after 5 consecutive failures; records timestamp and error
    in `process_notes` for operator review.
  - Date range uses `DD/MM/YY` format as required by the OLX API. OLX HTTP 500 on the
    leads endpoint is treated as "no leads" (not an error) because that is what the API
    returns for empty result sets.
  - `olx.socks_proxy` system parameter routes traffic through a SOCKS5 proxy in dev
    (where the local IP is not whitelisted). Leave empty in production.
  - `lead.olx.account` management UI accessible from `Leads > Lead Operations > OLX Accounts`.

- **Retroactive lead relink on portal listing changes** (`PropertyPortalListingLeadRelink`
  in `models/property_base_extend.py`):
  - Hooks `property.portal.listing.create` and `.write`.
  - When a listing is created or its `portal_listing_id` / `property_base_id` is updated,
    all unlinked `leads.new` records (`property_base_id=False`) matching that portal + ID
    are linked to the property and reassigned to its RM.
  - Appends an audit note to `process_notes` on every relinked lead.
  - Leads already linked are never overwritten.

- **Test suite** — `tests/test_olx_leads.py` (32 tests across 4 test classes):
  - `TestOlxLeadParsing` — phone normalization, ad enrichment, raw_data structure.
  - `TestOlxAccountState` — failure tracking, auto-disable, rotation ordering.
  - `TestOlxApiMocked` — HTTP-mocked tests for `_api_fetch_olx` and cron rotation.
  - `TestPortalListingRelink` — retroactive relink on listing create/write.

### Fixed

- **In-method imports removed** from `new_portal_leads.py`:
  `from datetime import date, timedelta` and `import json as _json` were inside method
  bodies. Both now resolved at module level — `date` added to the top-level datetime
  import; the in-method `json` alias removed (module-level `import json` already present).

### Changed

- `lead_olx_account.py`: magic number `5` for consecutive failure threshold replaced
  with named constant `_CONSECUTIVE_FAILURE_THRESHOLD = 5` at module level.
- Module ownership headers added to `lead_olx_account.py` and `property_base_extend.py`.
- `README.md` updated: model table, OLX integration section, system parameters, and
  ingestion flow diagram.

### Validation

- Module loads without errors: `python3 odoo-bin -u leads --stop-after-init` exit 0.
- Live cron run end-to-end: 3 OLX leads fetched, created, and assigned correctly via
  SOCKS5 proxy tunnel in dev.
- Property matching and RM assignment verified for matched and unmatched ad IDs.

### Files Added

- `models/lead_olx_account.py`
- `data/olx_account_cron.xml`
- `data/olx_accounts_data.xml`
- `data/pull_leads_cron.xml`
- `views/lead_olx_account_views.xml`
- `tests/test_olx_leads.py`

### Files Updated

- `models/new_portal_leads.py`
- `models/property_base_extend.py`
- `models/__init__.py`
- `tests/__init__.py`
- `security/ir.model.access.csv`
- `__manifest__.py`
- `README.md`

---

## [1.3.1] - 2026-04-01

### Changed

- **API endpoints — `rescheduled` bucket removed from site-visits responses (breaking change)**
  - `GET /api/track/lead/site-visits` (buyer) and `GET /api/track/property/site-visits` (seller)
    no longer accept or return a `rescheduled` bucket.
  - `_VISIT_STATUSES` reduced to `{"site_visit_scheduled", "site_visit_done"}` in both
    `controllers/buyer/site_visits.py` and `controllers/seller/site_visits.py`.
  - Records with `current_status="rescheduled"` (pre-v1.3 legacy data) are now ignored by
    the API. Since `lead.site.visit._sync_inquiry_snapshot` writes `"site_visit_scheduled"`
    for rescheduled visits, all current-system rescheduled visits are already in the
    `upcoming` bucket. Consumers must remove any client-side handling of `rescheduled`.
  - Response shape: `data.rescheduled` array and `data.totals.rescheduled` key removed.

### Fixed

- **Test documentation** — added "Model integration notes" sections across all test files
  that write `current_status` or `site_visit_date` directly, clarifying the production
  path (via `lead.site.visit._sync_inquiry_snapshot`) versus the direct-write path used
  for unit-test isolation:
  - `test_buyer_activity_api.py` — module docstring + `test_01`, `test_05`, `test_16`, `test_17`
  - `test_seller_activity_api.py` — module docstring + `test_01`, `test_18`
  - `test_lead_score.py` — class docstring + `test_04`, `test_05` (LEGACY note), `test_06`, `test_08`
  - `test_portal_lead_crud.py` — class docstring + `test_06`, `test_09`
  - `test_seller_funnel_api.py` — module docstring (legacy note for `"rescheduled"` in `ALL_FUNNEL_STAGES`)
  - `test_lead_property_interest.py` — class docstring (independence from `lead.site.visit` clarified)
  - `test_seller_portal_performance_api.py` — module docstring

### Validation

- Test suite run after API changes: `0 failed, 0 error(s)` of 347 tests.

### Files Updated

- `controllers/buyer/site_visits.py`
- `controllers/seller/site_visits.py`
- `controllers/API_DOCUMENTATION.md`
- `tests/README.md`
- `tests/test_buyer_activity_api.py`
- `tests/test_seller_activity_api.py`
- `tests/test_lead_score.py`
- `tests/test_portal_lead_crud.py`
- `tests/test_seller_funnel_api.py`
- `tests/test_lead_property_interest.py`
- `tests/test_seller_portal_performance_api.py`

---

## [1.3.0] - 2026-03-28

### Added
- Source-focused lead test suite in `tests/test_lead_source.py` with 12 post-install tests covering:
  - source/category constraints and uniqueness
  - canonical portal mapping and source auto-creation behavior
  - lead source requirement and portal-name-based source autofill
  - manual lead assignment and chatter note behavior
- Test package registration for the new suite in `tests/__init__.py`.
- Lead Source search view (`views/lead_source_views.xml`) with operator-friendly filters and group-by options:
  - Portal Sources
  - Manual Sources
  - Needs Fallback RM
  - Group by Category
  - Group by Fallback RM
- Lead Source UI guidance banner and no-content help text for fallback RM setup.

### Changed
- Source-based lead creation and source normalization were completed and validated end-to-end:
  - leads now require `source_id` during create
  - `portal_name` input auto-resolves/creates source records
  - canonical portal aliases map to standard portal codes
  - unknown portal labels gracefully fallback to manual source classification
- Manual lead behavior was unified and stabilized:
  - manual leads are assigned to creator by default
  - state transitions and chatter behavior are consistent for manual inflow
- Portal fallback assignment messaging was made user-friendly:
  - `default_rm_user_id` label changed to **Fallback RM**
  - fallback RM now constrained to internal users (`share = False`)
  - process notes explicitly explain fallback and admin fallback path when no RM is configured
- Leads navigation and naming were cleaned for readability and consistency in menu/action labels.
- WhatsApp replies navigation was restructured so:
  - **WhatsApp Replies** is the parent entry under Lead Operations
  - **Inbox** and **Positive Replies** are sibling child menus under WhatsApp Replies
  - Positive Replies no longer appears as a separate main-level menu entry

### Fixed
- XML syntax issue introduced during filter definition updates in `views/lead_source_views.xml`.
- Accessibility warning in lead source form banner by adding the required ARIA role.

### Validation
- Fresh DB targeted test runs were executed for the new source suite.
- Result: `0 failed, 0 error(s)` for `tests/test_lead_source.py`.
- Final verified DB run in this session: `test_leads_ui_1774690725`.

### Files Updated During This Work Window
- `models/lead_source.py`
- `models/new_portal_leads.py`
- `views/lead_source_views.xml`
- `views/lead_score_menu.xml`
- `views/lead_score_views.xml`
- `views/new_portal_lead_views.xml`
- `views/whatsapp_response_views.xml`
- `tests/test_lead_source.py`
- `tests/__init__.py`
