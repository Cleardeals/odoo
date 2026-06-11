import logging

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module : leads
# Model  : lead.reassignment.log
# Purpose: Immutable audit record — one row per bulk RM-reassignment operation
#          performed through the Bulk Reassign wizard. Lets managers trace a
#          mass transfer ("which leads moved, from whom, to whom, why, when")
#          and drill into the affected leads via lead_ids.
# Owner  : Cleardeals Tech
# ---------------------------------------------------------------------------


class LeadReassignmentLog(models.Model):
    _name = "lead.reassignment.log"
    _description = "Bulk Lead Reassignment Batch"
    _order = "reassign_date desc, id desc"

    name = fields.Char(
        string="Batch Reference",
        readonly=True,
        copy=False,
        index=True,
        help="Human-readable reference for this bulk reassignment batch.",
    )
    reassigned_by_id = fields.Many2one(
        "res.users",
        string="Reassigned By",
        readonly=True,
        default=lambda self: self.env.user,
        help="Manager who performed the bulk reassignment.",
    )
    reassign_date = fields.Datetime(
        string="Reassigned On",
        readonly=True,
        default=fields.Datetime.now,
    )
    new_rm_id = fields.Many2one(
        "res.users",
        string="New RM",
        readonly=True,
        help="The RM all selected leads were moved to.",
    )
    source_rm_summary = fields.Char(
        string="Previous RMs",
        readonly=True,
        help="Summary of the RMs the leads belonged to before the transfer, "
        "e.g. 'Naresh Rojiya (120), Mayuri Malivad (30)'.",
    )
    reason = fields.Text(
        string="Reason",
        readonly=True,
        required=True,
        help="Mandatory remark explaining why the leads were reassigned.",
    )
    lead_count = fields.Integer(string="Leads Moved", readonly=True)
    site_visits_moved = fields.Integer(string="Site Visits Moved", readonly=True)
    bde_reassigned_count = fields.Integer(
        string="BDE Re-assigned",
        readonly=True,
        help="OPS-sale leads whose BDE was swapped because the new RM was not "
        "authorised for the previous BDE.",
    )
    failed_count = fields.Integer(string="Could Not Move (BDE)", readonly=True)
    lead_ids = fields.One2many(
        "leads.new",
        "last_reassignment_batch_id",
        string="Affected Leads",
        readonly=True,
    )
    failed_lead_ids = fields.Many2many(
        "leads.new",
        "lead_reassignment_log_failed_rel",
        string="Leads Needing Attention",
        readonly=True,
        help="OPS-sale leads left with their current RM because the new RM is "
        "not authorised for any BDE — surfaced here for management review.",
    )

    # ------------------------------------------------------------------
    # Append-only: a batch log is a historical record and must never be
    # edited or deleted after creation (mirrors the convention used by the
    # other audit-style models in this module).
    # ------------------------------------------------------------------

    def write(self, vals):
        raise UserError(
            "Reassignment logs are an immutable audit trail and cannot be edited."
        )

    def unlink(self):
        raise UserError(
            "Reassignment logs are an immutable audit trail and cannot be deleted."
        )
