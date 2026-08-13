"""Lead status gate — a lead cannot leave "Lead" until someone has messaged.

The problem this solves is a reporting one.  ``current_status`` on ``leads.new``
is writable at every layer — no readonly, no transition guard, no server-side
check — so an inquiry can be marked "Requirement Closed" or "Busy" by someone who
never contacted the buyer at all.  That became urgent when clearing the backlog
of inquiries still parked at "Lead" was handed to an operator who is *meant* to
WhatsApp each buyer first, with no way to verify that they did.

The rule
--------
Only the transition **out of** ``lead`` is gated, and only for RMs::

    lead ──(needs an outbound WhatsApp attempt)──> anything else
    anything else ─────────(unrestricted)────────> anything else

Restricting one transition is what makes this safe to switch on for the whole
history: the only inquiries affected are the ones still sitting at ``lead``,
which is exactly the population in question.  Every inquiry that has already
moved on keeps working normally.

What counts as an attempt
-------------------------
Any outbound ``wa.message`` on **that inquiry** — including ``queued``,
``failed`` and ``meta_blocked``.  The bar is deliberately "attempted", not
"delivered": Meta blocks messages and templates get rejected for reasons the RM
cannot control, and they did their part either way.

Why there is no bypass
----------------------
There is no context flag that skips this check, because a flag that exists to be
set is a flag that gets set.  In particular ``lead.site.visit`` syncing its
status back onto the inquiry is **not** exempt — the details have to go out
before a visit can be scheduled.  Note that sync arrives via ``sudo()``, which
raises the superuser flag but leaves ``env.user`` as the RM, so the gate still
sees them.

The system paths keep working without needing an exemption, because the gate
keys on **group membership**: the Pub/Sub push controller runs as the public
user and the crons as OdooBot, and neither is in the Leads RM group.  Managers
are exempt for the same reason — they own corrections and data cleanup.
"""

import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# The one status the gate guards the exit from.
_GATED_STATUS = 'lead'

_RM_GROUP = 'leads.group_lead_score_rm'
_MANAGER_GROUP = 'leads.group_lead_score_manager'


class WaLeadStatusGate(models.Model):
    """Gates ``leads.new.current_status`` on a WhatsApp send having happened."""

    _inherit = 'leads.new'

    wa_status_change_allowed = fields.Boolean(
        string='Status Change Allowed',
        compute='_compute_wa_status_change_allowed',
        compute_sudo=True,
        help="Whether the current user may move this inquiry off 'Lead'.  "
             "Drives the readonly state of the status field; the real "
             "enforcement is the write() guard.",
    )

    # ------------------------------------------------------------------
    # Gate
    # ------------------------------------------------------------------

    def _wa_user_is_gated(self) -> bool:
        """Is the acting user subject to the gate?

        True only for a Leads RM who is not also a Leads Manager.  Everyone
        else — managers, OdooBot on a cron, the public user handling a Pub/Sub
        push, an administrator — passes straight through.  This is what lets the
        gate have no bypass flag while leaving the automated paths alone.
        """
        user = self.env.user
        # No acting user at all.  The Pub/Sub push route is auth='none', so
        # env.uid is None and env.user is an EMPTY res.users recordset —
        # has_group() calls ensure_one() and would raise "Expected singleton:
        # res.users()", taking down the whole event handler.  That is not a
        # theoretical edge: it is the exact path the automatic "details shared"
        # status update runs on, so this gate crashed the feature it was meant
        # to leave alone.  No user means no RM to gate.
        if not user or not user.id:
            return False
        return (
            user.has_group(_RM_GROUP)
            and not user.has_group(_MANAGER_GROUP)
        )

    def _wa_has_send_attempt(self) -> bool:
        """Has anyone attempted an outbound WhatsApp message on this inquiry?

        Matched on ``effective_inquiry_id`` rather than the raw ``lead_id``:
        that field resolves through the conversation segment, so when an RM
        re-points a span of a thread to the inquiry it was really about, the
        attempt follows it to the right inquiry.

        Deliberately inquiry-scoped and never phone-scoped.  One phone number
        legitimately carries several inquiries (the same buyer asking about
        three properties), and crediting one message across all of them would
        let a single send unlock every inquiry that buyer has.

        Message status is not filtered — see the module docstring.
        """
        self.ensure_one()
        return bool(self.env['wa.message'].sudo().search_count([
            ('direction', '=', 'outbound'),
            ('effective_inquiry_id', '=', self.id),
        ]))

    @api.depends('current_status')
    def _compute_wa_status_change_allowed(self):
        """Allowed unless the gate would actually bite.

        Not dependent on ``wa.message`` rows: outbound messages are written by
        the Pub/Sub push path in a different transaction, so the ORM dependency
        graph would never see them anyway.  The field recomputes when the view
        reloads, which is when the RM needs it to be right.

        Batched into one ``read_group`` rather than a ``search_count`` per
        record — this field renders in the list view, where the per-record form
        would fire one query per row.
        """
        gated_user = self._wa_user_is_gated()
        if not gated_user:
            self.wa_status_change_allowed = True
            return

        pending = self.filtered(lambda r: r.current_status == _GATED_STATUS)
        (self - pending).wa_status_change_allowed = True
        if not pending:
            return

        groups = self.env['wa.message'].sudo()._read_group(
            [('direction', '=', 'outbound'),
             ('effective_inquiry_id', 'in', pending.ids)],
            groupby=['effective_inquiry_id'],
        )
        attempted = {inquiry.id for (inquiry,) in groups}
        for rec in pending:
            rec.wa_status_change_allowed = rec.id in attempted

    def write(self, vals):
        new_status = vals.get('current_status')
        # Only the exit from 'lead' is gated, and only for RMs.
        if (
            new_status
            and new_status != _GATED_STATUS
            and self._wa_user_is_gated()
        ):
            for rec in self:
                if rec.current_status != _GATED_STATUS:
                    # Already moved on — every later change is unrestricted.
                    continue
                if rec._wa_has_send_attempt():
                    continue
                _logger.info(
                    "wa_status_gate: refused %s → %r on lead %s (%s) for uid %s "
                    "— no outbound WhatsApp message on this inquiry",
                    _GATED_STATUS, new_status, rec.id, rec.name, self.env.uid,
                )
                raise UserError(
                    "You haven't messaged this buyer yet.\n\n"
                    "Send the property details from the WhatsApp Activity tab "
                    "on this inquiry, then change the status.\n\n"
                    "(A message that failed or was blocked still counts — the "
                    "attempt is what matters.)"
                )
        return super().write(vals)
