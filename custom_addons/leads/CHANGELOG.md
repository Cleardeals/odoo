# Changelog - Lead Scoring (leads)

All notable changes to this module are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)

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
