# 08 — Controllers and HTTP

[← Security](07-security.md) · [Index](00-INDEX.md) · [Next: Sessions →](09-sessions.md)

---

Most of Odoo's UI needs no controller — the web client and the generic
`call_kw` bridge cover it. You write a controller when something *outside*
Odoo needs to talk to it: a webhook, a REST API, a file upload, a push
subscription. We have all four.

## 8.1 How a controller gets found

```python
from odoo import http


class MyController(http.Controller):

    @http.route("/my/endpoint", type="http", auth="user", methods=["GET"])
    def my_endpoint(self, **kwargs):
        return request.make_json_response({"ok": True})
```

Subclassing `http.Controller` registers the class; `@http.route` registers each
method into the routing map, which is built per database from all installed
modules. Controllers must live in a `controllers/` package that is imported from
the module's `__init__.py` — the same import-chain rule as models
([Chapter 05](05-writing-a-module.md)).

> **Trap.** Routes are collected when the registry loads. A **new** controller
> file needs a server restart, not just `-u`. If your brand-new endpoint 404s,
> restart before you debug the path.

Our full route inventory, which is a useful map of the system's edges:

| Route | Module | Type | Auth | Purpose |
|-------|--------|------|------|---------|
| `/wa/pubsub/push` | `wa_communication` | http | none | GCP Pub/Sub push receiver |
| `/wa/media/upload` | `wa_communication` | http | user | RM uploads media for a WA send |
| `/api/v1/properties` (GET, PUT) | `properties` | http | public | REST list / create |
| `/api/v1/properties/<identifier>` (GET, PATCH, DELETE) | `properties` | http | public | REST read / update / delete |
| `/api/v1/magicbricks_webhook` | `leads` | http | public | portal lead intake |
| `/api/v1/99acres_webhook` | `leads` | http | public | portal lead intake |
| `/api/v1/cleardeals_lead` | `leads` | http | public | website/app lead intake |
| `/api/v1/squareyards_webhook` | `leads` | http | public | portal lead intake |
| plus webhooks in `properties/controllers/webhooks.py` | `properties` | http | public | property sync |

## 8.2 `@http.route` — every parameter

```python
@http.route(
    "/wa/pubsub/push",
    type="http",
    auth="none",
    methods=["POST"],
    csrf=False,
    save_session=False,
    readonly=False,
)
```

| Parameter | Meaning |
|-----------|---------|
| route | A path, or a list of paths. Supports converters: `<int:id>`, `<string:identifier>`, `<path:rest>` |
| `type` | `"http"` or `"jsonrpc"` — see §8.3 |
| `auth` | `"user"`, `"public"`, `"none"` — see [Chapter 07](07-security.md) §7.7 |
| `methods` | List of allowed HTTP verbs. **Always set it.** Omitting it allows everything |
| `csrf` | CSRF protection. `False` for machine callers |
| `save_session` | `False` stops Odoo writing a session file for this request |
| `readonly` | Whether the transaction is read-only — see §8.4 |
| `cors` | e.g. `"*"` to add CORS headers |
| `website` | Only for website-module pages |

### `type="http"` vs `type="jsonrpc"`

| | `type="http"` | `type="jsonrpc"` |
|---|---|---|
| Request body | form data or raw | JSON-RPC 2.0 envelope |
| Return | a `Response`, or a string | a Python dict/list, serialised for you |
| Errors | you handle them | wrapped into a JSON-RPC error |
| Use for | webhooks, REST, file uploads/downloads | calls from OWL |

> **Trap.** In Odoo 19, **`type="json"` is a deprecated alias for
> `type="jsonrpc"`**. The source is explicit (`odoo/http.py:765`):
>
> ```
> "Since 19.0, @route(type='json') is a deprecated alias to @route(type='jsonrpc')"
> ```
>
> It still works and logs a deprecation. Write `type="jsonrpc"` in new code.

> **Our convention.** All our external-facing endpoints use `type="http"`, even
> the JSON ones, and build responses explicitly. Reason: a webhook provider
> expects plain JSON and meaningful status codes, not a JSON-RPC envelope, and
> we need control over the status code. `type="jsonrpc"` is for the OWL client
> only — and there you almost never write a controller at all, because
> `call_kw` already exists (§8.7).

### `methods` and `csrf` together

`csrf=False` disables the token check. That is mandatory for a webhook (an
external server has no token) and dangerous on anything a browser can be
tricked into calling. The rule:

> **Our convention.** `csrf=False` is only acceptable when the endpoint
> authenticates by something a browser will not send automatically — a header
> API key, a bearer token, an HMAC signature. Never `csrf=False` on an endpoint
> that trusts the session cookie.

## 8.3 `save_session=False`

Every one of our machine endpoints sets this. It stops Odoo persisting a session
file per request.

> **Our convention.** Set `save_session=False` on any endpoint called by a
> machine. Without it, a webhook hit thousands of times a day writes thousands
> of session files into the filestore, all of them useless
> ([Chapter 09](09-sessions.md) and [Chapter 10](10-filestore-and-attachments.md)).

## 8.4 `readonly` — the Odoo 19 trap

This is the single most consequential controller change in 19, and it is covered
in [Chapter 03](03-server-and-execution-modes.md) §3.5. Restated here because
this is where you will meet it:

Odoo 19 starts every request on a **read-only cursor**, and the default for
`readonly` depends on `auth` (`odoo/http.py:924`):

```python
default_mode = submethod.original_routing.get('readonly', default_auth == 'none')
```

**`auth='none'` ⇒ `readonly=True` by default.**

If such a route writes, Odoo notices the failure and re-runs the whole request on
a read/write cursor, logging `..., retrying with a read/write cursor`. In
production that silently doubles the work. Under `HttpCase` in the test suite the
retry does not rescue you and the test fails.

Our push receiver documents the fix at the call site — this comment is the model
to copy:

```python
@http.route(
    '/wa/pubsub/push',
    type='http',
    auth='none',
    methods=['POST'],
    csrf=False,
    save_session=False,
    # In Odoo 19 routes default to readonly when ``auth='none'``.  This
    # endpoint *writes* (creates conversations, messages, event-log rows),
    # so it must be explicitly read/write — otherwise the handler runs in a
    # read-only transaction and relies on the implicit readonly→readwrite
    # retry, which wastes a request in production and fails outright under
    # HttpCase.  Declaring it here keeps the write intent unambiguous.
    readonly=False,
)
```
— [`push_controller.py`](../../custom_addons/wa_communication/controllers/push_controller.py)

> **Our convention.** State `readonly` explicitly on every endpoint that writes.
> Do not rely on the default in either direction.

## 8.5 The `request` object

```python
from odoo.http import request
```

A thread-local for the current request.

| Attribute | What it gives you |
|-----------|-------------------|
| `request.env` | the Environment — models, user, cursor |
| `request.env.user` | current user (the public user for `auth="public"`) |
| `request.params` | merged query string + form body + JSON body |
| `request.httprequest` | the raw werkzeug request |
| `request.httprequest.args` | query string only |
| `request.httprequest.headers` | headers |
| `request.httprequest.files` | uploaded files |
| `request.httprequest.get_data()` | the raw body bytes |
| `request.httprequest.content_length` | declared body size, **before parsing** |
| `request.session` | the session ([Chapter 09](09-sessions.md)) |
| `request.db` | database name |
| `request.make_json_response(data, status=…)` | build a JSON response |
| `request.make_response(body, headers=…)` | build an arbitrary response |
| `request.redirect(url)` | a redirect |

> **Our convention.** For webhooks, read the **raw body** with
> `request.httprequest.get_data()` rather than `request.params`. Providers send
> JSON with varying content types, and `params` will silently give you nothing
> if the content type is not what Odoo expects. Parse it yourself and you get a
> real error instead of a mystery.

### Reading `content_length` before touching `files`

The media upload controller has a genuinely clever guard worth internalising:

```python
# ── Guard 1: pre-parse ────────────────────────────────────────────────
# Reject on Content-Length BEFORE touching request.httprequest.files —
# that attribute is what makes werkzeug parse the body and spool it to a
# temp file. ``kind`` therefore travels as a QUERY parameter, so we can
# pick the right cap without reading the body at all.
kind = (request.httprequest.args.get("kind") or "document").lower()
cap = wa_media_size_cap(kind)
declared = request.httprequest.content_length or 0
if declared > cap + _MULTIPART_OVERHEAD_BYTES:
    return request.make_json_response(
        {"error": "This %s is %s — WhatsApp allows at most %s. "
                  "Please compress it or share a link instead."
                  % (kind, wa_format_bytes(declared), wa_format_bytes(cap))},
        status=413,
    )

file = request.httprequest.files.get("file")
if not file:
    return request.make_json_response({"error": "no file"}, status=400)
```
— [`media_upload.py`](../../custom_addons/wa_communication/controllers/media_upload.py)

Two lessons:

1. **Accessing `request.httprequest.files` is what triggers werkzeug to parse
   and spool the body to disk.** Checking `content_length` first rejects an
   oversized upload without ever writing it anywhere.
2. Because of that, the discriminator (`kind`) has to arrive as a **query
   parameter**, not a form field — a form field would require parsing the body.
   That is an architectural consequence of a performance guard, and it is
   documented in the comment so nobody "tidies" it later.

## 8.6 Responses

### JSON, the framework way

```python
return request.make_json_response({"ok": True}, status=200)
```

### JSON, our REST way

The properties API wraps every response in a consistent envelope via two
helpers, so a controller needs one `return`:

```python
def success_response(data, http_status: int = 200) -> Response:
    body = json.dumps(
        {"success": True, "data": data},
        default=_json_default,
        ensure_ascii=False,
    )
    return Response(body, status=http_status, mimetype=_MIME)
```
— [`response_utils.py`](../../custom_addons/properties/controllers/response_utils.py)

Usage:

```python
return success_response({"id": 1, "name": "My Property"})
return error_response(404, "Property not found.")
return success_response(data, http_status=201)
```

> **Our convention.** A REST surface gets a single response module. Every
> endpoint returns `{"success": bool, "data": …}` or `{"success": false,
> "error": …}` with a real HTTP status. `default=_json_default` handles dates,
> and `ensure_ascii=False` keeps non-ASCII readable rather than escaping it —
> which matters for Indian names and addresses.

### Files

```python
return request.make_response(
    pdf_bytes,
    headers=[
        ("Content-Type", "application/pdf"),
        ("Content-Disposition", 'attachment; filename="report.pdf"'),
    ],
)
```

For attachments already in the filestore, prefer the built-in
`/web/content` route ([Chapter 10](10-filestore-and-attachments.md)).

## 8.7 How the web client calls the server

You will rarely write a controller for the UI, because one generic endpoint
already exists: **`POST /web/dataset/call_kw`**. It means "call this method on
this model with these arguments".

Here is a **real captured request** from this handbook's instance — our own
notification model being polled on page load:

```json
{
  "id": 0,
  "jsonrpc": "2.0",
  "method": "call",
  "params": {
    "model": "cleardeals.notification",
    "method": "get_unread",
    "args": [],
    "kwargs": {
      "context": {
        "lang": "en_US",
        "tz": "Europe/Brussels",
        "uid": 2,
        "allowed_company_ids": [1]
      }
    }
  }
}
```

The `this.orm.call(...)` in an OWL component
([Chapter 06](06-views-and-web-client.md)) becomes exactly this. Note:

- `model` and `method` are the target.
- `args` are positional, `kwargs` keyword.
- **`context` rides along in `kwargs`** — this is how `lang`, `tz`, `uid` and
  the active companies reach the server on every single call.

> **Trap — the security consequence.** `call_kw` can call **any public method on
> any model** the user has ACL access to. It is subject to ACLs and record
> rules, and to `get_public_method` (`odoo/service/model.py:44`) which blocks
> private names — but that means **a method's name is part of its security
> surface**. A method not prefixed with `_` is a remotely callable API endpoint,
> whether you meant it to be or not.
>
> **Our convention.** Any model method that is not deliberately part of a public
> API gets a leading underscore. Our `_cron_*` and `_compute_*` methods follow
> this. When you *do* expose one — like `wa.dashboard.get_metrics` — treat it as
> an API: validate every argument, and remember the caller controls them.

You can watch this traffic in your browser's Network tab, filtered to
`call_kw` — the fastest way to find out which method a screen is actually
calling.

## 8.8 Worked example — a Pub/Sub push receiver

[`push_controller.py`](../../custom_addons/wa_communication/controllers/push_controller.py)
is the most instructive controller we have. Its module docstring states the
security model up front:

```python
"""HTTP controller for the WA Pub/Sub push endpoint.

GCP Pub/Sub delivers inbound WA events (messages, receipts, bridge ACKs) to
``POST /wa/pubsub/push`` with a Google-signed OIDC JWT in the
``Authorization: Bearer <token>`` header.

Security model
--------------
1. Token verification:  :func:`verify_push_token` from ``cleardeals_pubsub``
   validates the OIDC JWT, checks the ``aud`` claim against
   ``wa_communication.inbound_push_audience``, and optionally asserts the
   signing service account email against
   ``wa_communication.inbound_push_sa_email``.

2. Token verification is skipped when ``PUBSUB_EMULATOR_HOST`` is set so the
   local Pub/Sub emulator can push events without real JWTs.

3. The controller always returns HTTP 200 once the envelope has been parsed,
   even if message processing fails — this prevents GCP from retrying the
   delivery indefinitely.  Processing errors are logged to ``wa.event.log``.

4. Invalid envelopes (malformed JSON, missing ``message.data``) return HTTP
   200 too (logged, dropped).  Only authentication failures return 401.
"""
```

Four design decisions in there, each generalisable:

**1. Authenticate by header, not session.** An unauthenticated route
(`auth='none'`) that does its own OIDC verification. This is the right shape for
any machine caller.

**2. Return 200 even on failure — deliberately.** Pub/Sub retries non-2xx
responses, with backoff, indefinitely. A poison message that always fails would
be redelivered forever. So the controller acknowledges the delivery and records
the failure in `wa.event.log` for a human to look at. **Only auth failures
return 401**, because those are worth retrying after a token refresh.

> **Our convention.** For any at-least-once delivery source, decide explicitly
> what your status code means to the *sender*. "Success" often means "I have
> durably taken responsibility for this", not "I processed it correctly".

**3. Do not swallow concurrency errors.** Covered in
[Chapter 03](03-server-and-execution-modes.md), and it lives here:

```python
# Postgres concurrency errors that must NOT be swallowed: a serialization
# failure or deadlock means the transaction has to be retried in a FRESH one
# (Odoo runs the request inside ``service.model.retrying``, which does exactly
# that).  Swallowing them here would silently drop the event's writes — e.g. a
# 'read' status + seen_at lost because a concurrent 'delivered' event touched
# the same wa.message row.
_PG_RETRY_ERRORS = (
    psycopg2.errorcodes.SERIALIZATION_FAILURE,
    psycopg2.errorcodes.DEADLOCK_DETECTED,
)
```

The general shape of a catch-all that is still correct:

```python
try:
    self._process(payload)
except psycopg2.Error as exc:
    if exc.pgcode in _PG_RETRY_ERRORS:
        raise                       # let the framework retry in a fresh txn
    _log_to_event_log(exc)
except Exception:                   # noqa: BLE001 — see docstring point 3
    _log_to_event_log(...)
return _ack()
```

Note that a broad `except` here is a *considered* exception to the no-blind-catch
rule, justified in the docstring, with the retryable class re-raised first. That
is how to break a convention properly.

**4. Correlate logs across the boundary.**

```python
# Make every log line emitted while handling a /wa/pubsub/push request carry the
# platform-supplied [trace=<id>] prefix. Idempotent; a no-op outside such requests.
install_trace_filter()
```

The trace id is generated by the GCP platform and travels in the message, so one
customer interaction can be followed across both systems.
[Chapter 16](16-debugging-and-ops.md) covers using it.

## 8.9 Worked example — an authenticated REST API

The properties API is `auth="public"` plus an API key. The key lives in
`ir.config_parameter`:

```python
_API_KEY_PARAM = "properties.api_key"
_HEADER_NAME = "X-API-Key"


def validate_api_key(request: http.Request):
    """Validate the ``X-API-Key`` header against the value stored in
    ``ir.config_parameter``."""
    # 1. Read the expected key from system parameters.
    #    Use sudo() so the config param is accessible regardless of the
    #    caller's session user (public/portal/internal).
    expected_key = (
        request.env["ir.config_parameter"].sudo().get_param(_API_KEY_PARAM, default="")
    )

    if not expected_key:
        _logger.warning(
            "Properties API: system parameter '%s' is not set. "
            "All API requests will be rejected until it is configured.",
            _API_KEY_PARAM,
        )
        return False, error_response(503, ...)
```
— [`properties/controllers/auth.py`](../../custom_addons/properties/controllers/auth.py)

Three things done right:

- **Fail closed.** No key configured means *reject everything* with 503, plus a
  warning log. The opposite default — no key means no check — is how APIs end up
  wide open.
- **A justified `sudo()`**, with the reason in a comment, on the narrowest
  possible operation.
- **A constant-time comparison.** The actual check is

  ```python
  if not hmac.compare_digest(supplied_key, expected_key):
  ```

  not `==`. Comparing secrets with `==` short-circuits on the first differing
  byte and leaks length and prefix information through timing. Use
  `hmac.compare_digest` for every secret comparison — API keys, tokens,
  signatures.

And the handler shape — validate first, then parse, then work:

```python
def list_properties(self, **kwargs):
    """Return a paginated list of properties. ..."""
    ok, err = validate_api_key(request)
    if not ok:
        return err

    params = request.httprequest.args

    try:
        page = max(1, int(params.get("page", 1)))
    except ValueError:
        return error_response(400, "'page' must be an integer.")

    try:
        page_size = min(200, max(1, int(params.get("page_size", 20))))
    except ValueError:
        return error_response(400, "'page_size' must be an integer (1-200).")

    domain = []
    ...
```
— [`properties/controllers/controllers.py`](../../custom_addons/properties/controllers/controllers.py)

> **Our convention.** Note `min(200, max(1, ...))` on `page_size`. **Clamp every
> client-supplied limit.** An unbounded `page_size` is a denial-of-service
> vector — one request asking for 10 million rows. Same for any `limit` reaching
> `search()`.

Also note the docstring listing every query parameter. Because that is the
external contract, it is documented at the endpoint, and the module additionally
ships [`API_DOCUMENTATION.md`](../../custom_addons/properties/API_DOCUMENTATION.md)
and a Postman collection in [`postman/`](../../postman).

## 8.10 Writing a new endpoint — checklist

- [ ] `controllers/` package imported from the module's `__init__.py`
- [ ] `methods=[…]` explicitly set
- [ ] `auth=` chosen deliberately; if `public` or `none`, the endpoint
      authenticates itself
- [ ] `csrf=False` only alongside header/token auth
- [ ] `save_session=False` for machine callers
- [ ] **`readonly=False` if it writes** — especially with `auth='none'`
- [ ] every client-supplied number parsed defensively and **clamped**
- [ ] every client-supplied id validated before it reaches `sudo().browse()`
- [ ] secrets compared with `hmac.compare_digest`
- [ ] status codes chosen for what they mean *to the caller*, and retry
      behaviour considered
- [ ] concurrency errors re-raised, not swallowed
- [ ] handler idempotent — the framework may run it twice
- [ ] the docstring documents the request and response contract
- [ ] tests with `HttpCase` ([Chapter 13](13-testing.md))
- [ ] **restart** the server, not just `-u`, to pick up the new route

## 8.11 What to take away

1. Controllers are for the outside world; `call_kw` already covers the UI.
2. `type='json'` is a deprecated alias for `type='jsonrpc'` in 19.
3. `auth='none'` defaults to `readonly=True`. Declare `readonly=False` if you
   write.
4. `save_session=False` on machine endpoints, or you litter the filestore.
5. Any method without a leading underscore is a remotely callable API.
6. Decide what your status code means to an at-least-once sender.
7. Clamp every client-supplied limit; validate every client-supplied id.
8. New controller file ⇒ restart.

---

[← Security](07-security.md) · [Index](00-INDEX.md) · [Next: Sessions →](09-sessions.md)
