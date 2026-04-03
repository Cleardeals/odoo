import logging

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Migration: post-01-rename_superseded_status.py
# Module   : leads  v1.4.0
# Phase    : post  (runs after ORM upgrade)
#
# PURPOSE
# -------
# Rename the system-internal "Superseded" site-visit status to "Rescheduled"
# and mark it inactive so it no longer appears in user-facing dropdowns.
#
# Background:
#   The "superseded" status was introduced in v1.3.0 as the terminal state
#   applied to the OLD visit when an RM reschedules.  The name "Superseded"
#   is internal jargon that confused RMs — they expect to see "Rescheduled"
#   on visits that were displaced by a later booking.
#
#   The seed record in lead_site_visit_status_data.xml (noupdate="1") cannot
#   update existing rows, so this migration applies the change directly.
#
# MIGRATION PLAN
# ──────────────
# Step 0  — Pre-flight: verify lead_site_visit_status table exists.
# Step 1  — Rename "Superseded" → "Rescheduled" for code='superseded'.
# Step 2  — Mark active=False so it is hidden from all user dropdowns.
# Step 3  — VERIFICATION: log final state.
#
# IDEMPOTENCY
# ───────────
# Both UPDATEs are conditional on the current value, so re-running is safe.
# ---------------------------------------------------------------------------


def _table_exists(cr, table_name):
    cr.execute(
        """
        SELECT 1
          FROM information_schema.tables
         WHERE table_schema = 'public'
           AND table_name    = %s
        """,
        (table_name,),
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    """
    Rename the 'superseded' status record to 'Rescheduled' and mark inactive.

    Context:
        The seed data uses noupdate="1", so existing records are not touched
        during normal module upgrades.  This migration applies the display-name
        and visibility change in-place on the current database.
    """

    # ── Step 0 — Pre-flight ──────────────────────────────────────────────────
    if not _table_exists(cr, "lead_site_visit_status"):
        _logger.warning(
            "[leads 1.4.0] [step 0] lead_site_visit_status table not found — "
            "skipping migration (fresh install will use updated seed data)."
        )
        return

    _logger.info("[leads 1.4.0] [step 0] Pre-flight OK — lead_site_visit_status exists.")

    # ── Step 1 — Rename ──────────────────────────────────────────────────────
    cr.execute(
        """
        UPDATE lead_site_visit_status
           SET name = 'Rescheduled',
               write_date = NOW() AT TIME ZONE 'UTC'
         WHERE code  = 'superseded'
           AND name != 'Rescheduled'
        """
    )
    renamed = cr.rowcount
    _logger.info(
        "[leads 1.4.0] [step 1] Renamed %d status record(s) from 'Superseded' to 'Rescheduled'.",
        renamed,
    )

    # ── Step 2 — Mark inactive ───────────────────────────────────────────────
    cr.execute(
        """
        UPDATE lead_site_visit_status
           SET active     = FALSE,
               write_date = NOW() AT TIME ZONE 'UTC'
         WHERE code   = 'superseded'
           AND active = TRUE
        """
    )
    deactivated = cr.rowcount
    _logger.info(
        "[leads 1.4.0] [step 2] Deactivated %d status record(s) with code='superseded'.",
        deactivated,
    )

    # ── Step 3 — Verification ────────────────────────────────────────────────
    cr.execute(
        "SELECT name, active FROM lead_site_visit_status WHERE code = 'superseded'"
    )
    row = cr.fetchone()
    if row:
        _logger.info(
            "[leads 1.4.0] [step 3] Final state: code='superseded' → name='%s', active=%s.",
            row[0],
            row[1],
        )
    else:
        _logger.info(
            "[leads 1.4.0] [step 3] No record with code='superseded' found "
            "(may have been installed fresh from updated seed data)."
        )

    _logger.info("[leads 1.4.0] Migration complete.")
