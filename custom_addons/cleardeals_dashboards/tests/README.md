# ClearDeals Dashboards Module - Test Suite Documentation

> **Odoo 19 Custom Module Testing Documentation**  
> **Module:** `cleardeals_dashboards`  
> **Path:** `/custom_addons/cleardeals_dashboards/tests/`

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Test Architecture](#test-architecture)
3. [Running Tests](#running-tests)
4. [Test Files Reference](#test-files-reference)
5. [Test Coverage Matrix](#test-coverage-matrix)
6. [Common Test Fixtures](#common-test-fixtures)
7. [Template System](#template-system)
8. [Best Practices](#best-practices)
9. [Troubleshooting](#troubleshooting)

---

## Overview

This test suite provides comprehensive coverage for the **ClearDeals Lead Scoring Dashboards Module** in Odoo 19. The module provides WhatsApp communication tracking, lead scoring metrics, and event-driven analytics.

### Models Under Test

| Model | Description |
|-------|-------------|
| `lead.scoring.lead` | Lead records with scoring, workflow stages, and computed metrics |
| `lead.scoring.event` | WhatsApp message events (sent, delivered, read, failed, replies) |

### Test Statistics

- **Total Test Files:** 7
- **Test Categories:** CRUD, Events, Funnel Metrics, Smart Buttons, Template Counts
- **Test Tags:** `@tagged('post_install', '-at_install')`

---

## Test Architecture

```
tests/
├── __init__.py                           # Test module imports
├── test_lead_scoring_common.py           # Base test fixtures (LeadScoringTestCase)
│
├── Lead Model Tests
│   ├── test_lead_scoring_crud.py         # CRUD operations (7 tests)
│   ├── test_lead_scoring_funnel.py       # Funnel metrics (8 tests)
│   ├── test_lead_scoring_metrics.py      # Message counts (8 tests)
│   ├── test_lead_scoring_template_counts.py  # Template tracking (10 tests)
│   └── test_lead_scoring_smart_buttons.py    # UI actions (4 tests)
│
├── Event Model Tests
│   └── test_lead_scoring_events.py       # Event relationships (3 tests)
│
└── README.md                             # This documentation
```

---

## Running Tests

### Run All ClearDeals Dashboards Tests

```bash
# Windows (from project root)
python odoo-bin -c odoo.conf -d <database_name> --test-enable --stop-after-init -i cleardeals_dashboards

# With specific log level
python odoo-bin -c odoo.conf -d <database_name> --test-enable --stop-after-init -i cleardeals_dashboards --log-level=test
```

### Run Specific Test File

```bash
# Run only funnel tests
python odoo-bin -c odoo.conf -d <database_name> --test-enable --stop-after-init --test-file=custom_addons/cleardeals_dashboards/tests/test_lead_scoring_funnel.py
```

### Run Tests by Tag

```bash
# Run post_install tests only
python odoo-bin -c odoo.conf -d <database_name> --test-tags=post_install
```

### Using pytest-odoo (Alternative)

```bash
pytest custom_addons/cleardeals_dashboards/tests/ -v --odoo-database=<database_name>
```

---

## Test Files Reference

### 1. `test_lead_scoring_common.py` - Base Test Fixtures

**Purpose:** Provides the `LeadScoringTestCase` base class with shared fixtures and helper methods.

#### Class Variables:

| Variable | Type | Description |
|----------|------|-------------|
| `_phone_counter` | `int` | Counter for unique phone generation |
| `timestamp` | `str` | Unique identifier for test isolation |
| `TEMPLATE_TRIGGERS` | `list` | Outbound trigger template names |
| `TEMPLATE_RESPONSES` | `list` | Response template names |

#### Helper Methods:

```python
def create_lead(self, **kwargs):
    """
    Create a lead with guaranteed unique phone number.
    
    Default Values:
        - lead_name: 'Test Lead'
        - lead_phone: Auto-generated unique
        - property_tag: 'PROP-{unique}'
        - assigned_rm: 'Test RM'
        - predicted_score: 0.85
        - current_status: 'lead'
        - workflow_stage: 'ringing'
    
    Returns:
        lead.scoring.lead: Created lead record
    """

def create_event(self, lead=None, **kwargs):
    """
    Create an event with defaults.
    
    Default Values:
        - event_id: Auto-generated unique
        - correlation_id: Auto-generated unique
        - event_timestamp: now()
        - event_type: 'message_sent'
        - message_direction: 'outbound'
        - template_name: 'ringing'
    
    Returns:
        lead.scoring.event: Created event record
    """

def create_outbound_sent_event(self, lead, template_name, correlation_id=None):
    """Create a message_sent outbound event."""

def create_status_event(self, lead, status_type, correlation_id):
    """Create a status event (delivered/read/failed)."""

def create_inbound_event(self, lead, message_content='Customer reply'):
    """Create an inbound message event."""
```

---

### 2. `test_lead_scoring_crud.py` - Lead CRUD Operations

**Class:** `TestLeadScoringCRUD(LeadScoringTestCase)`  
**Model Under Test:** `lead.scoring.lead`  
**Total Tests:** 7

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_create_lead_with_required_fields` | Basic lead creation |
| 02 | `test_02_lead_phone_required` | Phone DB constraint |
| 03 | `test_03_unique_phone_constraint` | Unique phone enforcement |
| 04 | `test_04_default_values` | Default computed fields |
| 05 | `test_05_workflow_stage_values` | Valid workflow stages |
| 06 | `test_06_optional_fields_storage` | Optional field persistence |
| 07 | `test_07_lead_ordering` | Order by last_activity desc |

#### Valid Workflow Stages:

```python
[
    'ringing',
    'detail_shared_of_property_message',
    'site_visit_schedule_reminder',
    'site_visit_schedule_after_visit',
    'other'
]
```

#### Default Computed Field Values:

```python
# On creation, all funnel metrics default to False
is_delivered = False
is_read = False
has_replied = False
```

---

### 3. `test_lead_scoring_events.py` - Event Relationships

**Class:** `TestLeadScoringEvents(LeadScoringTestCase)`  
**Model Under Test:** `lead.scoring.event`  
**Total Tests:** 3

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_event_one2many_relationship` | Lead access to events |
| 02 | `test_02_events_isolated_per_lead` | Event isolation per lead |
| 03 | `test_03_event_cascade_delete` | Cascade delete on lead removal |

#### Relationship Diagram:

```
lead.scoring.lead (1) ──────────< (∞) lead.scoring.event
       │                                    │
       │ event_ids (One2many)               │
       └────────────────────────────────────┘
                                 lead_id (Many2one)

ON DELETE: CASCADE (events deleted with lead)
```

---

### 4. `test_lead_scoring_funnel.py` - Funnel Metrics

**Class:** `TestLeadScoringFunnel(LeadScoringTestCase)`  
**Model Under Test:** `lead.scoring.lead`  
**Total Tests:** 8

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_initial_funnel_state` | All metrics False initially |
| 02 | `test_02_is_delivered_on_delivered_event` | Delivered flag on status_delivered |
| 03 | `test_03_is_delivered_on_read_event` | Delivered flag on status_read |
| 04 | `test_04_is_read_on_read_event` | Read flag on status_read |
| 05 | `test_05_is_read_not_set_on_delivered_event` | Read False if only delivered |
| 06 | `test_06_has_replied_on_inbound_message` | Replied flag on inbound |
| 07 | `test_07_last_response_captures_inbound_content` | Most recent reply content |
| 08 | `test_08_last_response_false_when_no_replies` | False when no inbound |

#### Funnel Metric Logic:

```
Message Flow:
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  message_sent   │ -> │ status_delivered│ -> │   status_read   │
│                 │    │ is_delivered=✓  │    │ is_delivered=✓  │
│                 │    │                 │    │ is_read=✓       │
└─────────────────┘    └─────────────────┘    └─────────────────┘

Customer Reply:
┌─────────────────┐
│message_received │ -> has_replied=✓, last_response="content"
│   (inbound)     │
└─────────────────┘
```

---

### 5. `test_lead_scoring_metrics.py` - Message Count Metrics

**Class:** `TestLeadScoringMetrics(LeadScoringTestCase)`  
**Model Under Test:** `lead.scoring.lead`  
**Total Tests:** 8

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_initial_counts_zero` | All counts zero initially |
| 02 | `test_02_total_outbound_counts_unique_messages` | Unique outbound count |
| 03 | `test_03_total_outbound_ignores_status_events` | Exclude status events |
| 04 | `test_04_total_outbound_deduplicates_same_correlation` | Deduplicate by correlation_id |
| 05 | `test_05_total_inbound_counts_all_replies` | All inbound messages |
| 06 | `test_06_total_failed_counts_unique_failures` | Unique failed count |
| 07 | `test_07_total_failed_deduplicates_same_correlation` | Deduplicate failures |
| 08 | `test_08_last_activity_tracks_most_recent_event` | Latest event timestamp |

#### Count Metrics Logic:

```python
# total_outbound: Unique correlation_ids for message_sent events
# Excludes: status_delivered, status_read, status_failed

# total_inbound: All inbound message_received events
# No deduplication (each reply counted)

# total_failed: Unique correlation_ids for status_failed events
# Deduplicated by correlation_id
```

---

### 6. `test_lead_scoring_template_counts.py` - Template Tracking

**Class:** `TestLeadScoringTemplateCounts(LeadScoringTestCase)`  
**Model Under Test:** `lead.scoring.lead`  
**Total Tests:** 10

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_all_template_counts_initially_zero` | All counts zero |
| 02 | `test_02_cnt_ringing_counts_ringing_template` | Ringing template count |
| 03 | `test_03_cnt_details_counts_detail_shared_template` | Details template count |
| 04 | `test_04_cnt_visit_reminder_counts_reminder_template` | Visit reminder count |
| 05 | `test_05_cnt_visit_feedback_counts_feedback_template` | Visit feedback count |
| 06 | `test_06_response_templates_counted_separately` | Response template isolation |
| 07 | `test_07_template_counts_deduplicate_by_correlation` | Correlation deduplication |
| 08 | `test_08_template_counts_ignore_non_template_events` | Ignore null templates |
| 09 | `test_09_template_counts_only_outbound` | Outbound only |
| 10 | `test_10_multiple_templates_counted_independently` | Independent template counts |

#### Template Count Fields:

| Field | Template Name |
|-------|---------------|
| `cnt_ringing` | `ringing` |
| `cnt_details` | `detail_shared_of_property_message` |
| `cnt_visit_reminder` | `site_visit_schedule_reminder` |
| `cnt_visit_feedback` | `site_visit_schedule_after_visit` |
| `cnt_resp_going_visit` | `going_for_visit_today` |
| `cnt_resp_need_help` | `need_help_for_site_visit_today` |
| `cnt_resp_visit_done` | `visit_done_response_after_site_visit` |
| `cnt_resp_abhi_call` | `ringing_abhi_call_kare` |

---

### 7. `test_lead_scoring_smart_buttons.py` - UI Actions

**Class:** `TestLeadScoringSmartButtons(LeadScoringTestCase)`  
**Model Under Test:** `lead.scoring.lead`  
**Total Tests:** 4

| Test ID | Method | Description |
|---------|--------|-------------|
| 01 | `test_01_action_view_events_returns_outbound_domain` | Events button action |
| 02 | `test_02_action_view_replies_returns_inbound_domain` | Replies button action |
| 03 | `test_03_action_view_failures_returns_failed_domain` | Failures button action |
| 04 | `test_04_smart_button_actions_have_default_context` | Context with default_lead_id |

#### Smart Button Action Structure:

```python
# action_view_events()
{
    'type': 'ir.actions.act_window',
    'res_model': 'lead.scoring.event',
    'view_mode': 'list,form',
    'domain': [
        ('lead_id', '=', lead.id),
        ('message_direction', '=', 'outbound')
    ],
    'context': {'default_lead_id': lead.id}
}

# action_view_replies()
{
    'type': 'ir.actions.act_window',
    'res_model': 'lead.scoring.event',
    'domain': [
        ('lead_id', '=', lead.id),
        ('message_direction', '=', 'inbound')
    ],
    'context': {'default_lead_id': lead.id}
}

# action_view_failures()
{
    'type': 'ir.actions.act_window',
    'res_model': 'lead.scoring.event',
    'domain': [
        ('lead_id', '=', lead.id),
        ('event_type', '=', 'status_failed')
    ],
    'context': {'default_lead_id': lead.id}
}
```

---

## Test Coverage Matrix

| Feature | CRUD | Compute | Validation | Relationship | UI Actions |
|---------|:----:|:-------:|:----------:|:------------:|:----------:|
| Lead Creation | ✅ | | ✅ | | |
| Phone Uniqueness | | | ✅ | | |
| Event Tracking | ✅ | | | ✅ | |
| Funnel Metrics | | ✅ | | | |
| Message Counts | | ✅ | | | |
| Template Counts | | ✅ | | | |
| Last Activity | | ✅ | | | |
| Smart Buttons | | | | | ✅ |
| Cascade Delete | | | | ✅ | |

---

## Common Test Fixtures

### Creating Unique Test Data

```python
# The helper automatically generates unique phones
lead = self.create_lead()  # Phone auto-generated

# Override specific phone if needed
lead = self.create_lead(lead_phone='9876543210')
```

### Event Creation Patterns

```python
# Full message flow: sent -> delivered -> read
corr_id = 'corr_123'

self.create_outbound_sent_event(lead, 'ringing', correlation_id=corr_id)
self.create_status_event(lead, 'status_delivered', corr_id)
self.create_status_event(lead, 'status_read', corr_id)

# Customer reply
self.create_inbound_event(lead, 'Yes, interested')
```

### Testing Database Constraints

```python
from odoo.tools import mute_logger
from psycopg2 import IntegrityError

# Test NOT NULL constraint
with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
    self.env['lead.scoring.lead'].create({
        'lead_name': 'Test',
        # Missing 'lead_phone' triggers IntegrityError
    })

# Test UNIQUE constraint
with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
    self.create_lead(lead_phone='9876543210')  # Already exists
```

### Cache Invalidation

```python
# After creating events, invalidate computed fields
lead.invalidate_recordset()

# Or specific fields
lead.invalidate_recordset(['is_delivered', 'is_read', 'total_outbound'])
```

---

## Template System

### Trigger Templates (Outbound)

```python
TEMPLATE_TRIGGERS = [
    'ringing',                           # Initial contact
    'detail_shared_of_property_message', # Property details
    'site_visit_schedule_reminder',      # Visit reminder
    'site_visit_schedule_after_visit'    # Post-visit follow-up
]
```

### Response Templates

```python
TEMPLATE_RESPONSES = [
    'going_for_visit_today',
    'need_help_for_site_visit_today',
    'visit_done_response_after_site_visit',
    'liked_property_after_site_visit',
    'call_the_expert_after_site_vist',
    'reschedule_visit_response',
    'ringing_abhi_call_kare',
    'ringing_slot_book_kare',
    'schedule_visit_now_response',
    'talk_to_a_property_expert_response'
]
```

### Event Types

| Event Type | Description | Direction |
|------------|-------------|-----------|
| `message_sent` | Initial message send | Outbound |
| `status_sent` | Send confirmation | Outbound |
| `status_delivered` | Delivery confirmation | Outbound |
| `status_read` | Read receipt | Outbound |
| `status_failed` | Delivery failure | Outbound |
| `message_received` | Customer reply | Inbound |

### Correlation ID Usage

```
correlation_id links related events:

message_sent (corr_001) ─┬─> status_delivered (corr_001)
                         └─> status_read (corr_001)

Deduplication: Counts use DISTINCT correlation_id
```

---

## Best Practices

### 1. Use Helper Methods

```python
# ✅ Good - Uses helper with auto-unique phone
lead = self.create_lead()

# ❌ Bad - Manual creation without unique phone handling
lead = self.env['lead.scoring.lead'].create({...})
```

### 2. Track Correlation IDs

```python
# ✅ Good - Explicit correlation_id for related events
corr_id = 'corr_unique_123'
self.create_outbound_sent_event(lead, 'ringing', correlation_id=corr_id)
self.create_status_event(lead, 'status_delivered', corr_id)

# ❌ Bad - Auto-generated correlation_ids (can't link events)
self.create_outbound_sent_event(lead, 'ringing')
self.create_status_event(lead, 'status_delivered', 'different_corr')
```

### 3. Invalidate Cache After Event Creation

```python
# Create events
self.create_outbound_sent_event(lead, 'ringing', 'corr_1')
self.create_status_event(lead, 'status_delivered', 'corr_1')

# ✅ Good - Invalidate before assertions
lead.invalidate_recordset()
self.assertTrue(lead.is_delivered)

# ❌ Bad - Stale cache may cause false assertions
self.assertTrue(lead.is_delivered)  # May be False from cache
```

### 4. Test Naming Convention

```
test_{order}_{description}

Examples:
- test_01_create_lead_with_required_fields
- test_02_lead_phone_required
- test_03_unique_phone_constraint
```

---

## Troubleshooting

### Common Issues

#### 1. IntegrityError Not Raised

```python
# Ensure mute_logger is used
from odoo.tools import mute_logger
from psycopg2 import IntegrityError

with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):
    # Code that should raise
```

#### 2. Computed Field Not Updating

```python
# Force cache invalidation
lead.invalidate_recordset()

# For specific fields
lead.invalidate_recordset(['is_delivered', 'total_outbound'])

# Or flush and invalidate
self.env.flush_all()
lead.invalidate_recordset()
```

#### 3. Duplicate Phone Errors in Tests

```python
# Use the helper - it auto-generates unique phones
lead = self.create_lead()  # ✅ Safe

# If manually specifying phone, ensure uniqueness
unique_phone = f'99{int(time.time())}_{random.randint(100,999)}'[-10:]
lead = self.create_lead(lead_phone=unique_phone)
```

#### 4. Event Order Issues

```python
# Events may not be in expected order - use timestamps
from datetime import datetime, timedelta

old_time = datetime.now() - timedelta(hours=2)
new_time = datetime.now()

self.create_event(lead=lead, event_timestamp=old_time)
self.create_event(lead=lead, event_timestamp=new_time)

lead.invalidate_recordset(['last_activity'])
# last_activity should be new_time
```

#### 5. Template Count Not Incrementing

```python
# Ensure template_name matches exactly
self.create_outbound_sent_event(lead, 'ringing', 'corr_1')  # ✅

# Wrong template name (typo)
self.create_outbound_sent_event(lead, 'Ringing', 'corr_1')  # ❌ Case sensitive

# Ensure it's outbound (inbound events don't count for templates)
self.create_event(
    lead=lead,
    message_direction='outbound',  # ✅ Required
    template_name='ringing',
    ...
)
```

---

## Contributing

When adding new tests:

1. Follow existing naming conventions
2. Inherit from `LeadScoringTestCase`
3. Use `@tagged('post_install', '-at_install')` decorator
4. Add test import to `__init__.py`
5. Update this README with new test documentation
6. Use helper methods for data creation
7. Always invalidate cache before assertions on computed fields
8. Use explicit correlation_ids for related events

---

## License

This test suite is part of the ClearDeals Dashboards module and follows the same licensing as the parent Odoo project.

---

*Last Updated: January 2026*  
*Odoo Version: 19.0*
