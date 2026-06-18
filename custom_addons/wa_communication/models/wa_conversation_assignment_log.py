"""Append-only ownership history for WhatsApp conversations.

``wa.conversation.assigned_user_id`` is a single mutable field — it tells you who
owns a chat *now*, but not who owned it last Tuesday at 14:00.  Fair historical
analytics (the By-RM responsiveness scorecard) need exactly that: *who was on the
hook for this buyer message at the moment it arrived/was answered.*

This module adds a tiny immutable ledger — one row per ownership change — and a
``wa.conversation`` ``create``/``write`` hook that appends to it on every
assignment path (auto-assign on inbound, the reassignment handshake,
``action_reassign``, or a plain manual write).  Hooking ``write`` rather than each
call site means no path can silently skip the log.

The ledger is append-only: rows are never updated or deleted in normal operation,
so the timeline is a trustworthy audit trail.  Resolve "owner at instant T" by
taking the row with the greatest ``effective_from <= T`` (see
``wa.dashboard._owner_at``).
"""

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class WaConversationAssignmentLog(models.Model):
    _name = 'wa.conversation.assignment.log'
    _description = 'WhatsApp Conversation Assignment History'
    _order = 'effective_from desc, id desc'

    conversation_id = fields.Many2one(
        'wa.conversation', string='Conversation',
        required=True, ondelete='cascade', index=True,
    )
    owner_user_id = fields.Many2one(
        'res.users', string='Owner', ondelete='set null', index=True,
        help="RM owning the conversation from ``effective_from`` onward. "
             "Empty means the chat was Unassigned during that interval.",
    )
    effective_from = fields.Datetime(
        string='Effective From', required=True, index=True,
        default=fields.Datetime.now,
        help="UTC instant this ownership interval began.",
    )


class WaConversation(models.Model):
    _inherit = 'wa.conversation'

    assignment_log_ids = fields.One2many(
        'wa.conversation.assignment.log', 'conversation_id',
        string='Assignment History',
    )

    # ------------------------------------------------------------------
    # Ownership ledger — append on every assignment change
    # ------------------------------------------------------------------

    def _owa_log_assignment(self, owner_id, when=None):
        """Append one ownership-history row for each conversation in ``self``."""
        if not self:
            return
        when = when or fields.Datetime.now()
        self.env['wa.conversation.assignment.log'].sudo().create([
            {
                'conversation_id': conv.id,
                'owner_user_id': owner_id or False,
                'effective_from': when,
            }
            for conv in self
        ])

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Seed the ledger only for conversations that were born already owned
        # (rare — most are created Unassigned and get their first owner via a
        # later write, which the override below logs).
        for conv in records:
            if conv.assigned_user_id:
                conv._owa_log_assignment(conv.assigned_user_id.id)
        return records

    def write(self, vals):
        if 'assigned_user_id' not in vals:
            return super().write(vals)
        # Snapshot pre-write owners so we only log genuine changes.
        new_owner = vals['assigned_user_id'] or False
        changed = self.filtered(
            lambda c: (c.assigned_user_id.id or False) != new_owner)
        result = super().write(vals)
        changed._owa_log_assignment(new_owner)
        return result
