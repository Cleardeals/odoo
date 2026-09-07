#!/usr/bin/env python3
"""
scripts/setup_local_wa_push.py
─────────────────────────────────────────────────────────────────────────────
Creates a Pub/Sub **push** subscription on the local emulator that delivers
wa-odoo-events to the Odoo dev container.

Run this once after `make up` and after running the WA platform's
`create_local_pubsub.py` (which creates the topics).  Re-running is safe —
the existing subscription is silently skipped.

Usage:
    python scripts/setup_local_wa_push.py

Requirements:
    pip install google-cloud-pubsub

Environment:
    PUBSUB_EMULATOR_HOST   default: localhost:8085
    GCP_PROJECT            default: cleardeals-wa-local
    GCP_ENV                default: local
    ODOO_HOST              default: host.docker.internal:8069
                           (use localhost:8069 if running Odoo outside Docker)
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import os
import sys

EMULATOR_HOST = os.environ.get('PUBSUB_EMULATOR_HOST', 'localhost:8085')
GCP_PROJECT   = os.environ.get('GCP_PROJECT', 'cleardeals-wa-local')
GCP_ENV       = os.environ.get('GCP_ENV', 'local')
ODOO_HOST     = os.environ.get('ODOO_HOST', 'host.docker.internal:8069')

os.environ['PUBSUB_EMULATOR_HOST'] = EMULATOR_HOST

TOPIC_NAME = f'cd-{GCP_ENV}-wa-odoo-events'
SUB_NAME   = f'cd-{GCP_ENV}-wa-odoo-events-odoo-push-sub'
PUSH_URL   = f'http://{ODOO_HOST}/wa/pubsub/push'


def main() -> None:
    try:
        from google.api_core.exceptions import AlreadyExists
        from google.cloud import pubsub_v1
    except ImportError:
        print("ERROR: google-cloud-pubsub is not installed.")
        print("       pip install google-cloud-pubsub")
        sys.exit(1)

    print(f"Emulator : {EMULATOR_HOST}")
    print(f"Project  : {GCP_PROJECT}")
    print(f"Topic    : projects/{GCP_PROJECT}/topics/{TOPIC_NAME}")
    print(f"Sub      : projects/{GCP_PROJECT}/subscriptions/{SUB_NAME}")
    print(f"Push URL : {PUSH_URL}")
    print()

    publisher  = pubsub_v1.PublisherClient()
    subscriber = pubsub_v1.SubscriberClient()

    topic_path = publisher.topic_path(GCP_PROJECT, TOPIC_NAME)
    sub_path   = subscriber.subscription_path(GCP_PROJECT, SUB_NAME)

    # Ensure the topic exists (create_local_pubsub.py should have done this)
    try:
        publisher.create_topic(request={'name': topic_path})
        print(f'[created] topic {topic_path}')
    except AlreadyExists:
        print(f'[exists]  topic {topic_path}')

    # Create the push subscription
    try:
        subscriber.create_subscription(request={
            'name':  sub_path,
            'topic': topic_path,
            'push_config': {'push_endpoint': PUSH_URL},
            'ack_deadline_seconds': 30,
        })
        print(f'[created] subscription {sub_path}')
        print(f'          → pushing to {PUSH_URL}')
    except AlreadyExists:
        print(f'[exists]  subscription {sub_path}')

    subscriber.close()
    print('\nDone. Odoo will now receive wa-odoo-events via push.')
    print(f'Odoo must be running at {PUSH_URL}')
    print('Odoo env must have PUBSUB_EMULATOR_HOST set to skip OIDC check.')


if __name__ == '__main__':
    main()
