# Lead Suggestor Module - Test Suite Documentation

> **Odoo 19 Custom Module Testing Documentation**  
> **Module:** `lead_suggestor`  
> **Path:** `/custom_addons/lead_suggestor/tests/`

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Test Architecture](#test-architecture)
3. [Running Tests](#running-tests)
4. [Test Files Reference](#test-files-reference)
5. [Test Coverage Matrix](#test-coverage-matrix)
6. [Common Test Fixtures](#common-test-fixtures)
7. [Mocking BigQuery](#mocking-bigquery)
8. [Best Practices](#best-practices)
9. [Troubleshooting](#troubleshooting)

---

## Overview

This test suite provides comprehensive coverage for the **Lead Suggestor Module** in Odoo 19. The module enables property-based lead suggestions using BigQuery integration for ML-driven recommendations.

### Models Under Test

| Model | Description |
|-------|-------------|
| `property.inventory` | Property listings with portal IDs, RM assignments, and service dates |
| `property.lead.suggestion` | ML-generated lead suggestions linked to properties |

### Test Statistics

- **Total Test Files:** 11
- **Test Categories:** CRUD, Dates, Counts, WhatsApp, Feedback, Cron Jobs, Integration
- **External Dependencies:** Google BigQuery (mocked in tests)
- **Test Tags:** `@tagged('post_install', '-at_install')`

---

## Test Architecture

```
tests/
├── __init__.py                       # Test module imports
├── test_property_common.py           # Base test fixtures (PropertyInventoryTestCase)
│
├── Property Inventory Tests
│   ├── test_property_inventory_crud.py   # CRUD operations (8 tests)
│   ├── test_property_inventory_dates.py  # Date formatting (7 tests)
│   └── test_property_inventory_cron.py   # Cron jobs (6 tests)
│
├── Suggestion Tests
│   ├── test_suggestion_crud.py           # CRUD operations (9 tests)
│   ├── test_suggestion_counts.py         # Count computations (5 tests)
│   ├── test_suggestion_whatsapp.py       # WhatsApp integration (12 tests)
│   ├── test_suggestion_feedback.py       # Feedback logging (4 tests)
│   ├── test_suggestion_cron.py           # BigQuery sync (5 tests)
│   └── test_suggestion_dates.py          # Date formatting (4 tests)
│
├── test_integration.py               # Cross-model integration (3 tests)
└── README.md                         # This documentation
```

---

## Running Tests

### Run All Lead Suggestor Module Tests

```bash
# Windows (from project root)
python odoo-bin -c odoo.conf -d <database_name> --test-enable --stop-after-init -i lead_suggestor

# With specific log level
python odoo-bin -c odoo.conf -d <database_name> --test-enable --stop-after-init -i lead_suggestor --log-level=test
```

### Run Specific Test File

```bash
# Run only suggestion CRUD tests
python odoo-bin -c odoo.conf -d <database_name> --test-enable --stop-after-init --test-file=custom_addons/lead_suggestor/tests/test_suggestion_crud.py
```

### Run Tests by Tag

```bash
# Run post_install tests only
python odoo-bin -c odoo.conf -d <database_name> --test-tags=post_install
```

### Using pytest-odoo (Alternative)

```bash
pytest custom_addons/lead_suggestor/tests/ -v --odoo-database=<database_name>
```

---

## Test Files Reference

### 1. `test_property_common.py` - Base Test Fixtures

**Purpose:** Provides the `PropertyInventoryTestCase` base class with shared fixtures for all tests.

#### Fixtures Created:

| Fixture | Type | Description |
|---------|------|-------------|
| `cls.rm_user` | `res.users` | Primary test Relationship Manager |
| `cls.rm_user2` | `res.users` | Secondary RM for assignment tests |
| `cls.timestamp` | `str` | Unique identifier for test isolation |

#### Helper Methods:

```python
def create_property(self, **kwargs):
    """
    Create Property Inventory with sensible defaults.
    
    Default Values:
        - property_tag: Unique auto-generated tag
        - rm_user_id: cls.rm_user.id
        - is_active: True
        - service_expiry_date: today + 30 days
        - welcome_call_date: today
        - bhk: '3 BHK'
        - location: 'Test Location'
        - city: 'Test City'
    
    Returns:
        property.inventory: Created property record
    """

def create_suggestion(self, property_rec=None, **kwargs):
    """
    Create a Lead Suggestion with sensible defaults.
    
    Args:
        property_rec: Optional property record (creates one if None)
        **kwargs: Override any default field values
    
    Default Values:
        - suggested_lead_phone: Unique auto-generated phone
        - lead_name: 'Test Lead'
        - original_property_tag: 'OLD-PROP-001'
        - original_property_similarity: 85.0
        - generation_date: today
        - contact_type: 'New'
        - status: 'new'
    
    Returns:
        property.lead.suggestion: Created suggestion record
    """
```

---

### 2. `test_property_inventory_crud.py` - Property CRUD Operations

**Class:** `TestPropertyInventoryCRUD(PropertyInventoryTestCase)`  
**Model Under Test:** `property.inventory`  
**Total Tests:** 8

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_create_property_with_required_fields` | Basic property creation |
| 02 | `test_02_property_tag_required` | DB constraint for property_tag |
| 03 | `test_03_property_tag_unique_constraint` | Unique tag enforcement |
| 04 | `test_04_default_is_active` | Default active status |
| 05 | `test_05_rm_user_assignment` | RM user linkage |
| 06 | `test_06_optional_fields_storage` | Optional field persistence |
| 07 | `test_07_portal_ids_storage` | Portal ID storage |
| 08 | `test_08_property_ordering` | Order by service_expiry_date asc |

#### Portal IDs Tested:

```python
# All portal IDs stored in test_07
- magicbricks_id: 'MB12345'
- housing_id: 'HSG67890'
- ninety_nine_acres_id: '99ACR11223'
- olx_id: 'OLX44556'
```

---

### 3. `test_property_inventory_dates.py` - Property Date Handling

**Class:** `TestPropertyInventoryDates(PropertyInventoryTestCase)`  
**Model Under Test:** `property.inventory`  
**Total Tests:** 7

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_service_expiry_date_storage` | Date field storage |
| 02 | `test_02_welcome_call_date_storage` | Welcome call date |
| 03 | `test_03_service_expiry_display_format` | DD/MM/YYYY format |
| 04 | `test_04_welcome_call_display_format` | DD/MM/YYYY format |
| 05 | `test_05_date_display_with_leading_zeros` | Leading zeros in dates |
| 06 | `test_06_empty_date_display` | Empty string for null dates |
| 07 | `test_07_date_recompute_on_change` | Display recomputation |

#### Date Display Format:

```
Input: date(2026, 3, 14)
Output: '14/03/2026'  (DD/MM/YYYY)

Input: date(2026, 1, 5)
Output: '05/01/2026'  (with leading zeros)

Input: False/None
Output: ''  (empty string)
```

---

### 4. `test_property_inventory_cron.py` - Property Cron Jobs

**Class:** `TestPropertyInventoryCron(PropertyInventoryTestCase)`  
**Model Under Test:** `property.inventory`  
**Total Tests:** 6

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_cleanup_marks_expired_properties_inactive` | Deactivate expired |
| 02 | `test_02_cleanup_keeps_active_properties_active` | Keep future-expiry active |
| 03 | `test_03_cleanup_handles_multiple_expired` | Batch expired handling |
| 04 | `test_04_cleanup_skips_already_inactive` | Skip inactive properties |
| 05 | `test_05_cleanup_boundary_today` | Today's expiry = active |
| 06 | `test_06_sync_properties_handles_bigquery_error` | BQ error handling |

#### Cron Method: `_cron_cleanup_expired_properties`

```
Expiry Logic:
├── service_expiry_date < today → is_active = False
├── service_expiry_date = today → remains active
└── service_expiry_date > today → remains active
```

---

### 5. `test_suggestion_crud.py` - Suggestion CRUD Operations

**Class:** `TestSuggestionCRUD(PropertyInventoryTestCase)`  
**Model Under Test:** `property.lead.suggestion`  
**Total Tests:** 9

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_create_suggestion_with_required_fields` | Basic creation |
| 02 | `test_02_suggestion_requires_property` | Property FK required |
| 03 | `test_03_suggestion_requires_phone` | Phone field required |
| 04 | `test_04_unique_constraint_property_phone` | Unique per property |
| 05 | `test_05_same_phone_different_properties_allowed` | Cross-property allowed |
| 06 | `test_06_property_tag_related_field` | Related field access |
| 07 | `test_07_default_status_new` | Default 'new' status |
| 08 | `test_08_status_field_values` | Valid status values |
| 09 | `test_09_suggestion_ordering` | Order by date desc |

#### Valid Status Values:

```python
[
    'new',
    'contacted', 
    'details_shared_of_property',
    'not_interested',
    'interested',
    'converted',
    'whatsapp_done',
    'other'
]
```

#### Unique Constraint:

```
UNIQUE(property_inventory_id, suggested_lead_phone)

✅ Allowed: Same phone for DIFFERENT properties
❌ Blocked: Same phone for SAME property
```

---

### 6. `test_suggestion_counts.py` - Count Computations

**Class:** `TestSuggestionCounts(PropertyInventoryTestCase)`  
**Model Under Test:** `property.inventory` (computed fields)  
**Total Tests:** 5

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_initial_counts_zero` | Zero counts on new property |
| 02 | `test_02_total_count_increases` | Total count increments |
| 03 | `test_03_new_count_only_counts_new_status` | Filter by 'new' status |
| 04 | `test_04_counts_update_on_status_change` | Dynamic count updates |
| 05 | `test_05_multiple_properties_independent_counts` | Property isolation |

#### Computed Fields:

| Field | Description |
|-------|-------------|
| `suggestion_count` | Total suggestions linked to property |
| `new_suggestion_count` | Suggestions with status='new' only |

---

### 7. `test_suggestion_whatsapp.py` - WhatsApp Integration

**Class:** `TestSuggestionWhatsapp(PropertyInventoryTestCase)`  
**Model Under Test:** `property.lead.suggestion`  
**Total Tests:** 12

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_whatsapp_url_10_digit_phone` | Standard 10-digit phone |
| 02 | `test_02_whatsapp_url_with_91_prefix` | Handle 91 prefix |
| 03 | `test_03_whatsapp_url_with_leading_zero` | Strip leading zero |
| 04 | `test_04_whatsapp_url_with_spaces_dashes` | Clean special chars |
| 05 | `test_05_whatsapp_url_with_plus_sign` | Handle +91 prefix |
| 06 | `test_06_whatsapp_url_invalid_phone` | Invalid = False |
| 07 | `test_07_whatsapp_url_empty_phone` | Empty = False |
| 08 | `test_08_whatsapp_html_contains_icon` | fa-whatsapp icon |
| 09 | `test_09_whatsapp_html_no_url_shows_plain_phone` | Fallback display |
| 10 | `test_10_action_whatsapp_returns_client_action` | Client action type |
| 11 | `test_11_action_whatsapp_message_contains_details` | Message content |
| 12 | `test_12_action_whatsapp_uses_first_name_only` | First name extraction |

#### Phone Standardization Examples:

| Input | Output URL Contains |
|-------|---------------------|
| `9876543210` | `phone=919876543210` |
| `919876543210` | `phone=919876543210` |
| `09876543210` | `phone=919876543210` |
| `98765-43210` | `phone=919876543210` |
| `+919876543210` | `phone=919876543210` |
| `INVALID` | `False` |
| `` (empty) | `False` |

#### WhatsApp Action Structure:

```python
{
    'type': 'ir.actions.client',
    'tag': 'whatsapp_with_copy',
    'context': {
        'whatsapp_url': 'whatsapp://send?phone=91...',
        'message_text': 'Hi {name}, ...'  # Contains BHK, location, city, link
    }
}
```

---

### 8. `test_suggestion_feedback.py` - Feedback Logging

**Class:** `TestSuggestionFeedback(PropertyInventoryTestCase)`  
**Model Under Test:** `property.lead.suggestion`  
**Total Tests:** 4

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_action_log_feedback_returns_wizard` | Returns wizard action |
| 02 | `test_02_action_log_feedback_passes_context` | Context with defaults |
| 03 | `test_03_rm_feedback_field_storage` | Feedback text storage |
| 04 | `test_04_status_transitions` | Status can be changed |

#### Feedback Wizard Action:

```python
{
    'type': 'ir.actions.act_window',
    'res_model': 'suggestion.feedback.wizard',
    'view_mode': 'form',
    'target': 'new',
    'context': {
        'default_suggestion_id': suggestion.id,
        'default_status': 'contacted',
        'default_rm_feedback': 'Initial contact made'
    }
}
```

---

### 9. `test_suggestion_cron.py` - BigQuery Sync Cron

**Class:** `TestSuggestionCron(PropertyInventoryTestCase)`  
**Model Under Test:** `property.lead.suggestion`  
**Total Tests:** 5

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_cron_sync_creates_new_suggestions` | Create from BQ data |
| 02 | `test_02_cron_sync_skips_duplicates` | Skip existing phone+property |
| 03 | `test_03_cron_sync_skips_unknown_properties` | Skip non-existent properties |
| 04 | `test_04_cron_sync_handles_multiple_suggestions` | Batch creation |
| 05 | `test_05_cron_sync_handles_bigquery_error` | Graceful error handling |

#### BigQuery Mock Structure:

```python
from collections import namedtuple

BQRow = namedtuple('Row', [
    'active_property_tag',
    'suggested_lead_phone',
    'lead_name',
    'original_property_tag',
    'original_property_similarity',
    'generation_date',
    'current_status'
])
```

---

### 10. `test_suggestion_dates.py` - Suggestion Date Handling

**Class:** `TestSuggestionDates(PropertyInventoryTestCase)`  
**Model Under Test:** `property.lead.suggestion`  
**Total Tests:** 4

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_generation_date_default_today` | Default to today |
| 02 | `test_02_generation_date_display_format` | DD/MM/YYYY format |
| 03 | `test_03_generation_date_display_with_zeros` | Leading zeros |
| 04 | `test_04_generation_date_recompute` | Recompute on change |

---

### 11. `test_integration.py` - Cross-Model Integration

**Class:** `TestPropertySuggestionIntegration(PropertyInventoryTestCase)`  
**Models Under Test:** `property.inventory`, `property.lead.suggestion`  
**Total Tests:** 3

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_property_cascade_delete_suggestions` | Cascade delete |
| 02 | `test_02_suggestion_one2many_relationship` | One2many access |
| 03 | `test_03_multiple_properties_suggestion_isolation` | Data isolation |

#### Relationship Diagram:

```
property.inventory (1) ──────────< (∞) property.lead.suggestion
       │                                        │
       │ suggestion_ids (One2many)              │
       └────────────────────────────────────────┘
                                     property_inventory_id (Many2one)

ON DELETE: CASCADE (suggestions deleted with property)
```

---

## Test Coverage Matrix

| Feature | CRUD | Compute | Validation | Cron | Integration |
|---------|:----:|:-------:|:----------:|:----:|:-----------:|
| Property Creation | ✅ | | ✅ | | |
| Property Tags | ✅ | | ✅ | | |
| Portal IDs | ✅ | | | | |
| Date Formatting | | ✅ | | | |
| Service Expiry | | ✅ | | ✅ | |
| Suggestion Creation | ✅ | | ✅ | | |
| Unique Constraints | | | ✅ | | |
| Suggestion Counts | | ✅ | | | |
| WhatsApp URLs | | ✅ | | | |
| WhatsApp Messages | | ✅ | | | |
| Feedback Wizard | ✅ | | | | |
| BigQuery Sync | | | | ✅ | ✅ |
| Cascade Delete | | | | | ✅ |

---

## Common Test Fixtures

### Creating Unique Test Data

```python
import time
import random

# Unique suffix for test isolation
unique_suffix = f"{int(time.time() * 100000)}_{random.randint(1000, 9999)}"

# Unique phone number
unique_phone = f'9{unique_suffix[-9:]}'

# Unique property tag
property_tag = f'TEST-PROP-{unique_suffix}'
```

### Testing Database Constraints

```python
from odoo.tools import mute_logger
import psycopg2

# Test NOT NULL constraint
with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.IntegrityError):
    self.env['property.inventory'].create({
        'is_active': True,
        # Missing 'property_tag' triggers IntegrityError
    })

# Test UNIQUE constraint
with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.IntegrityError):
    self.create_property(property_tag='DUPLICATE-TAG')  # Already exists
```

### Cache Invalidation

```python
# Invalidate specific field
prop.invalidate_recordset(['suggestion_count'])

# Invalidate all fields
prop.invalidate_recordset()
```

---

## Mocking BigQuery

### Basic Setup

```python
from unittest.mock import patch, MagicMock

@patch('google.cloud.bigquery.Client')
def test_bigquery_sync(self, mock_bq_client):
    # Create mock instance
    mock_instance = mock_bq_client.return_value
    mock_query_job = MagicMock()
    mock_instance.query.return_value = mock_query_job
    
    # Define row structure
    from collections import namedtuple
    BQRow = namedtuple('Row', [
        'active_property_tag',
        'suggested_lead_phone',
        'lead_name',
        'original_property_tag',
        'original_property_similarity',
        'generation_date',
        'current_status'
    ])
    
    # Create mock data
    mock_rows = [
        BQRow(
            active_property_tag='PROP-001',
            suggested_lead_phone='9876543210',
            lead_name='Test Lead',
            original_property_tag='OLD-PROP',
            original_property_similarity=0.85,
            generation_date=date.today(),
            current_status='New'
        )
    ]
    
    mock_query_job.result.return_value = mock_rows
    
    # Run the method
    self.env['property.lead.suggestion']._cron_sync_suggestions()
```

### Mocking Errors

```python
@patch('google.cloud.bigquery.Client')
def test_bigquery_error_handling(self, mock_bq_client):
    # Simulate connection error
    mock_bq_client.side_effect = Exception("BigQuery connection failed")
    
    # Should not raise - handles gracefully
    try:
        self.env['property.lead.suggestion']._cron_sync_suggestions()
    except Exception as e:
        self.fail(f"Should handle BQ errors gracefully: {e}")
```

---

## Best Practices

### 1. Test Independence

Each test should be independent:

```python
def setUp(self):
    super().setUp()
    self.property = self.create_property()  # Fresh data each test
```

### 2. Use High-Resolution Unique IDs

```python
# ✅ Good - High resolution + random
unique_suffix = f"{int(time.time() * 100000)}_{random.randint(1000, 9999)}"

# ❌ Bad - May collide in fast tests
unique_suffix = str(int(time.time()))
```

### 3. Test Naming Convention

```
test_{order}_{description}

Examples:
- test_01_create_property_with_required_fields
- test_02_property_tag_required
- test_03_property_tag_unique_constraint
```

### 4. Always Invalidate Cache After Status Changes

```python
suggestion.status = 'contacted'
prop.invalidate_recordset(['new_suggestion_count'])  # Recompute
```

### 5. Group Related Assertions

```python
# ✅ Good - Clear grouping
self.assertEqual(prop.suggestion_count, 4)
self.assertEqual(prop.new_suggestion_count, 2)

# ❌ Bad - Mixed concerns
self.assertTrue(prop.id)
self.assertEqual(prop.suggestion_count, 4)
self.assertEqual(prop.property_tag, 'TAG')
```

---

## Troubleshooting

### Common Issues

#### 1. IntegrityError Not Raised

```python
# Ensure you're using mute_logger to suppress expected errors
from odoo.tools import mute_logger
import psycopg2

with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.IntegrityError):
    # Code that should raise
```

#### 2. Computed Field Not Updating

```python
# Force recomputation
record.invalidate_recordset(['computed_field'])

# Or invalidate all
record.invalidate_recordset()
```

#### 3. BigQuery Mock Not Working

```python
# Ensure you're patching the correct import path
@patch('google.cloud.bigquery.Client')  # ✅ Correct

# NOT the method path
@patch('odoo.addons.lead_suggestor.models.property.bigquery.Client')  # May not work
```

#### 4. Unique Constraint Violations in Tests

```python
# Use high-resolution unique identifiers
unique_suffix = f"{int(time.time() * 100000)}_{random.randint(1000, 9999)}"

# NOT just timestamp (can collide in fast tests)
unique_suffix = str(int(time.time()))  # ❌
```

#### 5. Tests Not Isolated

```python
# Always create fresh data in setUp or test method
def setUp(self):
    super().setUp()
    self.prop = self.create_property()  # Fresh each test

# DON'T rely on class-level data for mutable state
@classmethod
def setUpClass(cls):
    # Only for truly immutable fixtures (users, etc.)
```

---

## Contributing

When adding new tests:

1. Follow existing naming conventions
2. Inherit from `PropertyInventoryTestCase`
3. Use `@tagged('post_install', '-at_install')` decorator
4. Add test import to `__init__.py`
5. Update this README with new test documentation
6. Mock external dependencies (BigQuery, APIs)
7. Use unique identifiers to prevent test pollution

---

## License

This test suite is part of the Lead Suggestor module and follows the same licensing as the parent Odoo project.

---

*Last Updated: January 2026*  
*Odoo Version: 19.0*
