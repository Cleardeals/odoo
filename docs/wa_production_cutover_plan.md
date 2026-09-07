# WhatsApp → Production Cutover Plan

**Status:** proposal, nothing executed
**Written:** 7 Sep 2026
**Scope:** promote the WhatsApp suite from stage to production — 4 new Odoo
modules, upgrades to 2 existing ones, platform database prune, and the traffic
cutover from stage Odoo to production Odoo.

Everything in "Where we actually are" below was measured on 7 Sep 2026, not
assumed. §9 records the handful of things that remain unverifiable, and why.

**Revision 3** — re-checked with `tech@` admin access. Q1–Q3 answered and folded
in; the Interakt webhook confirmed from the dashboard; the deprecated modules
ruled out for good (§4.6). **Q4, the window, is the only thing left to decide.**

---

## 1. Where we actually are

### 1.1 Odoo production

| | |
|---|---|
| VM | `odoo-19-prod`, zone `us-central1-f`, project `odoo-472708` |
| Service account | `odoo-prod-vm@odoo-472708.iam.gserviceaccount.com`, scope `cloud-platform` |
| Deploy root | `/opt/odoo` (git checkout, `docker-compose.yml`) |
| Branch / commit | `19.0` @ `56ed2310669` |
| Database | `odoo_db` |
| Domain | `odoo.cleardeals.xyz` (traefik + Let's Encrypt) |
| Containers | `odoo-project-odoo-1`, `odoo-project-db-1`, `traefik` |
| Deploy | **Cloud Build `odoo-cd-19`**, triggered by push to `19.0`, **approval-gated**. Not a manual SSH deploy. |
| Addons | **Baked into the image** at `/opt/cleardeals-addons` — `custom_addons` is deliberately *not* bind-mounted |
| Backups | Daily disk snapshots of `odoo-19-prod` (60 GB). **No database dump cron and no `backups/` directory on the VM.** |
| Runtime | `workers = 4`, `max_cron_threads = 2`, `limit_time_real = 240`, `list_db = False`, `dbfilter = ^odoo_db$` |
| Disk | 58 GB, **33 GB used (58%)** — room for the dump in §6 Phase 2.1 |
| Secrets | Secret Manager: `odoo-admin-passwd`, `odoo-db-password`, rendered to tmpfs at container start |
| Rollback targets | Artifact Registry holds prior SHA-tagged images (`56ed231`, `fd0b359`, `5f1372d`, …) |

Installed custom modules:

| Module | Installed version |
|---|---|
| `leads` | 19.0.1.7.1 |
| `properties` | 19.0.1.6.0 |
| `cleardeals_dashboards` | 19.0.1.0 |
| `lead_suggestor` | 19.0.1.0.0 |
| `property_dashboard`, `property_listings`, `property_renewal` | present in the tree, **uninstalled — DEPRECATED, must never be installed** (§4.6) |

No `wa_communication.*` or `cleardeals_pubsub.*` config parameters exist in
production. The only Cleardeals parameter is `cleardeals.lead.api.key`.

### 1.2 Odoo stage

`odoo-stage` (us-central1-c), DB `cleardeals_19_stage`, branch `feature/pub-sub`
@ `f6c7ce35`, 11 custom modules installed including the whole WhatsApp suite.

### 1.3 The WhatsApp platform

| | |
|---|---|
| Cluster | `cleardeals-wa-prod-cluster`, zone us-central1-c, namespace `wa-automation` |
| Services | 7 deployments, all on image tag `b85b7a02…` (today's build) |
| Database | Cloud SQL `cleardeals-wa-prod:us-central1:cleardeals-wa-db` |
| Schema version | Alembic `0012` — **equal to the newest migration in the repo, so no platform migrations are pending** |
| Ingress | `waco.cleardeals.xyz` → `136.68.101.215` (webhook-gateway). DNS resolves; the blocker recorded in earlier notes is cleared. |
| Interakt webhook | **Confirmed configured** to `https://waco.cleardeals.xyz/webhook/…` with a secret key set and the WhatsApp channel selected (dashboard screenshot, 7 Sep). Unchanged by this cutover. |

Table row counts (7 Sep 2026):

| Table | Rows | | Table | Rows |
|---|---:|---|---|---:|
| `inbound_messages` | 474 | | `workflow_step_log` | 518 |
| `outbound_messages` | 405 | | `actor_timeline` | 385 |
| `workflow_enrollments` | 102 | | `rm_assignments` | 184 |
| `conversation_context` | 30 | | `dead_letter_queue` | 12 |
| `workflows` | 9 (2 active) | | `workflow_opt_outs` | 1 |
| `odoo_send_requests` | 0 | | `rm_reply_analytics` | 0 |
| `scheduled_reminders` | 0 | | | |

Data spans **2026-07-18 → 2026-09-07** and is still arriving today.

### 1.4 The single most important fact

```
cd-prod-wa-odoo-events-staging-push-sub          state: ACTIVE
  pushEndpoint:  https://odoo-stage.cleardeals.xyz/wa/pubsub/push
  oidcToken.audience: https://odoo-stage.cleardeals.xyz/wa/pubsub/push
  oidcToken.serviceAccountEmail: wa-worker-sa@cleardeals-wa-prod.iam.gserviceaccount.com
  ackDeadlineSeconds: 30
  messageRetentionDuration: 604800s   (7 days)
  retryPolicy: min 1s, max 10s
```

That is the **only** push subscription on `cd-prod-wa-odoo-events`. All WhatsApp
traffic lands in **stage Odoo right now**. The cutover is, at its core, moving
this one subscription — everything else is preparation for it.

Two details that matter more than they look:

- **The OIDC audience is a second copy of the URL.** Changing `--push-endpoint`
  alone leaves the audience pointing at stage, and `push_controller.py`
  validates the token audience against the `wa_communication.inbound_push_audience`
  parameter. Mismatch → every push rejected → a silent inbox. **Both must
  change together.**
- **7-day message retention** means the Phase 2 outage is comfortably safe. An
  Odoo restart of minutes cannot lose an event.

### 1.5 Branch divergence

`feature/pub-sub` is **114 commits ahead of and 75 commits behind
`development_19`** (and 76 behind `19.0`, which is one merge commit further on).

`development_19` is the only way in: **nothing merges directly to `19.0`.**
Today `development_19` is 0 ahead of `19.0` and 1 behind it, so the two are
identical in content — `19.0` simply carries the merge commit from the last
promotion (#124).

The good news, measured rather than assumed:

- Across the 75 commits `development_19` has that the branch lacks, the only
  file differing inside `custom_addons/` is
  `leads/tests/test_portal_lead_crud.py`. Module code is effectively aligned.
- A trial merge conflicts in exactly **3 files**, none of them module code:
  `.gitignore`, `Dockerfile`, `docker-compose.yml`.

The trap is version numbers, which diverged independently:

| Module | on `development_19` / `19.0` | on `feature/pub-sub` | installed in prod |
|---|---|---|---|
| `leads` | 1.7.1 | 1.8.0 | 19.0.1.7.1 |
| `properties` | 19.0.1.6.0 | 19.0.1.7.0 | 19.0.1.6.0 |

`development_19` carries newer *code* under a lower version string. After merging, both
manifests need a version above both sides or Odoo may skip the upgrade.

### 1.6 The production pipeline (and the gap in it)

`cloudbuild.yaml` on `19.0`, trigger `odoo-cd-19`:

```
build image → image-contents gate → config-check gate → test gate
           → push to Artifact Registry → ssh to VM → scripts/deploy.sh $COMMIT_SHA
```

`scripts/deploy.sh` pulls the new tag, `docker compose up -d odoo`, waits on a
health gate (`/web/health?db_server_status=1` plus an edge check through
Traefik on `odoo.cleardeals.xyz`), and **rolls back to the previous image tag**
if either fails. Images are tagged by commit SHA — never `:latest`.

This is a good pipeline. It has one gap that matters enormously here:

> **Nothing in the pipeline installs or upgrades a module.** `deploy.sh` is an
> image swap. There is no `-i`, no `-u`, and no migration step anywhere in
> `scripts/`. Every module currently in production was installed before this
> pipeline existed.

So a merge that ships `wa_communication` does **not** install it, and — more
dangerous — it ships `leads` at the new version while the database is still at
`19.0.1.7.1`. New Python running against an old schema is how you get missing
columns at runtime rather than at deploy time.

The second gap is smaller but must not be missed: the pipeline's **test gate
installs and tests only the four existing modules**:

```
-i leads,lead_suggestor,cleardeals_dashboards,properties
--test-tags /leads,/lead_suggestor,/cleardeals_dashboards,/properties
```

Merge the suite as-is and the WhatsApp modules ship through the production
pipeline **never having been tested by it**.

---

## 2. What this deployment actually consists of

Four separable workstreams. Only the fourth is user-visible.

0. **Teach the pipeline to install modules** — a prerequisite change to
   `cloudbuild.yaml` and `scripts/deploy.sh`, shipped ahead of the suite (§4.4).
1. **Ship the Odoo code** — merge, release, install 4 new modules, upgrade 2.
2. **Grant production Odoo access to the platform** — IAM + config parameters.
3. **Prune the platform database** — remove stage-era data (see §5; read the
   warning first).
4. **Cut traffic over** — repoint one push subscription.

---

## 3. Downtime

**Zero downtime is not achievable for the Odoo step, and anyone promising it is
wrong.** Installing a module rewrites the registry and regenerates asset
bundles; old and new code cannot serve one database concurrently. With the
upgrade running inside `deploy.sh` (§4.4b) plus the one-time install and two
restarts, realistic target: **5–10 minutes of Odoo unavailability**, in a
low-traffic window.

**Zero *message* loss is achievable, and is the target that matters.** While
Odoo is down the push subscription receives 5xx/connection errors and Pub/Sub
retries with backoff (1s–10s), and undelivered messages survive on the
subscription for **7 days** — confirmed, not assumed. A restart of minutes is
nowhere near that. Nothing is lost provided:

- the cutover in §6 uses `subscriptions update`, never delete-then-create, and
- the OIDC audience moves with the endpoint (§6 Phase 4).

| Phase | Odoo down | WhatsApp affected |
|---|---|---|
| 0 Pre-flight (incl. pipeline change) | no | no |
| 1 IAM + parameters | no | no |
| 2 Odoo release | **yes, 5–10 min** — image swap + `-u` upgrade + one-time `-i` install + two restarts | queued, delivered on recovery |
| 3 Platform prune | no | brief pause of workflow engines |
| 4 Cutover | no | one subscription update, atomic |
| 5 Verify | no | no |

---

## 4. Phase 0 — Pre-flight (no production change)

Do all of this before booking a window.

### 4.1 Reconcile the branch

Bring the feature branch up to date with **`development_19`** — that is the
base it will be reviewed against, and branch protection enforces "up to date
with base" before a merge is allowed:

```bash
git checkout feature/pub-sub
git merge origin/development_19   # conflicts: .gitignore, Dockerfile, docker-compose.yml
```

Resolve those three by hand — they are infrastructure files where
`development_19` is authoritative (its content is what production runs). Then
set both manifests above both sides:

- `leads` → `1.9.0`
- `properties` → `19.0.1.8.0`

Run the full suite (`my-odoo-image`, all modules, `--test-tags` for each) and
confirm the Hoot browser suites run rather than skip.

### 4.2 Rehearse the migration on real data

Use the `odoo-prod-migration-check` skill: it streams a **read-only** snapshot
of `odoo_db` to this machine and runs the upgrade locally. Production is only
ever read.

This is the step that proves `wa_communication`'s five migration scripts
(`1.1.1`, `1.1.2`, `1.1.9`, `1.2.5`, `1.3.0`) behave against real rows, and that
`leads`/`properties` upgrade cleanly. **Do not skip it.** A fresh install in a
scratch database proves nothing about production data.

### 4.3 Promote through `development_19` — never straight to `19.0`

Every change is gated through `development_19` first. That makes this **two**
pull requests, not one, and the second cannot be skipped just because the first
was reviewed.

**PR 1 — `feature/pub-sub` → `development_19`.** The substantive review: 114
commits, 4 new modules, and the WhatsApp suite in its entirety. A formality only
if someone has been reviewing along the way. CI must be green.

**PR 2 — `development_19` → `19.0`.** The promotion, matching how #122–#124
landed. Small and mechanical *provided PR 1 has already merged*.

Two consequences of the strict up-to-date policy worth planning for:

- `feature/pub-sub` must be up to date with `development_19` before PR 1 can
  merge — that is what §4.1 does. If anything else lands on `development_19`
  in the meantime, repeat the merge.
- `development_19` is currently **1 commit behind `19.0`** (the promotion merge
  from #124). Before PR 2 can merge, `19.0` has to be merged back into
  `development_19` — exactly what commit `4b51372b643`, "Merge 19.0 into
  development_19 for the strict up-to-date policy", did last time. Expect to do
  it again.

Only after PR 2 merges does `19.0` carry the WhatsApp suite, and only then can
Phase 2 pull it onto the production VM.

### 4.4 Make the pipeline able to install modules — ship this FIRST

Three changes — two to files the pipeline itself reads, plus the deprecated-module
guard from §4.6 — all promoted through `development_19` → `19.0` like anything
else. Ship them as **their own release, before the suite**, so the mechanism is
proven by an ordinary no-op deploy rather than debugged during the one that
matters.

**(a) `cloudbuild.yaml` — widen the test gate** to cover what is being shipped:

```
-i leads,lead_suggestor,cleardeals_dashboards,properties,\
   cleardeals_pubsub,cleardeals_notification,cleardeals_ui,wa_communication
--test-tags /leads,/lead_suggestor,/cleardeals_dashboards,/properties,\
            /cleardeals_pubsub,/cleardeals_notification,/cleardeals_ui,/wa_communication
```

This makes the gate run the OWL/Hoot browser suites, which need Chromium. The
repo `Dockerfile` installs it via Playwright — deliberately, because Ubuntu's
`chromium` package is a snap stub that cannot run in a container (its own
comment says so, and I hit exactly that failure locally on 7 Sep).

**This gate has to go green inside Cloud Build, not merely on a laptop.** That
is the entire reason §4.4 ships as its own release: if Chromium does not start
under Cloud Build's sandbox, we find out on a no-op deploy instead of on the one
carrying the WhatsApp suite.

Two properties make the result trustworthy:

- `browser_js` **skips silently** when no browser is found, so a green build
  proves nothing on its own. Each module's `test_browser_harness_is_available`
  turns that skip into a **failure** — check the build log shows
  `[HOOT] Passed N tests`, not a skip.
- If Chromium cannot start under Cloud Build, the fallback is to run the Hoot
  suites in the PR gate only and keep the CD gate to Python — but that is a
  deliberate, recorded downgrade, not something to discover mid-release.

**(b) `scripts/deploy.sh` — an opt-in upgrade step** between the image pull and
`up -d`, so the schema is migrated by the same image that is about to serve it,
while Odoo is still stopped:

```bash
# after: docker compose pull odoo
if [[ -n "${ODOO_UPGRADE_MODULES:-}" ]]; then
  log "upgrading modules: ${ODOO_UPGRADE_MODULES}"
  docker compose run --rm --no-deps odoo \
      odoo -c /etc/odoo/odoo.conf -d "${ODOO_DB:-odoo_db}" \
           -u "${ODOO_UPGRADE_MODULES}" --stop-after-init \
    || die "module upgrade failed; image not swapped"
fi
# then: docker compose up -d odoo
```

Opt-in via an environment variable means every ordinary deploy is byte-for-byte
unchanged, and the release that needs an upgrade asks for one explicitly.
Failing *before* the swap leaves the old container running on the old image and
the old schema — the one combination that is definitely consistent.

The install of brand-new modules (`-i`) is deliberately **not** wired into the
pipeline. A first install is a one-time act that wants a human watching it, and
a permanent `-i` flag is a permanent invitation to install a module by accident.
It stays a manual step (§6, Phase 2.3), run once.

### 4.5 Confirm the window (§8, Q4)

Q1–Q3 are settled. Only the window is outstanding, and it gates execution.

### 4.6 Deprecated modules — never install

`property_dashboard`, `property_listings` and `property_renewal` are
**deprecated**. They are in the tree and therefore baked into the image (the
`image-contents` gate requires image and repo to match), but they are
uninstalled in production and must stay that way.

Nothing in this plan installs them. The risk is not the plan — it is that all
three are still `installable: True`, so they appear in Apps and are one click
away for anyone with the rights. Close that door while we are already shipping
a pipeline release:

```python
# custom_addons/property_dashboard/__manifest__.py  (and the other two)
'installable': False,
```

A one-line change per module, it rides along with §4.4, and it converts a
convention into something the system enforces. Deleting the directories would
be cleaner still, but that is a separate decision — leaving them baked and
uninstallable costs nothing.

---

## 5. Phase 3 — The platform database prune

**Decided (Q1): prune everything.** The traffic is internal — employees testing
against their own handsets, no customers involved (confirmed 7 Sep). The dead
letter queue corroborates it: of its 12 rows, the payloads read `Pratham test`,
`Final Test Watch Check`, `khushi`, `dhavalbhaii`, and two are addressed to
phone numbers that are not phone numbers (`84017`, `917384654`).

So the earlier caution in this section is withdrawn: there is no customer
history at stake, and a full prune is the right call.

Three practical rules still apply.

**Consider keeping `workflow_opt_outs`.** One row. It records a handset that
sent STOP. Even if that handset belongs to an employee, Meta's opt-out rules do
not care whose phone it is, and re-messaging it after the prune is a policy
breach for the sake of deleting one row. Cheap to keep, mildly expensive to get
wrong — my recommendation is to keep it, but it is a judgement call and pruning
it is defensible now that Q1 is settled.

**Never delete `workflows`.** These are the 9 workflow *definitions* (2 active:
`initial_nudge_property_v1`, `initial_nudge_no_property_v1`), not traffic.
Deleting them breaks the engines.

**Take a Cloud SQL export first.** Automated backups are on (daily 07:00) and
**point-in-time recovery is enabled with 7 days of transaction logs**, so there
is already a rollback path — but PITR restores to a *new instance*, which is a
slow way to recover from a bad `DELETE`. Take an explicit export as well and
confirm it is readable.

### 5.1 Delete order (foreign keys first)

```sql
BEGIN;
DELETE FROM workflow_step_log;
DELETE FROM actor_timeline;
DELETE FROM rm_reply_analytics;
DELETE FROM scheduled_reminders;
DELETE FROM conversation_context;
DELETE FROM inbound_messages;
DELETE FROM outbound_messages;   -- after inbound: context references it
DELETE FROM workflow_enrollments;
DELETE FROM rm_assignments;      -- decide: current RM ownership may be worth keeping
DELETE FROM odoo_send_requests;
DELETE FROM dead_letter_queue;   -- triage the 12 rows first, do not just drop them
-- KEEP: workflows (definitions, not traffic), alembic_version
-- KEEP (recommended): workflow_opt_outs — see above
COMMIT;
```

Run inside one transaction so a foreign-key surprise rolls the whole thing back.
Primary keys are UUIDs, so no sequences need resetting.

### 5.2 Triage the dead letter queue first

12 rows, all between 18 Jul and 13 Aug, now read in full. They are worth two
minutes of attention not because the messages matter — they are internal tests —
but because the *failure classes* will recur in production:

| Failures | Cause | Still a risk? |
|---|---|---|
| 4 × `131026` "Message undeliverable" | target not reachable on WhatsApp | Yes — expect it on real leads with no WhatsApp account |
| 2 × `131049` "not delivered to maintain healthy ecosystem engagement" | Meta throttling marketing-ish sends | Yes — a volume/quality signal, not a bug |
| 2 × invalid phone (`84017`, `917384654`) | lead data quality | Yes — nothing validates phone shape before enrolment |
| 2 × template `initial_nudge_v1_msg_2_u0` not approved in `hi` | config drift | **No** — the workflow now uses `_xc`, verified approved |
| 1 × empty body variable | a property field was blank | Partly — the manual share path guards this now; the workflow path does not |

The first three are worth a monitoring rule after go-live, not a blocker.

### 5.3 Pause the engines during the prune

Deleting enrollments under a running workflow engine invites half-processed
state. Scale to zero, prune, scale back:

```bash
kubectl scale deploy we-nudge-property we-nudge-no-property -n wa-automation --replicas=0
# prune
kubectl scale deploy we-nudge-property we-nudge-no-property -n wa-automation --replicas=1
```

Inbound webhooks keep being accepted throughout — webhook-gateway and
wa-sender stay up, so nothing is dropped at the edge.

---

## 6. The ordered runbook

### Phase 1 — IAM and parameters (no user impact, do the day before)

**1.1 — IAM. Verified with `tech@`; the exact grant set is known.**

`odoo-stage-vm@` holds `roles/pubsub.publisher` at **topic level** on exactly six
topics, and nothing at project level. Production needs the same six for
`odoo-prod-vm@odoo-472708.iam.gserviceaccount.com`:

```bash
for T in cd-prod-actor-events cd-prod-customer-events cd-prod-nudge-events \
         cd-prod-odoo-wa-requests cd-prod-property-events cd-prod-visit-events; do
  gcloud pubsub topics add-iam-policy-binding "$T" \
      --project cleardeals-wa-prod \
      --member "serviceAccount:odoo-prod-vm@odoo-472708.iam.gserviceaccount.com" \
      --role roles/pubsub.publisher
done
```

Requires an account with `pubsub.topics.setIamPolicy` — `tech@` has it,
`developer2@` does not.

Verify from the production VM *before* the window, because an unnoticed failure
here breaks every outbound send:

```bash
gcloud pubsub topics publish cd-prod-odoo-wa-requests --message '{"ping":1}'
```

The subscriber will reject the payload — that is fine. A publish that is
*accepted* proves the binding.

**1.2 — Message retention: already confirmed at 7 days** on
`cd-prod-wa-odoo-events-staging-push-sub`. No action; recorded so nobody has to
re-check it under time pressure.

### Phase 2 — Odoo release (the only downtime)

The deploy is **Cloud Build, not SSH**. A merge to `19.0` queues `odoo-cd-19`
and waits for a human to approve it — nothing ships until someone presses it.

**2.1 — Take a database dump, by hand, and verify it.**
Daily disk snapshots exist (most recent confirmed), but a disk snapshot is a
crash-consistent image of a running Postgres, not a dump, and restoring one
means rebuilding a VM. There is **no dump cron on this VM**. For a release that
runs migrations, take a real one and check it is readable:

```bash
sudo docker exec odoo-project-db-1 pg_dump -U odoo -Fc odoo_db > ~/odoo_db_precutover.dump
pg_restore --list ~/odoo_db_precutover.dump | head        # proves it is not truncated
sudo tar czf ~/filestore_precutover.tar.gz ./odoo-web-data
```

`odoo-web-data` is the filestore volume from `docker-compose.yml`. A database
without its filestore is not a backup — attachments and assets live there.

**2.2 — Merge PR 2, then approve the build.**
Watch the gates: `image-contents` proves the image carries exactly the eleven
module directories in the repo; `test` now covers the WhatsApp suite (§4.4a).
With `ODOO_UPGRADE_MODULES` set (§4.4b), `deploy.sh` upgrades `leads` and
`properties` while Odoo is stopped, then swaps the image and health-gates it.

If the health gate fails, the pipeline rolls back the **image** automatically.
It cannot roll back a migration — that is what 2.1 is for. Read the rollback
note in `deploy.sh`; it says so explicitly.

**2.3 — Install the four new modules. One-time, manual, watched.**

```bash
# On odoo-19-prod, with the image the pipeline just deployed.
cd /opt/odoo
sudo docker compose run --rm --no-deps odoo \
     odoo -c /etc/odoo/odoo.conf -d odoo_db \
          -i cleardeals_pubsub,cleardeals_notification,cleardeals_ui,wa_communication \
          --stop-after-init
sudo docker compose restart odoo
```

Dependency chain, resolved by Odoo but worth knowing:
`cleardeals_notification` → `cleardeals_ui` → (`cleardeals_pubsub`, `leads`) →
`wa_communication`.

Note the addons path: modules are **baked into the image** at
`/opt/cleardeals-addons`, and `custom_addons` is deliberately not bind-mounted.
Do not add a mount to "make it easier" — it shadows the baked copy and quietly
breaks rollback, which is why the compose file says so in a comment.

**2.4 — Set the configuration parameters.** The module data files ship sensible
defaults for the topic names, but three parameters are environment-specific and
one is a secret. Settings → Technical → System Parameters:

| Parameter | Production value |
|---|---|
| `wa_communication.interakt_api_key` | **secret** — copy from stage, never into git |
| `wa_communication.interakt_base_url` | `https://api.interakt.ai` |
| `wa_communication.inbound_push_audience` | `https://odoo.cleardeals.xyz/wa/pubsub/push` ← **must change from the stage URL** |
| `wa_communication.inbound_push_sa_email` | `wa-worker-sa@cleardeals-wa-prod.iam.gserviceaccount.com` (unchanged) |
| `wa_communication.topic_*` (6) | shipped as defaults; verify they read `cd-prod-*` |
| `wa_communication.quick_share_template` | `details_shared_v4` (shipped default) |
| `wa_communication.segments_enabled` | `1` (shipped default) |

`inbound_push_audience` is the OIDC audience the push route validates. If it
still says `odoo-stage`, **every inbound push to production is rejected** and the
symptom is a silent inbox.

**2.5 — Grant the Leads/WhatsApp groups to the RMs who need them**, then restart
Odoo once more. Trap found on 7 Sep: changing a user's groups from a shell or
another process does **not** invalidate the running worker's cached membership —
the user sees a half-empty menu until the server restarts. Doing this last means
the 2.3 restart does not have to be repeated.

### Phase 3 — Prune

Per §5. Independent of Phase 2; can run in the same window or a later one.

### Phase 4 — Cutover (the actual switch)

**Use `update`, not delete-then-create — and move the audience with the endpoint.**

```bash
gcloud pubsub subscriptions update cd-prod-wa-odoo-events-staging-push-sub \
    --project cleardeals-wa-prod \
    --push-endpoint=https://odoo.cleardeals.xyz/wa/pubsub/push \
    --push-auth-service-account=wa-worker-sa@cleardeals-wa-prod.iam.gserviceaccount.com \
    --push-auth-token-audience=https://odoo.cleardeals.xyz/wa/pubsub/push
```

Two things this gets right that the obvious version does not:

*The audience.* `--push-endpoint` alone leaves `oidcToken.audience` pointing at
stage. `push_controller.py` validates the token audience against
`wa_communication.inbound_push_audience`, so a half-move rejects every push and
production looks alive but deaf. Set both, and make sure the parameter in §6
Phase 2.4 carries the same string.

*`update`, not delete-then-create.* A new subscription only receives messages
published **after** it exists, so delete-then-create loses everything in the
gap. Running both at once is worse — every message reaches both Odoos, and stage
starts replying to people. `update` is atomic and has neither problem.

The subscription's name still says `staging`. Cosmetic; rename later if it
bothers you, but not during a cutover.

**Interakt needs no change.** Its webhook already points at
`https://waco.cleardeals.xyz/webhook/interakt` with a secret key set — confirmed
from the dashboard on 7 Sep. Interakt talks to the *platform*, never to Odoo, so
moving Odoo from stage to production is invisible to it.

While that dialog is open, though, confirm the **event subscriptions**, because
the platform silently depends on six of them and a missing tick is indistinguishable
from a bug:

| Interakt event | What breaks without it |
|---|---|
| `message_received` | inbound messages never arrive — and STOP is never detected |
| `message_api_clicked` | quick-reply / CTA button taps are lost |
| `message_api_sent` | **template body, footer and buttons never render** — bubbles show a bare template name |
| `message_api_delivered` | no delivery ticks, and no message cost |
| `message_api_read` | no read receipts |
| `message_api_failed` | failures are invisible; nothing reaches the dead letter queue |

`message_api_sent` is the one worth double-checking: it is the earliest webhook
carrying `raw_template`, which is where the rendered body and the quick-reply
button labels come from. Its absence produces exactly the symptom chased on
5 Sep — a card with no button under it — but from configuration rather than
code.

### Phase 5 — Verify (30 minutes, watching)

1. Send one inbound message from a test handset → appears in **production**
   Odoo's inbox within seconds.
2. Reply from production Odoo → arrives on the handset. This exercises the
   publish path and therefore the Phase 1 IAM grant.
3. Send a template (Share Property Details) → delivered, and `wa.message`
   records `template_buttons` (the fix deployed 5 Sep).
4. Check the lead status gate: an RM cannot move an inquiry off "Lead" without
   an outbound attempt, and the "Chat assigned to X" pill does not count.
5. `kubectl logs -n wa-automation -l app=odoo-bridge --since=30m` — no errors.
6. Confirm the stage Odoo inbox has gone quiet. If it has not, the subscription
   update did not take.
7. Re-read the subscription and confirm **both** fields moved:

   ```bash
   gcloud pubsub subscriptions describe cd-prod-wa-odoo-events-staging-push-sub \
       --project cleardeals-wa-prod --format='value(pushConfig.pushEndpoint,pushConfig.oidcToken.audience)'
   ```

   Both must read `https://odoo.cleardeals.xyz/wa/pubsub/push`. If only the
   first moved, inbound pushes are being rejected on audience and the inbox is
   silently deaf — the failure this whole document keeps warning about.

---

## 7. Rollback

| Failure | Rollback |
|---|---|
| Upgrade fails inside `deploy.sh` | The image is **not** swapped — old container, old image, old schema, all consistent. Fix forward. |
| Health gate fails after a migration ran | The pipeline auto-rolls the **image** back, but the schema stays migrated. Restore `~/odoo_db_precutover.dump` + filestore. This is why 2.1 exists, and `deploy.sh` says so in its own comments. |
| New modules misbehave after install | Uninstalling `wa_communication` drops its tables and its data. Prefer restoring the dump, or disable the feature via config rather than uninstalling. |
| Cutover works, WhatsApp misbehaves | `gcloud pubsub subscriptions update … --push-endpoint=https://odoo-stage.cleardeals.xyz/wa/pubsub/push`. Seconds, atomic, and stage still has the modules installed. |
| Prune deleted too much | Restore the Cloud SQL export. Irreversible without it — which is the whole point of taking it. |

The Odoo modules can stay installed after a WhatsApp rollback; with the
subscription pointed back at stage, production simply receives nothing.

---

## 8. Decisions — settled 7 Sep 2026

**Q1 — What happens to the platform's data? → Prune everything.**
It is internal employee testing, no customers involved. §5 is written to that
decision. The one nuance left is `workflow_opt_outs` (one row); keeping it costs
nothing and avoids re-messaging a handset that sent STOP.

**Q2 — Migrate stage's WhatsApp history into production? → No.**
Same reason: nothing in it is customer conversation. Production's
`wa_conversation` / `wa_message` tables start empty and that is correct. This
removes a phase that would otherwise have been a day of FK-remapping work with
its own rehearsal.

**Q3 — Who runs the IAM grant? → `tech@`, and the exact grants are now known.**
Six topic-level `roles/pubsub.publisher` bindings, mirroring what
`odoo-stage-vm@` already holds. Commands in §6 Phase 1.1. `developer2@` cannot
do this and cannot even read the current policy.

**Q4 — Which window? → Open.** Needs 5–10 minutes of Odoo downtime plus ~30
minutes of watching. Early morning IST, before the RM day starts, is the obvious
choice. This is the only thing left to decide, and it gates execution.

### Pre-production checks already done

Worth recording so they are not repeated, and so a regression is noticeable:

- **All six templates used by the two active workflows are APPROVED in Interakt,
  in `hi`** — `initial_nudge_v1_msg_1`, `..._msg_2_xc`, `..._msg_3_jt`,
  `..._unassigned_msg_1`, `..._unassigned_msg_2`, plus `details_shared_v4` for
  the Share Property Details button. The `_u0`-in-Hindi failure that appears
  twice in the dead letter queue is historical; that template is no longer
  referenced.
- **Platform schema is current** — Alembic `0012`, equal to the newest migration
  in the repo. No platform migration runs during this cutover.
- **Cloud SQL has automated backups (daily 07:00) and PITR with 7 days of logs.**
- **Production Odoo has 25 GB free** (58 GB disk, 58% used) — enough for the
  dump and tarball in Phase 2.1.

## 9. What remains unverifiable

Nothing material. Every item from revision 1 has been resolved and moved into
the body of this document:

| Was unverified | Now |
|---|---|
| Topic-level IAM bindings | Read with `tech@` — six `roles/pubsub.publisher` grants, commands in §6 Phase 1.1 |
| Interakt's webhook URL | Confirmed from the dashboard, 7 Sep — `waco.cleardeals.xyz`, secret key set |
| `dead_letter_queue` contents | Read in full — 12 rows, failure classes tabulated in §5.2 |
| Production worker count | `workers = 4`, `max_cron_threads = 2` |
| Deprecated modules | Answered: **never install** — §4.6 |
| Subscription retention | 7 days |
| Cloud SQL backup posture | Daily 07:00 + PITR, 7 days of logs |

One thing is *unprovable in advance* rather than unverified: **whether the
widened test gate passes inside Cloud Build**. Chromium starting under Cloud
Build's sandbox cannot be established by inspection — only by running it. That
is precisely why §4.4 is a separate, earlier release: the answer arrives on a
no-op deploy rather than on the one that carries the suite.
