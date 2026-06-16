"""Backfill ``leads.new.hard_to_reach_since`` from existing status history.

The field is maintained going forward by the ``current_status`` write-hook in
``wa_lead_event_publisher.py``, but historical leads that became hard-to-reach
before this release have no stamp.  Odoo already tracks ``current_status``
changes (``tracking=True``) in ``mail.tracking.value``, so we can recover, per
lead, the most recent time it transitioned *into* a hard-to-reach status and
seed the column with it.

For a Selection field, ``mail.tracking.value.new_value_char`` stores the
*label* (not the code), so we match on the labels of the hard-to-reach codes.
Idempotent: only rows where ``hard_to_reach_since IS NULL`` are touched.  Best
effort — any unexpected schema shape is logged and skipped, never failing the
upgrade.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

_HARD_CODES = ('ringing', 'call_back_later', 'busy', 'switched_off')


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    field = env['ir.model.fields']._get('leads.new', 'current_status')
    if not field:
        _logger.warning("htr backfill: leads.new.current_status field not found — skipped")
        return

    # Resolve the hard-to-reach labels as stored in mail.tracking.value.
    selection = dict(env['leads.new']._fields['current_status'].selection or [])
    hard_labels = tuple(selection[c] for c in _HARD_CODES if c in selection)
    if not hard_labels:
        _logger.warning("htr backfill: no hard-to-reach labels resolved — skipped")
        return

    try:
        cr.execute(
            """
            UPDATE leads_new ln
               SET hard_to_reach_since = sub.dt
              FROM (
                    SELECT mm.res_id AS lead_id, MAX(mm.date) AS dt
                      FROM mail_tracking_value tv
                      JOIN mail_message mm ON mm.id = tv.mail_message_id
                     WHERE tv.field_id = %s
                       AND mm.model = 'leads.new'
                       AND tv.new_value_char IN %s
                  GROUP BY mm.res_id
                   ) sub
             WHERE ln.id = sub.lead_id
               AND ln.hard_to_reach_since IS NULL
            """,
            (field.id, hard_labels),
        )
        _logger.info("htr backfill: stamped %s lead(s) from status history", cr.rowcount)
    except Exception:  # noqa: BLE001 — best-effort backfill must never block upgrade
        _logger.exception("htr backfill: failed; leaving hard_to_reach_since unset")
