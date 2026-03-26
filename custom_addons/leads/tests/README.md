# Leads Module - Test Suite Documentation

> **Odoo 19 Custom Module Testing Documentation**
> **Module:** `leads`
> **Path:** `/custom_addons/leads/tests/`

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Test Architecture](#test-architecture)
3. [Running Tests](#running-tests)
4. [Test Files Reference](#test-files-reference)
5. [Test Coverage Matrix](#test-coverage-matrix)
6. [Common Test Fixtures](#common-test-fixtures)
7. [Best Practices](#best-practices)
8. [Troubleshooting](#troubleshooting)

---

## Overview

This test suite provides comprehensive coverage for the **Leads Management Module** in Odoo 19. The tests cover two main models:

| Model | Description |
|-------|-------------|
| `leads.new` | Portal leads from external sources (MagicBricks, Housing.com, 99acres, OLX) |
| `lead.score` | Scored/processed leads with follow-up management |

### Test Statistics

- **Total Test Files:** 17
- **Total Tests:** ~355+
- **Test Categories:** CRUD, Processing, API (Buyer/Seller), Webhook, Cron Jobs, WhatsApp Integration, Property Interests, Site Visits, Activity Logs, Performance
- **Test Tags:** `@tagged('post_install', '-at_install')`

---

## Test Architecture

```
tests/
├── __init__.py                      # Test module imports
├── test_portal_common.py            # Base test fixtures (PortalLeadTestCase)
├── test_lead_score.py               # Lead scoring model tests (20 tests)
├── test_portal_lead_crud.py         # Basic CRUD operations (10 tests)
├── test_portal_lead_duplicate.py    # Duplicate detection logic (5 tests)
├── test_portal_lead_phone.py        # Phone standardization (9 tests)
├── test_portal_lead_processing.py   # Lead assignment & property matching (15 tests)
├── test_portal_lead_whatsapp.py     # WhatsApp URL generation (5 tests)
├── test_portal_lead_cron.py         # Cron job operations (3 tests)
├── test_portal_lead_api.py          # External API integrations (4 tests)
├── test_portal_lead_webhook.py      # n8n webhook functionality (3 tests)
├── test_lead_property_interest.py   # Property interests & computed fields (21 tests)
│
├── BUYER API ENDPOINTS
├── test_buyer_site_visits_api.py    # Buyer site visits classification & serialization (35 tests)
├── test_buyer_activity_api.py       # Buyer activity logs & feed (TBD tests)
│
├── SELLER API ENDPOINTS
├── test_seller_site_visits_api.py   # Seller site visits with property filtering (32 tests)
├── test_seller_activity_api.py      # Seller activity logs & events (TBD tests)
├── test_seller_summary_api.py       # Seller dashboard summary data (25 tests)
├── test_seller_portal_performance_api.py  # Seller portal performance metrics (33 tests)
│
└── README.md                        # This documentation
```

---

## Running Tests

### Run All Leads Module Tests

```bash
# Windows (from project root)
python odoo-bin -c odoo.conf -d <database_name> --test-enable --stop-after-init -i leads

# With specific log level
python odoo-bin -c odoo.conf -d <database_name> --test-enable --stop-after-init -i leads --log-level=test
```

### Run Specific Test File

```bash
# Run only lead score tests
python odoo-bin -c odoo.conf -d <database_name> --test-enable --stop-after-init --test-file=custom_addons/leads/tests/test_lead_score.py
```

### Run Tests by Tag

```bash
# Run post_install tests only
python odoo-bin -c odoo.conf -d <database_name> --test-tags=post_install
```

### Using pytest-odoo (Alternative)

```bash
pytest custom_addons/leads/tests/ -v --odoo-database=<database_name>
```

---

## Test Files Reference

### 1. `test_portal_common.py` - Base Test Fixtures

**Purpose:** Provides the `PortalLeadTestCase` base class with shared fixtures for all portal lead tests.

#### Fixtures Created:

| Fixture | Type | Description |
|---------|------|-------------|
| `cls.rm_user` | `res.users` | Test Relationship Manager user |
| `cls.naresh_user` | `res.users` | Fallback user for Housing.com/OLX/unknown portal leads |
| `cls.pratham_user` | `res.users` | Default RM for 99acres leads when property not found |
| `cls.mayuri_user` | `res.users` | Default RM for MagicBricks leads when property not found |
| `cls.test_property` | `property.base` | Test property with multiple portal listings (`portal_listing_ids`) |
| `cls.mb_id` | `str` | Dynamic MagicBricks property ID |
| `cls.hsg_id` | `str` | Dynamic Housing.com property ID |
| `cls.acres_id` | `str` | Dynamic 99acres property ID |
| `cls.olx_id` | `str` | Dynamic OLX property ID |

#### Helper Methods:

```python
def create_portal_lead(self, **kwargs):
    """
    Helper method to create portal leads with sensible defaults.

    Args:
        **kwargs: Override any default field values

    Returns:
        leads.new: Created lead record

    Example:
        lead = self.create_portal_lead(
            name='Custom Lead',
            phone='9876543210',
            portal_name='MagicBricks'
        )
    """
```

---

### 2. `test_lead_score.py` - Lead Scoring Model Tests

**Class:** `TestLeadScore(TransactionCase)`
**Model Under Test:** `lead.score`
**Total Tests:** 20

#### Test Cases:

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_default_values` | Verify default values on creation |
| 02 | `test_02_required_fields` | Enforce required fields (name) |
| 03 | `test_03_actionable_flag_logic` | `is_actionable_today` computation |
| 04 | `test_04_site_visit_follow_up_logic` | Auto follow-up date on site visit |
| 05 | `test_05_rescheduled_follow_up_logic` | Follow-up on rescheduled status |
| 06 | `test_06_site_visit_without_date` | Handle missing site visit date |
| 07 | `test_07_onchange_status_behavior` | UI onchange follow-up update |
| 08 | `test_08_onchange_does_not_affect_site_visit` | Onchange preserves site visit date |
| 09 | `test_09_whatsapp_integration_count` | WhatsApp response counter |
| 10 | `test_10_whatsapp_one2many_relationship` | One2many relationship integrity |
| 11 | `test_11_cron_job_recomputation` | Cron recomputes actionable flag |
| 12 | `test_12_cron_job_with_overdue_leads` | Batch overdue lead processing |
| 13 | `test_13_multiple_status_changes` | Sequential status transitions |
| 14 | `test_14_state_and_current_status_independence` | Field independence |
| 15 | `test_15_lead_ordering` | Score-based ordering |
| 16 | `test_16_feedback_fields_set_correctly` | Feedback field storage |
| 17 | `test_17_edge_case_far_future_date` | Future date handling |
| 18 | `test_18_edge_case_far_past_date` | Past date handling (overdue) |
| 19 | `test_19_property_fields_storage` | Property data persistence |
| 20 | `test_20_notes_field` | Notes field storage |

#### Key Tested Logic:

```python
# Actionable Flag Logic (is_actionable_today)
- True if: next_follow_up_date <= today OR next_follow_up_date is False
- False if: next_follow_up_date > today

# Site Visit Follow-up Logic
- When current_status = 'site_visit_scheduled'
- next_follow_up_date = site_visit_scheduled_date + 1 day
```

---

### 3. `test_portal_lead_crud.py` - CRUD Operations

**Class:** `TestPortalLeadCRUD(PortalLeadTestCase)`
**Model Under Test:** `leads.new`
**Total Tests:** 10

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_create_lead_with_required_fields` | Basic lead creation |
| 02 | `test_02_missing_required_fields` | Required field validation |
| 04 | `test_04_related_property_fields` | Property field propagation |
| 05 | `test_05_compute_create_date_only` | Date computation |
| 06 | `test_06_compute_site_visit_date_only` | Site visit date extraction |
| 07 | `test_07_ops_sales_lead_flag` | OPS sales lead boolean flag |
| 08 | `test_08_feedback_general_field` | Feedback general selection field |
| 09 | `test_09_feedback_site_visit_done_field` | Feedback site visit done selection |
| 10 | `test_10_feedback_fields_independent` | Independent feedback fields |

---

### 4. `test_portal_lead_duplicate.py` - Duplicate Detection

**Class:** `TestPortalLeadDuplicateDetection(PortalLeadTestCase)`
**Model Under Test:** `leads.new`
**Total Tests:** 5

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_no_duplicate_different_phone` | Different phones = not duplicate |
| 02 | `test_02_no_duplicate_different_property` | Different property = not duplicate |
| 03 | `test_03_duplicate_same_phone_and_property_recent` | Same phone + property + <30 days = duplicate |
| 04 | `test_04_not_duplicate_after_30_days` | Same lead after 30 days allowed |
| 05 | `test_05_duplicate_detection_log_message` | Logs message on existing lead |

#### Duplicate Detection Rules:

```
DUPLICATE if ALL conditions met:
├── Same phone number (standardized)
├── Same resolved `property_base_id` (from `property.portal.listing`)
└── Created within last 30 days

Fallback duplicate key (only when portal mapping is missing):
├── Same phone number
├── Same portal_name + portal_property_id
└── Created within last 30 days

NOT DUPLICATE if ANY:
├── Different phone number
├── Different resolved property (or different portal tuple in fallback mode)
└── More than 30 days old
```

---

### 5. `test_portal_lead_phone.py` - Phone Standardization

**Class:** `TestPortalLeadPhoneStandardization(PortalLeadTestCase)`
**Model Under Test:** `leads.new`
**Total Tests:** 9

| Test ID | Input | Expected Output |
|---------|-------|-----------------|
| 01 | `9876543210` | `9876543210` |
| 02 | `919876543210` | `9876543210` |
| 03 | `98765 43210` | `9876543210` |
| 04 | `98765-43210` | `9876543210` |
| 05 | `+919876543210` | `9876543210` |
| 06 | `(987) 654-3210` | `9876543210` |
| 07 | `` (empty) | `` |
| 08 | `None` | `` |
| 09 | `+91 98765-43210` (via creation) | `9876543210` |

---

### 6. `test_portal_lead_processing.py` - Lead Processing

**Class:** `TestPortalLeadProcessing(PortalLeadTestCase)`
**Model Under Test:** `leads.new`
**Total Tests:** 15

| Test ID | Method | Description |
|---------|--------|-------------|
| 01-04 | `test_0X_find_property_by_*` | Property lookup by portal ID |
| 05 | `test_05_property_not_found_returns_empty` | Empty recordset on not found |
| 06 | `test_06_find_rm_from_property` | RM extraction from property |
| 07 | `test_07_process_lead_assigns_property_and_rm` | Full processing flow |
| 08 | `test_08_process_lead_magicbricks_not_found_assigns_mayuri` | MagicBricks fallback to Mayuri |
| 09 | `test_09_process_lead_adds_notes` | Processing notes |
| 10 | `test_10_process_lead_skips_non_new_leads` | Skip already processed |
| 11 | `test_11_process_ops_lead_assignment` | OPS sales lead processing |
| 12 | `test_12_process_lead_99acres_not_found_assigns_pratham` | 99acres fallback to Pratham |
| 13 | `test_13_process_lead_housing_not_found_assigns_naresh` | Housing.com fallback to Naresh |
| 14 | `test_14_process_lead_olx_not_found_assigns_naresh` | OLX fallback to Naresh |
| 15 | `test_15_process_lead_unknown_portal_not_found_assigns_naresh` | Unknown portal fallback to Naresh |

#### Property Matching Logic:

```python
Portal Name          → `property.portal.listing.portal_name`
────────────────────────────────────────────────────────────
'MagicBricks'        → 'MagicBricks'
'Housing.com'        → 'Housing.com'
'99acres'            → '99acres'
'OLX'                → 'OLX'

Lookup key used by lead processing:
- `portal_property_id` → `property.portal.listing.portal_listing_id`
```

#### Fallback RM Assignment (When Property Not Found):

```python
Portal Name          → Default RM Assigned
─────────────────────────────────────────────
'99acres'            → Pratham Bhandari
'MagicBricks'        → Mayuri Malivad
'Housing.com'        → Naresh Rojiya
'OLX'                → Naresh Rojiya
(Unknown Portal)     → Naresh Rojiya (default)
```

#### OPS Sales Lead Flag:

```python
# is_ops_sales_lead field behavior:
- Default: False (standard leads)
- True: Marks lead as OPS sales lead
- Processing: Flag preserved during lead assignment
- RM Assignment: Still assigns RM even when is_ops_sales_lead=True
```

---

### 7. `test_portal_lead_whatsapp.py` - WhatsApp Integration

**Class:** `TestPortalLeadWhatsapp(PortalLeadTestCase)`
**Model Under Test:** `leads.new`
**Total Tests:** 5

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_whatsapp_url_10_digit_phone` | URL with 10-digit phone |
| 02 | `test_02_whatsapp_url_with_91_prefix` | URL with existing prefix |
| 03 | `test_03_whatsapp_url_no_phone` | Returns False when no phone |
| 04 | `test_04_whatsapp_html_includes_icon` | HTML includes fa-whatsapp icon |
| 05 | `test_05_action_whatsapp_generates_message` | Action returns proper context |

#### WhatsApp URL Format:

```
Input: 9876543210
Output: whatsapp://send?phone=919876543210
```

---

### 8. `test_portal_lead_cron.py` - Scheduled Jobs

**Class:** `TestPortalLeadCron(PortalLeadTestCase)`
**Model Under Test:** `leads.new`
**Total Tests:** 3

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_cron_reprocesses_old_unassigned_leads` | Process leads >1 hour old |
| 02 | `test_02_cron_skips_recent_leads` | Skip leads <1 hour old |
| 03 | `test_03_cron_skips_already_assigned` | Skip assigned leads |

#### Cron Method: `_cron_reprocess_unassigned_leads`

```
Criteria for reprocessing:
├── state = 'new'
├── create_date < (now - 1 hour)
└── Not already assigned
```

---

### 9. `test_portal_lead_api.py` - External API Integration

**Class:** `TestPortalLeadAPI(PortalLeadTestCase)`
**Model Under Test:** `leads.new`
**Total Tests:** 4

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_housing_api_fetch_success` | Successful API fetch |
| 02 | `test_02_housing_api_no_leads` | Handle empty response |
| 03 | `test_03_housing_api_error` | Handle connection errors |
| 04 | `test_04_cron_full_flow` | Full integration test |

#### Mocking Setup:

```python
# Mock requests.get for API tests
@patch('requests.get')
def test_01_housing_api_fetch_success(self, mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'data': [...]}
    mock_get.return_value = mock_response
```

---

### 10. `test_portal_lead_webhook.py` - Webhook Functionality

**Class:** `TestPortalLeadWebhook(PortalLeadTestCase)`
**Model Under Test:** `leads.new`
**Total Tests:** 3

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_webhook_sends_unsent_leads` | Sends to n8n webhook |
| 02 | `test_02_webhook_includes_property_details` | Payload contains property info |
| 03 | `test_03_webhook_skips_if_url_not_configured` | Skip when URL not set |

#### System Parameters Used:

```python
'n8n.new_lead_webhook_url'  # Webhook endpoint URL
'housing.api.key'           # Housing.com API key
'housing.api.id'            # Housing.com API ID
```

---

### 11. `test_lead_property_interest.py` - Property Interests & Computed Fields

**Classes:**
- `TestLeadPropertyInterest(PortalLeadTestCase)` - 10 tests
- `TestLeadAllAssociatedProperties(PortalLeadTestCase)` - 6 tests
- `TestLeadDateComputations(PortalLeadTestCase)` - 5 tests

**Models Under Test:** `lead.property.interest`, `leads.new`
**Total Tests:** 21

#### TestLeadPropertyInterest - Property Interest Model Tests

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_create_lead_property_interest` | Basic interest record creation |
| 02 | `test_02_unique_constraint_lead_property` | Unique constraint (lead_id, property_id) |
| 03 | `test_03_related_property_fields` | Related fields (bhk, location) |
| 04 | `test_04_site_visit_date_only_computation` | site_visit_date_only computed field |
| 05 | `test_05_site_visit_date_only_empty_when_no_date` | Empty date handling |
| 06 | `test_06_cascade_delete_on_lead` | Cascade delete behavior |
| 07 | `test_07_feedback_fields` | Basic feedback field tests |
| 08 | `test_08_multiple_interests_per_lead` | Multiple interests per lead |
| 09 | `test_09_feedback_general_all_options` | All feedback_general options |
| 10 | `test_10_feedback_site_visit_done_all_options` | All feedback_site_visit_done options |

#### TestLeadAllAssociatedProperties - Computed Many2many Tests

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_all_associated_with_primary_only` | Primary property only |
| 02 | `test_02_all_associated_with_no_properties` | No properties linked |
| 03 | `test_03_all_associated_with_primary_and_interests` | Primary + interests combined |
| 04 | `test_04_all_associated_with_interests_only` | Interests only (no primary) |
| 05 | `test_05_all_associated_updates_on_interest_change` | Dynamic updates on change |
| 06 | `test_06_no_duplicate_in_all_associated` | No duplicate properties |

#### TestLeadDateComputations - Date Field Computations

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_create_date_only_is_computed` | create_date_only auto-compute |
| 02 | `test_02_create_date_only_matches_ist_date` | IST timezone conversion |
| 03 | `test_03_site_visit_date_only_on_lead` | site_visit_date_only on leads.new |
| 04 | `test_04_site_visit_date_only_empty_when_no_visit` | Empty site visit handling |
| 05 | `test_05_site_visit_date_only_updates_on_change` | Dynamic updates |

#### Feedback Fields Reference:

```python
# feedback_general options:
- 'buyer_did_not_visit_property'  # Buyer Did Not Visit Property
- 'buyer_not_interested'          # Buyer Not Interested
- 'buyer_not_picking_call'        # Buyer Not Picking Call
- 'visit_needs_to_be_rescheduled' # Visit Needs to be Rescheduled
- 'other'                         # Other

# feedback_site_visit_done options:
- 'buyer_liked_property'              # Buyer Liked Property
- 'buyer_requirement_closed'          # Buyer Requirement Closed
- 'buyer_visit_from_outside'          # Buyer Visit From Outside
- 'buyer_not_pickup_call'             # Buyer Not Picking Call
- 'planning_for_second_visit'         # Planning for Second Visit
- 'negotiation_stage'                 # Negotiation Stage
- 'visit_done_confirmed_by_owner'     # Visit Done - Confirmed by Owner
- 'looking_for_more_options'          # Looking for More Options
- 'price_is_high'                     # Price is High
- 'location_mismatch'                 # Location Mismatch
- 'deal_closed'                       # Deal Closed
- 'other'                             # Other
```

#### Unique Constraint (Odoo 19.0 Syntax):

```python
# New models.Constraint syntax replacing _sql_constraints
_lead_prop_uniq = models.Constraint(
    'UNIQUE(lead_id, property_id)',
    message='This property is already linked to the lead.'
)
```

---

## 12. `test_buyer_site_visits_api.py` - Buyer Site Visits API

**Class:** `TestBuyerSiteVisitsAPI(PortalLeadTestCase)`
**Endpoint:** `/api/buyer/site_visits`
**Models Under Test:** `leads.new`, `lead.property.interest`
**Total Tests:** 35

### Overview

Comprehensive test suite for the buyer site visits endpoint that classifies, serializes, and aggregates site visit records across primary and recommended properties. Tests the complete pipeline from visit classification through API response building.

### Visit Classification Logic

Visits are classified into 5 buckets based on status, date, and feedback:

| Bucket | Condition | Sort Order |
|--------|-----------|-----------|
| `upcoming` | status='site_visit_scheduled' AND date > now | Ascending (soonest first) |
| `pending_feedback` | status='site_visit_scheduled' AND date ≤ now AND feedback in {None, "", "other", False} | Ascending (oldest first) |
| `cancelled` | status='site_visit_scheduled' AND date ≤ now AND feedback NOT in _EMPTY_FEEDBACK | Descending (recent first) |
| `rescheduled` | status='rescheduled' | Descending (recent first) |
| `completed` | status='site_visit_done' | Descending (recent first) |

### Valid Status Values

```python
_VISIT_STATUSES = {"site_visit_scheduled", "site_visit_done", "rescheduled"}
_EMPTY_FEEDBACK = {None, "", "other", False}
```

### Test Categories (35 tests)

#### Category 1: Visit Classification (7 tests)
- test_001: upcoming (future scheduled)
- test_002: pending_feedback (past scheduled, no feedback)
- test_003: cancelled (past scheduled, feedback value)
- test_004: rescheduled (status="rescheduled")
- test_005: completed (status="site_visit_done")
- test_006: empty string feedback → pending_feedback
- test_007: False feedback → pending_feedback

#### Category 2: Primary Lead Record Building (4 tests)
- test_008: all base fields present
- test_009: null name/portal handling (False for empty, not None)
- test_010: ISO datetime format for site_visit_datetime
- test_011: property details accessible via property_id

#### Category 3: Recommended Interest Building (2 tests)
- test_012: interest structure with parent link
- test_013: inherits lead info via lead_id relation

#### Category 4: Bucket-Specific Fields (7 tests)
- test_014: pending_feedback excludes feedback_general field
- test_015: cancelled includes feedback_general
- test_016: rescheduled status preserved
- test_017: completed includes feedback_site_visit_done
- test_018: completed includes remarks when feedback="other"
- test_019: completed excludes remarks when feedback!="other"
- test_020: upcoming has no bucket-specific fields

#### Category 5: Sorting Logic (4 tests)
- test_021: upcoming ascending (soonest first)
- test_022: pending_feedback ascending (oldest first)
- test_023: cancelled descending (recent first)
- test_024: completed descending (recent first)

#### Category 6: Source Field (Primary vs Recommended) (3 tests)
- test_025: primary lead has source="primary"
- test_026: recommended interest has source="recommended"
- test_027: mixed primary and recommended together

#### Category 7: Multiple Inquiries (3 tests)
- test_028: multiple inquiries per buyer
- test_029: multiple recommendations per inquiry
- test_030: primary + 2 recommended = 3 records

#### Category 8: Aggregation & Filtering (5 tests)
- test_031: cross-bucket totals calculation
- test_032: lead without visits excluded
- test_033: single primary only
- test_034: missing visit_date excluded
- test_035: invalid status excluded

### Key Fields

**Base Record Fields (all buckets):**
```python
{
    "source": "primary" | "recommended",
    "lead_id": int,
    "lead_name": str | None,
    "portal": str | None,
    "property_tag": str | None,
    "property_bhk": str | None,
    "property_location": str | None,
    "property_city": str | None,
    "site_visit_datetime": "ISO8601" | None,
    "site_visit_date": "ISO8601" | None,
    "current_status": str,
    "remarks": str | None,
}
```

**Bucket-Specific Fields:**
```python
# pending_feedback bucket
{"note": "Visit date has passed — awaiting RM feedback"}

# cancelled bucket
{
    "feedback_general": str,
    "note": "Visit did not occur due to buyer status"
}

# rescheduled bucket
{"note": "Visit was rescheduled — confirm new date with RM"}

# completed bucket
{
    "feedback_site_visit_done": str,
    "remarks": str | None  # Only if feedback == "other"
}

# upcoming bucket
{}  # No extra fields
```

### Response Structure

```json
{
    "buyer_phone": "9876543210",
    "upcoming": [...],
    "pending_feedback": [...],
    "cancelled": [...],
    "rescheduled": [...],
    "completed": [...],
    "totals": {
        "upcoming": int,
        "pending_feedback": int,
        "cancelled": int,
        "rescheduled": int,
        "completed": int
    },
    "error": null
}
```

---

## 13. `test_seller_site_visits_api.py` - Seller Site Visits API

**Class:** `TestSellerSiteVisitsAPI(PortalLeadTestCase)`
**Endpoint:** `/api/seller/property/{property_tag}/site_visits`
**Models Under Test:** `leads.new`, `lead.property.interest`
**Total Tests:** 32

### Overview

Test suite for seller site visits endpoint that aggregates visits grouped by property and bucket. Similar classification to buyer endpoint but filtered by property_tag and organized per-property.

### Test Categories (32 tests)

- test_01-07: Visit classification tests (upcoming, pending_feedback, cancelled, rescheduled, completed, empty_feedback variants)
- test_08-10: Base record building and null handling
- test_11-17: Bucket-specific fields (pending note, cancelled feedback, rescheduled note, completed feedback, remarks logic, upcoming minimal)
- test_18-21: Sorting logic (upcoming ascending, pending ascending, cancelled descending, completed descending)
- test_22: Filter by property_tag
- test_23: No visits for property without site_visit_date
- test_24: Visits combine primary and recommended
- test_25: Mixed bucket distribution
- test_26: Totals calculation
- test_27: Empty all buckets
- test_28-29: ISO format for datetime and date fields
- test_30: Property tag mapping
- test_31: Visit with all feedback types
- test_32: site_visit_date_only vs datetime differentiation

---

## 14. `test_buyer_activity_api.py` - Buyer Activity API

**Class:** `TestBuyerActivityAPI(PortalLeadTestCase)`
**Endpoint:** `/api/buyer/activity`
**Models Under Test:** `leads.new`
**Total Tests:** TBD

### Overview

Test suite for buyer activity logs endpoint that returns a chronological feed of buyer interactions and status changes.

### Expected Test Coverage

- Activity log creation and timestamps
- Chronological ordering
- Status change logging
- Property interactions
- Feed pagination
- Empty activity handling

---

## 15. `test_seller_activity_api.py` - Seller Activity API

**Class:** `TestSellerActivityAPI(PortalLeadTestCase)`
**Endpoint:** `/api/seller/property/{property_tag}/activity`
**Models Under Test:** `leads.new`, `lead.property.interest`
**Total Tests:** TBD

### Overview

Test suite for seller activity logs endpoint that tracks all interactions and changes for a specific property.

### Expected Test Coverage

- Activity filtering by property
- Buyer interactions on property
- Status transitions
- Timestamps and chronological ordering
- Bulk activity aggregation

---

## 16. `test_seller_summary_api.py` - Seller Summary API

**Class:** `TestSellerSummaryAPI(PortalLeadTestCase)`
**Endpoint:** `/api/seller/summary`
**Models Under Test:** `leads.new`, `lead.property.interest`
**Total Tests:** 25

### Overview

Comprehensive test suite for seller dashboard summary endpoint that aggregates leads, inquiries, and performance metrics across all seller properties and portals.

### Test Categories (25 tests)

#### Phone Normalization (7 tests)
- test_01-06: Phone format variations (10-digit, 91 prefix, spaces, dashes, etc.)
- test_07: Invalid phone handling

#### Property and Lead Querying (8 tests)
- test_07-10: Get properties for phone (exact match, 91 fallback, nonexistent phone, active only)
- test_11-13: Get primary leads for tags
- test_14-15: Get recommended leads for tags

#### Portal Breakdown (3 tests)
- test_16: Portal breakdown known portals (MagicBricks, Housing.com, 99acres, OLX)
- test_17: Portal breakdown unknown portal

#### Inquiry Management (3 tests)
- test_18: Inquiry count (primary + recommended)
- test_19: Inquiry count empty results
- test_25: Leads from different portals counted separately

#### Properties List (4 tests)
- test_20: Properties list all seller tags
- test_21: Primary lead has correct properties
- test_22: Recommended interest links correctly
- test_24: Multiple properties same seller isolated

#### Data Consistency (1 test)
- test_23: Portal breakdown totals consistency

### Response Structure

```json
{
    "seller_phone": "9876543210",
    "properties": [
        {
            "property_tag": "PROP-001",
            "bhk": "2 BHK",
            "location": "Location Name",
            "city": "City Name",
            "inquiries": {
                "total": int,
                "by_portal": {
                    "MagicBricks": int,
                    "Housing.com": int,
                    "99acres": int,
                    "OLX": int,
                    "unknown": int
                }
            }
        }
    ],
    "summary": {
        "total_properties": int,
        "total_inquiries": int,
        "by_portal": { ... }
    },
    "error": null
}
```

---

## 17. `test_seller_portal_performance_api.py` - Seller Portal Performance API

**Class:** `TestSellerPortalPerformanceAPI(PortalLeadTestCase)`
**Endpoint:** `/api/seller/property/{property_tag}/performance`
**Models Under Test:** `leads.new`, `lead.property.interest`
**Total Tests:** 33

### Overview

Performance metrics and analytics test suite for seller portal that tracks inquiry sources, conversion rates, and engagement metrics per property and portal.

### Test Categories (33 tests)

#### Basic Metrics (5 tests)
- test_01: Total inquiries per property
- test_02: Portal source breakdown
- test_03: Empty property metrics
- test_04: Multiple portals aggregation
- test_05: Property filtering accuracy

#### Visit Conversion (6 tests)
- test_06: Visit count by portal
- test_07: Conversion rate calculation
- test_08: Feedback distribution
- test_09: Rescheduled visit tracking
- test_10: Completed visit tracking
- test_11: Pending follow-up count

#### Engagement Metrics (5 tests)
- test_12: Primary vs recommended breakdown
- test_13: Interest persistence
- test_14: Feedback completion rate
- test_15: Response time tracking
- test_16: Activity frequency

#### Time-Based Analysis (8 tests)
- test_17-20: Period filtering (today, week, month, all)
- test_21-22: Trend calculation (week-over-week, month-over-month)
- test_23: Date range flexibility
- test_24: Timezone handling

#### Data Formats & Consistency (9 tests)
- test_25: Percentage formatting
- test_26: Null handling
- test_27: Empty result handling
- test_28: DateTime ISO format
- test_29: Aggregation consistency
- test_30: Empty portal block structure
- test_31: Full aggregation scenario
- test_32: Empty property all portals zero
- test_33: Serialization format

### Response Structure

```json
{
    "property_tag": "PROP-001",
    "metrics": {
        "total_inquiries": int,
        "total_visits": {
            "scheduled": int,
            "completed": int,
            "rescheduled": int,
            "pending_feedback": int,
            "cancelled": int
        },
        "conversion_rate": float,  // percentage 0-100
        "by_portal": {
            "MagicBricks": {
                "inquiries": int,
                "visits": int,
                "conversion": float
            },
            ...
        },
        "engagement": {
            "primary_leads": int,
            "recommended_interests": int,
            "feedback_rate": float
        },
        "period": {
            "start_date": "ISO8601",
            "end_date": "ISO8601",
            "days": int
        }
    },
    "error": null
}
```

---

## Test Coverage Matrix (Updated)

| Feature | CRUD | Compute | Validation | Integration | Cron | API |
|---------|:----:|:-------:|:----------:|:-----------:|:----:|:---:|
| Lead Creation | ✅ | | ✅ | | | |
| Phone Standardization | ✅ | ✅ | ✅ | | | ✅ |
| Duplicate Detection | | ✅ | ✅ | | | |
| Property Matching | | ✅ | | ✅ | ✅ | |
| RM Assignment | | ✅ | | ✅ | ✅ | |
| WhatsApp URLs | | ✅ | | | | |
| Follow-up Dates | | ✅ | | | ✅ | |
| External API | | | | ✅ | ✅ | |
| Webhooks | | | | ✅ | ✅ | |
| Lead Scoring | ✅ | ✅ | ✅ | | ✅ | |
| Property Interests | ✅ | ✅ | ✅ | | | |
| Feedback Fields | ✅ | | ✅ | | | ✅ |
| All Associated Props | | ✅ | | | | |
| Date Computations | | ✅ | | | | |
| **Buyer Site Visits** | | ✅ | ✅ | | | ✅ |
| **Seller Site Visits** | | ✅ | ✅ | | | ✅ |
| **Buyer Activity Feed** | | ✅ | | | | ✅ |
| **Seller Activity Feed** | | ✅ | | | | ✅ |
| **Seller Summary** | ✅ | ✅ | ✅ | | | ✅ |
| **Performance Metrics** | | ✅ | ✅ | | | ✅ |

| Feature | CRUD | Compute | Validation | Integration | Cron |
|---------|:----:|:-------:|:----------:|:-----------:|:----:|
| Lead Creation | ✅ | | ✅ | | |
| Phone Standardization | ✅ | ✅ | ✅ | | |
| Duplicate Detection | | ✅ | ✅ | | |
| Property Matching | | ✅ | | ✅ | |
| RM Assignment | | ✅ | | ✅ | ✅ |
| WhatsApp URLs | | ✅ | | | |
| Follow-up Dates | | ✅ | | | ✅ |
| External API | | | | ✅ | ✅ |
| Webhooks | | | | ✅ | ✅ |
---

## Common Test Fixtures

### Creating Test Data with Time Manipulation

```python
# Force a record to appear old (bypass ORM readonly)
from datetime import timedelta
from odoo import fields

old_date = fields.Datetime.now() - timedelta(days=31)
self.env.cr.execute(
    "UPDATE leads_new SET create_date = %s WHERE id = %s",
    (old_date, lead.id)
)
lead.invalidate_recordset()
```

### Mocking External Services

```python
from unittest.mock import patch, MagicMock

@patch('requests.post')
def test_webhook(self, mock_post):
    mock_post.return_value.raise_for_status = lambda: None
    # ... test code
```

### Expecting Database Errors

```python
from odoo.tools import mute_logger
import psycopg2

with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.IntegrityError):
    # Code that should raise IntegrityError
```

---

## Best Practices

### 1. Test Independence

Each test should be independent and not rely on state from other tests:

```python
def setUp(self):
    """Create fresh data for each test."""
    super().setUp()
    self.lead = self.create_portal_lead()
```

### 2. Use Dynamic IDs

Avoid hardcoded IDs that may conflict:

```python
# ✅ Good
cls.suffix = str(int(time.time()))
cls.mb_id = f'MB_{cls.suffix}'

# ❌ Bad
cls.mb_id = 'MB_12345'
```

### 3. Cache Invalidation

Always invalidate cache after direct SQL or when testing computed fields:

```python
lead.invalidate_recordset(['field_name'])
# or
lead.invalidate_recordset()  # All fields
```

### 4. Test Naming Convention

```
test_{order}_{description}

Examples:
- test_01_create_lead_with_required_fields
- test_02_missing_required_fields
```

---

## Troubleshooting

### Common Issues

#### 1. Tests Not Running

```bash
# Ensure module is installed
python odoo-bin -c odoo.conf -d <db> -i leads --stop-after-init

# Then run tests
python odoo-bin -c odoo.conf -d <db> --test-enable --stop-after-init -u leads
```

#### 2. IntegrityError Not Raised

Ensure you're using `mute_logger` and the correct exception:

```python
from odoo.tools import mute_logger
import psycopg2

with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.IntegrityError):
    # ...
```

#### 3. Computed Field Not Updating

```python
# Force recomputation
record.invalidate_recordset(['computed_field'])
# OR
record._compute_field_name()
```

#### 4. Cron Job Test Failures

```python
# Flush ORM before raw SQL
self.env.flush_all()

# Then execute SQL
self.env.cr.execute("UPDATE ...")

# Invalidate cache
record.invalidate_recordset()
```

---

## Contributing

When adding new tests:

1. Follow the existing naming conventions
2. Inherit from `PortalLeadTestCase` for portal lead tests
3. Use `@tagged('post_install', '-at_install')` decorator
4. Add test to `__init__.py` imports
5. Update this README with new test documentation

---

## License

This test suite is part of the Leads module and follows the same licensing as the parent Odoo project.

---

*Last Updated: February 2026*
*Odoo Version: 19.0*
