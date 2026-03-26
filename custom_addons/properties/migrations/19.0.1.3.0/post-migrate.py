def migrate(cr, version):
    """
    Backfill portal listings from legacy property.base portal-id fields and
    normalize auto-generated labels to a no-property-tag format.

    Label format:
        <property short code> | <portal> | <portal listing id>

    Legacy fields are intentionally kept untouched.
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
                CONCAT_WS(
                    ' | ',
                    NULLIF(TRIM(pb.prop_id), ''),
                    %s,
                    TRIM(pb.{source_col})
                ),
                TRUE
            FROM property_base pb
            WHERE pb.{source_col} IS NOT NULL
              AND TRIM(pb.{source_col}) <> ''
            ON CONFLICT (portal_name, portal_listing_id) DO NOTHING
            """,
            (portal_name, portal_name),
        )

    cr.execute(
        """
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
               OR TRIM(ppl.listing_label) = COALESCE(NULLIF(TRIM(pb.property_tag), ''), '')
               OR TRIM(ppl.listing_label) = CONCAT_WS(
                   ' | ',
                   NULLIF(TRIM(pb.prop_id), ''),
                   COALESCE(NULLIF(TRIM(pb.property_tag), ''), NULLIF(TRIM(pb.name), '')),
                   NULLIF(TRIM(ppl.portal_listing_id), '')
               )
           )
        """,
    )
