import logging

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Migration: post-02-remove_orphan_server_actions.py
# Module   : leads  v1.4.0
# Phase    : post  (runs after ORM upgrade)
#
# PURPOSE
# -------
# Remove the "Recompute Creation Date" server action that was bound to the
# leads.new list Action menu.  This record has no XML external ID so it is
# not managed by any data file and cannot be removed via an XML <delete> tag.
# It must be deleted directly from the DB.
#
# The other two Action-menu entries ("Backfill Property Links (Migration)"
# and "Recompute Stored Property Fields") DO have external XML IDs.  Their
# binding_model_id was removed from the view XML files in this release, so
# the standard -u leads module upgrade already sets binding_model_id = NULL
# on those records.  No SQL is needed for them here.
#
# MIGRATION PLAN
# ──────────────
# Step 1  — Find the orphan action by name + model (safe even on fresh DBs
#            where the record was never created).
# Step 2  — Delete binding_group rows for it (FK child before parent).
# Step 3  — Delete the action record itself.
# Step 4  — Log result.
#
# IDEMPOTENCY
# ───────────
# Uses DELETE WHERE, so re-running on a DB where the record was already
# removed is completely safe — it simply deletes 0 rows.
# ---------------------------------------------------------------------------


def migrate(cr, version):
    """Remove the orphan 'Recompute Creation Date' server action from all DBs.

    This action was never declared in any XML data file for the leads module.
    It has no ir_model_data entry and therefore survives module upgrades.
    The only way to remove it reliably across all environments is via a
    post-migration script that targets it by name and model.
    """

    _logger.info("post-02: removing orphan 'Recompute Creation Date' server action")

    # Step 1: find the record ID (may not exist on every DB)
    cr.execute(
        """
        SELECT a.id
          FROM ir_act_server a
          JOIN ir_model m ON m.id = a.model_id
         WHERE m.model  = 'leads.new'
           AND a.name::text ILIKE '%%Recompute Creation Date%%'
        """,
    )
    rows = cr.fetchall()

    if not rows:
        _logger.info("post-02: 'Recompute Creation Date' action not found — nothing to do")
        return

    ids = [row[0] for row in rows]
    _logger.info("post-02: found orphan action id(s): %s — deleting", ids)

    # Step 2: remove group bindings (child table, FK constraint)
    cr.execute(
        "DELETE FROM ir_act_server_group_rel WHERE act_id = ANY(%s)",
        (ids,),
    )

    # Step 3: delete the action record itself
    cr.execute(
        "DELETE FROM ir_act_server WHERE id = ANY(%s)",
        (ids,),
    )

    _logger.info("post-02: orphan server action(s) deleted successfully")
