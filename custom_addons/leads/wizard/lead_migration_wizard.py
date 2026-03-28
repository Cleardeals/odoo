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
    recomputed_count = fields.Integer(string="Fields Recomputed", readonly=True)

    # count of leads that have property_base_id but empty stored related fields
    stale_fields_count = fields.Integer(
        string="Leads With Missing Stored Fields",
        readonly=True,
        help="Leads linked to a property.base but whose stored fields (BHK, location, city etc.) are blank — usually from a raw SQL update that bypassed the ORM.",
    )

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

        # Count leads linked via SQL that have empty stored related fields
        stale_fields_count = self.env["leads.new"].search_count(
            [
                ("property_base_id", "!=", False),
                ("base_property_city", "=", False),
            ]
        )

        res["pending_count"] = pending
        res["already_linked_count"] = already_linked
        res["stale_count"] = stale_count
        res["stale_fields_count"] = stale_fields_count
        return res

    # --- Actions ---

    def action_run_migration(self):
        """
        Backfills property_id on all eligible leads.

        Eligible = portal_property_id is set AND property_id is False.
        Uses the existing _find_property() lookup (source portal code + listing ID).
        Processes in batches of 100 and commits after each batch to avoid
        cursor timeouts on large datasets.
        """
        self.ensure_one()

        # Fetch IDs only — avoids holding a huge recordset open across commits
        lead_ids = (
            self.env["leads.new"]
            .search(
                [
                    ("portal_property_id", "!=", False),
                    ("portal_property_id", "!=", ""),
                    ("property_base_id", "=", False),
                ],
            )
            .ids
        )

        total = len(lead_ids)
        _logger.info(
            "MIGRATION: Starting property backfill for %d leads.",
            total,
        )

        matched = 0
        unmatched = 0
        BATCH_SIZE = 100

        for batch_start in range(0, total, BATCH_SIZE):
            batch_ids = lead_ids[batch_start : batch_start + BATCH_SIZE]
            leads_batch = self.env["leads.new"].browse(batch_ids)

            for lead in leads_batch:
                try:
                    property_rec = lead._find_property()
                    if property_rec:
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
                            lead.source_id.name,
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

            # Commit after each batch to release the transaction and prevent
            # cursor timeouts on large datasets
            self.env.cr.commit()
            _logger.info(
                "MIGRATION: Progress %d/%d (matched: %d, unmatched: %d)",
                min(batch_start + BATCH_SIZE, total),
                total,
                matched,
                unmatched,
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

    def action_recompute_stored_fields(self):
        """
        Force-recomputes all stored related fields sourced from property_base_id
        on leads that were linked via raw SQL (bypassing the ORM).

        Processes in batches of 200 with a commit after each batch to avoid
        memory and cursor timeout issues.
        """
        self.ensure_one()

        lead_ids = (
            self.env["leads.new"]
            .search(
                [
                    ("property_base_id", "!=", False),
                    ("base_property_city", "=", False),
                ]
            )
            .ids
        )

        total = len(lead_ids)
        _logger.info("MIGRATION: Recomputing stored fields for %d leads.", total)

        BATCH_SIZE = 200
        STORED_FIELDS = [
            "base_property_bhk",
            "base_property_location",
            "base_property_city",
            "base_property_owner_name",
            "base_property_link",
            "all_associated_properties",
        ]

        for batch_start in range(0, total, BATCH_SIZE):
            batch = self.env["leads.new"].browse(
                lead_ids[batch_start : batch_start + BATCH_SIZE]
            )
            # Notify ORM that property_base_id changed so it schedules recompute
            batch.modified(["property_base_id"])
            # Flush pending recomputes for just these fields
            self.env["leads.new"]._recompute_model(fnames=STORED_FIELDS)
            self.env.cr.commit()
            _logger.info(
                "MIGRATION: Recomputed %d/%d",
                min(batch_start + BATCH_SIZE, total),
                total,
            )

        _logger.info("MIGRATION: Stored field recompute complete for %d leads.", total)
        self.write({"recomputed_count": total, "state": "done"})

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
