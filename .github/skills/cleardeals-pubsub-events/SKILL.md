---
name: cleardeals-pubsub-events
description: >
  Adds, audits, and debugs GCP Pub/Sub event publishing from any Odoo model
  in the Cleardeals codebase. Use this skill whenever the user wants to: publish
  a new event from an Odoo model (create/write/unlink/button action), add a new
  Pub/Sub topic, wire up a new workflow trigger, connect a new downstream service,
  or debug why an event is not arriving. Trigger on: "publish an event", "trigger
  a workflow", "new pub/sub event", "add a topic", "actor.created", "event not
  arriving", "workflow not firing", "connect this to the workflow engine",
  "pub/sub integration", "event payload", "postcommit", "cleardeals.pubsub",
  or any request to make an Odoo action produce a Pub/Sub message. Always use
  this skill for Pub/Sub work — it contains the architecture, the exact API
  contract, all known edge cases, and the test pattern.
---

# Cleardeals Pub/Sub Event Publisher

You add Pub/Sub event publishing to Odoo models. Every event you produce must
be safe (no spurious fires on rollback), correctly encoded (no double-encoding),
and testable end-to-end against the local emulator before touching production.

---

## Architecture Overview

```
Odoo ORM hook (create / write / unlink / button)
  │
  ├─ pre-write snapshot (for write diffs)
  │
  ├─ super().create() / super().write()
  │
  └─ env.cr.postcommit.add(_publish)   ← deferred AFTER SQL COMMIT
                │
                ▼
       cleardeals.pubsub.publish_async(topic_name, payload_dict)
                │
                ▼
       google-cloud-pubsub BatchThread  ← async, non-blocking
                │
                ▼
       GCP Pub/Sub topic  (or local emulator at host.docker.internal:8085)
                │
          ┌─────┴──────────────────────┐
          ▼                            ▼
   workflow-engine sub           other downstream subs
```

**Key invariant**: the `postcommit` callback runs only after the Odoo transaction
commits successfully. A DB rollback means no event is ever published. This is
mandatory — never call `publish_async` directly inside a model method.

---

## The Two Files You Always Touch

### 1. `custom_addons/wa_communication/models/wa_lead_event_publisher.py`

All lead-related events live here. The pattern:

```python
import logging
from odoo import api, models

_logger = logging.getLogger(__name__)

_TOPIC_ACTOR    = 'wa_communication.topic_actor_events'
_TOPIC_VISIT    = 'wa_communication.topic_visit_events'
_TOPIC_PROPERTY = 'wa_communication.topic_property_events'
_TOPIC_CUSTOMER = 'wa_communication.topic_customer_events'


class WaLeadEventPublisher(models.Model):
    _inherit = 'leads.new'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._wa_schedule_publish(
                _TOPIC_ACTOR,
                rec._wa_lead_payload('actor.created'),
            )
        return records

    def write(self, vals):
        # Always snapshot BEFORE super() for any field you need to diff
        pre = {rec.id: {'field': rec.field} for rec in self} if 'field' in vals else {}
        result = super().write(vals)
        for rec in self:
            snap = pre.get(rec.id, {})
            if 'field' in vals and rec.field != snap.get('field'):
                rec._wa_schedule_publish(_TOPIC_ACTOR, rec._wa_lead_payload('event.name'))
        return result

    def _wa_lead_payload(self, event_type: str) -> dict:
        self.ensure_one()
        return {
            'event_type':    event_type,
            'actor_type':    'buyer_inquiry',   # REQUIRED by workflow engine — never None
            'actor_id':      self.id,            # REQUIRED by workflow engine — never None
            'lead_id':       self.id,
            'customer_name': self.name,
            'phone':         self.phone or '',
            'current_status': self.current_status or '',
            'rm_user_id':    self.user_id.id or None,
            'rm_name':       self.user_id.name or '',
            'source':        self.source_id.name or '',
        }

    def _wa_schedule_publish(self, topic_key: str, payload: dict) -> None:
        self.ensure_one()
        topic = self.env['ir.config_parameter'].sudo().get_param(topic_key, '')
        if not topic:
            _logger.debug(
                "wa_lead_event: topic key %r not configured — event %r skipped for lead %s",
                topic_key, payload.get('event_type'), self.id,
            )
            return

        def _publish():
            try:
                self.env['cleardeals.pubsub'].publish_async(topic, payload)
            except Exception:
                _logger.exception(
                    "wa_lead_event: publish_async failed for event=%r lead=%s topic=%s",
                    payload.get('event_type'), self.id, topic,
                )

        self.env.cr.postcommit.add(_publish)
```

### 2. `custom_addons/wa_communication/data/wa_communication_config_data.xml`

All topic names are stored as `ir.config_parameter` records so they can be
changed per-environment without a code deploy. Every new topic needs a record here.

```xml
<data noupdate="1">
    <record id="param_topic_actor_events" model="ir.config_parameter">
        <field name="key">wa_communication.topic_actor_events</field>
        <field name="value">cd-prod-actor-events</field>
    </record>
</data>
```

`noupdate="1"` means the value is set on first install only. Module upgrades
(`-u wa_communication`) will NOT overwrite it. This is required because
prod/staging/local all need different topic names.

**After every `-u wa_communication` on dev**, re-apply the local value:
```sql
UPDATE ir_config_parameter
   SET value = 'cd-local-actor-events'
 WHERE key = 'wa_communication.topic_actor_events';
```

---

## The `cleardeals.pubsub` API

```python
# Fire-and-forget from any ORM hook (always use this in postcommit callbacks)
self.env['cleardeals.pubsub'].publish_async(
    'cd-local-actor-events',    # full topic name from config param
    {'event_type': 'actor.created', 'actor_type': 'buyer_inquiry', ...},
)

# Blocking publish — only for cron jobs, never in request/ORM hooks
msg_id = self.env['cleardeals.pubsub'].publish_sync(
    'cd-local-actor-events',
    {'event_type': 'actor.created', ...},
    timeout=30,
)
```

`publish_async` serialises the dict to JSON bytes internally via
`_encode_payload`. **Never pre-encode the payload yourself.** Passing `bytes`
as the `payload` argument causes double-encoding where the bytes object gets
serialised as the string `"b'...'"` — this is the most common bug in this
codebase.

---

## Standard Event Payload Contract

Every payload MUST include these fields. The workflow engine has NOT NULL
constraints on `actor_type` and `actor_id`. Missing either causes an
`IntegrityError` on upsert.

| Field | Type | Notes |
|---|---|---|
| `event_type` | `str` | Dot-notation name e.g. `actor.created` |
| `actor_type` | `str` | Always `'buyer_inquiry'` for `leads.new` records |
| `actor_id` | `int` | Always `self.id` — the Odoo record ID |
| `phone` | `str` | E.164 without `+`, empty string if unknown |

Additional fields are topic-specific. Extend `_wa_lead_payload()` with keyword
args or spread with `{**rec._wa_lead_payload('event.name'), 'extra': val}`.

---

## How To Add a New Event — Step by Step

### Step 1 — Decide which trigger

| Trigger | How |
|---|---|
| Record created | Override `create()` after `super()` |
| Field changed on write | Snapshot before `super()`, compare after |
| Button / wizard action | Call `rec._wa_schedule_publish(...)` at the end of the method |
| Status machine transition | Add the new status to the relevant dict constant |

### Step 2 — Decide which topic

| Topic key | When to use |
|---|---|
| `_TOPIC_ACTOR` | Lead/actor lifecycle: created, RM assigned, status updates |
| `_TOPIC_VISIT` | Site visit: scheduled, done, rescheduled |
| `_TOPIC_PROPERTY` | Property linked, changed, or removed |
| `_TOPIC_CUSTOMER` | Customer name or phone updated |

If the event fits none of the above, add a new topic (Step 2a below).

### Step 2a — Adding a new topic (if needed)

1. Add a constant at the top of `wa_lead_event_publisher.py`:
   ```python
   _TOPIC_MY_NEW = 'wa_communication.topic_my_new_events'
   ```

2. Add an `ir.config_parameter` record in `wa_communication_config_data.xml`
   inside the existing `<data noupdate="1">` block:
   ```xml
   <record id="param_topic_my_new_events" model="ir.config_parameter">
       <field name="key">wa_communication.topic_my_new_events</field>
       <field name="value">cd-prod-my-new-events</field>
   </record>
   ```

3. Create the topic on the local emulator if it doesn't exist:
   ```bash
   curl -s -X PUT "http://localhost:8085/v1/projects/cleardeals-wa-local/topics/cd-local-my-new-events"
   ```

4. After upgrading the module, set the dev value:
   ```sql
   UPDATE ir_config_parameter
      SET value = 'cd-local-my-new-events'
    WHERE key = 'wa_communication.topic_my_new_events';
   ```

### Step 3 — Write the hook

For a **create** event:
```python
@api.model_create_multi
def create(self, vals_list):
    records = super().create(vals_list)
    for rec in records:
        rec._wa_schedule_publish(_TOPIC_ACTOR, rec._wa_lead_payload('actor.created'))
    return records
```

For a **write** event (field diff):
```python
def write(self, vals):
    if 'my_field' in vals:
        pre = {rec.id: rec.my_field for rec in self}
    else:
        pre = {}

    result = super().write(vals)

    for rec in self:
        if rec.id in pre and rec.my_field != pre[rec.id]:
            rec._wa_schedule_publish(
                _TOPIC_ACTOR,
                {**rec._wa_lead_payload('my_field.changed'), 'my_field': rec.my_field},
            )

    return result
```

For a **status dict** event, add to the relevant constant:
```python
_ACTOR_STATUS_EVENTS = {
    ...
    'my_new_status': 'my_event.name',
}
```

### Step 4 — Upgrade and fix config params

```bash
docker exec odoo-dev-app /opt/odoo-venv/bin/python3 /usr/bin/odoo \
    -d cleardeals_19_dev --stop-after-init -u wa_communication --no-http

docker exec odoo-dev-app bash -c "PGPASSWORD=odoo psql -h db -U odoo \
    -d cleardeals_19_dev -c \"UPDATE ir_config_parameter \
    SET value = 'cd-local-actor-events' \
    WHERE key = 'wa_communication.topic_actor_events';\""
```

Always re-pin all local topic params after an upgrade. The `noupdate="1"` flag
protects the DB value starting from the SECOND upgrade onwards. The first
upgrade after changing the XML still resets it.

### Step 5 — Write the integration test

Copy `scripts/test_lead_actor_created.py` as a template. Key sections:

```python
# 1. Create test subscription BEFORE triggering the event
ensure_test_subscription()   # idempotent — uses AlreadyExists exception

# 2. Trigger via Odoo shell (docker exec -i)
run_odoo_shell()             # outputs JSON with the new record ID

# 3. Pull and validate
payload = pull_from_subscription(timeout_s=20)

# 4. Assert required fields
assert payload['event_type'] == 'my.event'
assert payload['actor_type'] == 'buyer_inquiry'
assert payload['actor_id'] == record_id
```

The test subscription is separate from the live subscriber. It receives its own
copy of every message on the topic. Always create it BEFORE triggering the
action — messages published before the subscription exists are lost.

---

## Edge Cases and Rules

### 1. Double-encoding (most common bug)

**Wrong:**
```python
data = json.dumps(payload).encode()          # bytes
self.env['cleardeals.pubsub'].publish_async(topic, data)   # WRONG — bytes as payload
```

**Correct:**
```python
self.env['cleardeals.pubsub'].publish_async(topic, payload)  # dict
```

`publish_async` calls `_encode_payload(payload)` internally. The `payload`
argument must always be a `dict`.

### 2. postcommit is mandatory

**Wrong:**
```python
def create(self, vals_list):
    records = super().create(vals_list)
    self.env['cleardeals.pubsub'].publish_async(topic, payload)  # WRONG
    return records
```

**Correct:**
```python
def create(self, vals_list):
    records = super().create(vals_list)
    for rec in records:
        rec._wa_schedule_publish(_TOPIC_ACTOR, rec._wa_lead_payload('actor.created'))
    return records
```

If the Odoo transaction rolls back after `publish_async` is called directly, a
spurious event is published. The workflow engine will try to start a workflow
for a lead that doesn't exist.

### 3. write() — always snapshot before super()

```python
def write(self, vals):
    if 'current_status' in vals:
        pre = {rec.id: rec.current_status for rec in self}   # BEFORE super()
    else:
        pre = {}
    result = super().write(vals)     # DB changes happen here
    for rec in self:
        if rec.id in pre and rec.current_status != pre[rec.id]:
            # now rec.current_status is the NEW value
            ...
    return result
```

If you snapshot after `super()`, both `pre` and the current value are the same
new value — you can never detect the change.

### 4. actor_type and actor_id are REQUIRED

The workflow engine's `workflow_executions` table has NOT NULL constraints on
`actor_type` and `actor_id`. Any event missing these fields causes:

```
sqlalchemy.exc.IntegrityError: ... null value in column "actor_type"
```

For all `leads.new` events: `actor_type = 'buyer_inquiry'`, `actor_id = self.id`.
These must be in every payload built by `_wa_lead_payload`.

### 5. Recommended vs primary inquiries

Both primary and recommended inquiries (`inquiry_type = 'primary'|'recommended'`)
on `leads.new` produce the same `actor.created` event. The `inquiry_type` field
is included in the payload for the workflow engine to branch on. If you only
want to fire for primary inquiries, check `self.inquiry_type != 'recommended'`
before calling `_wa_schedule_publish`.

### 6. Short-lived processes (shell / tests) don't flush the batch

`publish_async` enqueues in a `BatchThread`. The thread is flushed when the
process exits cleanly OR when `client.stop()` is called. In the Odoo shell or
integration test scripts, call `stop()` after `commit()`:

```python
env.cr.commit()
import time; time.sleep(1)
import odoo.addons.cleardeals_pubsub.models.pubsub_publisher as _pub_mod
_pc = _pub_mod._publisher_client
if _pc is not None:
    _pc.stop()
```

Use `_pub_mod._publisher_client` (attribute access on the module), not
`from module import _publisher_client` (which copies the reference at import
time and won't see the client created after import).

### 7. Topic name in config param vs full path

`ir.config_parameter` stores the short topic name: `cd-local-actor-events`.

`cleardeals.pubsub._topic_path()` builds the full path:
`projects/cleardeals-wa-local/topics/cd-local-actor-events`.

Pass the short name from the config param to `publish_async`. Never hard-code
the full `projects/...` path.

### 8. Checking if the emulator has the topic

```bash
curl -s "http://localhost:8085/v1/projects/cleardeals-wa-local/topics" | python3 -m json.tool
```

Create a missing topic:
```bash
curl -s -X PUT "http://localhost:8085/v1/projects/cleardeals-wa-local/topics/cd-local-new-topic"
```

### 9. Verifying config params in the running DB

```bash
docker exec odoo-dev-app bash -c "PGPASSWORD=odoo psql -h db -U odoo \
    -d cleardeals_19_dev \
    -c \"SELECT key, value FROM ir_config_parameter WHERE key LIKE 'wa_communication.topic_%';\""
```

### 10. Tracing a missing event

If the event never arrives on the subscription:

1. Check the config param is set to the correct local topic name (not the prod value).
2. Check the Odoo container logs for `publish_async failed` or `topic key not configured`.
3. Check `PUBSUB_PROJECT_ID` inside the container matches the project in the emulator URL.
4. Check that the test subscription was created BEFORE the event was triggered.
5. Check for double-encoding (`b'...'` string in the payload).

```bash
# Odoo publish errors
docker logs odoo-dev-app 2>&1 | grep -i "pubsub\|publish" | tail -20

# PUBSUB_PROJECT_ID inside the container
docker exec odoo-dev-app env | grep PUBSUB
```

---

## Existing Events Reference

| Event type | Topic key | Trigger |
|---|---|---|
| `actor.created` | `_TOPIC_ACTOR` | `leads.new.create()` |
| `lead_contacted` | `_TOPIC_ACTOR` | `current_status → 'lead'` |
| `lead_busy` | `_TOPIC_ACTOR` | `current_status → 'busy'` |
| `lead_call_back_later` | `_TOPIC_ACTOR` | `current_status → 'call_back_later'` |
| `lead_closed` | `_TOPIC_ACTOR` | `current_status → 'requirement_closed'` |
| `lead_no_requirements` | `_TOPIC_ACTOR` | `current_status → 'no_requirements'` |
| `lead_rm_assigned` | `_TOPIC_ACTOR` | `user_id` changed |
| `site_visit_scheduled` | `_TOPIC_VISIT` | `current_status → 'site_visit_scheduled'` |
| `site_visit_done` | `_TOPIC_VISIT` | `current_status → 'site_visit_done'` |
| `site_visit_rescheduled` | `_TOPIC_VISIT` | `current_status → 'rescheduled'` |
| `lead_property_linked` | `_TOPIC_PROPERTY` | `property_base_id` changed |
| `customer_updated` | `_TOPIC_CUSTOMER` | `phone` or `name` changed |

---

## Integration Test Template

```python
#!/usr/bin/env python3
"""Integration test: <describe what this verifies>."""

import json, os, subprocess, sys, time

ODOO_DB        = os.environ.get('ODOO_DB', 'cleardeals_19_dev')
ODOO_CONTAINER = os.environ.get('ODOO_CONTAINER', 'odoo-dev-app')
EMULATOR_HOST  = os.environ.get('PUBSUB_EMULATOR_HOST', 'localhost:8085')
GCP_PROJECT    = os.environ.get('GCP_PROJECT', 'cleardeals-wa-local')
GCP_ENV        = os.environ.get('GCP_ENV', 'local')
os.environ['PUBSUB_EMULATOR_HOST'] = EMULATOR_HOST

TOPIC_NAME    = f'cd-{GCP_ENV}-actor-events'
TEST_SUB_NAME = f'cd-{GCP_ENV}-actor-events-my-test-sub'

_ODOO_SHELL_SCRIPT = r"""
import json, sys, time

# ... create/modify the Odoo record ...

env.cr.commit()
time.sleep(1)
try:
    import odoo.addons.cleardeals_pubsub.models.pubsub_publisher as _pub_mod
    _pc = _pub_mod._publisher_client
    if _pc is not None:
        _pc.stop()
except Exception as _e:
    sys.stderr.write(f'[warn] could not flush publisher: {_e}\n')

print(json.dumps({'record_id': record.id}))
"""

def ensure_test_subscription():
    from google.api_core.exceptions import AlreadyExists
    from google.cloud import pubsub_v1
    sub = pubsub_v1.SubscriberClient()
    topic = f'projects/{GCP_PROJECT}/topics/{TOPIC_NAME}'
    path  = sub.subscription_path(GCP_PROJECT, TEST_SUB_NAME)
    try:
        sub.create_subscription(request={'name': path, 'topic': topic, 'ack_deadline_seconds': 30})
        print(f'[pubsub] created {TEST_SUB_NAME}')
    except AlreadyExists:
        print(f'[pubsub] using existing {TEST_SUB_NAME}')
    finally:
        sub.close()

def pull_from_subscription(timeout_s=20):
    from google.cloud import pubsub_v1
    sub  = pubsub_v1.SubscriberClient()
    path = sub.subscription_path(GCP_PROJECT, TEST_SUB_NAME)
    dead = time.monotonic() + timeout_s
    while time.monotonic() < dead:
        resp = sub.pull(request={'subscription': path, 'max_messages': 1}, timeout=3)
        if resp.received_messages:
            msg = resp.received_messages[0]
            sub.acknowledge(request={'subscription': path, 'ack_ids': [msg.ack_id]})
            payload = json.loads(msg.message.data.decode())
            sub.close()
            return payload
        time.sleep(0.5)
    sub.close()
    return None

def run_odoo_shell():
    result = subprocess.run(
        ['docker', 'exec', '-i', ODOO_CONTAINER,
         '/opt/odoo-venv/bin/python3', '/usr/bin/odoo',
         'shell', '-d', ODOO_DB, '--no-http'],
        input=_ODOO_SHELL_SCRIPT.encode(),
        capture_output=True, timeout=90,
    )
    stdout = result.stdout.decode(errors='replace')
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith('{') and 'record_id' in line:
            return json.loads(line)
    print('ERROR: no JSON from shell'); print(stdout[-2000:]); sys.exit(1)

def main():
    ensure_test_subscription()
    odoo = run_odoo_shell()
    payload = pull_from_subscription()
    if payload is None:
        print('FAIL — no message received'); sys.exit(1)
    print(json.dumps(payload, indent=2))
    # assertions here
    assert payload['event_type'] == 'actor.created', payload
    assert payload['actor_type'] == 'buyer_inquiry', payload
    assert payload['actor_id'] == odoo['record_id'], payload
    print('PASS')

if __name__ == '__main__':
    main()
```

---

## Quick Reference — Local Dev Commands

```bash
# Upgrade module
docker exec odoo-dev-app /opt/odoo-venv/bin/python3 /usr/bin/odoo \
    -d cleardeals_19_dev --stop-after-init -u wa_communication --no-http

# Re-pin ALL local topic params after upgrade
docker exec odoo-dev-app bash -c "PGPASSWORD=odoo psql -h db -U odoo \
    -d cleardeals_19_dev -c \"
    UPDATE ir_config_parameter SET value='cd-local-actor-events'    WHERE key='wa_communication.topic_actor_events';
    UPDATE ir_config_parameter SET value='cd-local-visit-events'    WHERE key='wa_communication.topic_visit_events';
    UPDATE ir_config_parameter SET value='cd-local-property-events' WHERE key='wa_communication.topic_property_events';
    UPDATE ir_config_parameter SET value='cd-local-customer-events' WHERE key='wa_communication.topic_customer_events';
    UPDATE ir_config_parameter SET value='cd-local-odoo-wa-requests' WHERE key='wa_communication.topic_odoo_wa_requests';
    \""

# List emulator topics
curl -s "http://localhost:8085/v1/projects/cleardeals-wa-local/topics" | python3 -m json.tool

# Run actor.created integration test
.venv/bin/python scripts/test_lead_actor_created.py

# Run WA send integration test
.venv/bin/python scripts/test_odoo_to_wa_integration.py
```
