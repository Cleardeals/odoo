import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """
    Backfill `leads_new.is_auto_created` for the leads 1.8.0 release.

    Context:
        `is_auto_created` distinguishes leads the system ingested (portal
        webhooks, the Housing/OLX crons) from leads a human created (the lead
        form, the Recommend Property wizard, the CSV import, WhatsApp inbox
        triage).  Going forward it is set in `leads.new.create()` from the
        creation context.  Rows that predate this release have no such context
        to recover, so they are classified from the data itself.

        The discriminator is `source_type = 'portal' AND portal_property_id`
        being non-empty.  `source_type` alone is not enough: RMs routinely
        hand-enter leads they found on MagicBricks or 99acres, which gives a
        manual lead a portal source.  `portal_property_id` is the portal's own
        listing identifier and is only ever written by the ingestion paths —
        an RM typing a lead into the form never fills it.  The pair is
        therefore a far better proxy than either field alone.

        The ORM creates the column (defaulting every row to FALSE) before this
        script runs, so this only needs to flip the auto-created rows to TRUE.

    Consequences:
        None at runtime.  The only consumer that gates on this flag is the
        WhatsApp initial-nudge publisher, which fires from `create()` — no
        historical lead can be re-triggered whichever way it is classified
        here.  The backfill exists so that later analytics and any future
        auto-vs-manual reporting see a sane history.

    Idempotency:
        Safe to re-run.  The UPDATE is a pure function of columns this script
        does not modify, so a second run rewrites the same values.
    """
    _logger.info("=== %s %s: starting ===", __name__, version)

    cr.execute(
        """
        SELECT COUNT(*) FROM information_schema.columns
         WHERE table_name = 'leads_new' AND column_name = 'is_auto_created'
        """
    )
    if not cr.fetchone()[0]:
        _logger.error(
            "leads_new.is_auto_created is absent — the ORM should have created "
            "it before post scripts run.  Backfill skipped."
        )
        return

    cr.execute(
        """
        UPDATE leads_new
           SET is_auto_created = TRUE
         WHERE source_type = 'portal'
           AND portal_property_id IS NOT NULL
           AND btrim(portal_property_id) != ''
           AND is_auto_created IS DISTINCT FROM TRUE
        """
    )
    flipped = cr.rowcount

    cr.execute(
        "SELECT COUNT(*) FILTER (WHERE is_auto_created), COUNT(*) FROM leads_new"
    )
    auto, total = cr.fetchone()
    _logger.info(
        "=== %s %s: done — %s rows flipped; %s of %s leads now auto-created ===",
        __name__, version, flipped, auto, total,
    )
