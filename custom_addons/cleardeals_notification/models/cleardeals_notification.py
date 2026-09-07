"""Reusable, persistent notification backend — ``cleardeals.notification``.

WhatsApp-independent. Any module emits notifications with::

    self.env['cleardeals.notification'].notify(
        users,                       # recordset / id / list of ids
        'reassignment_request',      # notif_type (frontend registry key)
        title="Chat handover requested",
        body="Nirat wants to take over this chat.",
        payload={'request_id': req.id, 'suppress_key': phone, ...},
        actionable=True,             # persists in the bell until acted upon
    )

Each call persists one row per recipient AND pushes the serialised row over the
per-user ``cleardeals_notification_{uid}`` bus channel. The frontend
(``cleardeals_ui``) shows a live popup and keeps a systray-bell history; on the
next page load it also pulls :meth:`get_unread`, so a notification raised while
the user was offline is never lost.

``payload`` is spread into the message, so type-specific frontend handlers read
their keys (``request_id``, ``conversation_id``, …) at the top level. The special
key ``suppress_key`` lets a caller mark a notification as redundant while the
user is already looking at the matching context (e.g. that exact WA chat) — the
frontend suppresses only the *popup* in that case, never the history entry.
"""

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Per-user bus channel prefix. The frontend subscribes to
# ``cleardeals_notification_{uid}`` and listens for the ``cd_notification`` type.
BUS_CHANNEL_PREFIX = 'cleardeals_notification_'
BUS_MESSAGE_TYPE = 'cd_notification'


class CleardealsNotification(models.Model):
    _name = 'cleardeals.notification'
    _description = 'User Notification'
    _order = 'create_date desc, id desc'

    user_id = fields.Many2one(
        'res.users', string='Recipient', required=True, index=True,
        ondelete='cascade',
    )
    notif_type = fields.Char(
        'Type', required=True, index=True,
        help="Event key the frontend registry maps to an icon/colour/actions, "
             "e.g. 'reassignment_request', 'lead_replied'.",
    )
    title = fields.Char('Title')
    body = fields.Text('Message')
    payload = fields.Json(
        'Payload',
        help="Arbitrary event data (ids, names, urls). Spread into the client "
             "message so type-specific handlers can read it at the top level.",
    )
    is_actionable = fields.Boolean(
        'Actionable', default=False,
        help="Has inline actions (e.g. Approve/Decline); stays until resolved.",
    )
    is_read = fields.Boolean('Read', default=False, index=True)
    sticky = fields.Boolean(
        'Sticky', default=False,
        help="Popup does not auto-dismiss; stays in the bell until read.",
    )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def _to_dict(self) -> dict:
        """Serialise for the bus message / RPC, spreading the payload."""
        self.ensure_one()
        data = {
            'notification_id': self.id,
            'type': self.notif_type,
            'title': self.title or '',
            'message': self.body or '',
            'actionable': self.is_actionable,
            'sticky': self.sticky or self.is_actionable,
            'is_read': self.is_read,
            'created_at': self.create_date.isoformat() if self.create_date else None,
        }
        if isinstance(self.payload, dict):
            # Payload keys (request_id, conversation_id, suppress_key, …) take
            # precedence so existing consumers read them at the top level.
            data.update(self.payload)
        # Re-assert canonical keys payload must never override.
        data['notification_id'] = self.id
        data['type'] = self.notif_type
        return data

    # ------------------------------------------------------------------
    # Emission (reusable API)
    # ------------------------------------------------------------------

    @api.model
    def notify(self, users, notif_type, title='', body='', payload=None,
               actionable=False, sticky=False):
        """Persist + push a notification to one or more users.

        :param users: a ``res.users`` recordset, a single id, or a list of ids.
        :param notif_type: frontend registry key (str).
        :returns: the created ``cleardeals.notification`` recordset.
        """
        user_ids = self._coerce_user_ids(users)
        if not user_ids:
            return self.browse()

        recs = self.sudo().create([{
            'user_id': uid,
            'notif_type': notif_type,
            'title': title,
            'body': body,
            'payload': payload or {},
            'is_actionable': actionable,
            'sticky': sticky or actionable,
        } for uid in user_ids])

        for rec in recs:
            try:
                self.env['bus.bus']._sendone(
                    '%s%d' % (BUS_CHANNEL_PREFIX, rec.user_id.id),
                    BUS_MESSAGE_TYPE,
                    rec._to_dict(),
                )
            except Exception:  # noqa: BLE001 — a bus hiccup must not lose the row
                _logger.warning(
                    "cleardeals.notification: bus push failed uid=%s type=%s",
                    rec.user_id.id, notif_type, exc_info=True)
        _logger.info(
            "cleardeals.notification: emitted '%s' to uids=%s (actionable=%s)",
            notif_type, user_ids, actionable)
        return recs

    @staticmethod
    def _coerce_user_ids(users) -> list:
        if not users:
            return []
        if isinstance(users, models.BaseModel):
            return list(users.ids)
        if isinstance(users, (list, tuple, set)):
            return [int(u) for u in users if u]
        return [int(users)]

    # ------------------------------------------------------------------
    # Client RPC helpers (scoped to the current user)
    # ------------------------------------------------------------------

    @api.model
    def get_unread(self, limit=40) -> list:
        """Return the current user's unread notifications (newest first).

        Called by the frontend on mount so anything raised while the user was
        offline / elsewhere is recovered rather than lost.
        """
        recs = self.search(
            [('user_id', '=', self.env.uid), ('is_read', '=', False)], limit=limit)
        return [r._to_dict() for r in recs]

    @api.model
    def get_unread_count(self) -> int:
        return self.search_count(
            [('user_id', '=', self.env.uid), ('is_read', '=', False)])

    @api.model
    def mark_read(self, ids) -> bool:
        """Flag the given notifications read (caller's own only)."""
        recs = self.browse(ids).filtered(lambda r: r.user_id.id == self.env.uid)
        if recs:
            recs.write({'is_read': True})
        return True

    @api.model
    def mark_all_read(self) -> bool:
        self.search(
            [('user_id', '=', self.env.uid), ('is_read', '=', False)]
        ).write({'is_read': True})
        return True
