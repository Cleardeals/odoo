"""Deduplicate + canonicalize wa.conversation phone numbers.

Historically conversations were created without an enforced unique index on
``phone_number`` (the index failed to build because duplicates already existed),
and rows were stored in mixed formats — some bare 10-digit, some 12-digit
``91…``.  Two compounding effects followed:

* a race in ``_get_or_create_for_phone`` inserted duplicate rows for the same
  number (two concurrent inbound deliveries), and
* the same contact could hold both a 10-digit and a 12-digit conversation that
  never deduplicated against each other.

This **pre**-migration runs before the model schema is (re)loaded, so once it
collapses every number to a single canonical 12-digit row, the new
``UNIQUE(phone_number)`` index created during model loading succeeds.

Strategy: compute a canonical key (``91`` + 10 digits) for every conversation,
pick one survivor per key (prefer an assigned chat, else the lowest id), repoint
child rows (``wa_message``, ``wa_reassignment_request``) onto the survivor, sum
unread counters, delete the losers, write the canonical phone, and recompute the
last-message snapshot from the merged history.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # 1. Canonical key per conversation (skip blank/NULL phones).
    cr.execute("""
        CREATE TEMP TABLE _conv_canon ON COMMIT DROP AS
        SELECT id,
               assigned_user_id,
               CASE
                 WHEN phone_number ~ '^91[0-9]{10}$' THEN phone_number
                 WHEN phone_number ~ '^[0-9]{10}$'   THEN '91' || phone_number
                 ELSE regexp_replace(phone_number, '\\D', '', 'g')
               END AS canon
        FROM wa_conversation
        WHERE phone_number IS NOT NULL AND phone_number <> '';
    """)

    # 2. One survivor per canonical number: prefer an assigned chat, else lowest id.
    cr.execute("""
        CREATE TEMP TABLE _conv_survivor ON COMMIT DROP AS
        SELECT DISTINCT ON (canon) canon, id AS survivor_id
        FROM _conv_canon
        ORDER BY canon, (assigned_user_id IS NULL), id;
    """)

    # 3. Full old -> survivor map.
    cr.execute("""
        CREATE TEMP TABLE _conv_map ON COMMIT DROP AS
        SELECT c.id AS old_id, s.survivor_id, c.canon
        FROM _conv_canon c
        JOIN _conv_survivor s USING (canon);
    """)

    cr.execute("SELECT COUNT(*) FROM _conv_map WHERE old_id <> survivor_id;")
    dup_count = cr.fetchone()[0]

    # 4. Repoint child rows from losers to survivors.
    cr.execute("""
        UPDATE wa_message m SET conversation_id = cm.survivor_id
        FROM _conv_map cm
        WHERE m.conversation_id = cm.old_id AND cm.old_id <> cm.survivor_id;
    """)
    cr.execute("""
        UPDATE wa_reassignment_request r SET conversation_id = cm.survivor_id
        FROM _conv_map cm
        WHERE r.conversation_id = cm.old_id AND cm.old_id <> cm.survivor_id;
    """)

    # 5. Roll the losers' unread counters into the survivor before deleting.
    cr.execute("""
        UPDATE wa_conversation s SET unread_count = agg.total
        FROM (
            SELECT cm.survivor_id, SUM(COALESCE(c.unread_count, 0)) AS total
            FROM _conv_map cm
            JOIN wa_conversation c ON c.id = cm.old_id
            GROUP BY cm.survivor_id
        ) agg
        WHERE s.id = agg.survivor_id;
    """)

    # 6. Delete the loser rows.
    cr.execute("""
        DELETE FROM wa_conversation c
        USING _conv_map cm
        WHERE c.id = cm.old_id AND cm.old_id <> cm.survivor_id;
    """)

    # 7. Write the canonical phone onto every survivor.
    cr.execute("""
        UPDATE wa_conversation c SET phone_number = cm.canon
        FROM _conv_map cm
        WHERE c.id = cm.survivor_id AND c.phone_number <> cm.canon;
    """)

    # 8. Recompute the last-message snapshot from the merged history.
    cr.execute("""
        UPDATE wa_conversation c SET
            last_message_at = lm.occurred_at,
            last_message_preview = LEFT(
                COALESCE(NULLIF(lm.body, ''), lm.template_body, ''), 100)
        FROM (
            SELECT DISTINCT ON (conversation_id)
                   conversation_id, occurred_at, body, template_body
            FROM wa_message
            ORDER BY conversation_id, occurred_at DESC NULLS LAST, id DESC
        ) lm
        WHERE c.id = lm.conversation_id;
    """)

    _logger.info(
        "wa_communication 1.1.2: merged %s duplicate conversation row(s) and "
        "canonicalized phone numbers to 12-digit E.164.", dup_count)
