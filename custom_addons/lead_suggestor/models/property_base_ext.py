import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PropertyBaseLeadSuggestor(models.Model):
    """
    Extends property.base (defined in the `properties` module) with the
    lead-suggestor-specific fields.

    Kept in lead_suggestor so the base model stays clean and the dependency
    flows one-way: lead_suggestor → properties, never the reverse.
    """

    _inherit = "property.base"

    # -------------------------------------------------------------------------
    # Suggestion relationship — inverse side of property_base_id on
    # property.lead.suggestion
    # -------------------------------------------------------------------------

    suggestion_ids = fields.One2many(
        "property.lead.suggestion",
        "property_base_id",
        string="Suggested Leads",
    )

    suggestion_count = fields.Integer(
        string="Total Suggestions",
        compute="_compute_suggestion_counts",
        store=True,
    )
    new_suggestion_count = fields.Integer(
        string="New Suggestions",
        compute="_compute_suggestion_counts",
        store=True,
    )

    @api.depends("suggestion_ids", "suggestion_ids.status")
    def _compute_suggestion_counts(self):
        """Counts total and new (status='new') suggestions for each property."""
        for prop in self:
            prop.suggestion_count = len(prop.suggestion_ids)
            prop.new_suggestion_count = len(
                prop.suggestion_ids.filtered(lambda s: s.status == "new"),
            )

    # -------------------------------------------------------------------------
    # One-time migration action — manager-only button in the UI
    # -------------------------------------------------------------------------

    def action_backfill_suggestions(self):
        """
        Back-fill property_base_id on every property.lead.suggestion row that
        still has property_tag set but no property_base_id, then refresh the
        stored suggestion counts for all property.base records.

        Matching key: suggestion.property_tag == property_base.property_tag

        Safe to call repeatedly — only NULL property_base_id rows are updated.
        Shows a summary notification when done.
        """
        cr = self.env.cr

        # Step 1 — backfill FK
        cr.execute(
            """
            UPDATE property_lead_suggestion pls
               SET property_base_id = pb.id
              FROM property_base pb
             WHERE pb.property_tag = pls.property_tag
               AND pls.property_tag IS NOT NULL
               AND pls.property_tag != ''
               AND pls.property_base_id IS NULL
            """
        )
        backfilled = cr.rowcount
        _logger.info("Backfilled property_base_id on %d suggestion rows.", backfilled)

        # Step 2 — refresh stored counts
        cr.execute(
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
            """
        )
        _logger.info("Refreshed suggestion counts on all property.base records.")

        # Bust the ORM field cache so updated values are visible immediately
        self.env["property.base"].invalidate_model(
            ["suggestion_count", "new_suggestion_count"]
        )

        # Step 3 — count still-unmatched rows for user feedback
        cr.execute(
            """
            SELECT COUNT(*)
              FROM property_lead_suggestion
             WHERE property_base_id IS NULL
            """
        )
        unmatched = cr.fetchone()[0]

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Suggestion Migration Complete",
                "message": (
                    f"Linked {backfilled} suggestion rows to property.base. "
                    f"{unmatched} rows could not be matched (no property_tag match)."
                ),
                "type": "success" if unmatched == 0 else "warning",
                "sticky": True,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
