import logging

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module : leads
# Model  : lead.bulk.reassign.wizard
# Purpose: Manager-only tool to move many leads (leads.new) from their current
#          RM(s) to a single new RM in one operation, with a mandatory reason.
#          Records the operation in lead.reassignment.log and cascades the new
#          RM onto every site visit of each moved lead.
#
# Entry point: the manager-only "Bulk Reassign RM" header button on the
#          leads.new list (calls leads.new.action_open_bulk_reassign). The web
#          client resolves the user's selection (manual tick or "select all
#          matching") into context['active_ids'], so default_get reads it directly.
# Owner  : Cleardeals Tech
# ---------------------------------------------------------------------------

# Hard cap on how many leads one operation may move. Configurable via the
# ir.config_parameter key below; this constant is the fallback default.
_DEFAULT_MAX = 1000
_MAX_PARAM_KEY = "leads.bulk_reassign_max"

# How many leads to process per transaction before committing — keeps large
# operations within cursor/memory limits (mirrors lead_migration_wizard).
_BATCH_SIZE = 100

# Number of source RMs to spell out in the summary before collapsing the rest.
_SUMMARY_LIMIT = 6


class LeadBulkReassignWizard(models.TransientModel):
    _name = "lead.bulk.reassign.wizard"
    _description = "Bulk Lead Reassignment Wizard"

    lead_ids = fields.Many2many(
        "leads.new",
        string="Leads to Reassign",
        help="The leads selected in the list view.",
    )
    lead_count = fields.Integer(string="Selected Leads", readonly=True)
    over_limit = fields.Boolean(readonly=True)
    max_leads = fields.Integer(readonly=True)
    source_rm_summary = fields.Char(string="Current RMs", readonly=True)
    source_rm_html = fields.Html(
        string="Currently assigned to",
        readonly=True,
        sanitize=False,
        help="Current owners of the selected leads, shown as badges.",
    )

    new_rm_id = fields.Many2one(
        "res.users",
        string="New RM",
        help="All selected leads (and their site visits) will be moved to this RM.",
    )
    reason = fields.Text(
        string="Reason",
        help="Mandatory remark — recorded on every lead and in the audit log.",
    )
    cascade_site_visits = fields.Boolean(
        string="Also move site visits",
        default=True,
        help="Move every site visit of the selected leads to the new RM so the "
        "new RM can see the full visit history. BDE links are left unchanged.",
    )

    state = fields.Selection(
        [("preview", "Preview"), ("done", "Done")],
        default="preview",
        readonly=True,
    )
    reassigned_count = fields.Integer(string="Leads Moved", readonly=True)
    skipped_count = fields.Integer(string="Already on New RM", readonly=True)
    site_visits_moved_count = fields.Integer(string="Site Visits Moved", readonly=True)
    batch_id = fields.Many2one("lead.reassignment.log", readonly=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @api.model
    def _get_max_leads(self):
        raw = self.env["ir.config_parameter"].sudo().get_param(
            _MAX_PARAM_KEY, _DEFAULT_MAX
        )
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = _DEFAULT_MAX
        return value if value > 0 else _DEFAULT_MAX

    @api.model
    def _build_source_summary(self, leads):
        """Return 'Naresh (120), Mayuri (30)' style summary of current owners."""
        counts = {}
        for lead in leads:
            label = lead.user_id.name or "Unassigned"
            counts[label] = counts.get(label, 0) + 1
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        shown = ordered[:_SUMMARY_LIMIT]
        parts = [f"{name} ({n})" for name, n in shown]
        remaining = len(ordered) - len(shown)
        if remaining > 0:
            parts.append(f"+{remaining} more")
        return ", ".join(parts)

    @api.model
    def _build_source_html(self, leads):
        """Render the current owners as Bootstrap pill badges (name + count)."""
        counts = {}
        for lead in leads:
            label = lead.user_id.name or "Unassigned"
            counts[label] = counts.get(label, 0) + 1
        if not counts:
            return Markup("<span class='text-muted'>No leads selected.</span>")
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        shown = ordered[:_SUMMARY_LIMIT]
        chips = Markup("")
        for name, n in shown:
            chips += Markup(
                "<span class='badge rounded-pill text-bg-light border me-1 mb-1' "
                "style='font-weight:500;'>{name} "
                "<span class='badge rounded-pill text-bg-secondary ms-1'>{n}</span>"
                "</span>"
            ).format(name=html_escape(name), n=n)
        remaining = len(ordered) - len(shown)
        if remaining > 0:
            chips += Markup(
                "<span class='badge rounded-pill text-bg-light text-muted border mb-1'>"
                "+{n} more</span>"
            ).format(n=remaining)
        return Markup("<div class='d-flex flex-wrap'>") + chips + Markup("</div>")

    # ------------------------------------------------------------------
    # Default get — resolve the list-view selection
    # ------------------------------------------------------------------

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        ctx = self.env.context
        lead_ids = []
        if ctx.get("active_model") == "leads.new":
            # The web client resolves "select all matching" into active_ids
            # (capped at active_ids_limit), so active_ids is authoritative.
            lead_ids = list(ctx.get("active_ids") or [])
            if not lead_ids and ctx.get("active_domain"):
                lead_ids = self.env["leads.new"].search(ctx["active_domain"]).ids

        leads = self.env["leads.new"].browse(lead_ids).exists()
        max_leads = self._get_max_leads()

        res["lead_ids"] = [(6, 0, leads.ids)]
        res["lead_count"] = len(leads)
        res["max_leads"] = max_leads
        res["over_limit"] = len(leads) > max_leads
        res["source_rm_summary"] = self._build_source_summary(leads)
        res["source_rm_html"] = self._build_source_html(leads)
        return res

    # ------------------------------------------------------------------
    # Open helper (used by the bound server action)
    # ------------------------------------------------------------------

    def action_open(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Bulk Reassign RM",
            "res_model": "lead.bulk.reassign.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    # ------------------------------------------------------------------
    # Confirm
    # ------------------------------------------------------------------

    def action_confirm_reassign(self):
        self.ensure_one()

        if not self.new_rm_id:
            raise UserError("Please choose the RM to reassign these leads to.")
        if not (self.reason and self.reason.strip()):
            raise UserError("A reason is required to reassign leads.")

        max_leads = self._get_max_leads()
        if self.lead_count > max_leads:
            raise UserError(
                f"You selected {self.lead_count} leads, but at most {max_leads} "
                f"can be reassigned in a single operation. Narrow your filter and "
                f"try again."
            )

        # Only move leads not already owned by the target RM.
        leads_to_move = self.lead_ids.filtered(
            lambda lead: lead.user_id.id != self.new_rm_id.id
        )
        skipped = len(self.lead_ids) - len(leads_to_move)

        if not leads_to_move:
            raise UserError(
                f"All {len(self.lead_ids)} selected leads already belong to "
                f"{self.new_rm_id.name}. Nothing to do."
            )

        # Count site visits up front so the (immutable) log can be created once
        # with final figures.
        site_visits = self.env["lead.site.visit"]
        if self.cascade_site_visits:
            site_visits = self.env["lead.site.visit"].search(
                [("inquiry_id", "in", leads_to_move.ids)]
            )

        reassign_date = fields.Datetime.now()
        batch = self.env["lead.reassignment.log"].create(
            {
                "name": "RB/" + fields.Datetime.now().strftime("%Y%m%d/%H%M%S"),
                "reassigned_by_id": self.env.user.id,
                "reassign_date": reassign_date,
                "new_rm_id": self.new_rm_id.id,
                "source_rm_summary": self._build_source_summary(leads_to_move),
                "reason": self.reason.strip(),
                "lead_count": len(leads_to_move),
                "site_visits_moved": len(site_visits),
            }
        )

        note_line = (
            f"\n[{reassign_date}] Bulk reassigned to {self.new_rm_id.name} "
            f"by {self.env.user.name} [batch {batch.name}]: {self.reason.strip()}\n"
        )

        # Process in one transaction so the operation is atomic — either every
        # lead (and the log's counts) is consistent, or nothing changes. The
        # 1000-lead cap keeps a single transaction comfortably bounded. Leads
        # are still iterated in chunks to bound the in-memory recordset.
        lead_ids = leads_to_move.ids
        total = len(lead_ids)
        for start in range(0, total, _BATCH_SIZE):
            chunk_ids = lead_ids[start : start + _BATCH_SIZE]
            for lead in self.env["leads.new"].browse(chunk_ids):
                lead.write(
                    {
                        "user_id": self.new_rm_id.id,
                        "last_reassignment_batch_id": batch.id,
                        "process_notes": (lead.process_notes or "") + note_line,
                    }
                )
            if self.cascade_site_visits:
                self.env["lead.site.visit"].search(
                    [("inquiry_id", "in", chunk_ids)]
                ).write({"assigned_rm_id": self.new_rm_id.id})

        _logger.info(
            "BULK REASSIGN [%s]: %d leads moved to %s by %s",
            batch.name,
            total,
            self.new_rm_id.name,
            self.env.user.name,
        )

        self.write(
            {
                "state": "done",
                "reassigned_count": total,
                "skipped_count": skipped,
                "site_visits_moved_count": len(site_visits),
                "batch_id": batch.id,
            }
        )
        return self.action_open()

    def action_view_batch(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Reassignment Batch",
            "res_model": "lead.reassignment.log",
            "res_id": self.batch_id.id,
            "view_mode": "form",
            "target": "current",
        }
