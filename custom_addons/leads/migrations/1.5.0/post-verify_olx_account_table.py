import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """
    Guard migration for the leads 1.5.0 release (OLX Account Integration).

    Context:
        A new model `lead.olx.account` (table: lead_olx_account) is introduced
        in this release. The table is created entirely by the ORM on fresh installs
        and upgrades alike — no SQL DDL is needed here.

        Passwords for each account are stored in ir.config_parameter, not in the
        lead_olx_account table. No column migration is needed.

        This post-migration script verifies the table exists and logs the row count
        so that the deployment log provides a clear audit trail.

    Idempotency:
        Safe to re-run. The SELECT is read-only and has no side effects.

    Assumptions:
        - The ORM has already created the lead_olx_account table before post
          scripts run. If the table is absent, a clear error is logged.
    """
    _logger.info("=== %s %s: starting ===", __name__, version)

    cr.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = 'lead_olx_account'
        )
        """
    )
    table_exists = cr.fetchone()[0]

    if not table_exists:
        _logger.error(
            "%s %s: lead_olx_account table does not exist — "
            "ORM may not have run yet. Check upgrade logs.",
            __name__,
            version,
        )
        return

    cr.execute("SELECT COUNT(*) FROM lead_olx_account")
    row_count = cr.fetchone()[0]
    _logger.info(
        "%s %s: lead_olx_account table present with %d rows.",
        __name__,
        version,
        row_count,
    )

    _logger.info("=== %s %s: done ===", __name__, version)
