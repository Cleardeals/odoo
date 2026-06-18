"""Seed the assignment-history ledger for conversations that already have an owner.

``wa.conversation.assignment.log`` is maintained going forward by the
``create``/``write`` hook in ``wa_conversation_assignment_log.py``, but
conversations assigned *before* this release have no history rows — so the By-RM
obligation engine would treat them as Unassigned for their whole past.

We seed one baseline row per currently-owned conversation, effective at the
conversation's first message (best proxy for "owned since"), falling back to the
conversation's create date.

**Honest caveat:** true point-in-time history doesn't exist before this release.
A chat reassigned in the past is backfilled only with its *current* owner, so
pre-release periods attribute that chat's obligations to whoever owns it now.
Attribution is exact only from this release forward — that's the best the data
allows, and it's why we're starting the ledger now.

Idempotent: skips any conversation that already has a log row.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    try:
        cr.execute(
            """
            INSERT INTO wa_conversation_assignment_log
                   (conversation_id, owner_user_id, effective_from,
                    create_uid, create_date, write_uid, write_date)
            SELECT c.id,
                   c.assigned_user_id,
                   COALESCE(fm.first_dt, c.create_date),
                   1, now() AT TIME ZONE 'UTC', 1, now() AT TIME ZONE 'UTC'
              FROM wa_conversation c
              LEFT JOIN (
                        SELECT conversation_id, MIN(occurred_at) AS first_dt
                          FROM wa_message
                      GROUP BY conversation_id
                   ) fm ON fm.conversation_id = c.id
             WHERE c.assigned_user_id IS NOT NULL
               AND NOT EXISTS (
                        SELECT 1 FROM wa_conversation_assignment_log l
                         WHERE l.conversation_id = c.id
                   )
            """
        )
        _logger.info(
            "assignment-log backfill: seeded %s baseline ownership row(s)",
            cr.rowcount,
        )
    except Exception:  # noqa: BLE001 — best-effort backfill must never block upgrade
        _logger.exception("assignment-log backfill failed; ledger starts empty")
