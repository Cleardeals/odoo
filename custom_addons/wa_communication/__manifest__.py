{
    'name': 'WhatsApp Communication',
    'version': '1.3.7',
    'summary': 'WA messaging layer: push receiver, conversation threads, outbound publishing.',
    'description': """
WhatsApp ↔ Odoo communication layer built on GCP Pub/Sub transport.

**Inbound (GCP → Odoo)**
Receives push deliveries from the ``cd-prod-wa-odoo-events`` subscription at
``POST /wa/pubsub/push``, verifies the OIDC bearer token, parses the WA Cloud
API webhook envelope, and routes events to the appropriate handler:

- Inbound WA messages  → create/update ``wa.conversation`` + ``wa.message``
- Delivery/read status updates → update ``wa.message.status``
- Unknown events → log to ``wa.event.log``

**Outbound (Odoo → GCP → WA)**
``wa.conversation.send_message()`` creates a pending ``wa.message`` and
publishes a send request to the ``cd-prod-odoo-wa-requests`` topic.  The WA
bridge picks it up, sends the actual WA message, and delivers status receipts
back via the inbound push path.

**Lead event publishing**
Inherits ``leads.new`` to publish configurable Pub/Sub events whenever
relevant lead state changes occur (lead created, site visit scheduled/done,
etc.).  Each event category has its own configurable topic.

**WA Dashboard**
Client action at WhatsApp → Dashboard providing:
- Headline KPI cards (Sent, Delivered, Read, Failed, Active Enrollments, Replied)
- Workflow Health table with manager-controlled active/pause toggle
- Hourly Send Volume bar chart
- Recent Failures table with direct lead navigation

**Configuration** (Settings → Technical → System Parameters):
  ``wa_communication.inbound_push_audience``         — OIDC ``aud`` claim
  ``wa_communication.inbound_push_sa_email``         — optional SA email
  ``wa_communication.topic_odoo_wa_requests``        — outbound WA sends
  ``wa_communication.topic_actor_events``            — lead/RM events
  ``wa_communication.topic_visit_events``            — site-visit events
  ``wa_communication.topic_property_events``         — property events
  ``wa_communication.topic_customer_events``         — customer events
  ``wa_communication.topic_workflow_control``        — workflow pause/resume toggle
    """,
    'author': 'Cleardeals Technology',
    'category': 'Technical',
    'license': 'LGPL-3',
    'depends': ['cleardeals_pubsub', 'leads', 'cleardeals_ui', 'cleardeals_notification'],
    'data': [
        'security/wa_security.xml',
        'security/ir.model.access.csv',
        'security/wa_quick_reply_rules.xml',
        'data/wa_communication_config_data.xml',
        'data/wa_lead_source_data.xml',
        'views/wa_message_views.xml',
        'views/wa_dashboard_action.xml',
        'views/wa_inbox_action.xml',
        'views/wa_lead_form_inherit.xml',
        'views/wa_communication_menus.xml',
        'views/wa_quick_reply_action.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'wa_communication/static/src/**/*.js',
            'wa_communication/static/src/**/*.xml',
            'wa_communication/static/src/**/*.scss',
        ],
        # Hoot (OWL) unit tests — run in a browser at /odoo/web/tests.
        'web.assets_unit_tests': [
            'wa_communication/static/tests/**/*.test.js',
        ],
    },
    'external_dependencies': {
        'python': ['google-cloud-pubsub', 'google-auth'],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
