---
name: odoo-migration-writer
description: >
  Generates complete, production-quality Odoo 19 migration scripts from a plain-English
  description of what changed in a module. Use this skill whenever the user says things
  like "write a migration for", "I renamed a field", "I added a new model", "I'm dropping
  a column", "generate a migration", "I need a migration script", "write the upgrade
  script for this change", or describes any structural database change — field rename,
  column drop, data backfill, table seeding, data transformation. Also trigger when the
  user shares a diff, a model change, or a manifest and asks what migration is needed.
  Always use this skill for Odoo migration writing — the output must meet strict naming,
  idempotency, logging, and safety standards specific to the Odoo 19 upgrade framework.
---

# Odoo Migration Writer

You generate complete, production-ready Odoo 19 migration scripts. Every script you
produce must be deployable to production without modification — not a skeleton, not a
starting point, but the finished, correct thing.

---

## Step 1 — Gather what you need before writing anything

Ask for any information that is missing. Never guess on these:

| Information needed | Why it matters |
|---|---|
| Which module | Determines the folder path and version namespace |
| Current manifest version | New migration folder must be one patch higher |
| What changed in the code | Determines which phase(s) are needed and what SQL to write |
| Source table/column names | Cannot be assumed — Odoo naming conventions have edge cases |
| Target table/column names | Same |
| Whether ORM manages the affected columns | Determines pre vs post phase |

If the user shares the model file or manifest alongside the request, extract
this information yourself. Only ask if it cannot be determined from context.

---

## Step 2 — Determine the file path and name

Read: `references/naming.md` for the full convention.

The structure is always:

```
{module}/migrations/{full_version}/{phase}-{descriptor}.py
```

- `{full_version}` = Odoo major version + module minor version, e.g. `19.0.1.4.0`
- `{phase}` = `pre`, `post`, or `end`
- `{descriptor}` = a short snake_case description of what the script does,
  optionally prefixed with a two-digit order number for sequencing

Examples:
```
properties/migrations/19.0.1.4.0/pre-seed_portal_listings.py
properties/migrations/19.0.1.4.0/post-drop_legacy_portal_columns.py
leads/migrations/19.0.1.2.0/pre-rename_portal_name_to_source.py
leads/migrations/19.0.1.2.0/post-recompute_stored_fields.py
```

If multiple scripts are needed in the same phase, prefix with numbers for
explicit ordering:
```
properties/migrations/19.0.1.4.0/pre-01-validate_data.py
properties/migrations/19.0.1.4.0/pre-02-seed_portal_listings.py
```

Within a phase, files execute in lexical order. Numbers make the order explicit
and immune to future filename changes.

---

## Step 3 — Determine the phase(s)

Read: `references/phases.md` for the full decision tree with examples.

Quick reference:

| Change | Phase | Reason |
|---|---|---|
| Seed new table from existing flat columns | `pre` | Old columns exist pre-ORM; gone after |
| Rename a column (not tracked by ORM) | `pre` | Must happen before ORM tries to create the new name |
| Copy data before a field deletion | `pre` | Field deleted by ORM — rescue first |
| Transform data in an existing column | `pre` | Before ORM potentially changes the column type |
| Drop legacy columns after field removed from Python | `post` | ORM must finish first; column may still be referenced |
| Recompute stored/related fields | `post` | Needs new column structure to exist |
| Create indexes on new ORM-managed columns | `post` | Column must exist first |
| Cross-module data fixes after all modules updated | `end` | Needs all modules to be in their final state |

---

## Step 4 — Write the migration

Read: `references/patterns.md` for complete, copy-paste-ready code patterns
for every change type.

Every migration file you write must follow this exact structure:

```python
import logging

_logger = logging.getLogger(__name__)

# --- constants (if needed) ---
# Column name whitelists, portal maps, etc. go here at module level.


# --- helper functions (if needed) ---
# _table_exists(), _column_exists() go here.


def migrate(cr, version):
    """
    [One-sentence summary of what this script does.]

    Context:
        [Why this migration is needed — what changed in the code.]

    Idempotency:
        [What makes this safe to re-run — ON CONFLICT, IF EXISTS checks, etc.]

    Assumptions:
        [What must be true for this to run correctly — table existence,
         column existence, prior migrations having run, etc.]
    """
    _logger.info("=== %s %s: starting ===", __name__, version)

    # ... migration body ...

    _logger.info("=== %s %s: done ===", __name__, version)
```

### Non-negotiable requirements

Every script must satisfy all of these. Check each one before outputting.

**1. Correct file path and name**
Following the `{phase}-{descriptor}.py` convention. Never `pre_migrate.py`,
never `migrate.py`, never any other name.

**2. Only `migrate(cr, version)` — no other entry points**
Odoo calls exactly this function. Other function names are never invoked
automatically. Helper functions are fine, but the entry point is always
`migrate(cr, version)`.

**3. Full docstring on `migrate()`**
Covers: what, context (why), idempotency guarantee, assumptions.

**4. Logging at start, per-operation, and end**
```python
_logger.info("=== %s %s: starting ===", __name__, version)
# ... before each operation:
_logger.info("%s %s: [what is about to happen]", __name__, version)
# ... after each INSERT/UPDATE/DELETE:
_logger.info("%s %s: %d rows affected", __name__, version, cr.rowcount)
# ... final state:
cr.execute("SELECT COUNT(*) FROM target_table")
_logger.info("%s %s: %d total rows in target_table",
             __name__, version, cr.fetchone()[0])
_logger.info("=== %s %s: done ===", __name__, version)
```

**5. Idempotency on every operation**
- `INSERT` → `ON CONFLICT (...) DO NOTHING`
- `ADD COLUMN` → `ADD COLUMN IF NOT EXISTS`
- `DROP COLUMN` → `DROP COLUMN IF EXISTS`
- `RENAME COLUMN` → check `information_schema.columns` first
- `CREATE INDEX` → `CREATE INDEX IF NOT EXISTS`
- `UPDATE` → `WHERE` clause that naturally skips already-correct rows

**6. Whitelist guard before any column name in an f-string**
psycopg2 cannot parameterise column names — only values. Any column
name interpolated into SQL via an f-string must be validated against
a hardcoded `frozenset` before use. If not in the set: `raise ValueError`.

**7. System fields in every INSERT into an Odoo model table**
```sql
create_date, write_date, create_uid, write_uid
-- values: NOW(), NOW(), 1, 1
```
Omitting these causes NULL constraint errors.

**8. No `cr.commit()`**
Odoo owns the transaction. `cr.commit()` mid-migration destroys the
rollback guarantee and can leave the database in a corrupt half-state.

**9. Table and column existence guards**
Never assume a table or column exists. Use `_table_exists()` and
`_column_exists()` helpers before operating. On a fresh install,
migrations do not run — but on an upgrade from a partial state,
a missing table should produce a clear error, not a cryptic PostgreSQL
exception.

---

## Step 5 — Output format

Produce everything the developer needs to deploy, in this order:

### 1. The migration file(s)

Show the full file path as a comment at the top of each code block:

```
# custom_addons/properties/migrations/19.0.1.4.0/pre-seed_portal_listings.py
```

Then the complete file contents. No placeholders, no TODOs, no
"fill in your table name here". The file must be copy-paste deployable.

### 2. Manifest bump instruction

```
Bump __manifest__.py "version" from "19.0.1.3.0" to "19.0.1.4.0"
```

### 3. Upgrade command

```bash
odoo-bin -u {module} -d {database} --stop-after-init \
  2>&1 | tee migration_{version}_$(date +%Y%m%d_%H%M%S).log
```

### 4. Post-deployment verification queries

Exact SQL to run immediately after upgrade to confirm the migration
worked. Always include:
- Row count grouped by the key dimension (e.g. portal_name)
- NULL/empty check on newly populated columns
- Duplicate detection if a unique constraint is involved
- A random spot-check of 5 rows showing the new data shape

---

## Cleardeals-specific conventions

These are established patterns in this codebase. Follow them exactly
when writing migrations for Cleardeals modules.

**Odoo version prefix:** `19.0`

**Module versions (current as of last known state):**
- `properties` module: `19.0.1.3.0`
- `leads` module: check manifest before assuming

**Table name derivation** (Odoo converts `model._name` dots to underscores):
```
property.base              → property_base
property.portal.listing    → property_portal_listing
leads.new                  → leads_new
lead.property.interest     → lead_property_interest
res.users                  → res_users
```

**Portal name string values** (stored in `portal_name` column):
```
"99acres"   "Housing.com"   "MagicBricks"   "OLX"
```

**Label format** for `property_portal_listing.listing_label`:
```
{prop_id} | {portal_name} | {portal_listing_id}
Example: "CD-4521 | MagicBricks | MB9871234"
```

**Standard portal column whitelist:**
```python
_PORTAL_COLUMN_WHITELIST = frozenset({
    "ninety_nine_acres_id",
    "housing_id",
    "magicbricks_id",
    "olx_id",
})
```

**Standard portal-to-column map:**
```python
_PORTAL_COLUMN_MAP = (
    ("99acres",     "ninety_nine_acres_id"),
    ("Housing.com", "housing_id"),
    ("MagicBricks", "magicbricks_id"),
    ("OLX",         "olx_id"),
)
```

---

## Quality checklist — run before every output

```
[ ] File path uses {phase}-{descriptor}.py naming — not pre_migrate.py
[ ] Entry point is exactly migrate(cr, version) — nothing else
[ ] docstring covers: what, context, idempotency, assumptions
[ ] _logger.info at: start, per-operation count, final state, end
[ ] Every INSERT has ON CONFLICT (...) DO NOTHING
[ ] Every ADD COLUMN has IF NOT EXISTS
[ ] Every DROP COLUMN has IF EXISTS
[ ] Every RENAME COLUMN checks information_schema first
[ ] Every column name in f-string has whitelist guard above it
[ ] Every INSERT into Odoo model table includes create/write uid+date
[ ] No cr.commit() anywhere in the file
[ ] _table_exists() and _column_exists() helpers defined and used
[ ] Manifest bump version included in output
[ ] Verification SQL queries included in output
[ ] Upgrade command included in output
```
