# Error Handling — Odoo

Handle errors deliberately. In Odoo "deliberate" has a specific meaning
because of the transaction model (every request is one DB transaction that
commits or rolls back) and the Pub/Sub at-least-once delivery the platform
relies on.

---

## Raise the right exception for the audience

```python
from odoo.exceptions import UserError, ValidationError

# User did something we can't fulfil → tell THEM, in plain language.
if self.window_state != 'open':
    raise UserError(
        "The 24-hour WhatsApp window is closed. You can only send templates "
        "until the customer replies.")

# A data invariant was violated → ValidationError (constraint-shaped).
def _check_phone(self):
    for rec in self:
        if not rec.phone_number:
            raise ValidationError("A conversation needs a phone number.")
```

`UserError` is for things the user can act on. `ValidationError` is for
broken invariants. Never use a bare `Exception` to signal these.

---

## The ONE sanctioned swallow: non-critical side effects

The generic rule "never swallow exceptions" has exactly one exception in
this repo: a **side effect whose failure must not roll back the real work**
— a Pub/Sub publish, a `bus.bus` notification, an analytics/telemetry write.
These are wrapped, **logged**, and **commented** with *why* swallowing is
correct.

```python
# ✅ Sanctioned: a broadcast failure must never break the create/write path.
def _broadcast_message_log_update(self):
    try:
        self.env['bus.bus']._sendone('wa_message_log', 'wa_message_update',
                                     {'ts': fields.Datetime.now().isoformat()})
    except Exception:
        pass  # never let a notification hiccup break the message write

# ✅ Sanctioned: orphan-relink is best-effort; a WA hiccup must not block
#    lead creation.
try:
    self.env['wa.conversation'].sudo()._owa_relink_orphan_for_lead(rec)
except Exception:
    _logger.warning("wa: orphan relink failed for lead %s", rec.id, exc_info=True)
```

Rules for a sanctioned swallow:
- It must be a *non-critical side effect*, never the core operation.
- It must log (`_logger.warning/exception(..., exc_info=True)`), except the
  hot-path broadcast where a comment alone is acceptable.
- It must carry a comment stating why failure is safe to ignore.

Everything else that looks like this is a bug-hider:

```python
# ❌ swallows a real failure — the user sees success, the work didn't happen
try:
    self._do_the_actual_thing()
except Exception:
    pass
```

---

## Concurrency errors are RE-RAISED, never swallowed

The push controller deliberately re-raises serialization/deadlock errors so
Odoo's `service.model.retrying` reruns the request in a fresh transaction.
Swallowing these silently *loses writes* (a `read` receipt, a `seen_at`).

```python
import psycopg2
_PG_RETRY_ERRORS = (psycopg2.errorcodes.SERIALIZATION_FAILURE,
                    psycopg2.errorcodes.DEADLOCK_DETECTED)

try:
    self._dispatch(...)
except psycopg2.OperationalError as exc:
    if exc.pgcode in _PG_RETRY_ERRORS:
        _logger.info("concurrency conflict (pgcode=%s) — retrying %s",
                     exc.pgcode, pubsub_message_id)
        raise                      # let Odoo retry on a fresh transaction
    _logger.exception("dispatch failed for %s", pubsub_message_id)
```

A catch-all that swallows `OperationalError` would defeat the retry and
drop data. Specific first, re-raise the retryable, then handle the rest.

---

## Don't lose context

```python
# ❌ context destroyed
except Exception:
    raise UserError("Send failed")

# ✅ specific handling preserves the real reason; unexpected errors propagate
except interakt_client.InteraktError as exc:
    raise UserError("WhatsApp send failed: %s" % exc.user_message)
except Exception:
    _logger.exception("unexpected send failure for conv %s", self.id)
    raise
```

---

## sudo() is error handling's cousin — use it deliberately

`sudo()` bypasses access rules. It is a scoped, justified escalation, never a
blanket "make the error go away." Each use carries a reason.

```python
# ✅ scoped + justified
# sudo(): read-only telemetry snapshot; the calling RM may lack property.base
#         ACL but this metadata never surfaces to them.
prop = self.property_base_id.sudo()

# ❌ unexplained blanket bypass hiding a genuine AccessError
record.sudo().write(vals)   # why? whose rule? — comment or don't sudo
```

If you reach for `sudo()` to silence an `AccessError`, first ask whether the
access rule is wrong, or whether only a *specific read* needs escalation.
