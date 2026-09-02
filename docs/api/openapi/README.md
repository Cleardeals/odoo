# Cleardeals Odoo — OpenAPI Specifications

Machine-readable specifications for **every HTTP endpoint** our Odoo custom
addons expose: 23 operations across 20 paths in `leads`, `properties` and
`wa_communication`.

Coverage is enforced, not asserted. `validate_specs.py` reads every
`@http.route` in `custom_addons/` and fails if any is missing from a spec, or if
any spec documents a path the code no longer serves. That check is what stops
these files from quietly rotting.

## The four specs

Split by **audience**, not by addon. Each spec has one authentication model and
one class of consumer, so its security block is honest and it can be handed to a
partner on its own.

| Spec | Operations | Who calls it | Auth |
|---|---|---|---|
| [`properties-api.yaml`](properties-api.yaml) | 7 | Cleardeals website, partner integrations | `X-API-Key` → `properties.api_key` |
| [`leads-intake-api.yaml`](leads-intake-api.yaml) | 4 | MagicBricks, 99acres, Square Yards, our own website and app | One key per portal — see below |
| [`track-api.yaml`](track-api.yaml) | 8 | Cleardeals website and mobile app backends | `X-API-Key` → `track_api.secret_key` |
| [`internal-api.yaml`](internal-api.yaml) | 4 | Odoo's own web client; the GCP WhatsApp platform | Odoo session cookie; Google OIDC |

Nothing is shared between files. Each is self-contained so it can be imported
into Postman, Swagger UI or an SDK generator without resolving external `$ref`s.

## Reading them

Any OpenAPI 3.1 tool works. Nothing needs to be running:

```bash
npx @redocly/cli preview-docs docs/api/openapi/properties-api.yaml
```

To browse without installing anything, open <https://editor.swagger.io> and
paste a file in.

## Validating them

```bash
make openapi-validate
```

Two tools run, because neither alone is enough.

**Redocly** enforces the OpenAPI structure strictly. This is what catches
malformed YAML that a lenient validator waves through — for example a
description containing an unquoted comma inside a flow mapping, which YAML
silently reads as the start of a new key:

```yaml
# Wrong — YAML reads "no offset." as a key, not part of the description
foo: { type: string, description: Naive UTC ISO-8601, no offset. }

# Right
foo: { type: string, description: "Naive UTC ISO-8601, no offset." }
```

**`validate_specs.py`** is the only check that knows about our controllers, and
runs three stages:

1. **OpenAPI 3.1 schema validity** — each file parses as a valid document with
   no broken `$ref`s.
2. **Operation hygiene** — every operation has a unique `operationId` and
   declares a security requirement. Unique ids are what keep generated SDK
   method names stable.
3. **Coverage against `custom_addons`** — every `@http.route` in the code
   appears in exactly one spec, and every documented path still exists.

Stage 3 is the one that matters. The rest only prove the files are well-formed;
stage 3 proves they are *true*.

CI runs both on every push and pull request that touches a controller or a spec
— see [`.github/workflows/openapi.yml`](../../../.github/workflows/openapi.yml).

### What the gate cannot catch

It compares **paths**, not payloads. Renaming a response field, changing a
status code, or adding a request parameter all pass the gate while making the
spec wrong. That part is a review responsibility — see
[Keeping these current](#keeping-these-current).

## Four API keys, four behaviours

There is no single Cleardeals API credential. Every key lives in an
`ir.config_parameter` so it can be rotated from
**Settings → Technical → System Parameters** with no deploy.

| Spec | Header | System parameter | Comparison | Header missing | Key wrong | Key unset on server |
|---|---|---|---|---|---|---|
| Properties | `X-API-Key` | `properties.api_key` | constant-time | `401` | `403` | `503` |
| Track | `X-API-Key` | `track_api.secret_key` | constant-time | `401` | `403` | `500` |
| Intake — MagicBricks | `X-API-KEY` | `magicbricks.api.key` | direct | `401` | `401` | `401` |
| Intake — 99acres | `X-API-KEY` | `99acres.webhook.api.key` | direct | `401` | `401` | `401` |
| Intake — Cleardeals | `X-API-KEY` | `cleardeals.lead.api.key` | direct | `401` | `401` | `401` |
| Intake — Square Yards | `apikey` or `X-API-KEY` | `squareyards.webhook.api.key` | constant-time | `401` | `401` | `503` |

The table is documentation of what the code does today, not an endorsement of
it. Three real inconsistencies are visible in it and are recorded in
[Known inconsistencies](#known-inconsistencies) below.

## Response envelopes are not uniform

Three different shapes are in production. A client cannot use one parser across
all of them, and each spec says so in its own description.

**Properties API** — error key is `status`, and `data` is absent on failure:

```json
{ "success": false, "error": { "status": 404, "message": "…" } }
```

**Track API** — error key is `code`, and `data` is present and null:

```json
{ "success": false, "data": null, "error": { "code": 404, "message": "…" } }
```

**Lead intake** — no envelope at all. Every response is `text/plain`:

```
Failed to push lead: Missing required fields.
```

## Known inconsistencies

These are documented deliberately. A specification that quietly smooths over
what the code really does is worse than none, because it makes an integration
fail in a way nobody can explain from the docs. Each is described in full in the
spec that owns it.

| # | What | Where | Impact |
|---|---|---|---|
| 1 | Three of the four intake webhooks compare API keys with `!=` rather than `hmac.compare_digest` | `leads-intake-api.yaml` | Theoretically timing-observable. Square Yards, written later, does it correctly. |
| 2 | Those same three return `401` when the server has **no** key configured, so a `401` does not prove the caller's credential is wrong | `leads-intake-api.yaml` | A misconfigured server is indistinguishable from a bad key. Square Yards returns `503`. |
| 3 | Those same three parse the request body outside their error handling, so malformed JSON yields Odoo's generic `500` HTML page instead of the documented `text/plain` body | `leads-intake-api.yaml` | A portal sending bad JSON gets an unparseable response. |
| 4 | "API key not configured" is `503` on the Properties API and `500` on the Track API | both specs | Same condition, different class — one reads as retryable, the other as a bug. |
| 5 | On seller site-visits `source` holds `primary`/`recommended`; on buyer site-visits `source` holds the portal name and `inquiry_type` holds `primary`/`recommended` | `track-api.yaml` | A shared record parser across the two endpoints will silently mis-read the field. |
| 6 | The Track API's `ai-suggestions` docstring claims `page_size` caps at 100; the shared paginator caps it at 200 | `track-api.yaml` | The specs document 200, the real behaviour. |

None of these is fixed here — this task was to document the surface, not change
it. Fixing 1–3 would be a small, self-contained change to
`portal_lead_controller.py`; 4 is a one-line change; 5 is a breaking API change
that needs the website team's agreement.

## Things the specs make explicit that the code does not

Worth knowing before integrating, and each is called out in the relevant spec:

- **`200` from an intake webhook does not mean a lead was created.** It also
  covers "duplicate suppressed" and "created but post-processing failed". A
  sender cannot tell these apart and must not retry a `200`.
- **`404` from the Track API is the empty state**, not an error. A seller with no
  properties gets `404`, not an empty array.
- **Track API pagination happens in memory**, after every matching record has
  been loaded and serialised. It bounds response size, not server work.
- **The Track API's `phone` parameter is the only thing scoping the data.** The
  API key authenticates the calling application, not the person whose enquiry
  history comes back.
- **`/wa/media/upload` creates a public, unauthenticated attachment**, because
  Interakt fetches it with no credentials.
- **`/wa/pubsub/push` returns `200` to almost everything on purpose**, because
  Pub/Sub reads any non-2xx as "redeliver".
- **Datetimes are naive UTC with no offset.** Render them; do not re-derive
  site-visit buckets from them client-side.

## Keeping these current

The specs are hand-written — Odoo has no decorator metadata rich enough to
generate a useful one — so they can drift in a way the ER diagram cannot. The
coverage gate catches the drift that matters most (a route added, renamed or
deleted) but it **cannot** catch a changed field, status code or payload shape.

**When you change a controller, update its spec in the same commit.** Concretely:

| Change | What to do |
|---|---|
| New `@http.route` | Add the operation. CI fails until you do. |
| Route deleted or path renamed | Remove or rename it in the spec. CI fails until you do. |
| New request field or query parameter | Add it to the schema, with a description saying what it is *for*. |
| Changed response shape | Update the schema **and** the example. Examples are what people actually read. |
| New error branch | Add the status code and an example message. |
| Auth change | Update the security scheme and the tables in this README. |

The examples matter more than the schemas. Most integrators copy the example,
adjust it, and never read the schema at all — so a stale example is a support
ticket waiting to happen.

### Adding a fifth spec

Split by audience and authentication, not by addon. If a new group of endpoints
shares an auth model and a consumer with an existing spec, add it there; if it
brings its own, give it its own file. Then add it to the table at the top of
this README — `validate_specs.py` picks up any `*.yaml` in this directory
automatically.

## Scope

**Covered** — every route in `custom_addons/`.

**Not covered, deliberately:**

- **Odoo core endpoints** (`/web/session/authenticate`, `/web/dataset/call_kw`,
  `/web/content/…`). Upstream code, versioned by Odoo, changing on upgrade.
  Documenting them would create a maintenance liability with no audit value.
- **The GCP WhatsApp platform's HTTP endpoints** (webhook-gateway and the other
  services in the `cleardeals-whatsapp-platform` repository). A separate
  codebase with its own CI. Its specs belong in that repository, where a
  coverage gate like this one can actually validate them against the code —
  cross-repo specs drift immediately. The Odoo end of that integration,
  `/wa/pubsub/push`, **is** documented here in `internal-api.yaml`.

## Postman collections

Not built yet — deferred by agreement. When they are wanted, generate them from
these specs rather than writing them by hand:

```bash
npx @apideck/portman --local docs/api/openapi/properties-api.yaml --output properties.postman.json
```

An existing hand-written collection for the Square Yards webhook lives in
[`postman/`](../../../postman/) at the repository root. It carries edge-case
assertions that a generated collection would not, so it should be kept rather
than replaced.
