import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class LeadMigrationWizard(models.TransientModel):
    """
    Migration wizard with two operations:

    1. BACKFILL — For leads that have portal_property_id but property_id = NULL:
       looks up the matching property.base record and links it.

    2. STALE LINK CLEANUP — For leads where property_id points to a
       property.base record that was deleted at the DB level (bypassing Odoo's
       ORM cascade), causing "Record does not exist or has been deleted" warnings.
       Nullifies those dangling FK references so the list view stops warning.

    Design principles:
    - Non-destructive: never changes state, user_id, or process_notes.
    - Idempotent: safe to run multiple times.
    """

    _name = "lead.migration.wizard"
    _description = "Lead Property Backfill Migration"

    # --- Preview / backfill fields ---
    pending_count = fields.Integer(
        string="Leads Pending Backfill",
        readonly=True,
        help="Leads with a portal_property_id but no linked property_id.",
    )
    already_linked_count = fields.Integer(
        string="Already Linked",
        readonly=True,
        help="Leads that already have property_id set — will be skipped by backfill.",
    )

    # --- Stale-link fields ---
    stale_count = fields.Integer(
        string="Stale Property Links",
        readonly=True,
        help=(
            "Leads whose property_id points to a property.base record that no "
            "longer exists (deleted at DB level). These cause 'Record does not "
            "exist or has been deleted' warnings in the server log."
        ),
    )
    stale_cleaned_count = fields.Integer(string="Stale Links Cleared", readonly=True)

    # --- Result fields ---
    state = fields.Selection(
        [("preview", "Preview"), ("done", "Done")],
        default="preview",
        readonly=True,
    )
    matched_count = fields.Integer(string="Successfully Linked", readonly=True)
    unmatched_count = fields.Integer(string="Could Not Match", readonly=True)

    # --- Helpers ---

    def _get_stale_lead_ids(self):
        """
        Returns a list of leads.new IDs where property_base_id is set but the
        corresponding property.base record no longer exists.

        Uses raw SQL to detect phantom IDs, bypassing the ORM which would
        itself emit 'Record does not exist' warnings during the detection.
        """
        self.env.cr.execute(
            """
            SELECT ln.id
            FROM leads_new ln
            WHERE ln.property_base_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM property_base pb WHERE pb.id = ln.property_base_id
              )
            """,
        )
        return [row[0] for row in self.env.cr.fetchall()]

    # --- Default Get ---

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        pending = self.env["leads.new"].search_count(
            [
                ("portal_property_id", "!=", False),
                ("portal_property_id", "!=", ""),
                ("property_base_id", "=", False),
            ],
        )

        already_linked = self.env["leads.new"].search_count(
            [("property_base_id", "!=", False)],
        )

        stale_count = len(self._get_stale_lead_ids())

        res["pending_count"] = pending
        res["already_linked_count"] = already_linked
        res["stale_count"] = stale_count
        return res

    # --- Actions ---

    def action_run_migration(self):
        """
        Backfills property_id on all eligible leads.

        Eligible = portal_property_id is set AND property_id is False.
        Uses the existing _find_property() lookup (portal name → portal field map).
        """
        self.ensure_one()

        leads_to_migrate = self.env["leads.new"].search(
            [
                ("portal_property_id", "!=", False),
                ("portal_property_id", "!=", ""),
                ("property_base_id", "=", False),
            ],
        )

        total = len(leads_to_migrate)
        _logger.info(
            "MIGRATION: Starting property backfill for %d leads.",
            total,
        )

        matched = 0
        unmatched = 0

        for lead in leads_to_migrate:
            try:
                property_rec = lead._find_property()
                if property_rec:
                    # Write only property_base_id — leave state/user_id/process_notes untouched
                    lead.write({"property_base_id": property_rec.id})
                    matched += 1
                    _logger.info(
                        "MIGRATION: Lead %d linked to property %s.",
                        lead.id,
                        property_rec.property_tag,
                    )
                else:
                    unmatched += 1
                    _logger.warning(
                        "MIGRATION: Lead %d (%s / %s) — no matching property found.",
                        lead.id,
                        lead.portal_name,
                        lead.portal_property_id,
                    )
            except Exception as e:
                unmatched += 1
                _logger.error(
                    "MIGRATION: Error processing lead %d: %s",
                    lead.id,
                    e,
                    exc_info=True,
                )

        _logger.info(
            "MIGRATION: Complete. Matched: %d, Unmatched: %d.",
            matched,
            unmatched,
        )

        self.write(
            {
                "matched_count": matched,
                "unmatched_count": unmatched,
                "state": "done",
            },
        )

        # Re-open the wizard to show results
        return {
            "type": "ir.actions.act_window",
            "res_model": "lead.migration.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_cleanup_stale_links(self):
        """
        Nullifies property_id on leads where the linked property.base record
        was deleted at the DB level, causing 'Record does not exist or has been
        deleted' warnings (e.g. property.base(3250,)).

        This is safe — stored related fields (property_bhk, property_location,
        property_city, property_owner_name) already retain their last values
        because they are store=True computed fields. Clearing the FK stops
        Odoo from emitting the warning on every list view load.
        """
        self.ensure_one()
        stale_ids = self._get_stale_lead_ids()

        if not stale_ids:
            _logger.info("MIGRATION: No stale property links found.")
            self.write({"stale_cleaned_count": 0, "state": "done"})
        else:
            _logger.info(
                "MIGRATION: Clearing stale property_id on %d leads: %s",
                len(stale_ids),
                stale_ids,
            )
            # Use sudo to bypass any potential access checks on these broken records
            stale_leads = self.env["leads.new"].sudo().browse(stale_ids)
            stale_leads.write({"property_base_id": False})
            _logger.info(
                "MIGRATION: Cleared stale property_id from %d leads.",
                len(stale_ids),
            )
            self.write({"stale_cleaned_count": len(stale_ids), "state": "done"})

        return {
            "type": "ir.actions.act_window",
            "res_model": "lead.migration.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
