def migrate(cr, version):
    """
    Backfill new property.portal.listing records from legacy single-value
    portal ID fields on property.base.

    IMPORTANT:
    - Legacy fields on property.base are intentionally NOT modified.
    - Uses ON CONFLICT DO NOTHING so reruns are safe/idempotent.
    """

    inserts = (
        ("99acres", "ninety_nine_acres_id"),
        ("Housing.com", "housing_id"),
        ("MagicBricks", "magicbricks_id"),
        ("OLX", "olx_id"),
    )

    for portal_name, source_col in inserts:
        cr.execute(
            f"""
            INSERT INTO property_portal_listing
                (property_base_id, portal_name, portal_listing_id, listing_label, active)
            SELECT
                pb.id,
                %s,
                TRIM(pb.{source_col}),
                pb.property_tag,
                TRUE
            FROM property_base pb
            WHERE pb.{source_col} IS NOT NULL
              AND TRIM(pb.{source_col}) <> ''
            ON CONFLICT (portal_name, portal_listing_id) DO NOTHING
            """,
            (portal_name,),
        )
