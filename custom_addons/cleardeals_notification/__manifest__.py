{
    'name': 'Cleardeals Notification',
    'version': '1.0.0',
    'summary': 'Reusable, persistent user-notification backend for all Cleardeals addons.',
    'description': """
Central notification backend.

Provides a single persistent model (``cleardeals.notification``) and a reusable
server API so any module can raise a user-facing notification that:

* **persists** — recovered on the user's next page load even if they were
  offline / on another screen when it fired (delivery is compulsory);
* **fans out live** over the per-user ``cleardeals_notification_{uid}`` bus
  channel for instant popups; and
* is **type-tagged** — callers pass a ``notif_type`` string which the frontend
  (in ``cleardeals_ui``) maps to an icon/colour/actions via a registry, so new
  notification kinds need no backend change.

Usage::

    self.env['cleardeals.notification'].notify(
        users, 'reassignment_request',
        title="Chat handover requested",
        body="Nirat wants to take over this chat.",
        payload={'request_id': req.id, 'suppress_key': phone, ...},
        actionable=True,
    )

The frontend UI (systray bell + popups) lives in ``cleardeals_ui``.
""",
    'author': 'Cleardeals Technology',
    'category': 'Technical',
    'license': 'LGPL-3',
    'depends': ['bus'],
    'data': [
        'security/ir.model.access.csv',
        'security/cleardeals_notification_rules.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
