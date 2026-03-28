import logging

_logger = logging.getLogger(__name__)


def _table_exists(cr, table_name):
    cr.execute(
        """
        SELECT 1
          FROM information_schema.tables
         WHERE table_schema = 'public'
           AND table_name = %s
        """,
        (table_name,),
    )
    return bool(cr.fetchone())


def _column_exists(cr, table_name, column_name):
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = %s
           AND column_name = %s
        """,
        (table_name, column_name),
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    """
    Backfill leads.new.source_id from legacy leads.new.portal_name values.

    Context:
        The leads module migrated from a plain-text portal_name field to a
        managed lead.source model with category and source type structure.
        Existing production leads must be mapped without data loss.

    Idempotency:
        - Category/source seed inserts use ON CONFLICT DO NOTHING.
        - Update queries only target rows where source_id IS NULL.
        - Fallback source assignment is repeat-safe.

    Assumptions:
        - ORM already created lead_source_category, lead_source, and source_id.
        - leads_new table exists on upgrade databases.
    """
    _logger.info("=== %s %s: starting ===", __name__, version)

    if not _table_exists(cr, "leads_new"):
        _logger.info("%s %s: table leads_new not found, skipping.", __name__, version)
        _logger.info("=== %s %s: done ===", __name__, version)
        return

    for table_name in ("lead_source_category", "lead_source"):
        if not _table_exists(cr, table_name):
            _logger.info(
                "%s %s: table %s not found, skipping.",
                __name__,
                version,
                table_name,
            )
            _logger.info("=== %s %s: done ===", __name__, version)
            return

    if not _column_exists(cr, "leads_new", "source_id"):
        _logger.info(
            "%s %s: column leads_new.source_id not found, skipping.",
            __name__,
            version,
        )
        _logger.info("=== %s %s: done ===", __name__, version)
        return

    has_portal_name = _column_exists(cr, "leads_new", "portal_name")

    _logger.info("%s %s: ensuring source categories exist", __name__, version)
    cr.execute(
        """
        INSERT INTO lead_source_category
            (name, code, source_type, sequence, active, create_date, write_date, create_uid, write_uid)
        VALUES
            ('Portals', 'portals', 'portal', 10, TRUE, NOW(), NOW(), 1, 1),
            ('Legacy Migrated', 'legacy_migrated', 'manual', 999, TRUE, NOW(), NOW(), 1, 1)
        ON CONFLICT (code) DO NOTHING
        """
    )
    _logger.info("%s %s: seeded source categories, rows affected=%d", __name__, version, cr.rowcount)

    cr.execute("SELECT id FROM lead_source_category WHERE code = 'portals' LIMIT 1")
    portal_category = cr.fetchone()
    portal_category_id = portal_category[0] if portal_category else None

    cr.execute(
        "SELECT id FROM lead_source_category WHERE code = 'legacy_migrated' LIMIT 1"
    )
    legacy_category = cr.fetchone()
    legacy_category_id = legacy_category[0] if legacy_category else None

    if not portal_category_id or not legacy_category_id:
        _logger.info(
            "%s %s: required categories missing after seed, aborting migration.",
            __name__,
            version,
        )
        _logger.info("=== %s %s: done ===", __name__, version)
        return

    _logger.info("%s %s: ensuring canonical portal sources exist", __name__, version)
    cr.execute(
        """
        INSERT INTO lead_source
            (name, category_id, portal_code, sequence, active, create_date, write_date, create_uid, write_uid)
        VALUES
            ('99acres', %s, '99acres', 10, TRUE, NOW(), NOW(), 1, 1),
            ('MagicBricks', %s, 'MagicBricks', 20, TRUE, NOW(), NOW(), 1, 1),
            ('Housing.com', %s, 'Housing.com', 30, TRUE, NOW(), NOW(), 1, 1),
            ('OLX', %s, 'OLX', 40, TRUE, NOW(), NOW(), 1, 1)
        ON CONFLICT (name) DO NOTHING
        """,
        (
            portal_category_id,
            portal_category_id,
            portal_category_id,
            portal_category_id,
        ),
    )
    _logger.info("%s %s: seeded canonical portal sources, rows affected=%d", __name__, version, cr.rowcount)

    if has_portal_name:
        _logger.info("%s %s: mapping canonical portal names to source_id", __name__, version)
        cr.execute(
            """
            UPDATE leads_new ln
               SET source_id = ls.id,
                   write_date = NOW(),
                   write_uid = 1
              FROM lead_source ls
             WHERE ln.source_id IS NULL
               AND ln.portal_name IS NOT NULL
               AND TRIM(ln.portal_name) <> ''
               AND ls.name = CASE
                   WHEN LOWER(TRIM(ln.portal_name)) IN ('99acres') THEN '99acres'
                   WHEN LOWER(TRIM(ln.portal_name)) IN ('magicbricks', 'magicbricks.com') THEN 'MagicBricks'
                   WHEN LOWER(TRIM(ln.portal_name)) IN ('housing.com', 'housing') THEN 'Housing.com'
                   WHEN LOWER(TRIM(ln.portal_name)) IN ('olx') THEN 'OLX'
                   ELSE ''
               END
            """
        )
        _logger.info("%s %s: canonical mapping rows updated=%d", __name__, version, cr.rowcount)

        _logger.info("%s %s: creating migrated manual sources from legacy portal_name", __name__, version)
        cr.execute(
            """
            INSERT INTO lead_source
                (name, category_id, sequence, active, create_date, write_date, create_uid, write_uid)
            SELECT DISTINCT
                TRIM(ln.portal_name),
                %s,
                900,
                TRUE,
                NOW(),
                NOW(),
                1,
                1
              FROM leads_new ln
             WHERE ln.source_id IS NULL
               AND ln.portal_name IS NOT NULL
               AND TRIM(ln.portal_name) <> ''
            ON CONFLICT (name) DO NOTHING
            """,
            (legacy_category_id,),
        )
        _logger.info("%s %s: migrated manual sources inserted=%d", __name__, version, cr.rowcount)

        _logger.info("%s %s: mapping remaining source names by exact match", __name__, version)
        cr.execute(
            """
            UPDATE leads_new ln
               SET source_id = ls.id,
                   write_date = NOW(),
                   write_uid = 1
              FROM lead_source ls
             WHERE ln.source_id IS NULL
               AND ln.portal_name IS NOT NULL
               AND TRIM(ln.portal_name) <> ''
               AND ls.name = TRIM(ln.portal_name)
            """
        )
        _logger.info("%s %s: exact-name mapping rows updated=%d", __name__, version, cr.rowcount)

    _logger.info("%s %s: ensuring fallback migrated source exists", __name__, version)
    cr.execute(
        """
        INSERT INTO lead_source
            (name, category_id, sequence, active, create_date, write_date, create_uid, write_uid)
        VALUES
            ('Unknown (Migrated)', %s, 1000, TRUE, NOW(), NOW(), 1, 1)
        ON CONFLICT (name) DO NOTHING
        """,
        (legacy_category_id,),
    )
    _logger.info("%s %s: fallback source seed rows affected=%d", __name__, version, cr.rowcount)

    cr.execute("SELECT id FROM lead_source WHERE name = 'Unknown (Migrated)' LIMIT 1")
    fallback_source = cr.fetchone()
    fallback_source_id = fallback_source[0] if fallback_source else None

    if fallback_source_id:
        _logger.info("%s %s: assigning fallback source to remaining null rows", __name__, version)
        cr.execute(
            """
            UPDATE leads_new
               SET source_id = %s,
                   write_date = NOW(),
                   write_uid = 1
             WHERE source_id IS NULL
            """,
            (fallback_source_id,),
        )
        _logger.info("%s %s: fallback assignment rows updated=%d", __name__, version, cr.rowcount)

    cr.execute("SELECT COUNT(*) FROM leads_new WHERE source_id IS NULL")
    null_count = cr.fetchone()[0]
    _logger.info("%s %s: leads_new rows with NULL source_id=%d", __name__, version, null_count)

    cr.execute(
        """
        SELECT COALESCE(ls.name, 'NULL') AS source_name, COUNT(*)
          FROM leads_new ln
          LEFT JOIN lead_source ls ON ls.id = ln.source_id
      GROUP BY COALESCE(ls.name, 'NULL')
      ORDER BY COUNT(*) DESC
        """
    )
    stats = cr.fetchall()
    _logger.info("%s %s: source distribution rows=%d", __name__, version, len(stats))

    _logger.info("=== %s %s: done ===", __name__, version)
