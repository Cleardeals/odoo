{
    'name': 'Cleardeals Pub/Sub',
    'version': '1.0.0',
    'summary': 'Generic GCP Pub/Sub transport layer for Cleardeals modules.',
    'description': """
Provides two capabilities:

1. **Publishing** — ``cleardeals.pubsub`` AbstractModel with:
   - ``publish_async()`` — fire-and-forget, safe from ORM hooks and request
     handlers (the library sends the RPC in its own BatchThread).
   - ``publish_sync()`` — blocking, for cron workers only.  Raises
     ``RuntimeError`` if ``odoo.evented`` is True to prevent event-loop
     deadlocks in threaded mode.

2. **Push-subscription verification** — ``push_utils.verify_push_token()``
   utility for validating the OIDC bearer token that GCP Pub/Sub includes on
   every push delivery.  Verification is skipped automatically when
   ``PUBSUB_EMULATOR_HOST`` is set.

Any Cleardeals addon that needs to publish events or receive Pub/Sub push
deliveries should declare ``cleardeals_pubsub`` as a dependency instead of
calling the Google Cloud library directly.
    """,
    'author': 'Cleardeals Technology',
    'category': 'Technical',
    'license': 'LGPL-3',
    'depends': ['base', 'web'],
    'data': [],
    'external_dependencies': {
        'python': ['google-cloud-pubsub', 'google-auth'],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
