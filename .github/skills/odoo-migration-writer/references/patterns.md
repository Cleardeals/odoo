# Migration Code Patterns

Complete, production-ready patterns for every migration type.
Copy the relevant pattern and fill in the specifics.

---

## Helper functions — include in every migration that needs them

```python
def _table_exists(cr, table_name):
    """Return True if the given table exists in the public schema."""
    cr.execute("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
    """, (table_name,))
    return cr.fetchone() is not None


def _column_exists(cr, table_name, column_name):
    """Return True if the given column exists on the given table."""
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table_name, column_name))
    return cr.fetchone() is not None
```

---

## Pattern A — Seed new table from flat columns (pre-phase)

Use when: a new relational model replaces flat fields on an existing model.

```python
# custom_addons/properties/migrations/19.0.1.4.0/pre-seed_portal_listings.py

import logging

_logger = logging.getLogger(__name__)

_PORTAL_COLUMN_WHITELIST = frozenset({
    "ninety_nine_acres_id",
    "housing_id",
    "magicbricks_id",
    "olx_id",
})

_PORTAL_COLUMN_MAP = (
    ("99acres",     "ninety_nine_acres_id"),
    ("Housing.com", "housing_id"),
    ("MagicBricks", "magicbricks_id"),
    ("OLX",         "olx_id"),
)


def _table_exists(cr, table_name):
    cr.execute("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
    """, (table_name,))
    return cr.fetchone() is not None


def _column_exists(cr, table_name, column_name):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table_name, column_name))
    return cr.fetchone() is not None


def migrate(cr, version):
    """
    Seed property_portal_listing from legacy flat portal ID columns on property_base.

    Context:
        Prior to this version, each property stored at most one listing ID per
        portal as a flat Char field. This migration seeds the new
        property_portal_listing table so existing data is preserved.
        Label format: {prop_id} | {portal_name} | {portal_listing_id}

    Idempotency:
        ON CONFLICT (portal_name, portal_listing_id) DO NOTHING.
        Safe to re-run. Source columns are intentionally not modified.

    Assumptions:
        - property_portal_listing table exists (created by ORM in a prior version).
        - property_base still has the four legacy columns.
        - Unique constraint exists on (portal_name, portal_listing_id).
    """
    _logger.info("=== %s %s: starting ===", __name__, version)

    if not _table_exists(cr, "property_portal_listing"):
        raise RuntimeError(
            f"{__name__} {version}: table 'property_portal_listing' does not exist. "
            "Ensure the module installed correctly before running migrations."
        )

    total_inserted = 0

    for portal_name, source_col in _PORTAL_COLUMN_MAP:

        if source_col not in _PORTAL_COLUMN_WHITELIST:
            raise ValueError(
                f"{__name__} {version}: '{source_col}' is not a whitelisted column. "
                "Migration aborted."
            )

        if not _column_exists(cr, "property_base", source_col):
            _logger.warning(
                "%s %s: property_base.%s not found — skipping portal '%s'.",
                __name__, version, source_col, portal_name,
            )
            continue

        cr.execute(
            f"""
            SELECT COUNT(*) FROM property_base
            WHERE {source_col} IS NOT NULL
              AND TRIM({source_col}) <> ''
            """
        )
        source_count = cr.fetchone()[0]
        _logger.info(
            "%s %s: portal '%s' — %d source rows in property_base.%s",
            __name__, version, portal_name, source_count, source_col,
        )

        if source_count == 0:
            _logger.info(
                "%s %s: no data for portal '%s', skipping.",
                __name__, version, portal_name,
            )
            continue

        cr.execute(
            f"""
            INSERT INTO property_portal_listing
                (property_base_id, portal_name, portal_listing_id,
                 listing_label, active,
                 create_date, write_date, create_uid, write_uid)
            SELECT
                pb.id,
                %s,
                TRIM(pb.{source_col}),
                CONCAT_WS(
                    ' | ',
                    NULLIF(TRIM(pb.prop_id), ''),
                    %s,
                    TRIM(pb.{source_col})
                ),
                TRUE,
                NOW(), NOW(), 1, 1
            FROM property_base pb
            WHERE pb.{source_col} IS NOT NULL
              AND TRIM(pb.{source_col}) <> ''
            ON CONFLICT (portal_name, portal_listing_id) DO NOTHING
            """,
            (portal_name, portal_name),
        )
        inserted = cr.rowcount
        total_inserted += inserted
        _logger.info(
            "%s %s: portal '%s' — inserted %d / %d rows (%d skipped, already existed).",
            __name__, version, portal_name, inserted, source_count,
            source_count - inserted,
        )

    cr.execute("SELECT COUNT(*) FROM property_portal_listing")
    _logger.info(
        "%s %s: complete. %d inserted this run. %d total rows in property_portal_listing.",
        __name__, version, total_inserted, cr.fetchone()[0],
    )
    _logger.info("=== %s %s: done ===", __name__, version)
```

---

## Pattern B — Rename a column (pre-phase)

Use when: a field is renamed in Python and the column must be renamed in Postgres
before the ORM runs (otherwise ORM creates a new empty column alongside the old one).

```python
# custom_addons/leads/migrations/19.0.1.2.0/pre-rename_portal_name_to_source.py

import logging

_logger = logging.getLogger(__name__)


def _column_exists(cr, table_name, column_name):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table_name, column_name))
    return cr.fetchone() is not None


def migrate(cr, version):
    """
    Rename leads_new.portal_name to leads_new.source.

    Context:
        The portal_name field is being generalised to source to support
        manual lead creation with free-form origin values (walk-in, referral,
        IVR) alongside the existing portal values (MagicBricks, 99acres, etc.).
        Renaming the column preserves the 6,000+ existing lead records.

    Idempotency:
        Checks information_schema before renaming. If 'portal_name' does not
        exist (already renamed), the rename is skipped cleanly.

    Assumptions:
        - leads_new table exists.
        - portal_name column exists (or was already renamed — handled gracefully).
    """
    _logger.info("=== %s %s: starting ===", __name__, version)

    if not _column_exists(cr, "leads_new", "portal_name"):
        _logger.info(
            "%s %s: leads_new.portal_name not found — "
            "already renamed or never existed. Skipping.",
            __name__, version,
        )
        _logger.info("=== %s %s: done ===", __name__, version)
        return

    cr.execute("ALTER TABLE leads_new RENAME COLUMN portal_name TO source")
    _logger.info(
        "%s %s: renamed leads_new.portal_name → leads_new.source.",
        __name__, version,
    )

    # Verify the rename landed correctly.
    if not _column_exists(cr, "leads_new", "source"):
        raise RuntimeError(
            f"{__name__} {version}: rename appeared to succeed but "
            "'source' column not found in information_schema. "
            "Manual investigation required."
        )

    _logger.info(
        "%s %s: verified leads_new.source exists.",
        __name__, version,
    )
    _logger.info("=== %s %s: done ===", __name__, version)
```

---

## Pattern C — Drop legacy columns (post-phase)

Use when: fields have been removed from the Python model and the ORM no longer
manages them. Run in post-phase only — never pre.

```python
# custom_addons/properties/migrations/19.0.1.4.0/post-drop_legacy_portal_columns.py

import logging

_logger = logging.getLogger(__name__)

# Columns to drop — verified safe to remove after portal_listing migration.
# All data from these columns was backfilled into property_portal_listing
# in migration 19.0.1.1.0 through 19.0.1.3.0.
_COLUMNS_TO_DROP = (
    ("property_base", "ninety_nine_acres_id"),
    ("property_base", "housing_id"),
    ("property_base", "magicbricks_id"),
    ("property_base", "olx_id"),
)


def migrate(cr, version):
    """
    Drop legacy flat portal ID columns from property_base.

    Context:
        These four columns stored at most one portal listing ID per portal.
        They were replaced by the property_portal_listing model in 19.0.1.1.0.
        Data was backfilled across 19.0.1.1.0–19.0.1.3.0 and verified.
        The Python field declarations were removed in this version, so the
        ORM no longer manages these columns. Safe to drop.

    Idempotency:
        DROP COLUMN IF EXISTS — safe to re-run.

    Assumptions:
        - Data has been verified in property_portal_listing before this runs.
        - Python field declarations for these columns have been removed.
        - No view, domain, or serialiser references these columns any longer.
    """
    _logger.info("=== %s %s: starting ===", __name__, version)

    for table_name, column_name in _COLUMNS_TO_DROP:
        cr.execute(
            f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS {column_name}"
        )
        if cr.rowcount == 0:
            _logger.info(
                "%s %s: %s.%s did not exist — skipped.",
                __name__, version, table_name, column_name,
            )
        else:
            _logger.info(
                "%s %s: dropped %s.%s.",
                __name__, version, table_name, column_name,
            )

    _logger.info("=== %s %s: done ===", __name__, version)
```

---

## Pattern D — Transform / normalise existing data (pre-phase)

Use when: data in an existing column needs to be reformatted or corrected.

```python
# custom_addons/properties/migrations/19.0.1.4.0/pre-normalise_listing_labels.py

import logging

_logger = logging.getLogger(__name__)


def _table_exists(cr, table_name):
    cr.execute("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
    """, (table_name,))
    return cr.fetchone() is not None


def migrate(cr, version):
    """
    Normalise listing_label on property_portal_listing to the canonical format:
    {prop_id} | {portal_name} | {portal_listing_id}

    Context:
        Earlier migration versions used inconsistent label formats.
        19.0.1.1.0 used property_tag as the label.
        19.0.1.2.0 used prop_id | property_tag | listing_id.
        This migration standardises all rows to prop_id | portal_name | listing_id.

    Idempotency:
        The WHERE clause matches only rows that do not already have the
        canonical format. Re-running changes nothing if already normalised.

    Assumptions:
        - property_portal_listing exists and has been seeded.
        - property_base.prop_id exists.
    """
    _logger.info("=== %s %s: starting ===", __name__, version)

    if not _table_exists(cr, "property_portal_listing"):
        raise RuntimeError(
            f"{__name__} {version}: 'property_portal_listing' not found."
        )

    # Count rows that need normalisation before updating.
    cr.execute("""
        SELECT COUNT(*) FROM property_portal_listing
        WHERE listing_label IS NULL OR TRIM(listing_label) = ''
    """)
    stale_count = cr.fetchone()[0]
    _logger.info(
        "%s %s: %d rows with missing or stale labels to normalise.",
        __name__, version, stale_count,
    )

    if stale_count == 0:
        _logger.info(
            "%s %s: all labels already in canonical format. Nothing to do.",
            __name__, version,
        )
        _logger.info("=== %s %s: done ===", __name__, version)
        return

    cr.execute("""
        UPDATE property_portal_listing ppl
           SET listing_label = CONCAT_WS(
               ' | ',
               NULLIF(TRIM(pb.prop_id), ''),
               NULLIF(TRIM(ppl.portal_name), ''),
               NULLIF(TRIM(ppl.portal_listing_id), '')
           )
          FROM property_base pb
         WHERE ppl.property_base_id = pb.id
           AND (
               ppl.listing_label IS NULL
               OR TRIM(ppl.listing_label) = ''
           )
    """)
    _logger.info(
        "%s %s: normalised %d rows.",
        __name__, version, cr.rowcount,
    )

    # Verify no nulls remain.
    cr.execute("""
        SELECT COUNT(*) FROM property_portal_listing
        WHERE listing_label IS NULL OR TRIM(listing_label) = ''
    """)
    remaining = cr.fetchone()[0]
    if remaining > 0:
        _logger.warning(
            "%s %s: %d rows still have empty labels after normalisation. "
            "These may have NULL prop_id and portal_name — investigate.",
            __name__, version, remaining,
        )

    cr.execute("SELECT COUNT(*) FROM property_portal_listing")
    _logger.info(
        "%s %s: complete. %d total rows in property_portal_listing.",
        __name__, version, cr.fetchone()[0],
    )
    _logger.info("=== %s %s: done ===", __name__, version)
```

---

## Pattern E — Add column with backfilled default (pre-phase)

Use when: a new field is added to a model and existing rows need a
non-NULL default value that cannot be expressed as a SQL column default.

```python
# custom_addons/leads/migrations/19.0.1.3.0/pre-add_lead_origin_type.py

import logging

_logger = logging.getLogger(__name__)


def _column_exists(cr, table_name, column_name):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table_name, column_name))
    return cr.fetchone() is not None


def migrate(cr, version):
    """
    Add leads_new.lead_origin column and backfill 'portal' for existing rows
    that have a source value, 'manual' for rows without.

    Context:
        Manual lead creation requires distinguishing portal-originated leads
        from manually created ones. The new lead_origin field stores this.
        Existing leads all came from portals, so they get 'portal'.
        Rows with no source are edge cases that default to 'manual'.

    Idempotency:
        ADD COLUMN IF NOT EXISTS prevents duplicate column errors.
        UPDATE WHERE lead_origin IS NULL skips already-set rows.

    Assumptions:
        - leads_new table exists.
        - The source column exists (renamed from portal_name in 19.0.1.2.0).
    """
    _logger.info("=== %s %s: starting ===", __name__, version)

    if not _column_exists(cr, "leads_new", "lead_origin"):
        cr.execute("""
            ALTER TABLE leads_new
            ADD COLUMN IF NOT EXISTS lead_origin VARCHAR
        """)
        _logger.info(
            "%s %s: added leads_new.lead_origin column.",
            __name__, version,
        )
    else:
        _logger.info(
            "%s %s: leads_new.lead_origin already exists — skipping ADD COLUMN.",
            __name__, version,
        )

    # Backfill: rows with a source value came from a portal.
    cr.execute("""
        UPDATE leads_new
           SET lead_origin = 'portal'
         WHERE lead_origin IS NULL
           AND source IS NOT NULL
           AND TRIM(source) <> ''
    """)
    _logger.info(
        "%s %s: backfilled 'portal' on %d rows.",
        __name__, version, cr.rowcount,
    )

    # Backfill: rows without a source are treated as manual.
    cr.execute("""
        UPDATE leads_new
           SET lead_origin = 'manual'
         WHERE lead_origin IS NULL
    """)
    _logger.info(
        "%s %s: backfilled 'manual' on %d rows.",
        __name__, version, cr.rowcount,
    )

    cr.execute("SELECT lead_origin, COUNT(*) FROM leads_new GROUP BY lead_origin")
    _logger.info("%s %s: lead_origin distribution:", __name__, version)
    for origin, count in cr.fetchall():
        _logger.info("  %-10s %d rows", origin, count)

    _logger.info("=== %s %s: done ===", __name__, version)
```

---

## Standard verification queries

Run these after every upgrade to confirm the migration worked.
Adapt table names and columns to match your specific migration.

```sql
-- 1. Row counts by key dimension
SELECT portal_name, COUNT(*)
FROM property_portal_listing
GROUP BY portal_name
ORDER BY portal_name;

-- 2. Null or empty check on newly populated columns (should return 0)
SELECT COUNT(*) FROM property_portal_listing
WHERE listing_label IS NULL OR TRIM(listing_label) = '';

-- 3. Duplicate detection if unique constraint is involved (should return 0 rows)
SELECT portal_name, portal_listing_id, COUNT(DISTINCT property_base_id)
FROM property_portal_listing
GROUP BY portal_name, portal_listing_id
HAVING COUNT(DISTINCT property_base_id) > 1;

-- 4. Unique constraint exists on the table
SELECT conname, contype FROM pg_constraint
WHERE conrelid = 'property_portal_listing'::regclass
  AND contype = 'u';

-- 5. Spot check — 5 random rows showing the new data shape
SELECT pb.prop_id, ppl.portal_name, ppl.portal_listing_id, ppl.listing_label
FROM property_portal_listing ppl
JOIN property_base pb ON pb.id = ppl.property_base_id
ORDER BY RANDOM()
LIMIT 5;

-- 6. Cross-check source counts (run before migration, compare after)
SELECT
    COUNT(*) FILTER (WHERE ninety_nine_acres_id IS NOT NULL
                     AND TRIM(ninety_nine_acres_id) <> '') AS acres_source,
    COUNT(*) FILTER (WHERE housing_id IS NOT NULL
                     AND TRIM(housing_id) <> '')           AS housing_source,
    COUNT(*) FILTER (WHERE magicbricks_id IS NOT NULL
                     AND TRIM(magicbricks_id) <> '')       AS mb_source,
    COUNT(*) FILTER (WHERE olx_id IS NOT NULL
                     AND TRIM(olx_id) <> '')               AS olx_source
FROM property_base;
```
