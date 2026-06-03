"""WhatsApp chat reassignment requests.

When an RM wants to reply on a chat owned by another RM, they raise a request.
The **current assignee** (or a manager) approves it; on approval Odoo asks the
wa-platform to reassign the chat in Interakt and update ``rm_assignments``.
Ownership only flips in Odoo once the platform sends back an
``assignment_confirmed`` event (handled in ``wa.conversation``).

State machine::

    pending ──approve──▶ confirming ──(assignment_confirmed ok)──▶ approved
        │                    │
        │                    └──(assignment_confirmed fail)──▶ failed
        ├──decline──▶ declined
        └──cancel───▶ cancelled
"""

import logging

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

    def approve(self):
        """Approve the handover → ask the platform to reassign to the requester."""
        self.ensure_one()
        self._assert_can_resolve()
        if self.state not in ('pending',):
            return
        # Trigger the platform-routed assign; ownership flips on confirmation.
        self.conversation_id._request_assign(self.requester_id, self.request_id)
        self.state = 'confirming'

    def decline(self):
        self.ensure_one()
        self._assert_can_resolve()
        if self.state not in ('pending',):
            return
        self.state = 'declined'
        self.resolved_at = fields.Datetime.now()
        self._notify_requester('reassignment_declined',
                               "Your assignment request was declined.")

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
            rec._notify_requester('reassignment_approved',
                                  "Your assignment request was approved — you can reply now.")

    def _mark_failed(self, reason=''):
        for rec in self:
            rec.state = 'failed'
            rec.resolved_at = fields.Datetime.now()
            rec._notify_requester('reassignment_failed',
                                  reason or "Reassignment failed in Interakt.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _notify_requester(self, event_type, message):
        self.ensure_one()
        try:
            conv = self.conversation_id
            self.env['bus.bus']._sendone(
                'wa_notification_%d' % self.requester_id.id,
                'wa_event',
                {
                    'type': event_type,
                    'message': message,
                    'phone': conv.phone_number,
                    'lead_name': conv.lead_id.name if conv.lead_id else '',
                    'conversation_id': conv.id,
                },
            )
        except Exception:  # noqa: BLE001 — never let a bus failure break the flow
            _logger.debug("reassignment notify failed", exc_info=True)
