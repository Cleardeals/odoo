import logging

_logger = logging.getLogger(__name__)

# (portal_name, legacy_column) — hardcoded whitelist. Column names are never
# taken from external input, so they are safe to interpolate into SQL below.
_LEGACY_COLUMNS = (
    ("99acres", "ninety_nine_acres_id"),
    ("Housing.com", "housing_id"),
    ("MagicBricks", "magicbricks_id"),
    ("OLX", "olx_id"),
)


def _column_exists(cr, table, column):
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = %s
           AND column_name = %s
        """,
        (table, column),
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    """
    Drop the legacy per-portal ID columns from property_base.

    Columns: ninety_nine_acres_id, housing_id, magicbricks_id, olx_id.

    These were superseded by the property.portal.listing model. The
    19.0.1.1.0 / 1.2.0 / 1.3.0 migrations already backfilled every non-null
    legacy id into property_portal_listing. As a final safety net we re-run
    that backfill (for any rows added since) and only then drop each column,
    so the drop is provably lossless.

    Idempotent: each column is guarded by an information_schema existence check
    and dropped with DROP COLUMN IF EXISTS, so re-running is a no-op.
    """
    for portal_name, col in _LEGACY_COLUMNS:
        if not _column_exists(cr, "property_base", col):
            _logger.info(
                "property_base.%s already dropped — skipping backfill + drop.",
                col,
            )
            continue

        # Safety-net backfill: capture any non-null legacy id not yet mirrored
        # into property_portal_listing before the column disappears. Mirrors the
        # proven INSERT from the 19.0.1.3.0 migration.
        cr.execute(
            f"""
            INSERT INTO property_portal_listing
                (property_base_id, portal_name, portal_listing_id, listing_label, active)
            SELECT
                pb.id,
                %s,
                TRIM(pb.{col}),
                CONCAT_WS(
                    ' | ',
                    NULLIF(TRIM(pb.prop_id), ''),
                    %s,
                    TRIM(pb.{col})
                ),
                TRUE
            FROM property_base pb
            WHERE pb.{col} IS NOT NULL
              AND TRIM(pb.{col}) <> ''
            ON CONFLICT (portal_name, portal_listing_id) DO NOTHING
            """,
            (portal_name, portal_name),
        )
        _logger.info(
            "property_base.%s: safety-net backfilled %d portal listing row(s) before drop.",
            col,
            cr.rowcount,
        )

        cr.execute(f"ALTER TABLE property_base DROP COLUMN IF EXISTS {col}")
        _logger.info("Dropped legacy column property_base.%s.", col)
