import logging

from . import models, wizards

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """
    On first install: back-fill property_base_id on any pre-existing
    property.lead.suggestion rows and refresh stored counts.

    Matching key: suggestion.property_tag == property_base.property_tag
    Safe to call multiple times — only NULL rows are updated.
    """
    _logger.info(
        "lead_suggestor post_init_hook: backfilling property_base_id on suggestions...",
    )
    env.cr.execute(
        """
        UPDATE property_lead_suggestion pls
           SET property_base_id = pb.id
          FROM property_base pb
         WHERE pb.property_tag = pls.property_tag
           AND pls.property_tag IS NOT NULL
           AND pls.property_tag != ''
           AND pls.property_base_id IS NULL
        """,
    )
    migrated = env.cr.rowcount
    _logger.info("Backfilled property_base_id on %d suggestion rows.", migrated)

    env.cr.execute(
        """
        UPDATE property_base pb
           SET suggestion_count = (
               SELECT COUNT(*)
                 FROM property_lead_suggestion pls
                WHERE pls.property_base_id = pb.id
           ),
           new_suggestion_count = (
               SELECT COUNT(*)
                 FROM property_lead_suggestion pls
                WHERE pls.property_base_id = pb.id
                  AND pls.status = 'new'
           )
        """,
    )
    _logger.info("Refreshed suggestion counts on all property.base records.")
    env["property.base"].invalidate_model(["suggestion_count", "new_suggestion_count"])

    env.cr.execute(
        """
        UPDATE property_lead_suggestion pls
           SET property_base_id = pb.id
          FROM property_base pb
         WHERE pb.property_tag = pls.property_tag
           AND pls.property_tag IS NOT NULL
           AND pls.property_tag != ''
           AND pls.property_base_id IS NULL
        """,
    )
    migrated = env.cr.rowcount
    _logger.info(
        "Backfilled property_base_id on %d suggestion rows.",
        migrated,
    )

    # Recompute stored suggestion_count / new_suggestion_count directly in SQL
    # so we don't have to iterate over 1200+ property.base records via ORM.
    env.cr.execute(
        """
        UPDATE property_base pb
           SET suggestion_count = (
               SELECT COUNT(*)
                 FROM property_lead_suggestion pls
                WHERE pls.property_base_id = pb.id
           ),
           new_suggestion_count = (
               SELECT COUNT(*)
                 FROM property_lead_suggestion pls
                WHERE pls.property_base_id = pb.id
                  AND pls.status = 'new'
           )
        """,
    )
    _logger.info("Updated suggestion counts on all property.base records.")
    # Invalidate the ORM cache for the affected computed fields so the
    # updated DB values are used without a stale-cache hit.
    env["property.base"].invalidate_model(["suggestion_count", "new_suggestion_count"])
