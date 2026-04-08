import logging

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Migration: post-01-backfill_site_visits.py
# Module   : leads  v1.2.0
# Phase    : post  (ORM has created lead_site_visit before this runs)
#
# PURPOSE
# -------
# Before lead.site.visit existed, site visit scheduling was stored as two flat
# columns on leads.new:
#
#   leads_new.site_visit_date    Datetime  — when the visit was scheduled
#   leads_new.current_status     Selection — e.g. 'site_visit_scheduled',
#                                            'site_visit_done', 'rescheduled'
#
# This migration creates one lead.site.visit record per legacy lead that has
# site_visit_date set, preserving datetime, property, RM, status, phone, and
# inquiry_type without data loss.
#
# MIGRATION PLAN
# ──────────────
# Step 0  — pre-flight: verify tables and mandatory columns exist.
# Step 1  — resolve status IDs: look up the 'scheduled' and 'completed'
#           lead.site.visit.status rows by immutable code.
# Step 2  — AUDIT: log a breakdown of every unmigrated legacy lead by
#           (current_status, has_property, has_date) before touching any row.
# Step 3  — SELECT all eligible candidates. Criteria for eligibility:
#             • site_visit_date IS NOT NULL  (we have a datetime to migrate)
#             • property_base_id IS NOT NULL (required FK on lead.site.visit)
#             • no lead.site.visit row already exists for that inquiry
#           Candidates are bucketed by current_status → status_id mapping.
# Step 4  — INSERT one lead.site.visit row per candidate.
#           • inquiry_phone and inquiry_type (stored-related fields) are
#             populated directly from the leads_new row — raw SQL INSERT
#             bypasses the ORM so these never auto-populate otherwise.
#           • inquiry_type defaults to 'primary' if the column is NULL or
#             absent (all pre-extension leads are primary inquiries).
#           • status_changed_on is set to site_visit_date, not NOW(), so
#             the historical timeline reflects the actual scheduling date.
#           • create_date / write_date are set to NOW() (admin uid=1).
# Step 5  — root_visit_id self-reference: UPDATE root_visit_id = id for
#           every migrated record (no reschedule lineage in legacy data).
# Step 6  — SKIP log: log every lead that had site_visit_date set but was
#           skipped (no property_base_id), so an admin can act on them.
# Step 7  — VERIFICATION: final counts grouped by status code + NULL checks.
#
# IDEMPOTENCY
# ───────────
# The SELECT in step 3 excludes all inquiry_ids that already have a
# lead.site.visit row. Re-running this script on a partially-migrated
# or fully-migrated database is completely safe — no duplicates created.
#
# STATUS MAPPING
# ──────────────
#   current_status == 'site_visit_done'   → status code='completed'
#   anything else with site_visit_date    → status code='scheduled'
#     (includes 'site_visit_scheduled', 'rescheduled', 'lead', etc.)
#     Rationale: if an RM stored a date, a visit was at minimum scheduled.
#     The actual terminal outcome is unknown from legacy data; 'scheduled'
#     is the conservative choice and can be manually corrected afterward.
#
# SKIPPED LEADS
# ─────────────
# Leads with site_visit_date IS NOT NULL but property_base_id IS NULL are
# skipped — property_base_id is a NOT NULL FK on lead.site.visit and cannot
# be NULL-inserted. These are logged with their IDs so a manager can run the
# Lead Property Migration Wizard to assign a property and then re-upgrade
# to complete the backfill.
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


# current_status values that indicate a completed visit in the legacy model.
_COMPLETED_STATUSES = frozenset({"site_visit_done"})


def migrate(cr, version):
    """
    Backfill lead.site.visit records from legacy site_visit_date flat columns.

    Context:
        The leads module introduced lead.site.visit as a proper model in v1.2.0.
        Before that, site visit state was stored on leads.new as two flat columns.
        This migration promotes every unmigrated lead that has site_visit_date set
        into the new model without data loss.

    Idempotency:
        Only leads whose inquiry_id has zero existing lead.site.visit rows are
        processed. Safe to re-run after a partial migration.

    Assumptions:
        - leads_new and lead_site_visit tables exist.
        - lead_site_visit_status has active rows with codes 'scheduled' and 'completed'.
        - Leads with site_visit_date but no property_base_id are skipped and logged.
        - inquiry_type defaults to 'primary' for records where the column is NULL.
    """
    _logger.info("=== %s %s: starting ===", __name__, version)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 0 — Pre-flight checks
    # ─────────────────────────────────────────────────────────────────────────
    _logger.info("%s %s: [step 0] pre-flight table & column checks", __name__, version)

    for tbl in ("leads_new", "lead_site_visit", "lead_site_visit_status"):
        if not _table_exists(cr, tbl):
            _logger.warning(
                "%s %s: required table '%s' not found — aborting.", __name__, version, tbl,
            )
            _logger.info("=== %s %s: done (aborted) ===", __name__, version)
            return

    for tbl, col in (
        ("leads_new", "site_visit_date"),
        ("leads_new", "current_status"),
        ("leads_new", "property_base_id"),
        ("leads_new", "user_id"),
        ("leads_new", "phone"),
    ):
        if not _column_exists(cr, tbl, col):
            _logger.warning(
                "%s %s: required column %s.%s not found — aborting.",
                __name__, version, tbl, col,
            )
            _logger.info("=== %s %s: done (aborted) ===", __name__, version)
            return

    # inquiry_type was added in a later extension — may be absent on old DBs
    has_inquiry_type_col = _column_exists(cr, "leads_new", "inquiry_type")
    _logger.info(
        "%s %s: leads_new.inquiry_type column present: %s",
        __name__, version, has_inquiry_type_col,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 1 — Resolve status IDs
    # ─────────────────────────────────────────────────────────────────────────
    _logger.info("%s %s: [step 1] resolving status IDs by code", __name__, version)

    cr.execute(
        "SELECT id FROM lead_site_visit_status WHERE code = %s AND active = TRUE LIMIT 1",
        ("scheduled",),
    )
    row = cr.fetchone()
    if not row:
        _logger.error(
            "%s %s: no active status code='scheduled' — aborting.", __name__, version,
        )
        _logger.info("=== %s %s: done (aborted) ===", __name__, version)
        return
    scheduled_status_id = row[0]
    _logger.info("%s %s: scheduled_status_id = %d", __name__, version, scheduled_status_id)

    cr.execute(
        "SELECT id FROM lead_site_visit_status WHERE code = %s AND active = TRUE LIMIT 1",
        ("completed",),
    )
    row = cr.fetchone()
    if not row:
        _logger.error(
            "%s %s: no active status code='completed' — aborting.", __name__, version,
        )
        _logger.info("=== %s %s: done (aborted) ===", __name__, version)
        return
    completed_status_id = row[0]
    _logger.info("%s %s: completed_status_id = %d", __name__, version, completed_status_id)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 2 — AUDIT: log breakdown before touching anything
    # ─────────────────────────────────────────────────────────────────────────
    _logger.info("%s %s: [step 2] pre-migration audit", __name__, version)

    cr.execute(
        "SELECT COUNT(*) FROM leads_new WHERE site_visit_date IS NOT NULL"
    )
    total_with_date = cr.fetchone()[0]
    _logger.info(
        "%s %s: audit — total leads_new rows with site_visit_date set: %d",
        __name__, version, total_with_date,
    )

    # Breakdown by current_status across all leads that have a site_visit_date
    cr.execute(
        """
        SELECT COALESCE(current_status, 'NULL'), COUNT(*) AS cnt
          FROM leads_new
         WHERE site_visit_date IS NOT NULL
         GROUP BY current_status
         ORDER BY cnt DESC
        """
    )
    for stat, cnt in cr.fetchall():
        _logger.info(
            "%s %s: audit — current_status=%-45s  count=%d",
            __name__, version, repr(stat), cnt,
        )

    cr.execute(
        """
        SELECT COUNT(DISTINCT lsv.inquiry_id)
          FROM lead_site_visit lsv
          JOIN leads_new ln ON ln.id = lsv.inquiry_id
         WHERE ln.site_visit_date IS NOT NULL
        """
    )
    already_migrated = cr.fetchone()[0]
    _logger.info(
        "%s %s: audit — already migrated (existing lead.site.visit rows): %d",
        __name__, version, already_migrated,
    )

    cr.execute(
        """
        SELECT COUNT(*)
          FROM leads_new ln
         WHERE ln.site_visit_date     IS NOT NULL
           AND ln.property_base_id    IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM lead_site_visit lsv WHERE lsv.inquiry_id = ln.id
           )
        """
    )
    eligible_count = cr.fetchone()[0]
    _logger.info(
        "%s %s: audit — eligible to migrate (date + property, no existing visit): %d",
        __name__, version, eligible_count,
    )

    cr.execute(
        """
        SELECT COUNT(*)
          FROM leads_new ln
         WHERE ln.site_visit_date  IS NOT NULL
           AND ln.property_base_id IS NULL
           AND NOT EXISTS (
               SELECT 1 FROM lead_site_visit lsv WHERE lsv.inquiry_id = ln.id
           )
        """
    )
    skip_no_property = cr.fetchone()[0]
    _logger.info(
        "%s %s: audit — will SKIP (site_visit_date set, property_base_id NULL): %d",
        __name__, version, skip_no_property,
    )

    if eligible_count == 0:
        _logger.info(
            "%s %s: nothing eligible to migrate — done.", __name__, version,
        )
        _logger.info("=== %s %s: done ===", __name__, version)
        return

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 3 — SELECT eligible candidates
    # ─────────────────────────────────────────────────────────────────────────
    _logger.info(
        "%s %s: [step 3] selecting %d eligible candidate(s)",
        __name__, version, eligible_count,
    )

    # inquiry_type: use column if present; fall back to literal 'primary'.
    # COALESCE handles rows where the column exists but is NULL.
    inquiry_type_expr = (
        "COALESCE(ln.inquiry_type, 'primary')" if has_inquiry_type_col else "'primary'"
    )

    # NOTE: inquiry_type_expr is built from two hardcoded strings — never from
    # user input — so f-string interpolation here is safe.
    cr.execute(
        f"""
        SELECT
            ln.id                              AS inquiry_id,
            ln.site_visit_date                 AS scheduled_datetime,
            ln.current_status                  AS old_status,
            ln.property_base_id                AS property_base_id,
            ln.user_id                         AS assigned_rm_id,
            ln.phone                           AS inquiry_phone,
            {inquiry_type_expr}                AS inquiry_type
        FROM leads_new ln
        WHERE ln.site_visit_date     IS NOT NULL
          AND ln.property_base_id    IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM lead_site_visit lsv WHERE lsv.inquiry_id = ln.id
          )
        ORDER BY ln.id
        """
    )
    candidates = cr.fetchall()
    _logger.info(
        "%s %s: fetched %d candidate row(s) from leads_new",
        __name__, version, len(candidates),
    )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 4 — INSERT one lead.site.visit per candidate
    # ─────────────────────────────────────────────────────────────────────────
    _logger.info("%s %s: [step 4] inserting site visit records", __name__, version)

    cr.execute(
        """
        CREATE TEMP TABLE _site_visit_migration (
            inquiry_id   INTEGER,
            new_visit_id INTEGER
        ) ON COMMIT DROP
        """
    )

    migrated_completed = 0
    migrated_scheduled = 0

    for (
        inquiry_id,
        scheduled_dt,
        old_status,
        property_base_id,
        assigned_rm_id,
        inquiry_phone,
        inquiry_type,
    ) in candidates:

        if old_status in _COMPLETED_STATUSES:
            resolved_status_id = completed_status_id
            status_name = "Completed"
            migrated_completed += 1
        else:
            resolved_status_id = scheduled_status_id
            status_name = "Scheduled"
            migrated_scheduled += 1

        # Use the same naming convention as _compute_name on the model:
        # "{inquiry_display_name} | {status_name} | {scheduled_datetime}"
        # inquiry display_name is not easily available here; use inquiry_id
        # as a placeholder — the ORM will recompute on first write.
        dt_str = (
            scheduled_dt.strftime("%Y-%m-%d %H:%M:%S")
            if hasattr(scheduled_dt, "strftime")
            else str(scheduled_dt)
        )
        # Fetch inquiry display_name from leads_new for accurate naming
        cr.execute("SELECT name FROM leads_new WHERE id = %s LIMIT 1", (inquiry_id,))
        inq_row = cr.fetchone()
        inq_name = inq_row[0] if inq_row and inq_row[0] else f"Inquiry #{inquiry_id}"
        name_value = f"{inq_name} | {status_name} | {dt_str}"

        cr.execute(
            """
            INSERT INTO lead_site_visit (
                inquiry_id,
                property_base_id,
                assigned_rm_id,
                scheduled_datetime,
                scheduled_date,
                status_id,
                status_changed_on,
                reschedule_iteration,
                inquiry_phone,
                inquiry_type,
                active,
                name,
                create_date,
                write_date,
                create_uid,
                write_uid
            )
            VALUES (
                %(inquiry_id)s,
                %(property_base_id)s,
                %(assigned_rm_id)s,
                %(scheduled_datetime)s,
                %(scheduled_datetime)s::timestamp::date,
                %(status_id)s,
                %(scheduled_datetime)s,
                0,
                %(inquiry_phone)s,
                %(inquiry_type)s,
                TRUE,
                %(name)s,
                NOW(),
                NOW(),
                1,
                1
            )
            RETURNING id
            """,
            {
                "inquiry_id":         inquiry_id,
                "property_base_id":   property_base_id,
                "assigned_rm_id":     assigned_rm_id,
                "scheduled_datetime": scheduled_dt,
                "status_id":          resolved_status_id,
                "inquiry_phone":      inquiry_phone,
                "inquiry_type":       inquiry_type,
                "name":               name_value,
            },
        )
        new_id = cr.fetchone()[0]
        cr.execute(
            "INSERT INTO _site_visit_migration (inquiry_id, new_visit_id) VALUES (%s, %s)",
            (inquiry_id, new_id),
        )

    _logger.info(
        "%s %s: inserted %d record(s) — scheduled=%d  completed=%d",
        __name__, version,
        len(candidates), migrated_scheduled, migrated_completed,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 5 — root_visit_id = id (no reschedule chain in legacy data)
    # ─────────────────────────────────────────────────────────────────────────
    _logger.info(
        "%s %s: [step 5] setting root_visit_id = id for migrated records",
        __name__, version,
    )
    cr.execute(
        """
        UPDATE lead_site_visit lsv
           SET root_visit_id = lsv.id
          FROM _site_visit_migration m
         WHERE lsv.id = m.new_visit_id
           AND lsv.root_visit_id IS NULL
        """
    )
    _logger.info(
        "%s %s: root_visit_id set on %d row(s)", __name__, version, cr.rowcount,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 6 — Log every skipped lead (date set but no property_base_id)
    # ─────────────────────────────────────────────────────────────────────────
    if skip_no_property > 0:
        _logger.info(
            "%s %s: [step 6] logging %d skipped lead(s)",
            __name__, version, skip_no_property,
        )
        cr.execute(
            """
            SELECT ln.id, ln.current_status, ln.site_visit_date
              FROM leads_new ln
             WHERE ln.site_visit_date  IS NOT NULL
               AND ln.property_base_id IS NULL
               AND NOT EXISTS (
                   SELECT 1 FROM lead_site_visit lsv WHERE lsv.inquiry_id = ln.id
               )
             ORDER BY ln.id
            """
        )
        for lead_id, cs, svd in cr.fetchall():
            _logger.warning(
                "%s %s: SKIPPED leads_new.id=%d  status=%s  visit_date=%s"
                "  — no property_base_id; run Lead Property Migration Wizard then re-upgrade",
                __name__, version, lead_id, cs, svd,
            )
    else:
        _logger.info(
            "%s %s: [step 6] no skips — all eligible leads had a property.",
            __name__, version,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 7 — Verification counts
    # ─────────────────────────────────────────────────────────────────────────
    _logger.info("%s %s: [step 7] post-migration verification", __name__, version)

    cr.execute(
        """
        SELECT s.code, COUNT(*) AS cnt
          FROM lead_site_visit lsv
          JOIN lead_site_visit_status s ON s.id = lsv.status_id
          JOIN _site_visit_migration m   ON m.new_visit_id = lsv.id
         GROUP BY s.code
         ORDER BY cnt DESC
        """
    )
    for code, cnt in cr.fetchall():
        _logger.info(
            "%s %s: verification — status_code=%-15s  count=%d",
            __name__, version, code, cnt,
        )

    # NULL-field check — stored related fields must be populated
    cr.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE lsv.inquiry_phone IS NULL) AS null_phone,
            COUNT(*) FILTER (WHERE lsv.inquiry_type  IS NULL) AS null_type
          FROM lead_site_visit lsv
          JOIN _site_visit_migration m ON m.new_visit_id = lsv.id
        """
    )
    null_phone, null_type = cr.fetchone()
    if null_phone:
        _logger.warning(
            "%s %s: verification — %d migrated row(s) have NULL inquiry_phone"
            " (lead had no phone on record; expected for some old leads)",
            __name__, version, null_phone,
        )
    else:
        _logger.info("%s %s: verification — inquiry_phone: 0 NULLs", __name__, version)

    if null_type:
        _logger.warning(
            "%s %s: verification — %d migrated row(s) have NULL inquiry_type"
            " (unexpected — review those records manually)",
            __name__, version, null_type,
        )
    else:
        _logger.info("%s %s: verification — inquiry_type: 0 NULLs", __name__, version)

    cr.execute("SELECT COUNT(*) FROM lead_site_visit")
    total_visits = cr.fetchone()[0]
    _logger.info(
        "%s %s: verification — total lead.site.visit rows in database: %d",
        __name__, version, total_visits,
    )

    _logger.info("=== %s %s: done ===", __name__, version)
