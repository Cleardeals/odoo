# cleardeals_pubsub — Known Gaps & Improvement Path

Status: **open / deferred.** Documented 2026-08-03. Not scheduled.

---

## 1. In-flight messages are lost when a worker exits

### Severity

High. Causes silent, permanent, unrecoverable message loss with **no error
logged anywhere**. Has occurred at least twice in staging (see Evidence).

### What happens

`publish_async()` is called from `cr.postcommit` callbacks, e.g. in
`wa_communication/models/wa_conversation_outbound.py`:

```python
def _publish():
    self.env['cleardeals.pubsub'].publish_async(topic, request_data)

self.env.cr.postcommit.add(_publish)
```

The full sequence for an outbound WhatsApp message:

```
1. INSERT wa.message row, status='queued'     ← inside the DB transaction
2. cr.postcommit.add(_publish)                ← a callback in RAM
3. COMMIT                                     ← row is durable in Postgres
4. postcommit runs → publish_async()
5. client.publish() appends to an in-memory batch   ← NOTHING sent yet
6. publish_async() returns; HTTP response goes to the RM
7. ...later... a daemon BatchThread flushes the batch over the network
```

Step 5 is the trap. `client.publish()` performs no network I/O. It appends to a
buffer owned by the process-level `PublisherClient` and returns a future. The
RPC happens on a background thread once a batch threshold trips — with our
tuned `_BATCH_SETTINGS`: 512 KiB, 50 messages, or **50 ms** elapsed.

Between steps 5 and 7 the message exists in exactly one place: **the heap of
that Odoo worker process.** It is not in Postgres as a pending item, not in
Pub/Sub, not on disk. The `wa.message` row reads `queued`, but that means only
"Odoo intended to send this" — it is not a queue that anything drains.

If the process dies in that window, the message is gone permanently. Nothing
retries, because nothing knows there is anything to retry.

### Why it is silent

`publish_async` has two error paths, and neither can fire here:

- the `try/except` around `client.publish()` — only catches failure to *enqueue*
- `future.add_done_callback(...)` — only logs if the publish *attempt* fails

Both require the process to still be alive. When the worker is killed mid-batch
the callback never runs and the `except` never executes. No error, no warning,
no traceback, in any service.

### This is NOT only an OOM problem

From the installed `google/cloud/pubsub_v1/publisher/_batch/thread.py`:

```python
commit_thread = threading.Thread(
    name="Thread-CommitBatchPublisher", target=self._commit, daemon=True
)
```

`daemon=True`. Python kills daemon threads abruptly at interpreter shutdown
without joining them. `cleardeals_pubsub` registers no `atexit` hook, no
`client.stop()`, and no flush-on-shutdown of any kind.

Therefore **any** worker exit drops in-flight messages:

- `limit_memory_hard` SIGKILL / OOM killer
- `limit_memory_soft` graceful recycle
- a deploy or `docker compose up -d`
- a config reload or admin restart

A deploy is arguably worse than an OOM kill, because it terminates every worker
simultaneously.

Raising `limit_memory_soft` (done 2026-08-02) and capping media uploads reduce
how often the trigger fires — staging went from 58 memory-limit recycles in one
day to 0 — but they **cannot** fix this. They narrow the window; they do not
close it.

### Why the current design is otherwise correct

The `postcommit` deferral is deliberate. Publishing *before* commit causes the
opposite bug: the consumer picks up the message and queries Postgres for a row
that has not committed yet. That race is already handled defensively in
wa-sender's `enrollment_not_found` branch, which nacks rather than acks
precisely because "not found" usually means "not committed yet."

So the design correctly avoids publish-before-commit, but lands on the classic
**dual-write problem**: two systems (Postgres, Pub/Sub) must both be updated
with no transaction spanning them. Commit-then-publish moves the failure window
rather than removing it.

### Evidence

**Incident A — lost media send (2026-07-18).** Three images were uploaded to
919023283799 within one second. Two published cleanly with full traces through
odoo-bridge → wa-sender → Interakt:

| Odoo msg | request_id | Result |
|---|---|---|
| 23 | `48336df4-4b5c-43cd-94c3-f5f55992fc7d` | delivered, full trace |
| 22 | `a54cf119-0d03-4a8c-89d8-040e0c74c65c` | delivered, full trace |
| 24 | `cdf67eef-64cf-4049-9cb5-5736de4b0986` | **zero log lines anywhere, no platform DB row** |

Message 24 never left Odoo. It sat at `queued` for 16 days until manually
resolved to `failed` on 2026-08-03.

**Incident B — lost reassignment request (2026-08-01).** Request #15 committed
as `confirming` with `request_id=0c1edde9`, which appears nowhere in platform
logs. The RM was left unable to request the chat, with no button and no error.
That day had 58 memory-limit worker deaths, with workers dying every 30–60s
during the affected window, driven by 37/77/86 MB video uploads.

Both incidents share the signature: **a committed Odoo row, and no trace of the
message in any downstream service.**

---

## Improvement path

### Fix 1 — flush on shutdown (small, partial)

Register an `atexit` hook that calls `client.stop()`, which blocks until
outstanding batches commit. Roughly ten lines in `pubsub_publisher.py`.

- **Fixes:** graceful exits — deploys, restarts, `limit_memory_soft` recycles.
  Probably the majority of real-world losses.
- **Does not fix:** `SIGKILL` from `limit_memory_hard` or the OOM killer, since
  no Python handler runs.
- **Risk:** a slow or hung flush delays worker shutdown. Bound it with a timeout.

### Fix 2 — synchronous publish (rejected)

Swap `publish_async` for the existing `publish_sync`, which blocks on the ack.

- **Fixes:** makes failures visible inside the request, so they can be surfaced
  to the RM immediately.
- **Does not fix:** if the process dies *during* the call, the row is still
  committed and still stranded.
- **Cost:** adds a Pub/Sub round-trip (tens of ms) to every send.
- **Verdict: not recommended.** Worst ratio of the three — latency on every
  send while still leaving a window open.

### Fix 3 — transactional outbox (the real fix)

Write the publish intent to a `wa_outbox` table in the **same transaction** as
the `wa.message` row, making the two atomic. A cron sweeps unsent rows,
publishes them, and marks them sent on success.

- **Fixes:** everything. If the process dies at any point, the outbox row
  survives in Postgres and the next sweep picks it up.
- **Cost:** a new table, a new cron, and consumers must tolerate duplicate
  delivery (at-least-once).
- **Duplicate tolerance is largely already there:** wa-sender's `already_sent`
  pre-send check and the `interakt_msg_id` uniqueness constraint both dedupe.
  This should be re-verified per topic before relying on it.

**Useful side effect:** the outbox makes stranded sends *queryable*. Today the
only way to find them is to diff Odoo's `queued` rows against platform logs by
hand — which is how both incidents above were found, after the fact. With an
outbox you would query for unsent rows older than N seconds, and could alert on
it.

### Recommendation

Do **Fix 1 and Fix 3**. Fix 1 is nearly free and covers the common case
immediately; Fix 3 is the only option that actually closes the hole. Skip
Fix 2.

---

## Detecting the problem in the meantime

Stuck sends surface as `wa.message` rows left at `status='queued'` long after
`occurred_at`. Anything older than a minute or two has almost certainly been
lost, since the normal round-trip is 1–2 seconds:

```sql
SELECT c.phone_number, m.id, m.kind, m.request_id, m.occurred_at
FROM wa_message m
JOIN wa_conversation c ON c.id = m.conversation_id
WHERE m.status = 'queued'
  AND m.occurred_at < NOW() - INTERVAL '5 minutes'
ORDER BY m.occurred_at;
```

To confirm a specific one was truly lost rather than merely slow, check whether
the `request_id` appears anywhere downstream:

```bash
gcloud logging read 'resource.labels.namespace_name="wa-automation" AND jsonPayload.request_id="<request_id>"' \
  --project=cleardeals-wa-prod --freshness=30d --limit=20 \
  --format='value(timestamp,resource.labels.container_name,jsonPayload.event)'
```

No rows returned = the message never left Odoo.
