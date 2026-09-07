import logging

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Migration: pre-migrate.py
# Module   : wa_communication  v1.1.1
# Phase    : pre  (runs BEFORE the new data files are loaded)
#
# PURPOSE
# -------
# ``action_wa_message_log`` was historically an ``ir.actions.act_window`` and is
# now an ``ir.actions.client``.  Odoo refuses to change a record's model in
# place, so on databases that still hold the legacy act_window the old record
# must be dropped before the (post-load) XML recreates it as a client action.
#
# This previously lived as a hard ``<delete model="ir.actions.act_window"
# id="action_wa_message_log"/>`` in wa_dashboard_action.xml.  That is FATAL on a
# fresh install — the xml id does not exist yet, so Odoo raises "External ID not
# found" and aborts the entire module install (breaking CI, which always
# installs fresh).  Moving the cleanup here makes it tolerant: it only acts when
# the legacy act_window actually exists, and fresh installs skip it entirely.
#
# IDEMPOTENCY
# -----------
# Guarded by an existence check on ir_model_data; re-running (or running on a DB
# that was never on the act_window version) deletes nothing and is a no-op.
# ---------------------------------------------------------------------------


def migrate(cr, version):
    """Drop the legacy ``action_wa_message_log`` act_window, if present."""
    cr.execute(
        """
        SELECT id, res_id
          FROM ir_model_data
         WHERE module = 'wa_communication'
           AND name   = 'action_wa_message_log'
           AND model  = 'ir.actions.act_window'
        """
    )
    row = cr.fetchone()
    if not row:
        _logger.info(
            "wa_communication 1.1.1: no legacy act_window for "
            "action_wa_message_log — nothing to migrate."
        )
        return

    imd_id, res_id = row
    _logger.info(
        "wa_communication 1.1.1: dropping legacy act_window "
        "action_wa_message_log (act_window id=%s) so it can be recreated as a "
        "client action.", res_id,
    )
    # Remove the action row, then its dangling ir_model_data pointer so the
    # post-load XML cleanly creates the ir.actions.client under the same xml id.
    cr.execute("DELETE FROM ir_act_window WHERE id = %s", (res_id,))
    cr.execute("DELETE FROM ir_model_data WHERE id = %s", (imd_id,))
    _logger.info("wa_communication 1.1.1: legacy act_window removed.")
