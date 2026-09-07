"""Property-anchor segments: backfill + collapse duplicate label-only spans.

``wa.conversation.segment.property_base_id`` changed from a stored *related*
(``inquiry_id.property_base_id``) to a plain stored field it can hold before an
inquiry exists (see wa_segment.py). Existing column values survive the upgrade;
this post-migration:

1. **Backfills** ``property_base_id`` from the linked inquiry for any bound span
   where it is somehow null (defensive — the old related had populated it).

2. **Collapses duplicate label-only spans.** Before this release ``_owa_ensure_segment``
   never deduped inquiry-less segments, so "New topic" clicked twice for the same
   property/label spawned separate orphan spans that split attribution. Within each
   conversation we merge inquiry-less spans that share a group key — the property
   when set, else the normalized label — into the earliest survivor: repoint their
   ``wa.message.segment_id`` and any ``wa.conversation.active_segment_id``, then
   delete the emptied losers. No immutable fact is touched; idempotent (a re-run
   finds nothing left to merge). Genuinely blank spans (no property AND no label)
   are left alone — they are not safely identifiable as duplicates.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # 1. Defensive backfill from the linked inquiry.
    cr.execute("""
        UPDATE wa_conversation_segment s
           SET property_base_id = l.property_base_id
          FROM leads_new l
         WHERE s.inquiry_id = l.id
           AND s.property_base_id IS NULL
           AND l.property_base_id IS NOT NULL
    """)
    _logger.info("wa 1.2.5: backfilled property on %s bound segment(s)", cr.rowcount)

    # 2. Find duplicate label-only spans (keep the earliest per group).
    cr.execute("""
        WITH grp AS (
            SELECT id,
                   conversation_id,
                   started_at,
                   COALESCE(property_base_id::text,
                            'L:' || lower(btrim(COALESCE(label, '')))) AS gkey
              FROM wa_conversation_segment
             WHERE inquiry_id IS NULL
               AND (property_base_id IS NOT NULL
                    OR btrim(COALESCE(label, '')) <> '')
        ),
        ranked AS (
            SELECT id,
                   first_value(id) OVER (
                       PARTITION BY conversation_id, gkey
                       ORDER BY started_at NULLS FIRST, id
                   ) AS survivor_id
              FROM grp
        )
        SELECT id, survivor_id FROM ranked WHERE id <> survivor_id
    """)
    mapping = cr.fetchall()  # [(loser_id, survivor_id), ...]
    if not mapping:
        _logger.info("wa 1.2.5: no duplicate label-only segments to collapse")
        return

    for loser_id, survivor_id in mapping:
        cr.execute(
            "UPDATE wa_message SET segment_id = %s WHERE segment_id = %s",
            (survivor_id, loser_id))
        cr.execute(
            "UPDATE wa_conversation SET active_segment_id = %s "
            "WHERE active_segment_id = %s",
            (survivor_id, loser_id))

    losers = tuple(loser_id for loser_id, _ in mapping)
    cr.execute("DELETE FROM wa_conversation_segment WHERE id IN %s", (losers,))
    _logger.info(
        "wa 1.2.5: collapsed %s duplicate label-only segment(s)", len(losers))
