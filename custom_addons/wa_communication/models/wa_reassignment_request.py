"""WhatsApp chat reassignment requests.

When an RM wants to reply on a chat owned by another RM, they raise a request.
The **current assignee** (or a manager) approves it; on approval Odoo asks the
wa-platform to reassign the chat in Interakt and update ``rm_assignments``.
Ownership only flips in Odoo once the platform sends back an
``assignment_confirmed`` event (handled in ``wa.conversation``).

State machine::

    pending ──approve──▶ confirming ──(assignment_confirmed ok)──▶ approved
        │                    │
        │                    ├──(assignment_confirmed fail)──▶ failed
        │                    └──(no confirmation in N min)────▶ failed
        ├──decline──▶ declined
        └──cancel───▶ cancelled

``confirming`` is the only state whose exit depends on an inbound event rather
than a user action, so it is the only one that can strand.  The sweeper cron
``_cron_release_stuck_confirming`` bounds that: see
``data/wa_reassignment_cron.xml``.
"""

import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class WaReassignmentRequest(models.Model):
    _name = 'wa.reassignment.request'
    _description = 'WhatsApp Chat Reassignment Request'
    _order = 'create_date desc'

    conversation_id = fields.Many2one(
        'wa.conversation', string='Conversation',
        required=True, ondelete='cascade', index=True,
    )
    requester_id = fields.Many2one(
        'res.users', string='Requested By',
        required=True, ondelete='cascade', index=True,
    )
    current_assignee_id = fields.Many2one(
        'res.users', string='Current Assignee', ondelete='set null',
        help="The RM who owned the chat when the request was raised; they "
             "approve or decline the handover.",
    )
    state = fields.Selection(
        [
            ('pending', 'Pending'),
            ('confirming', 'Confirming'),
            ('approved', 'Approved'),
            ('declined', 'Declined'),
            ('failed', 'Failed'),
            ('cancelled', 'Cancelled'),
        ],
        default='pending', required=True, index=True,
    )
    note = fields.Text('Note')
    request_id = fields.Char(
        'Correlation ID', index=True, copy=False,
        help="UUID echoed to the platform assign request and back on the "
             "assignment_confirmed event.",
    )
    resolved_at = fields.Datetime('Resolved At', readonly=True)

    # ------------------------------------------------------------------
    # Actions (called from the actionable WaNotification card)
    # ------------------------------------------------------------------

    def _assert_can_resolve(self):
        """Only the current assignee or a WA manager may approve/decline."""
        self.ensure_one()
        is_manager = self.env.user.has_group('wa_communication.group_wa_manager')
        if not is_manager and self.current_assignee_id.id != self.env.uid:
            raise UserError("Only the current assignee or a WhatsApp manager "
                            "can act on this reassignment request.")

    def _assert_still_actionable(self):
        """Refuse — audibly — to act on a request that is no longer pending.

        Both buttons used to ``return`` silently here, so a stale notification
        card (or a request that had moved to 'confirming') swallowed the click
        with no state change, no error and no feedback.  That is what made a
        stuck handover look like a broken button: the assignee pressed Decline,
        nothing happened, and nothing explained why.
        """
        self.ensure_one()
        if self.state == 'pending':
            return
        if self.state == 'confirming':
            raise UserError(
                "This chat is already being handed over — we're waiting for "
                "WhatsApp to confirm it. If the handover doesn't complete it is "
                "released automatically within a few minutes, and the requester "
                "can ask again.")
        raise UserError(
            "This request has already been %s."
            % dict(self._fields['state'].selection).get(
                self.state, self.state).lower())

    def approve(self):
        """Approve the handover → ask the platform to reassign to the requester."""
        self.ensure_one()
        self._assert_can_resolve()
        self._assert_still_actionable()
        # Trigger the platform-routed assign; ownership flips on confirmation.
        # Persist the correlation id returned by _request_assign so the
        # platform's assignment_confirmed event can be matched back to THIS
        # request (otherwise it stays stuck in 'confirming' forever).
        req_id = self.conversation_id._request_assign(
            self.requester_id, self.request_id or None)
        self.request_id = req_id
        self.state = 'confirming'

    def decline(self):
        self.ensure_one()
        self._assert_can_resolve()
        self._assert_still_actionable()
        self.state = 'declined'
        self.resolved_at = fields.Datetime.now()
        self._notify_requester(
            'reassignment_declined',
            "The current owner is keeping this chat for now. Focus on your other "
            "leads and check back if anything changes.")

    def cancel(self):
        """Requester cancels their own pending request."""
        self.ensure_one()
        if self.requester_id.id != self.env.uid and not \
                self.env.user.has_group('wa_communication.group_wa_manager'):
            raise UserError("Only the requester can cancel this request.")
        if self.state in ('pending', 'confirming'):
            self.state = 'cancelled'
            self.resolved_at = fields.Datetime.now()

    # ------------------------------------------------------------------
    # Confirmation hooks (called by wa.conversation on platform events)
    # ------------------------------------------------------------------

    def _mark_approved(self):
        for rec in self:
            rec.state = 'approved'
            rec.resolved_at = fields.Datetime.now()
            rec._notify_requester(
                'reassignment_approved',
                "Your handover request was approved — jump in and start replying "
                "to keep the conversation moving.")

    def _mark_failed(self, reason='', notify=True):
        """Mark the request failed.

        ``notify=False`` lets the caller own the notification fan-out (e.g. the
        assignment_confirmed handler, which tells BOTH the requester and the
        approver in one place) so the requester isn't toasted twice.
        """
        for rec in self:
            rec.state = 'failed'
            rec.resolved_at = fields.Datetime.now()
            if notify:
                rec._notify_requester('reassignment_failed',
                                      reason or "Reassignment failed in Interakt.")

    # ------------------------------------------------------------------
    # Stuck-handover sweeper
    # ------------------------------------------------------------------

    @api.model
    def _confirming_timeout_minutes(self) -> int:
        """Minutes a request may sit in 'confirming' before it is released.

        The normal Odoo → platform → Interakt → Odoo round-trip completes in
        under two seconds, so anything still confirming after the default 5
        minutes is not slow — the confirmation is never coming.
        """
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'wa_communication.confirming_timeout_minutes', '5')
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return 5

    @api.model
    def _cron_release_stuck_confirming(self) -> int:
        """Release handovers whose confirmation never arrived.

        'confirming' is the only state this model cannot leave on its own: it
        exits when the platform sends back ``assignment_confirmed``, so any
        failure to deliver that event strands the request permanently.  Three
        distinct causes have done so in practice — an in-flight Pub/Sub publish
        lost on worker exit, a swallowed serialisation failure, and Interakt
        itself never answering.  Without this sweep each one needed a DBA.

        Releasing to 'failed' (rather than 'approved') is the safe direction:
        the requester is told and can ask again, and a retry is harmless because
        wa-sender treats an already-assigned chat as success.  The cost of being
        wrong is one redundant request; the cost of guessing 'approved' would be
        Odoo claiming an ownership change that never happened in Interakt.

        :returns: how many requests were released.
        """
        timeout = self._confirming_timeout_minutes()
        cutoff = fields.Datetime.now() - timedelta(minutes=timeout)
        # write_date is when the row entered 'confirming': approve() sets
        # request_id and state in one write, and nothing else touches the row
        # until it leaves the state.
        stuck = self.sudo().search([
            ('state', '=', 'confirming'),
            ('write_date', '<', cutoff),
        ])
        if not stuck:
            return 0

        reason = ("WhatsApp never confirmed the handover, so the chat stays "
                  "with its current owner. You can request it again.")
        for rec in stuck:
            conv = rec.conversation_id.sudo()
            _logger.warning(
                "reassignment sweep: releasing request #%s (conv %s, phone %s, "
                "requester %s) — stuck in 'confirming' since %s (> %s min)",
                rec.id, conv.id, conv.phone_number,
                rec.requester_id.name, rec.write_date, timeout,
            )
            # Clear the spinner the assign set, or the composer stays locked
            # even though nothing is in flight any more.
            if conv.assignment_pending:
                conv.write({'assignment_pending': False})
            conv._owa_log_system_event(
                "Handover to %s was released — WhatsApp never confirmed it."
                % (rec.requester_id.name or 'the requesting RM'))
            rec._mark_failed(reason)
        return len(stuck)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _notify_requester(self, event_type, message):
        self.ensure_one()
        conv = self.conversation_id.sudo()
        lead_label = (conv.lead_id.name if conv.lead_id else None) \
            or conv.phone_number or 'the lead'
        title = {
            'reassignment_approved': '%s\'s chat is now yours' % lead_label,
            'reassignment_declined': 'Request for %s\'s chat declined' % lead_label,
            'reassignment_failed':   'Couldn\'t hand over %s\'s chat' % lead_label,
        }.get(event_type, 'WhatsApp assignment update')
        try:
            self.env['cleardeals.notification'].notify(
                self.requester_id.id, event_type,
                title=title, body=message,
                payload={
                    'phone': conv.phone_number,
                    'lead_id': conv.lead_id.id if conv.lead_id else None,
                    'lead_name': conv.lead_id.name if conv.lead_id else '',
                    'conversation_id': conv.id,
                },
            )
        except Exception:  # noqa: BLE001 — never let a notify failure break the flow
            _logger.warning("reassignment notify failed", exc_info=True)
