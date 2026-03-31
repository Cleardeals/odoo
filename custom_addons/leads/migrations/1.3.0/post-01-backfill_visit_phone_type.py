import logging

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Migration: post-01-backfill_visit_phone_type.py
# Module   : leads  v1.3.0
# Phase    : post  (runs after ORM upgrade)
#
# PURPOSE
# -------
# Two stored-related fields on lead.site.visit were not backfilled correctly
# for records created by the v1.2.0 raw-SQL migration (raw INSERTs bypass
# the ORM trigger that normally populates stored-related fields):
#
#   lead_site_visit.inquiry_phone  ← leads_new.phone
#   lead_site_visit.inquiry_type   ← leads_new.inquiry_type
#
# Additionally, root_visit_id must self-reference for root visits (those with
# no previous_visit_id), which may also be NULL on migrated records.
#
# MIGRATION PLAN
# ──────────────
# Step 0  — Pre-flight: verify tables and required columns exist.
# Step 1  — AUDIT: log counts of records with NULL phone/type before touching.
# Step 2  — Backfill inquiry_phone from leads_new.phone wherever NULL.
# Step 3  — Backfill inquiry_type from leads_new.inquiry_type wherever NULL,
#           defaulting to 'primary' when the source column is also NULL.
# Step 4  — Fix root_visit_id: set to self (id) for root visits where it
#           is currently NULL (records with no previous_visit_id).
# Step 5  — VERIFICATION: log final NULL counts to confirm success.
#
# IDEMPOTENCY
# ───────────
# All UPDATE statements are conditioned on the target field being NULL.
# Re-running on an already-migrated database is safe — no data is overwritten.
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


def _column_exists(cr, table_name, column_name):
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name   = %s
           AND column_name  = %s
        """,
        (table_name, column_name),
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    """
    Backfill inquiry_phone, inquiry_type, and root_visit_id on lead.site.visit.

    Context:
        The v1.2.0 migration inserted lead_site_visit rows via raw SQL, which
        bypasses stored-related field triggers. inquiry_phone and inquiry_type
        were left NULL on those rows. This migration fills them in from leads_new.

    Idempotency:
        All UPDATEs are guarded by IS NULL conditions. Safe to re-run.
    """
    _logger.info("=== %s %s: starting ===", __name__, version)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 0 — Pre-flight
    # ─────────────────────────────────────────────────────────────────────────
    _logger.info("%s %s: [step 0] pre-flight checks", __name__, version)

    for tbl in ("leads_new", "lead_site_visit"):
        if not _table_exists(cr, tbl):
            _logger.warning(
                "%s %s: table '%s' not found — aborting.", __name__, version, tbl
            )
            return

    for tbl, col in (
        ("leads_new", "phone"),
        ("leads_new", "inquiry_type"),
        ("lead_site_visit", "inquiry_phone"),
        ("lead_site_visit", "inquiry_type"),
        ("lead_site_visit", "root_visit_id"),
        ("lead_site_visit", "previous_visit_id"),
    ):
        if not _column_exists(cr, tbl, col):
            _logger.warning(
                "%s %s: column %s.%s not found — aborting.", __name__, version, tbl, col
            )
            return

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 1 — Audit: count NULLs before changes
    # ─────────────────────────────────────────────────────────────────────────
    _logger.info("%s %s: [step 1] pre-migration audit", __name__, version)

    cr.execute("SELECT COUNT(*) FROM lead_site_visit WHERE inquiry_phone IS NULL")
    null_phone = cr.fetchone()[0]

    cr.execute("SELECT COUNT(*) FROM lead_site_visit WHERE inquiry_type IS NULL")
    null_type = cr.fetchone()[0]

    cr.execute(
        "SELECT COUNT(*) FROM lead_site_visit WHERE root_visit_id IS NULL AND previous_visit_id IS NULL"
    )
    null_root = cr.fetchone()[0]

    cr.execute("SELECT COUNT(*) FROM lead_site_visit")
    total = cr.fetchone()[0]

    _logger.info(
        "%s %s: total visits=%d  null_phone=%d  null_type=%d  null_root_visit_id=%d",
        __name__, version, total, null_phone, null_type, null_root,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 2 — Backfill inquiry_phone from leads_new.phone
    # ─────────────────────────────────────────────────────────────────────────
    _logger.info("%s %s: [step 2] backfilling inquiry_phone", __name__, version)

    cr.execute(
        """
        UPDATE lead_site_visit sv
           SET inquiry_phone = ln.phone,
               write_date    = NOW() AT TIME ZONE 'UTC'
          FROM leads_new ln
         WHERE sv.inquiry_id    = ln.id
           AND sv.inquiry_phone IS NULL
           AND ln.phone         IS NOT NULL
        """
    )
    _logger.info(
        "%s %s: [step 2] inquiry_phone updated on %d rows", __name__, version, cr.rowcount
    )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 3 — Backfill inquiry_type from leads_new.inquiry_type
    #          Default to 'primary' when source is also NULL
    # ─────────────────────────────────────────────────────────────────────────
    _logger.info("%s %s: [step 3] backfilling inquiry_type", __name__, version)

    cr.execute(
        """
        UPDATE lead_site_visit sv
           SET inquiry_type = COALESCE(ln.inquiry_type, 'primary'),
               write_date   = NOW() AT TIME ZONE 'UTC'
          FROM leads_new ln
         WHERE sv.inquiry_id   = ln.id
           AND sv.inquiry_type IS NULL
        """
    )
    _logger.info(
        "%s %s: [step 3] inquiry_type updated on %d rows", __name__, version, cr.rowcount
    )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 4 — Fix root_visit_id: self-reference for root visits
    # ─────────────────────────────────────────────────────────────────────────
    _logger.info("%s %s: [step 4] fixing root_visit_id self-references", __name__, version)

    cr.execute(
        """
        UPDATE lead_site_visit
           SET root_visit_id = id,
               write_date    = NOW() AT TIME ZONE 'UTC'
         WHERE root_visit_id    IS NULL
           AND previous_visit_id IS NULL
        """
    )
    _logger.info(
        "%s %s: [step 4] root_visit_id fixed on %d rows", __name__, version, cr.rowcount
    )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 5 — Fix name: rewrite all non-standard names to match
    #          _compute_name: "{leads.new.name} | {status.name} | {datetime}"
    #          This includes the old "[Migrated]" prefix and any NULL names.
    # ─────────────────────────────────────────────────────────────────────────
    _logger.info("%s %s: [step 5] rewriting visit names to standard format", __name__, version)

    cr.execute(
        """
        UPDATE lead_site_visit sv
           SET name       = COALESCE(ln.name, 'Inquiry #' || ln.id::text)
                            || ' | '
                            || COALESCE(s.name, 'Visit')
                            || ' | '
                            || TO_CHAR(sv.scheduled_datetime AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
               write_date = NOW() AT TIME ZONE 'UTC'
          FROM leads_new ln
          JOIN lead_site_visit_status s ON s.id = sv.status_id
         WHERE sv.inquiry_id = ln.id
           AND (
               sv.name LIKE '[Migrated]%%'
               OR sv.name IS NULL
               OR sv.name = ''
           )
        """
    )
    _logger.info(
        "%s %s: [step 5] names rewritten on %d rows", __name__, version, cr.rowcount
    )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 6 — Backfill feedback_option_id for completed records that have
    #          no feedback set (legacy migrated visits from site_visit_done).
    #          Uses the "completed_legacy" feedback option as a placeholder.
    # ─────────────────────────────────────────────────────────────────────────
    _logger.info("%s %s: [step 6] backfilling legacy feedback for completed visits", __name__, version)

    cr.execute(
        "SELECT id FROM lead_site_visit_feedback_option WHERE code = %s AND active = TRUE LIMIT 1",
        ("completed_legacy",),
    )
    row = cr.fetchone()
    if row:
        legacy_feedback_id = row[0]
        cr.execute(
            """
            UPDATE lead_site_visit sv
               SET feedback_option_id = %(feedback_id)s,
                   write_date         = NOW() AT TIME ZONE 'UTC'
              FROM lead_site_visit_status s
             WHERE sv.status_id          = s.id
               AND s.is_completed_status = TRUE
               AND sv.feedback_option_id IS NULL
            """,
            {"feedback_id": legacy_feedback_id},
        )
        _logger.info(
            "%s %s: [step 6] legacy feedback set on %d completed visits",
            __name__, version, cr.rowcount
        )
    else:
        _logger.warning(
            "%s %s: [step 6] feedback option code='completed_legacy' not found — skipping.",
            __name__, version,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 7 — Verification
    # ─────────────────────────────────────────────────────────────────────────
    _logger.info("%s %s: [step 7] post-migration verification", __name__, version)

    cr.execute("SELECT COUNT(*) FROM lead_site_visit WHERE inquiry_phone IS NULL")
    still_null_phone = cr.fetchone()[0]

    cr.execute("SELECT COUNT(*) FROM lead_site_visit WHERE inquiry_type IS NULL")
    still_null_type = cr.fetchone()[0]

    cr.execute(
        "SELECT COUNT(*) FROM lead_site_visit WHERE root_visit_id IS NULL AND previous_visit_id IS NULL"
    )
    still_null_root = cr.fetchone()[0]

    _logger.info(
        "%s %s: [step 5] after migration — still null: phone=%d  type=%d  root_visit_id=%d",
        __name__, version, still_null_phone, still_null_type, still_null_root,
    )

    if still_null_phone > 0:
        _logger.warning(
            "%s %s: %d visits still have NULL inquiry_phone — their inquiry_id has no phone set.",
            __name__, version, still_null_phone,
        )
    if still_null_type > 0:
        _logger.warning(
            "%s %s: %d visits still have NULL inquiry_type after COALESCE fallback — investigate.",
            __name__, version, still_null_type,
        )

    _logger.info("=== %s %s: done ===", __name__, version)
