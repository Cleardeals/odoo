#!/usr/bin/env python3
"""
scripts/test_odoo_to_wa_integration.py
─────────────────────────────────────────────────────────────────────────────
Odoo → WA Platform integration test.

Verifies that an action in Odoo (calling send_message on a wa.conversation)
publishes an OdooWaRequest to the Pub/Sub topic that the WA platform bridge
(S7 odoo-bridge) is subscribed to.

What this script does:
  1.  Finds or creates a wa.conversation with a test phone number by piping
      Python directly into the Odoo shell (no password needed).
  2.  Calls wa.conversation.send_message() and captures the wa.message ID.
  3.  Immediately pulls the resulting message from the
      cd-local-odoo-wa-requests-bridge-sub Pub/Sub subscription
      (the same one odoo-bridge is consuming).
  4.  Prints the received payload and exits 0 on success.

Requirements:
    google-cloud-pubsub   (in the project .venv)
    Docker must be running with container odoo-dev-app accessible.

Environment:
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

ODOO_DB       = os.environ.get('ODOO_DB', 'cleardeals_19_dev')
ODOO_CONTAINER = os.environ.get('ODOO_CONTAINER', 'odoo-dev-app')

EMULATOR_HOST = os.environ.get('PUBSUB_EMULATOR_HOST', 'localhost:8085')
GCP_PROJECT   = os.environ.get('GCP_PROJECT', 'cleardeals-wa-local')
GCP_ENV       = os.environ.get('GCP_ENV', 'local')

os.environ['PUBSUB_EMULATOR_HOST'] = EMULATOR_HOST

TOPIC_NAME    = f'cd-{GCP_ENV}-odoo-wa-requests'
SUB_NAME      = f'cd-{GCP_ENV}-odoo-wa-requests-bridge-sub'
TEST_PHONE    = '919876500001'
TEST_BODY     = f'[integration-test] Hello from Odoo — sent at {datetime.now().isoformat()}'


# ── Odoo shell helper ─────────────────────────────────────────────────────────

# Python snippet that runs inside the Odoo shell.
# Outputs a single JSON line: {"conv_id": ..., "msg_id": ...}
_ODOO_SHELL_SCRIPT = r"""
import json, sys

phone = '{phone}'
body  = {body!r}

conv = env['wa.conversation'].sudo().search([('phone_number', '=', phone)], limit=1)
if not conv:
    conv = env['wa.conversation'].sudo().create({{'phone_number': phone}})

msg = conv.send_message(body, kind='freetext', initiator='rm')

# commit() runs postcommit callbacks automatically (see Odoo sql_db.py),
# which triggers the Pub/Sub publish via the cleardeals_pubsub model.
env.cr.commit()

# publish_async enqueues in a background BatchThread; call stop() so the
# batch is flushed before the process exits (stop() waits for delivery).
import time; time.sleep(1)
try:
    import odoo.addons.cleardeals_pubsub.models.pubsub_publisher as _pub_mod
    _pc = _pub_mod._publisher_client
    if _pc is not None:
        _pc.stop()
except Exception as _e:
    sys.stderr.write(f'[warn] could not flush publisher: {{_e}}\\n')

print(json.dumps({{'conv_id': conv.id, 'msg_id': msg.id,
                   'status': msg.status, 'direction': msg.direction,
                   'kind': msg.kind, 'body': (msg.body or '')[:80]}}))
""".format(phone=TEST_PHONE, body=TEST_BODY)


def run_odoo_shell() -> dict:
    """Pipe a Python snippet into the Odoo container shell and parse JSON output."""
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
            timeout=60,
        )
    except FileNotFoundError:
        print('ERROR: docker not found. Is Docker running?')
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print('ERROR: Odoo shell timed out after 60s.')
        sys.exit(1)

    stdout = result.stdout.decode(errors='replace')
    stderr = result.stderr.decode(errors='replace')

    # Find the JSON line in stdout (shell may print banners before it)
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith('{') and 'msg_id' in line:
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


# ── Pub/Sub pull verification ─────────────────────────────────────────────────

# We create a short-lived test subscription on the same topic so we get our
# own copy of every message, independent of the live WA bridge subscriber.
TEST_SUB_NAME = f'cd-{GCP_ENV}-odoo-wa-requests-integration-test-sub'


def ensure_test_subscription() -> bool:
    """Create a disposable test subscription on the topic if it doesn't exist.
    Returns True on success, False if pubsub library is unavailable.
    """
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
            'name':  sub_path,
            'topic': topic_path,
            'ack_deadline_seconds': 30,
        })
        print(f'[pubsub] created test subscription {TEST_SUB_NAME}')
    except AlreadyExists:
        print(f'[pubsub] using existing test subscription {TEST_SUB_NAME}')
    finally:
        subscriber.close()
    return True


def pull_from_subscription(timeout_s: int = 15) -> dict | None:
    """
    Pull one message from the TEST subscription and return its decoded payload.
    The test subscription receives its own copy of every published message,
    independent of the live WA bridge subscriber.
    The message IS acknowledged to keep the subscription clean.
    """
    try:
        from google.cloud import pubsub_v1
    except ImportError:
        print('WARNING: google-cloud-pubsub not installed — skipping pull verification.')
        return None

    subscriber = pubsub_v1.SubscriberClient()
    sub_path = subscriber.subscription_path(GCP_PROJECT, TEST_SUB_NAME)

    deadline = time.monotonic() + timeout_s
    print(f'[pubsub] polling {sub_path}  (up to {timeout_s}s) …')

    while time.monotonic() < deadline:
        response = subscriber.pull(
            request={'subscription': sub_path, 'max_messages': 1},
            timeout=3,
        )
        if response.received_messages:
            msg = response.received_messages[0]
            # Ack to keep the test subscription clean
            subscriber.acknowledge(
                request={'subscription': sub_path,
                         'ack_ids': [msg.ack_id]}
            )
            payload = json.loads(msg.message.data.decode('utf-8'))
            print(f'[pubsub] received message  message_id={msg.message.message_id}')
            subscriber.close()
            return payload
        time.sleep(0.5)

    subscriber.close()
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f'Odoo container : {ODOO_CONTAINER}  db={ODOO_DB}')
    print(f'Pub/Sub        : {EMULATOR_HOST}  project={GCP_PROJECT}')
    print(f'Topic          : {TOPIC_NAME}')
    print(f'Bridge sub     : {SUB_NAME}  (WA platform live subscriber)')
    print(f'Test sub       : {TEST_SUB_NAME}  (our dedicated copy)')
    print(f'Test phone     : {TEST_PHONE}')
    print()

    # Step 0: Create test subscription BEFORE triggering so we don't miss the message
    print('── Step 0: Create test subscription ───────────────────')
    if not ensure_test_subscription():
        print('WARNING: google-cloud-pubsub not in .venv — Pub/Sub verification will be skipped.')
        print('         .venv/bin/pip install google-cloud-pubsub')
    print()

    # Step 1: Trigger send_message via Odoo shell
    print('── Step 1: Odoo shell → send_message ───────────────────')
    odoo = run_odoo_shell()
    conv_id = odoo['conv_id']
    msg_id  = odoo['msg_id']
    print(f'[odoo] wa.conversation id={conv_id}')
    print(f'[odoo] wa.message      id={msg_id}  status={odoo["status"]}  direction={odoo["direction"]}  kind={odoo["kind"]}')
    print(f'[odoo]                 body="{odoo["body"]}"')
    if odoo['status'] != 'queued':
        print(f'WARNING: expected status=queued immediately after send_message(), got {odoo["status"]!r}')
    print()

    # Step 2: Pull from our test subscription to verify publish
    print('── Step 2: Pub/Sub verification ────────────────────────')
    payload = pull_from_subscription(timeout_s=15)

    if payload is None:
        print('FAIL: no message received on the test subscription within the timeout.')
        print()
        print('Possible causes:')
        print('  • PUBSUB_PROJECT_ID inside Odoo container != cleardeals-wa-local')
        print('  • postcommit hook did not fire in the shell context')
        print('  • google-cloud-pubsub not in .venv')
        print()
        print('Check Odoo logs for publish errors:')
        print('  docker logs odoo-dev-app 2>&1 | grep -i pubsub | tail -10')
        sys.exit(1)

    print('[pubsub] payload received:')
    print(json.dumps(payload, indent=2, default=str))
    print()

    # Validate payload matches OdooWaRequest schema (shared/models.py)
    errors = []
    if payload.get('request_type') != 'send':
        errors.append(f'expected request_type=send, got {payload.get("request_type")!r}')
    if payload.get('phone') != TEST_PHONE:
        errors.append(f'expected phone={TEST_PHONE!r}, got {payload.get("phone")!r}')
    if payload.get('kind') != 'freetext':
        errors.append(f'expected kind=freetext, got {payload.get("kind")!r}')
    if not payload.get('request_id'):
        errors.append('expected non-empty request_id (UUID)')
    if not payload.get('message_text'):
        errors.append('expected non-empty message_text')

    if errors:
        print('FAIL — payload validation errors:')
        for e in errors:
            print(f'  • {e}')
        sys.exit(1)

    print('PASS — Odoo published a valid send_message request to Pub/Sub.')
    print()
    print('The WA platform odoo-bridge (cd-local-odoo-wa-requests-bridge-sub)')
    print('is subscribed to the same topic and receives the same message for')
    print('delivery via WhatsApp.')
    print()
    print(f'NOTE: test subscription {TEST_SUB_NAME!r} left on emulator.')
    print('      Re-running this script reuses it (no stale messages will remain).')


if __name__ == '__main__':
    main()
