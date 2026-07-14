"""
Disable the legacy 3-hourly polling cron on already-installed databases.

``data/property_cron.xml`` is ``noupdate="1"``, so adding ``active=False`` to the
cron record there only affects fresh installs — on an upgrade the existing
``ir.cron`` row keeps its current (active) value.  This idempotent post-migration
deactivates it directly.

Property ingestion now happens via the inbound webhooks
(/api/v1/properties/webhook/{create,update}); the cron remains in place but
inactive so it can still be triggered manually for backfill / reconciliation.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        UPDATE ir_cron
           SET active = FALSE
         WHERE id IN (
             SELECT res_id
               FROM ir_model_data
              WHERE module = 'properties'
                AND name = 'ir_cron_sync_properties_from_api'
         )
           AND active = TRUE
        """,
    )
    if cr.rowcount:
        _logger.info(
            "properties 19.0.1.4.0: disabled legacy polling cron "
            "(ir_cron_sync_properties_from_api).",
        )
