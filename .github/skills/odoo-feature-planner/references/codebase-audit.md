# Codebase Audit Protocol

When the user provides a codebase path, repo, or says "consider the full
codebase", run this audit before asking any questions.

The audit answers one question per category: **what does this feature touch here?**

Work through every category. Do not skip any. Mark clearly if a category
is unaffected — a conscious "not affected" is different from "I didn't check".

---

## How to traverse the codebase

If you have filesystem access, run this first to understand the structure:

```bash
# Get the full module structure
find custom_addons -name "*.py" | sort
find custom_addons -name "*.xml" | sort
find custom_addons -name "*.csv" | sort
find custom_addons -name "__manifest__.py" | sort

# Find all references to a field or model name
grep -rn "field_name\|model_name" custom_addons --include="*.py" --include="*.xml"

# Find all cron definitions
grep -rn "ir.cron\|_cron_" custom_addons --include="*.py" --include="*.xml"

# Find all ir.rule definitions
grep -rn "ir.rule" custom_addons --include="*.xml"

# Find all webhook payload builders
grep -rn "batch_payload\|lead_data\|webhook" custom_addons --include="*.py"
```

If you have been given file contents in the conversation, read all of them
fully before starting the audit categories below.

---

## Audit Category 1 — Model layer

**Files:** `*/models/*.py`, `*/models/__init__.py`

For each model that the feature touches or is adjacent to:

```
□ What fields currently exist? Which are computed/stored?
□ What does create() currently do? Any non-trivial logic?
□ What does write() currently do? Any tracking/stamping logic?
□ Are there _sql_constraints? Will the feature conflict with them?
□ Are there @api.depends chains? Will a new field need to be added?
□ Are there related= fields on other models pointing here?
  (these auto-update — may cause unexpected side effects)
□ Does the model inherit mail.thread? (chatter implications)
□ What is the _order field? Will new records sort correctly?
```

**Red flags to document:**
- `write()` overrides with complex branching — new features can create
  unintended recursive paths
- Stored computed fields — adding a dependency field requires
  recomputing all existing records (migration needed)
- `_sql_constraints` on fields the feature will populate
  (ON CONFLICT behaviour in migration scripts)

---

## Audit Category 2 — Security layer

**Files:** `*/security/*.xml`, `*/security/ir.model.access.csv`

```
□ Which ir.rule records govern the affected models?
  Document each rule's domain_force exactly.
□ Does any rule use user.id comparison that would block the new feature?
□ Does the new feature require cross-user reads?
  (Check for existing context keys on field definitions — e.g. context={'search_all_properties_for_lead': True})
□ Are there group-based restrictions on views (groups= attribute)?
  Will new UI elements need to be gated on a group?
□ Does ir.model.access.csv cover all models the feature needs?
  If adding a new model: new rows required.
□ Which group does the requesting user role belong to?
  (group_property_rm vs group_property_manager)
```

**Critical check — the context key pattern:**
If a field definition has `context={'some_key': True}`, search for that
key in all `ir.rule` domain_force definitions. If no rule honours the key,
the context key does nothing and cross-user access is silently blocked.

---

## Audit Category 3 — View layer

**Files:** `*/views/*.xml`

```
□ List every view that displays fields from the affected model.
□ For form views: which tabs/pages exist? Where would new fields/tabs go?
□ For list views: which columns exist? Which are optional?
□ For search views: which fields are searchable? Which filter_domain
  attributes reference affected fields?
□ Are there group-by options that reference affected fields?
□ Are there decoration-* attributes in list views that check affected fields?
□ Are there attrs/invisible conditions referencing affected fields?
  (these may need updating if field semantics change)
□ Are there any hardcoded string values in views that reference field names?
  (help text, placeholder text, confirm dialogs)
```

**Red flags:**
- The same field appearing in two tabs simultaneously (duplicate display bug)
- A field being moved — old location must be removed from ALL views,
  including search views and any ir.filters records
- Views referencing fields that will be renamed or removed

---

## Audit Category 4 — Automation layer

**Files:** `*/models/*.py` (cron methods), `*/data/*_cron.xml`

This is the highest-risk category. Document every cron completely.

### leads module crons

**`_cron_reprocess_unassigned_leads`**
```
Domain: state='new', create_date < now - 1 hour
Action: calls _process_lead_logic() on each
Risk: picks up any record in state='new' regardless of origin
     → new feature must ensure manual leads never enter state='new'
```

**`_cron_send_new_lead_webhooks`**
```
Domain: is_webhook_sent=False
Action: sends batch payload to n8n, sets is_webhook_sent=True
Risk: payload shape is hardcoded — field renames break n8n workflow
     → new field additions require n8n workflow update coordination
```

**`_cron_pull_external_leads`**
```
Action: fetches Housing.com API, calls create_lead_if_not_duplicate()
Risk: creates leads with state='new', source='Housing.com'
     → new create() logic must not affect this path
     → requires context={'portal_lead_creation': True}
```

### properties module crons

**Property sync cron**
```
Action: queries BigQuery, overwrites SYNC_FIELDS on all matched properties
Risk: overwrites any manually set value on fields in SYNC_FIELDS
     → new feature fields must decide: BQ-sourced or Odoo-managed?
     → if Odoo-managed: must NOT be in SYNC_FIELDS
```

**Expiry cleanup cron**
```
Action: marks properties inactive when service_expiry_date passes
Risk: affects is_active on property.base
     → features that depend on is_active must account for this
```

**For any new cron introduced by the feature:**
```
□ What is the domain? Does it accidentally include records it should skip?
□ What is the frequency? Is that appropriate for the data volume?
□ What is the failure mode? Does it log? Does it update state on failure?
□ Is it idempotent? What happens if it runs twice in quick succession?
```

---

## Audit Category 5 — Integration layer

**Files:** `new_portal_leads.py` (_cron_send_new_lead_webhooks, _api_fetch_housing),
`lead_csv_import_wizard.py`, `property_sync.py`, `property_inventory.py`

```
□ n8n webhook payload (in _cron_send_new_lead_webhooks):
  Current keys: lead_id, name, phone, portal_name→source, portal_property_id,
  rm_name, property_id, property_tag, property_bhk, property_location,
  property_city, property_link
  → Does the feature add, rename, or remove any of these?
  → Coordinate n8n workflow update before deploying

□ Housing.com API fetch (_api_fetch_housing, _parse_housing_response):
  → Does the feature change how Housing.com leads are parsed or created?
  → Does the feature add fields that Housing.com leads need values for?

□ OLX CSV import (lead_csv_import_wizard.py):
  → Does the feature add fields that the CSV wizard must also populate?
  → Does the COLUMN_MAPPING dict need updating?

□ BigQuery sync (property_sync.py):
  → Does the feature add fields that BQ should source?
  → Does the feature add fields that BQ must NOT overwrite?
  → Does SYNC_FIELDS need updating?
  → Does property_inventory.py in lead_suggestor need the same change?
```

---

## Audit Category 6 — API layer

**Files:** `properties/controllers/controllers.py`, `properties/controllers/serializers.py`

```
□ PROPERTY_FIELDS list: which scalar fields are included in API reads?
  → Does the feature add fields that should be in the API response?
  → Does the feature remove fields that are currently in the API?

□ serializers.py: what is the current shape of the property response?
  → Does the feature add nested data (like portal_listings: []) that
    requires a list comprehension rather than a scalar field?

□ Are there any POST/PATCH endpoints that accept field values?
  → Does the feature add writable fields that should be settable via API?

□ Are there any external consumers of this API beyond n8n?
  → Any mobile app, dashboard, or third-party integration?
```

---

## Audit Category 7 — Test layer

**Files:** `*/tests/*.py`

```
□ List all test files and their primary subject.
□ Which test fixtures (setUpClass) create records of the affected model?
  These will need updating if field definitions change.
□ Which test assertions check field values that the feature changes?
  (assertEqual on flat fields that become relational, etc.)
□ Which test methods test the specific flows the feature modifies?
  (e.g. test_01_find_property_by_magicbricks_id → needs rename/rewrite)
□ Are there test helpers or shared fixtures (test_portal_common.py) that
  many tests inherit from? Changes here cascade to all inheriting tests.
```

**Known test files in Cleardeals codebase:**
```
leads/tests/test_portal_common.py        — shared fixture (olx_id, mb_id etc.)
leads/tests/test_portal_lead_processing.py — lead-to-property resolution tests
leads/tests/test_seller_summary_api.py   — API response shape tests
properties/tests/test_property_api_create.py — property creation with portal IDs
properties/tests/test_property_base_crud.py  — basic CRUD with portal IDs
lead_suggestor/tests/test_property_inventory_crud.py — inventory CRUD
```

---

## Audit Category 8 — Migration layer

For every DB change implied by the feature:

```
□ New model → new table (ORM handles automatically; access CSV row needed)
□ New field → new column (ORM handles automatically; backfill may be needed)
□ Renamed field → column rename (pre- script required before ORM runs)
□ Removed field → column drop (post- script after ORM, or leave for later)
□ Data transformation → pre- or post- script depending on column availability
□ New unique constraint → may conflict with existing data (check first)
```

For each required migration:
```
□ Which phase: pre- or post-?
□ What is the correct filename: pre-{descriptor}.py or post-{descriptor}.py?
□ What version folder: current manifest version + 1 patch?
□ Is idempotency guaranteed?
□ What are the verification queries?
```

---

## Audit output format

After running the full audit, produce a summary before asking questions:

```
## Codebase audit results

### Directly affected files
[List every file that needs to change, grouped by category]

### Conflict risks found
[List every potential conflict discovered, with the specific file/line/logic
that creates the risk]

### Assumptions in existing code that may break
[List any "accidentally correct" or fragile logic that this feature stresses]

### Questions surfaced by the audit
[The focused questions for Stage 3 — only ask what the audit cannot answer]
```