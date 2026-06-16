"""Conversation ownership: claim, reassignment handshake, send gating.

Part of the ``wa.conversation`` model — see wa_conversation.py for the base
definition (fields, constraints, inbound push dispatcher).
"""
import logging
import uuid

from odoo import api, models
from odoo.exceptions import UserError
from .wa_conversation import _TOPIC_WA_REQUESTS

_logger = logging.getLogger(__name__)

class WaConversation(models.Model):
    _inherit = 'wa.conversation'

    def _is_wa_manager(self) -> bool:
        return self.env.user.has_group('wa_communication.group_wa_manager')

    def _can_send(self) -> bool:
        """Whether the current user may send on this conversation."""
        self.ensure_one()
        if self._is_wa_manager():
            return True
        return bool(self.assigned_user_id) and self.assigned_user_id.id == self.env.uid

    def _send_gate_reason(self) -> str:
        """Human message for why the composer is locked (empty if unlocked)."""
        self.ensure_one()
        if self._can_send():
            return ''
        if not self.assigned_user_id:
            return "This chat is unassigned. Claim it to reply."
        return ("This chat is assigned to %s. Request assignment to reply."
                % self.assigned_user_id.name)

    def _assert_can_send(self) -> None:
        self.ensure_one()
        if not self._can_send():
            raise UserError(self._send_gate_reason())

    def _request_assign(self, target_user, request_id: str | None = None) -> str:
        """Publish a platform-routed assign request for ``target_user``.

        Ownership is NOT flipped here — it flips when the platform sends back an
        ``assignment_confirmed`` event (Interakt ``result:true`` + ``rm_assignments``
        updated). Sets ``assignment_pending`` so the UI shows a spinner.

        :returns: the correlation ``request_id`` used.
        """
        self.ensure_one()
        if not self.phone_number:
            raise UserError("Cannot assign — this conversation has no phone number.")
        if not target_user.email:
            raise UserError(
                "Cannot assign to %s — that user has no email (required as the "
                "Interakt agent identifier)." % target_user.name)

        import uuid as _uuid
        req_id = request_id or str(_uuid.uuid4())
        topic = self.env['ir.config_parameter'].sudo().get_param(
            _TOPIC_WA_REQUESTS, 'cd-prod-odoo-wa-requests'
        )
        request_data = {
            'request_type': 'assign',
            'request_id': req_id,
            'phone': self.phone_number,
            'rm_email': target_user.email,
            'rm_name': target_user.name,
            'rm_odoo_id': target_user.id,
            'actor_id': self.lead_id.id if self.lead_id else None,
        }
        self.sudo().write({'assignment_pending': True})

        def _publish():
            self.env['cleardeals.pubsub'].publish_async(topic, request_data)

        self.env.cr.postcommit.add(_publish)
        return req_id

    def action_claim(self) -> None:
        """Self-claim an unassigned conversation (instant, no approval)."""
        self.ensure_one()
        if self.assigned_user_id and not self._is_wa_manager():
            raise UserError(
                "This chat is already assigned to %s." % self.assigned_user_id.name)
        self._request_assign(self.env.user)

    def request_assignment(self, note: str | None = None) -> int:
        """Raise a reassignment request to the current assignee.

        Returns the ``wa.reassignment.request`` id.
        """
        self.ensure_one()
        if self._can_send():
            raise UserError("You can already reply on this chat.")
        if not self.assigned_user_id:
            # Nobody owns it — claim directly instead of a handshake.
            self.action_claim()
            return 0
        assignee = self.assigned_user_id
        existing = self.env['wa.reassignment.request'].search([
            ('conversation_id', '=', self.id),
            ('requester_id', '=', self.env.uid),
            ('state', 'in', ('pending', 'confirming')),
        ], limit=1)
        if existing:
            _logger.info(
                "request_assignment: %s already has an open request (#%s, %s) "
                "for conv %s — re-notifying assignee %s",
                self.env.user.name, existing.id, existing.state, self.id, assignee.name,
            )
            # Re-emit so the assignee gets another chance to see the card even
            # if they missed the first one (e.g. were offline).
            self._notify_assignee_of_request(existing)
            return existing.id
        req = self.env['wa.reassignment.request'].create({
            'conversation_id': self.id,
            'requester_id': self.env.uid,
            'current_assignee_id': assignee.id,
            'note': note or '',
            'state': 'pending',
        })
        _logger.info(
            "request_assignment: %s (uid=%s) requested chat %s (lead=%s) from "
            "assignee %s (uid=%s) — created request #%s, notifying channel "
            "wa_notification_%s",
            self.env.user.name, self.env.uid, self.phone_number,
            self.sudo().lead_id.name if self.lead_id else '-', assignee.name, assignee.id,
            req.id, assignee.id,
        )
        self._notify_assignee_of_request(req)
        return req.id

    def _notify_assignee_of_request(self, req) -> None:
        """Push the actionable handover card to the current assignee.

        Failures here must be loud (warning, not debug) — a swallowed bus error
        is exactly why "nothing happens" with no trace.
        """
        self.ensure_one()
        assignee = self.assigned_user_id
        if not assignee:
            return
        # The requester may not have lead-read rights ("RM See Own"); read lead
        # display data via sudo so requesting a handover never 403s.
        lead = self.sudo().lead_id
        requester_name = req.requester_id.name
        lead_label = self._owa_lead_label(lead, self.phone_number)
        self._push_user_notification(
            assignee.id, 'reassignment_request',
            title='%s wants to take over %s' % (requester_name, lead_label),
            body='%s has asked to handle %s\'s WhatsApp chat. Approve it if '
                 'you\'re no longer following up with them.' % (
                     requester_name, lead_label),
            payload={
                'request_id': req.id,
                'requester_name': requester_name,
                'phone': self.phone_number,
                'lead_id': lead.id if lead else None,
                'lead_name': lead.name if lead else '',
                'note': req.note or '',
                'conversation_id': self.id,
                'suppress_key': self.phone_number,
            },
            actionable=True,
        )

    def action_reassign(self, lead_id: int | None = None, user_id: int | None = None) -> None:
        """Manager force-reassign (or re-link inquiry) — platform-routed.

        Managers may reassign instantly without the approval handshake; the
        ownership flip still waits for the platform's ``assignment_confirmed``.
        """
        self.ensure_one()
        if not self._is_wa_manager():
            raise UserError("Only a WhatsApp manager can force-reassign a chat.")
        if lead_id:
            self.sudo().write({'lead_id': lead_id})
        if user_id:
            target = self.env['res.users'].sudo().browse(user_id)
            self._request_assign(target)

    def _handle_odoo_assignment_confirmed(self, event: dict, pubsub_message_id: str) -> None:
        """Platform confirmed (or failed) an Interakt chat assignment.

        On success: flip ``assigned_user_id``, clear the pending marker, resolve
        any matching reassignment request, log a system message, and notify the
        new assignee so their composer unlocks. On failure: notify the requester.
        """
        phone = event.get('phone')
        rm_odoo_id = event.get('rm_odoo_id')
        request_id = event.get('request_id')
        success = event.get('success', True)

        conv = self.search([('phone_number', '=', phone)], limit=1) if phone else self
        if not conv:
            return
        conv = conv[:1]

        req = None
        if request_id:
            req = self.env['wa.reassignment.request'].sudo().search(
                [('request_id', '=', request_id)], limit=1)

        if not success:
            reason = (event.get('failure_reason') or '').strip() \
                or "Interakt rejected the assignment."
            conv.sudo().write({'assignment_pending': False})

            target_user = (self.env['res.users'].sudo().browse(rm_odoo_id)
                           if rm_odoo_id else None)
            target_name = (target_user.name
                           if target_user and target_user.exists()
                           else "the requested RM")

            # Tell EVERYONE involved, with the reason:
            #  • the target RM (the requester / claimer who would have got it),
            #  • the approver (the request's current assignee), and
            #  • whoever currently owns the chat.
            notify_uids = set()
            if rm_odoo_id:
                notify_uids.add(rm_odoo_id)
            if req:
                notify_uids.add(req.requester_id.id)
                if req.current_assignee_id:
                    notify_uids.add(req.current_assignee_id.id)
                # Caller owns the notification fan-out below — don't double-toast.
                req._mark_failed(reason, notify=False)
            if conv.assigned_user_id:
                notify_uids.add(conv.assigned_user_id.id)

            # Persistent record in the thread (survives a missed real-time toast).
            conv._owa_log_system_event(
                "Chat could not be assigned to %s — %s" % (target_name, reason))
            conv._notify_assignment_failed(notify_uids, reason, target_name)
            _logger.info(
                "assignment failed for conv %s (target=%s): %s — notified uids=%s",
                conv.id, target_name, reason, sorted(notify_uids),
            )
            return

        new_user = self.env['res.users'].sudo().browse(rm_odoo_id) if rm_odoo_id else None
        vals = {'assignment_pending': False}
        if new_user and new_user.exists():
            vals['assigned_user_id'] = new_user.id
        conv.sudo().write(vals)

        if new_user:
            conv._owa_log_system_event("Chat assigned to %s" % new_user.name)
            lead_label = self._owa_lead_label(conv.lead_id, conv.phone_number)
            conv._push_user_notification(
                new_user.id, 'assignment_changed',
                title='%s\'s chat is now yours' % lead_label,
                body='You\'re now handling %s on WhatsApp. Open the chat, say '
                     'hello, and keep the conversation moving.' % lead_label,
                payload={
                    'phone': conv.phone_number,
                    'lead_id': conv.lead_id.id if conv.lead_id else None,
                    'lead_name': conv.lead_id.name if conv.lead_id else '',
                    'conversation_id': conv.id,
                },
            )
        if req:
            req._mark_approved()

    def _notify_assignment_failed(self, user_ids, reason: str, target_name: str) -> None:
        """Push a 'reassignment_failed' toast (with the reason) to each user.

        Used when the platform reports the Interakt assignment could not be
        completed (e.g. "Agent with email not found"). Failures must be loud and
        reach BOTH the requester and the approver so the chat isn't left in a
        silent limbo.
        """
        self.ensure_one()
        lead_label = self._owa_lead_label(self.lead_id, self.phone_number)
        message = ("%s's chat couldn't be handed to %s (%s). It stays with its "
                   "current owner — please follow up so the lead isn't dropped."
                   % (lead_label, target_name, reason))
        payload = {
            'reason': reason,
            'phone': self.phone_number,
            'lead_id': self.lead_id.id if self.lead_id else None,
            'lead_name': self.lead_id.name if self.lead_id else '',
            'conversation_id': self.id,
        }
        for uid in {u for u in user_ids if u}:
            self._push_user_notification(
                uid, 'reassignment_failed',
                title='Couldn\'t reassign %s\'s chat' % lead_label,
                body=message, payload=payload)
