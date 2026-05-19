#!/usr/bin/env python3
"""
scripts/test_lead_actor_created.py
─────────────────────────────────────────────────────────────────────────────
Integration test: creating a leads.new record publishes an actor.created event
to the cd-local-actor-events Pub/Sub topic.

Flow:
  1. Creates a test subscription on cd-local-actor-events before triggering.
  2. Creates a leads.new record via the Odoo shell (docker exec).
  3. Pulls from the test subscription and validates the actor.created payload.

Requirements:
    google-cloud-pubsub   (in the project .venv)
    Docker must be running with container odoo-dev-app accessible.

Environment variables (all have defaults for local dev):
    ODOO_DB               default: cleardeals_19_dev
    ODOO_CONTAINER        default: odoo-dev-app
    PUBSUB_EMULATOR_HOST  default: localhost:8085
    GCP_PROJECT           default: cleardeals-wa-local
    GCP_ENV               default: local
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────

ODOO_DB        = os.environ.get('ODOO_DB', 'cleardeals_19_dev')
ODOO_CONTAINER = os.environ.get('ODOO_CONTAINER', 'odoo-dev-app')

EMULATOR_HOST  = os.environ.get('PUBSUB_EMULATOR_HOST', 'localhost:8085')
GCP_PROJECT    = os.environ.get('GCP_PROJECT', 'cleardeals-wa-local')
GCP_ENV        = os.environ.get('GCP_ENV', 'local')

os.environ['PUBSUB_EMULATOR_HOST'] = EMULATOR_HOST

TOPIC_NAME    = f'cd-{GCP_ENV}-actor-events'
TEST_SUB_NAME = f'cd-{GCP_ENV}-actor-events-integration-test-sub'

TEST_PHONE    = '9876500099'
TEST_NAME     = f'Integration Test Lead {datetime.now().strftime("%Y%m%d-%H%M%S")}'


# ── Odoo shell script ─────────────────────────────────────────────────────────

# Runs inside `odoo shell`. Outputs a single JSON line.
_ODOO_SHELL_SCRIPT = r"""
import json, sys, time

phone = '{phone}'
name  = {name!r}

source = env['lead.source'].sudo().search([], limit=1)
lead = env['leads.new'].sudo().create({{
    'name':      name,
    'phone':     phone,
    'source_id': source.id,
}})

# commit() fires postcommit callbacks, which trigger the Pub/Sub publish.
env.cr.commit()

# publish_async uses a background BatchThread; stop() flushes it.
time.sleep(1)
try:
    import odoo.addons.cleardeals_pubsub.models.pubsub_publisher as _pub_mod
    _pc = _pub_mod._publisher_client
    if _pc is not None:
        _pc.stop()
except Exception as _e:
    sys.stderr.write(f'[warn] could not flush publisher: {{_e}}\\n')

print(json.dumps({{
    'lead_id': lead.id,
    'name':    lead.name,
    'phone':   lead.phone,
    'status':  lead.current_status or '',
}}))
""".format(phone=TEST_PHONE, name=TEST_NAME)


def run_odoo_shell() -> dict:
    """Pipe the shell script into the Odoo container and parse the JSON result."""
    cmd = [
        'docker', 'exec', '-i', ODOO_CONTAINER,
        '/opt/odoo-venv/bin/python3', '/usr/bin/odoo',
        'shell', '-d', ODOO_DB, '--no-http',
    ]
    try:
        result = subprocess.run(
            cmd,
            input=_ODOO_SHELL_SCRIPT.encode(),
            capture_output=True,
            timeout=90,
        )
    except FileNotFoundError:
        print('ERROR: docker not found. Is Docker running?')
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print('ERROR: Odoo shell timed out after 90s.')
        sys.exit(1)

    stdout = result.stdout.decode(errors='replace')
    stderr = result.stderr.decode(errors='replace')

    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith('{') and 'lead_id' in line:
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                pass

    print('ERROR: Odoo shell did not return expected JSON.')
    print('--- stdout ---')
    print(stdout[-2000:] if len(stdout) > 2000 else stdout)
    print('--- stderr ---')
    print(stderr[-2000:] if len(stderr) > 2000 else stderr)
    sys.exit(1)


# ── Pub/Sub helpers ───────────────────────────────────────────────────────────

def ensure_test_subscription() -> bool:
    """Create a test subscription on the actor-events topic if it doesn't exist."""
    try:
        from google.api_core.exceptions import AlreadyExists
        from google.cloud import pubsub_v1
    except ImportError:
        return False

    subscriber = pubsub_v1.SubscriberClient()
    topic_path = f'projects/{GCP_PROJECT}/topics/{TOPIC_NAME}'
    sub_path   = subscriber.subscription_path(GCP_PROJECT, TEST_SUB_NAME)

    try:
        subscriber.create_subscription(request={
            'name':                 sub_path,
            'topic':                topic_path,
            'ack_deadline_seconds': 30,
        })
        print(f'[pubsub] created test subscription {TEST_SUB_NAME}')
    except AlreadyExists:
        print(f'[pubsub] using existing test subscription {TEST_SUB_NAME}')
    finally:
        subscriber.close()
    return True


def drain_subscription() -> int:
    """Ack and discard any backlogged messages so only our new message arrives."""
    from google.cloud import pubsub_v1
    subscriber = pubsub_v1.SubscriberClient()
    sub_path   = subscriber.subscription_path(GCP_PROJECT, TEST_SUB_NAME)
    drained    = 0
    while True:
        resp = subscriber.pull(
            request={'subscription': sub_path, 'max_messages': 100},
            timeout=3,
        )
        if not resp.received_messages:
            break
        ack_ids = [m.ack_id for m in resp.received_messages]
        subscriber.acknowledge(request={'subscription': sub_path, 'ack_ids': ack_ids})
        drained += len(ack_ids)
    subscriber.close()
    if drained:
        print(f'[pubsub] drained {drained} stale message(s) from subscription')
    return drained


def pull_matching_message(lead_id: int, timeout_s: int = 20) -> dict | None:
    """Pull messages until we find the one for our specific lead_id.

    Acks and discards messages for other leads (from concurrent activity)
    and returns the first payload where actor_id == lead_id.
    """
    try:
        from google.cloud import pubsub_v1
    except ImportError:
        print('WARNING: google-cloud-pubsub not installed — skipping Pub/Sub verification.')
        return None

    subscriber = pubsub_v1.SubscriberClient()
    sub_path   = subscriber.subscription_path(GCP_PROJECT, TEST_SUB_NAME)
    deadline   = time.monotonic() + timeout_s
    print(f'[pubsub] polling {sub_path} for actor_id={lead_id}  (up to {timeout_s}s) …')

    while time.monotonic() < deadline:
        response = subscriber.pull(
            request={'subscription': sub_path, 'max_messages': 10},
            timeout=3,
        )
        for received in response.received_messages:
            subscriber.acknowledge(
                request={'subscription': sub_path, 'ack_ids': [received.ack_id]}
            )
            try:
                payload = json.loads(received.message.data.decode('utf-8'))
            except Exception:
                continue
            if payload.get('actor_id') == lead_id or payload.get('lead_id') == lead_id:
                print(f'[pubsub] received message  message_id={received.message.message_id}')
                subscriber.close()
                return payload
            print(f'[pubsub] skipping message for actor_id={payload.get("actor_id")} (not ours)')
        if not response.received_messages:
            time.sleep(0.5)

    subscriber.close()
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f'Odoo container : {ODOO_CONTAINER}  db={ODOO_DB}')
    print(f'Pub/Sub        : {EMULATOR_HOST}  project={GCP_PROJECT}')
    print(f'Topic          : {TOPIC_NAME}')
    print(f'Test sub       : {TEST_SUB_NAME}')
    print(f'Test lead name : {TEST_NAME}')
    print(f'Test phone     : {TEST_PHONE}')
    print()

    # Step 0: Ensure test subscription exists and is empty BEFORE the lead is created
    print('── Step 0: Create test subscription ───────────────────')
    if not ensure_test_subscription():
        print('ERROR: google-cloud-pubsub not in .venv.')
        print('       Run: .venv/bin/pip install google-cloud-pubsub')
        sys.exit(1)
    drain_subscription()
    print()

    # Step 1: Create leads.new record via Odoo shell
    print('── Step 1: Odoo shell → leads.new.create ───────────────')
    odoo = run_odoo_shell()
    lead_id = odoo['lead_id']
    print(f'[odoo] leads.new id={lead_id}  name={odoo["name"]!r}  phone={odoo["phone"]!r}')
    print()

    # Step 2: Pull and validate
    print('── Step 2: Pub/Sub verification ─────────────────────────')
    payload = pull_matching_message(lead_id, timeout_s=20)

    if payload is None:
        print('FAIL — no message received within the timeout.')
        print()
        print('Possible causes:')
        print(f'  • Config param wa_communication.topic_actor_events != {TOPIC_NAME!r}')
        print('  • PUBSUB_PROJECT_ID inside the Odoo container is wrong')
        print('  • postcommit hook did not fire')
        print()
        print('Check Odoo container logs:')
        print('  docker logs odoo-dev-app 2>&1 | grep -i pubsub | tail -20')
        print()
        print('Check config param:')
        print('  docker exec odoo-dev-app bash -c "PGPASSWORD=odoo psql -h db -U odoo -d cleardeals_19_dev '
              '-c \\"SELECT key, value FROM ir_config_parameter WHERE key LIKE \'%actor%\'\\""')
        sys.exit(1)

    print('[pubsub] payload received:')
    print(json.dumps(payload, indent=2, default=str))
    print()

    errors = []
    if payload.get('event_type') != 'actor.created':
        errors.append(f'expected event_type="actor.created", got {payload.get("event_type")!r}')
    if payload.get('actor_type') != 'buyer_inquiry':
        errors.append(f'expected actor_type="buyer_inquiry", got {payload.get("actor_type")!r}')
    if payload.get('actor_id') != lead_id:
        errors.append(f'expected actor_id={lead_id}, got {payload.get("actor_id")!r}')
    if payload.get('lead_id') != lead_id:
        errors.append(f'expected lead_id={lead_id}, got {payload.get("lead_id")!r}')
    if payload.get('phone') != TEST_PHONE:
        errors.append(f'expected phone={TEST_PHONE!r}, got {payload.get("phone")!r}')
    if not payload.get('customer_name'):
        errors.append('expected non-empty customer_name')

    if errors:
        print('FAIL — payload validation errors:')
        for e in errors:
            print(f'  • {e}')
        sys.exit(1)

    print(f'PASS — creating leads.new id={lead_id} published actor.created to {TOPIC_NAME}.')
    print()
    print(f'NOTE: test subscription {TEST_SUB_NAME!r} left on emulator.')
    print('      Re-running this script reuses it cleanly.')


if __name__ == '__main__':
    main()
