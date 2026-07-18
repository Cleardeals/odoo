"""Drop ``leads_new.wa_nudge_emitted`` — the initial-nudge once-only guard.

The guard existed because the nudge fired from ``write()`` on
``vals.get('state') == 'assigned'``, which is a *level* check: Odoo re-passes
unchanged values, so any later save of an already-assigned lead re-fired it. The
boolean converted that into an edge.

The trigger is now lead *creation* (``create`` runs exactly once per record), so
the guard has no job left. It was also never able to do the job it appeared to:
Pub/Sub delivers at-least-once, so duplicate ``nudge.initial`` events arise
*after* the publish, where an Odoo column cannot see them. That de-duplication
belongs to — and now lives in — the workflow engine's ``workflow_enrollments``
table, which is unique on ``(workflow_id, actor_id)`` and no longer resets an
existing enrollment from a trigger event.

Odoo does not drop columns for removed fields, so we drop it explicitly.
Nothing reads it: the column was write-only bookkeeping, never surfaced in a
view, and no historical value is worth keeping — "was this lead nudged" is
answered by the engine's enrollment row.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'leads_new'
           AND column_name = 'wa_nudge_emitted'
    """)
    if not cr.fetchone():
        _logger.info("wa_nudge_emitted already absent — nothing to drop.")
        return

    cr.execute("ALTER TABLE leads_new DROP COLUMN wa_nudge_emitted")
    _logger.info("Dropped leads_new.wa_nudge_emitted (initial-nudge guard retired).")
