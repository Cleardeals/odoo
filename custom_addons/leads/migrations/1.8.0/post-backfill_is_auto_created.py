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

        The discriminator is a portal source AND a non-empty
        `portal_property_id`.  Source type alone is not enough: RMs routinely
        hand-enter leads they found on MagicBricks or 99acres, which gives a
        manual lead a portal source.  `portal_property_id` is the portal's own
        listing identifier and is only ever written by the ingestion paths —
        an RM typing a lead into the form never fills it.  The pair is
        therefore a far better proxy than either field alone.

        Source type is read by JOINing `lead_source`, NOT from the stored
        `leads_new.source_type` column.  That column is a stored related field
        and is stale on historical rows — on staging, 58,696 leads whose source
        is demonstrably 'portal' in `lead_source` carry NULL there, every one of
        them created on or before 2026-04-12.  Reading the denormalised copy
        silently under-classified nearly half the table.

        The ORM creates the column before this script runs, but leaves existing
        rows NULL rather than FALSE, so this normalises the negatives too — an
        analyst filtering `WHERE NOT is_auto_created` would otherwise silently
        drop every historical lead.

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
        UPDATE leads_new l
           SET is_auto_created = TRUE
          FROM lead_source s
         WHERE s.id = l.source_id
           AND s.source_type = 'portal'
           AND l.portal_property_id IS NOT NULL
           AND btrim(l.portal_property_id) != ''
           AND l.is_auto_created IS DISTINCT FROM TRUE
        """
    )
    flipped = cr.rowcount

    # Normalise the negatives: the ORM leaves pre-existing rows NULL, and NULL
    # is not FALSE to anything querying this in SQL.
    cr.execute(
        "UPDATE leads_new SET is_auto_created = FALSE WHERE is_auto_created IS NULL"
    )
    normalised = cr.rowcount

    cr.execute(
        "SELECT COUNT(*) FILTER (WHERE is_auto_created), COUNT(*) FROM leads_new"
    )
    auto, total = cr.fetchone()
    _logger.info(
        "=== %s %s: done — %s rows flipped, %s NULLs normalised; "
        "%s of %s leads now auto-created ===",
        __name__, version, flipped, normalised, auto, total,
    )
