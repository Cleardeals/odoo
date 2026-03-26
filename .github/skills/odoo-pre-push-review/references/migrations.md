# Migration Scripts Reference

## File naming

Odoo looks for exactly two filenames inside each version folder:
- `pre_migrate.py` — runs before the ORM applies changes
- `post_migrate.py` — runs after the ORM applies changes

Any other filename is silently ignored. `migrate.py`, `migration.py`,
`post_migrate.py.bak` — none of these run. The folder name must exactly
match the version string (e.g. `19.0.1.3.0`), including all five segments.

## Pre vs post — when to use each

```
Current DB state
      │
      ▼
pre_migrate.py     ← old columns EXIST here. Rescue data before demolition.
      │
      ▼
ORM applies changes (adds/removes columns, creates tables)
      │
      ▼
post_migrate.py    ← new structure is in place. Old columns may be GONE.
```

**Use pre_migrate for:**
- Copying data from columns that are about to be removed
- Renaming columns (before ORM tries to create the new name)
- Seeding new tables from old data (new table exists, old columns exist)
- Any operation that reads from columns the ORM will delete

**Use post_migrate for:**
- Dropping legacy columns (after ORM no longer references them)
- Recomputing stored fields on the new structure
- Creating indexes on ORM-managed columns
- Sending notifications or triggering recomputes

**The classic mistake:** putting a DROP COLUMN in pre_migrate. The ORM
then fails trying to manage a column that no longer exists.

## Idempotency patterns

Every migration must be safe to run twice. These are the standard patterns:

```python
# INSERT
ON CONFLICT (unique_col1, unique_col2) DO NOTHING

# ADD COLUMN
ALTER TABLE leads_new ADD COLUMN IF NOT EXISTS source VARCHAR;

# DROP COLUMN
ALTER TABLE property_base DROP COLUMN IF EXISTS ninety_nine_acres_id;

# RENAME COLUMN — no native IF EXISTS, check manually
cr.execute("""
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'leads_new' AND column_name = 'portal_name'
""")
if cr.fetchone():
    cr.execute("ALTER TABLE leads_new RENAME COLUMN portal_name TO source")

# CREATE INDEX
CREATE INDEX IF NOT EXISTS idx_name ON table_name(col1, col2);

# UPDATE — WHERE clause naturally excludes already-updated rows
UPDATE table SET col = value
WHERE col IS NULL OR col = '';
```

## Column name f-strings — the injection guard

psycopg2 cannot parameterise column names, only values. Any column name
in an f-string is a potential injection point if the source ever changes.

**Always whitelist before using in f-string:**

```python
ALLOWED_COLUMNS = frozenset({
    "ninety_nine_acres_id",
    "housing_id",
    "magicbricks_id",
    "olx_id",
})

for portal_name, source_col in inserts:
    if source_col not in ALLOWED_COLUMNS:
        raise ValueError(f"Migration aborted: '{source_col}' not whitelisted.")
    # safe to f-string now
    cr.execute(f"SELECT {source_col} FROM property_base", ())
```

## Required logging

A migration with no logging gives you nothing to debug. Minimum required:

```python
import logging
_logger = logging.getLogger(__name__)

def migrate(cr, version):
    _logger.info("Migration %s: starting", version)

    # Before each operation — count what exists
    cr.execute("SELECT COUNT(*) FROM source_table WHERE col IS NOT NULL")
    source_count = cr.fetchone()[0]
    _logger.info("Migration %s: found %d source rows", version, source_count)

    # The operation
    cr.execute("INSERT INTO target_table ...")
    _logger.info("Migration %s: inserted %d rows", version, cr.rowcount)

    # Final state verification
    cr.execute("SELECT COUNT(*) FROM target_table")
    _logger.info("Migration %s: complete. Total rows: %d",
                 version, cr.fetchone()[0])
```

## Odoo system fields in INSERT

When inserting into an Odoo-managed table (any table from a `models.Model`
subclass), always include the four system fields:

```python
INSERT INTO property_portal_listing
    (property_base_id, portal_name, portal_listing_id,
     create_date, write_date, create_uid, write_uid)
SELECT
    pb.id, %s, TRIM(pb.olx_id),
    NOW(), NOW(), 1, 1
FROM property_base pb
WHERE pb.olx_id IS NOT NULL
```

Missing `create_uid`/`write_uid` causes NULL constraint violations on
Odoo versions where these columns are NOT NULL. `create_date`/`write_date`
default to NULL which breaks sorting and display in list views.

## Table existence guard

Before operating on a new table, verify it exists:

```python
cr.execute("""
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = %s
""", ('property_portal_listing',))
if not cr.fetchone():
    raise RuntimeError(
        f"Migration {version}: table 'property_portal_listing' does not exist. "
        "Module may not have installed correctly."
    )
```

This converts a confusing `UndefinedTable` PostgreSQL error into a clear
message that tells the developer exactly what went wrong.

## Never call cr.commit()

Odoo wraps each migration in a transaction. If the migration fails,
Odoo rolls back the entire upgrade — the database is left unchanged.
Calling `cr.commit()` inside a migration breaks this guarantee: a
partial migration commits, then the rest fails, leaving the database
in a corrupt half-migrated state with no clean rollback path.

## Verification queries to run after every migration

```sql
-- 1. Row counts by key grouping
SELECT portal_name, COUNT(*)
FROM property_portal_listing
GROUP BY portal_name ORDER BY portal_name;

-- 2. Null or empty labels (should be zero)
SELECT COUNT(*) FROM property_portal_listing
WHERE listing_label IS NULL OR TRIM(listing_label) = '';

-- 3. Duplicate listing IDs across properties (should be zero)
SELECT portal_name, portal_listing_id, COUNT(DISTINCT property_base_id)
FROM property_portal_listing
GROUP BY portal_name, portal_listing_id
HAVING COUNT(DISTINCT property_base_id) > 1;

-- 4. Unique constraint exists
SELECT conname FROM pg_constraint
WHERE conrelid = 'property_portal_listing'::regclass AND contype = 'u';

-- 5. Spot check
SELECT prop_id, portal_name, portal_listing_id, listing_label
FROM property_portal_listing ppl
JOIN property_base pb ON pb.id = ppl.property_base_id
ORDER BY RANDOM() LIMIT 5;
```
