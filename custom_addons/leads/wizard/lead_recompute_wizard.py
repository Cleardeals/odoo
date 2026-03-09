import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

BATCH_SIZE = 200
STORED_FIELDS = [
    "base_property_bhk",
    "base_property_location",
    "base_property_city",
    "base_property_owner_name",
    "base_property_link",
    "all_associated_properties",
]


class LeadRecomputeWizard(models.TransientModel):
    """
    Recomputes stored related fields (BHK, location, city, owner, link) on
    leads.new records where property_base_id is set but the stored fields are
    blank — typically caused by a raw SQL update that bypassed the ORM.

    Processes in batches of 200 and commits after each batch to avoid
    cursor timeouts.
    """

    _name = "lead.recompute.wizard"
    _description = "Recompute Lead Stored Property Fields"

    affected_count = fields.Integer(
        string="Leads Needing Recompute",
        readonly=True,
        help="Leads that have property_base_id set but base_property_city is blank.",
    )
    recomputed_count = fields.Integer(string="Fields Recomputed", readonly=True)
    state = fields.Selection(
        [("preview", "Preview"), ("done", "Done")],
        default="preview",
        readonly=True,
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        res["affected_count"] = self.env["leads.new"].search_count(
            [
                ("property_base_id", "!=", False),
                ("base_property_city", "=", False),
            ],
        )
        return res

    def action_recompute(self):
        self.ensure_one()

        lead_ids = (
            self.env["leads.new"]
            .search(
                [
                    ("property_base_id", "!=", False),
                    ("base_property_city", "=", False),
                ],
            )
            .ids
        )

        total = len(lead_ids)
        _logger.info("RECOMPUTE: Starting stored field recompute for %d leads.", total)

        for batch_start in range(0, total, BATCH_SIZE):
            batch = self.env["leads.new"].browse(
                lead_ids[batch_start : batch_start + BATCH_SIZE],
            )
            batch.modified(["property_base_id"])
            self.env["leads.new"]._recompute_model(fnames=STORED_FIELDS)
            self.env.cr.commit()
            _logger.info(
                "RECOMPUTE: %d/%d done.",
                min(batch_start + BATCH_SIZE, total),
                total,
            )

        _logger.info("RECOMPUTE: Complete for %d leads.", total)
        self.write({"recomputed_count": total, "state": "done"})

        return {
            "type": "ir.actions.act_window",
            "res_model": "lead.recompute.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
