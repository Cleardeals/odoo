#!/usr/bin/env python3
"""
scripts/test_wa_odoo_events.py
─────────────────────────────────────────────────────────────────────────────
Tests the wa_communication push endpoint by POSTing OdooWaEvent payloads
directly to Odoo (simulating what the Pub/Sub emulator would deliver via the
push subscription).

This bypasses the emulator delivery path and tests the Odoo handler logic
directly — which is the same code path the emulator uses.

Usage:
    python scripts/test_wa_odoo_events.py

    # Test a specific event type only:
    python scripts/test_wa_odoo_events.py message_sent

Requirements:
    pip install requests

Environment:
    ODOO_URL    default: http://localhost:8069
                (Odoo must be running with PUBSUB_EMULATOR_HOST set so
                 OIDC verification is bypassed)
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import base64
import json
import os
import sys
import uuid
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    print("ERROR: requests is not installed.  pip install requests")
    sys.exit(1)

ODOO_URL   = os.environ.get('ODOO_URL', 'http://localhost:8069').rstrip('/')
PUSH_PATH  = '/wa/pubsub/push'
ENDPOINT   = f'{ODOO_URL}{PUSH_PATH}'

# ── Test fixtures ─────────────────────────────────────────────────────────────
#
# Use a real-ish phone number and lead/actor IDs.  actor_id=1 / rm_odoo_id=1
# reference whatever records exist in the dev DB — the handler does a browse()
# which returns empty if the ID doesn't exist, and gracefully falls back to a
# phone search.

TEST_PHONE     = '919876500001'
TEST_ACTOR_ID  = 1          # set to an actual leads.new ID in your dev DB
TEST_RM_ID     = 2          # set to an actual res.users ID in your dev DB
TEST_REQ_ID    = str(uuid.uuid4())
TEST_WA_MSG_ID = f'wamid.test.{uuid.uuid4().hex[:12]}'
NOW_ISO        = datetime.now(timezone.utc).isoformat()


def _make_envelope(event_dict: dict) -> bytes:
    """Wrap an event dict in a Pub/Sub push envelope."""
    data_b64 = base64.b64encode(json.dumps(event_dict).encode()).decode()
    envelope = {
        'message': {
            'data':        data_b64,
            'messageId':   str(uuid.uuid4()),
            'publishTime': NOW_ISO,
            'attributes':  {},
        },
        'subscription': f'projects/cleardeals-wa-local/subscriptions/cd-local-wa-odoo-events-odoo-push-sub',
    }
    return json.dumps(envelope).encode()


def _post(event_dict: dict) -> requests.Response:
    """POST one event to Odoo's push endpoint."""
    return requests.post(
        ENDPOINT,
        data=_make_envelope(event_dict),
        headers={
            'Content-Type':  'application/json',
            # Emulator bypass: Odoo skips OIDC when PUBSUB_EMULATOR_HOST is set.
            # Any non-empty Bearer token is accepted.
            'Authorization': 'Bearer emulator-local-test',
        },
        timeout=10,
    )


# ── Event payloads ────────────────────────────────────────────────────────────

EVENTS: dict[str, dict] = {
    'message_sent': {
        'event_type':     'message_sent',
        'actor_type':     'buyer_inquiry',
        'actor_id':       TEST_ACTOR_ID,
        'rm_odoo_id':     TEST_RM_ID,
        'phone':          TEST_PHONE,
        'request_id':     TEST_REQ_ID,
        'wa_message_id':  TEST_WA_MSG_ID,
        'direction':      'outbound',
        'template_name':  'site_visit_reminder_v2',
        'workflow_slug':  'post_visit',
        'step_id':        'step_1',
        'enrollment_id':  str(uuid.uuid4()),
        'cost_inr':       None,
        'occurred_at':    NOW_ISO,
        'interakt_msg_id': None,
        'message_text':   None,
        'button_reply_id': None,
        'failure_code':   None,
        'failure_reason': None,
    },
    'message_delivered': {
        'event_type':     'message_delivered',
        'actor_type':     'buyer_inquiry',
        'actor_id':       TEST_ACTOR_ID,
        'rm_odoo_id':     TEST_RM_ID,
        'phone':          TEST_PHONE,
        'request_id':     TEST_REQ_ID,
        'wa_message_id':  TEST_WA_MSG_ID,
        'direction':      'outbound',
        'cost_inr':       0.9400,
        'occurred_at':    NOW_ISO,
        'interakt_msg_id': None,
        'message_text':   None,
        'button_reply_id': None,
        'failure_code':   None,
        'failure_reason': None,
        'template_name':  None,
        'workflow_slug':  None,
        'step_id':        None,
        'enrollment_id':  None,
    },
    'message_read': {
        'event_type':     'message_read',
        'actor_type':     'buyer_inquiry',
        'actor_id':       TEST_ACTOR_ID,
        'rm_odoo_id':     TEST_RM_ID,
        'phone':          TEST_PHONE,
        'request_id':     TEST_REQ_ID,
        'wa_message_id':  TEST_WA_MSG_ID,
        'occurred_at':    NOW_ISO,
        'direction':      'outbound',
        'cost_inr':       None,
        'interakt_msg_id': None,
        'message_text':   None,
        'button_reply_id': None,
        'failure_code':   None,
        'failure_reason': None,
        'template_name':  None,
        'workflow_slug':  None,
        'step_id':        None,
        'enrollment_id':  None,
    },
    'message_failed': {
        'event_type':     'message_failed',
        'actor_type':     'buyer_inquiry',
        'actor_id':       TEST_ACTOR_ID,
        'rm_odoo_id':     TEST_RM_ID,
        'phone':          TEST_PHONE,
        'request_id':     str(uuid.uuid4()),
        'wa_message_id':  f'wamid.test.failed.{uuid.uuid4().hex[:8]}',
        'occurred_at':    NOW_ISO,
        'direction':      'outbound',
        'failure_code':   131026,
        'failure_reason': 'Recipient phone number not in allowed list (Meta sandbox)',
        'cost_inr':       None,
        'interakt_msg_id': None,
        'message_text':   None,
        'button_reply_id': None,
        'template_name':  None,
        'workflow_slug':  None,
        'step_id':        None,
        'enrollment_id':  None,
    },
    'lead_replied': {
        'event_type':     'lead_replied',
        'actor_type':     'buyer_inquiry',
        'actor_id':       TEST_ACTOR_ID,
        'rm_odoo_id':     TEST_RM_ID,
        'phone':          TEST_PHONE,
        'request_id':     None,
        'wa_message_id':  f'wamid.test.reply.{uuid.uuid4().hex[:8]}',
        'message_text':   'Yes I want to visit tomorrow morning',
        'button_reply_id': None,
        'occurred_at':    NOW_ISO,
        'direction':      'inbound',
        'cost_inr':       None,
        'interakt_msg_id': None,
        'failure_code':   None,
        'failure_reason': None,
        'template_name':  None,
        'workflow_slug':  None,
        'step_id':        None,
        'enrollment_id':  None,
    },
    'ambiguous_reply': {
        'event_type':     'ambiguous_reply',
        'actor_type':     'buyer_inquiry',
        'actor_id':       None,
        'rm_odoo_id':     TEST_RM_ID,
        'phone':          '919000000099',     # unknown phone — no lead match
        'request_id':     None,
        'wa_message_id':  f'wamid.test.ambig.{uuid.uuid4().hex[:8]}',
        'message_text':   'Kya deal final hua?',
        'button_reply_id': None,
        'occurred_at':    NOW_ISO,
        'direction':      'inbound',
        'cost_inr':       None,
        'interakt_msg_id': None,
        'failure_code':   None,
        'failure_reason': None,
        'template_name':  None,
        'workflow_slug':  None,
        'step_id':        None,
        'enrollment_id':  None,
    },
    'enrollment_created': {
        'event_type':     'enrollment_created',
        'actor_type':     'buyer_inquiry',
        'actor_id':       TEST_ACTOR_ID,
        'rm_odoo_id':     TEST_RM_ID,
        'phone':          TEST_PHONE,
        'request_id':     None,
        'wa_message_id':  None,
        'occurred_at':    NOW_ISO,
        'workflow_slug':  'post_visit',
        'enrollment_id':  str(uuid.uuid4()),
        'step_id':        None,
        'direction':      None,
        'cost_inr':       None,
        'interakt_msg_id': None,
        'message_text':   None,
        'button_reply_id': None,
        'failure_code':   None,
        'failure_reason': None,
        'template_name':  None,
    },
    'enrollment_completed': {
        'event_type':     'enrollment_completed',
        'actor_type':     'buyer_inquiry',
        'actor_id':       TEST_ACTOR_ID,
        'rm_odoo_id':     TEST_RM_ID,
        'phone':          TEST_PHONE,
        'request_id':     None,
        'wa_message_id':  None,
        'occurred_at':    NOW_ISO,
        'workflow_slug':  'post_visit',
        'enrollment_id':  str(uuid.uuid4()),
        'step_id':        None,
        'direction':      None,
        'cost_inr':       None,
        'interakt_msg_id': None,
        'message_text':   None,
        'button_reply_id': None,
        'failure_code':   None,
        'failure_reason': None,
        'template_name':  None,
    },
}


# ── Runner ────────────────────────────────────────────────────────────────────

def run_test(name: str, event: dict) -> bool:
    print(f'  {name:<30}', end=' ', flush=True)
    try:
        resp = _post(event)
        if resp.status_code == 200:
            print('✓ 200 OK')
            return True
        elif resp.status_code == 401:
            print(f'✗ 401  — Odoo OIDC check rejected the request.')
            print(f'         Make sure PUBSUB_EMULATOR_HOST is set in Odoo\'s environment.')
            return False
        else:
            print(f'✗ {resp.status_code}  — {resp.text[:120]}')
            return False
    except requests.ConnectionError:
        print(f'✗ CONNECTION ERROR  — Is Odoo running at {ODOO_URL}?')
        return False
    except Exception as exc:
        print(f'✗ EXCEPTION  — {exc}')
        return False


def main() -> None:
    filter_type = sys.argv[1] if len(sys.argv) > 1 else None

    print(f'Odoo endpoint : {ENDPOINT}')
    print(f'Test phone    : {TEST_PHONE}')
    print(f'Test request  : {TEST_REQ_ID}')
    print(f'Test wamid    : {TEST_WA_MSG_ID}')
    print()
    print('NOTE: message_delivered and message_read use the same wa_message_id')
    print('      as message_sent — they should update the same wa.message record.')
    print()

    events_to_run = {
        k: v for k, v in EVENTS.items()
        if filter_type is None or k == filter_type
    }

    if not events_to_run:
        print(f'Unknown event type: {filter_type!r}')
        print(f'Valid types: {", ".join(EVENTS)}')
        sys.exit(1)

    passed = 0
    failed = 0
    for name, event in events_to_run.items():
        if run_test(name, event):
            passed += 1
        else:
            failed += 1

    print()
    print(f'Results: {passed} passed, {failed} failed')
    if failed:
        print()
        print('To see what Odoo logged:')
        print('  make logs-odoo | grep wa_push')
        print('  (or check Settings → Technical → WA Event Log in the Odoo UI)')
        sys.exit(1)


if __name__ == '__main__':
    main()
