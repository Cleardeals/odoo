#!/usr/bin/env bash
# scripts/deploy.sh — the production deploy, run ON the VM.
#
# Invoked by Cloud Build over SSH:
#     sudo /opt/odoo/scripts/deploy.sh <commit-sha>
#
# It lives in the repo rather than inline in cloudbuild.yaml on purpose. A
# heredoc in the build config would pass through three layers of quoting —
# Cloud Build substitution, then bash, then ssh — which is where deploy scripts
# reliably die over a stray quote nobody can see in a diff. Here it is
# reviewable in a PR, and runnable by hand when something has gone wrong at
# 3am and Cloud Build is not the tool you want.
#
# What it replaces: a workflow that ran `docker compose build` ON THIS VM,
# competing with Odoo for the CPU and the disk, and then reported success
# whether or not Odoo came back up.

set -euo pipefail

# Defined first: the project-id lookup below calls die().
log() { echo "[deploy $(date -u +%H:%M:%S)] $*"; }
die() { echo "[deploy] FATAL: $*" >&2; exit 1; }

SHA="${1:?usage: deploy.sh <commit-sha>}"

# Resolved, not hardcoded, so the Phase 4 move to /opt/odoo needs no flag day.
#
# The pipeline and this script must both keep working on BOTH sides of that
# move. Pinning either path means the deploy breaks for the window between the
# directory moving and the code that knows about it being deployed — and the
# only way to deploy that code is the deploy that is broken.
#
# /opt/odoo wins when it exists. Once the move is done and settled, the
# fallback can be deleted.
if [[ -n "${APP_DIR:-}" ]]; then
  :                                   # explicit override always wins
elif [[ -d /opt/odoo/.git ]]; then
  APP_DIR=/opt/odoo
elif [[ -d /home/cdgcphub/odoo-project/.git ]]; then
  APP_DIR=/home/cdgcphub/odoo-project
else
  echo "[deploy] FATAL: no checkout at /opt/odoo or /home/cdgcphub/odoo-project" >&2
  exit 1
fi
REGISTRY="${REGISTRY:-us-central1-docker.pkg.dev}"

# Project id is read from the instance metadata server rather than hard-coded.
# This repository is PUBLIC: no project identifier belongs in it. Reading it
# from metadata is also simply more correct — the VM knows which project it is
# in, and a copy of this script on another host cannot silently deploy to the
# wrong registry.
GCP_PROJECT="${GCP_PROJECT:-$(curl -fsS -H 'Metadata-Flavor: Google' \
  http://metadata.google.internal/computeMetadata/v1/project/project-id 2>/dev/null || true)}"
[[ -n "${GCP_PROJECT}" ]] || die "cannot determine GCP project (not on a GCE VM? set GCP_PROJECT)"

IMAGE_BASE="${IMAGE_BASE:-${REGISTRY}/${GCP_PROJECT}/odoo/odoo}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-300}"   # 5 min: a migration deploy is slow

# Public hostname, used by the edge gate below to prove traffic actually reaches
# Odoo through Traefik. It MUST match the Host(`...`) rule on the odoo router in
# docker-compose.yml — Traefik routes on it, so a value that does not match
# matches no router and returns 404.
#
# That coupling is deliberate rather than clever. Deriving it by parsing the
# compose labels would keep the two in sync automatically, but it would also
# silently follow a typo, and this gate exists precisely to notice when the
# public path is broken. If the domain ever changes, this line should be part of
# that change, and the failure message below says so outright.
EDGE_HOST="${EDGE_HOST:-odoo.cleardeals.xyz}"
EDGE_TIMEOUT="${EDGE_TIMEOUT:-60}"        # Traefik's docker provider is event-driven

cd "$APP_DIR" || die "app dir not found: $APP_DIR"

# git refuses to operate on a repository owned by another user ("detected
# dubious ownership"). This script runs as root; the checkout is owned by
# cdgcphub. The inline bootstrap in cloudbuild.yaml passes -c safe.directory on
# every call, but this script's own git commands did not — so all of them failed
# and the deploy died after the checkout.
#
# Set once here, for every git invocation in the script, via environment rather
# than `git config --global`: a deploy should not leave persistent config behind
# on the host.
#
# The real fix is Phase 4 moving the application out of a personal home
# directory to /opt/odoo owned by a deploy group. This is the third distinct
# failure caused by that location.
export GIT_CONFIG_COUNT=1
export GIT_CONFIG_KEY_0=safe.directory
export GIT_CONFIG_VALUE_0="$APP_DIR"

# ── One deploy at a time ──────────────────────────────────────────────────────
# Cloud Build does not serialise approved builds. Two people approving in quick
# succession would otherwise interleave .env writes and leave an image running
# that nobody chose.
exec 9>/var/lock/odoo-deploy.lock
flock -n 9 || die "another deploy is already running"

# ── Rollback pointer comes from what is RUNNING ───────────────────────────────
# Deliberately NOT from .env. If someone hand-edited that file and never
# restarted, it describes an intention rather than reality — and rollback would
# restore an image that was never actually serving traffic.
CONTAINER="$(docker compose ps -q odoo 2>/dev/null || true)"
if [[ -n "$CONTAINER" ]]; then
  PREV="$(docker inspect --format '{{.Config.Image}}' "$CONTAINER")"
  log "currently running: $PREV"
else
  PREV=""
  log "no running odoo container — this is a cold start, rollback unavailable"
fi

NEW="${IMAGE_BASE}:${SHA}"

# ── Bring the working tree to the exact commit being deployed ─────────────────
# compose file, odoo.prod.conf and this script must match the image. The
# application code itself is IN the image, not here.
log "checking out ${SHA}"
# HTTPS rather than the git@github.com remote the VM was set up with. This
# script runs under sudo; root has no GitHub key, so an SSH fetch fails with
# "Host key verification failed". The repository is public, so HTTPS needs no
# credentials — and the VM no longer needs a GitHub deploy key at all.
# Idempotent, so a hand-run deploy self-heals a remote someone changed back.
# When invoked by the pipeline the tree is ALREADY at the target commit — the
# build step checks it out before calling this script, because on a first run
# this file does not yet exist on the VM. So only fetch when the tree is not
# already where it needs to be. That makes the script idempotent and keeps it
# runnable by hand.
if [[ "$(git rev-parse HEAD)" != "$SHA" ]]; then
  # HTTPS rather than the git@github.com remote the VM was set up with. This
  # runs under sudo; root has no GitHub key, so an SSH fetch fails with "Host
  # key verification failed". The repo is public, so HTTPS needs no credentials
  # — and the VM no longer needs a GitHub deploy key at all.
  git remote set-url origin "${REPO_URL:-https://github.com/Cleardeals/odoo.git}"

  # --depth 1 is REQUIRED, not an optimisation. The checkout is a shallow clone,
  # and a plain `git fetch` on a shallow repo unshallows it, pulling the whole
  # history of a vendored Odoo fork. Measured live: .git grew from 980MB to
  # 5.3GB before the fetch was killed, and it had not finished.
  #
  # The BRANCH is fetched, not the commit: GitHub refuses to serve an arbitrary
  # SHA here ("couldn't find remote ref"). The assertion below then confirms the
  # tree really is the commit that was built.
  git fetch --depth 1 --quiet origin "${DEPLOY_BRANCH:-19.0}"
  git reset --hard --quiet FETCH_HEAD
fi
# The checkout must be EXACTLY the commit that was built and tested. The
# pipeline fetches a branch tip (GitHub will not serve an arbitrary SHA to
# fetch), so if someone pushed to the branch between the build starting and the
# deploy running, the tip is no longer what was tested. Refuse rather than ship
# an untested tree alongside a tested image.
ACTUAL="$(git rev-parse HEAD)"
[[ "$ACTUAL" == "$SHA" ]] || die "checkout is $ACTUAL but the built commit is $SHA — the branch moved mid-build; refusing to deploy"

# ── Config from Secret Manager into tmpfs ─────────────────────────────────────
log "rendering config"
bash scripts/render_odoo_conf.sh || die "config render failed — refusing to start Odoo with no config"

# ── Swap the image ────────────────────────────────────────────────────────────
# Docker needs a credential helper to pull from Artifact Registry. Without it
# the pull fails with "denied: Unauthenticated request" — the daemon does not
# use the VM's service account by itself. This is configured here rather than
# assumed as VM state, so a rebuilt or replaced VM works with no manual step.
# Idempotent: it just rewrites root's docker config.
log "configuring the Artifact Registry credential helper"
gcloud auth configure-docker "${REGISTRY}" --quiet >/dev/null 2>&1 \
  || die "could not configure the docker credential helper for ${REGISTRY}"

log "pulling ${NEW}"
docker compose pull odoo || die "cannot pull $NEW"

echo "ODOO_IMAGE=${NEW}" > .env
log "starting"
docker compose up -d odoo

# ── Health gate ───────────────────────────────────────────────────────────────
# A BARE /web/health IS NOT A HEALTH CHECK. Read the route in
# addons/web/controllers/home.py: it returns 200 {"status":"pass"} without
# touching the database unless db_server_status is passed. A gate polling the
# bare path goes green with Postgres down and then reports a successful deploy.
#
# db_server_status=1 proves the database is reachable; /web/login additionally
# proves the registry loaded and the modules initialised.
healthy() {
  docker compose exec -T odoo curl -fsS \
      "http://localhost:8069/web/health?db_server_status=1" 2>/dev/null \
    | grep -q '"status": *"pass"' \
  && docker compose exec -T odoo curl -fsS -o /dev/null \
      "http://localhost:8069/web/login" 2>/dev/null
}

log "waiting for health (up to ${HEALTH_TIMEOUT}s)"
deadline=$(( SECONDS + HEALTH_TIMEOUT ))
odoo_ok=false
while (( SECONDS < deadline )); do
  if healthy; then odoo_ok=true; break; fi
  sleep 5
done

# ── Rollback ──────────────────────────────────────────────────────────────────
if [[ "$odoo_ok" != true ]]; then
  log "health check FAILED after ${HEALTH_TIMEOUT}s"
  docker compose logs --tail=50 odoo 2>&1 | sed 's/^/    /' >&2

  if [[ -z "$PREV" ]]; then
    die "no previous image to roll back to — leaving the failed container for inspection"
  fi

  log "rolling back to ${PREV}"
  echo "ODOO_IMAGE=${PREV}" > .env
  docker compose up -d odoo

  # NOTE: this restores the IMAGE. It does not undo a schema migration — those are
  # not reversible by re-pinning a tag. A deploy that ran migrations and then
  # failed its health check needs the pre-deploy dump, not this path.
  die "deploy of ${SHA} failed health check; rolled back to ${PREV}"
fi

log "Odoo is healthy on ${SHA}; checking the public path"

# ── Edge gate ─────────────────────────────────────────────────────────────────
# EVERY CHECK ABOVE THIS LINE ASKS ODOO ABOUT ITSELF, FROM INSIDE ITS OWN
# CONTAINER. That is a real gate for "did the image boot and load the registry",
# and a complete blind spot for "can a user reach the site".
#
# The blind spot is not hypothetical. During the Phase 4c window Traefik's
# docker provider died on a client/daemon API mismatch, so it discovered no
# containers and served 404 for every request — while Odoo sat behind it
# perfectly healthy, answering the checks above. The deploy went green and the
# site was down. Nothing in this script could have known.
#
# So this asks the question from the outside in, over the same path a browser
# takes: TLS on 443, SNI and Host set to the public name, routed by Traefik,
# proxied to Odoo, 200 back.
#
# --resolve pins that hostname to the loopback address instead of using DNS.
# Two reasons: the check must test THIS host rather than whatever the public
# record currently points at, and it must not depend on the VM being able to
# reach its own external address. The Host header and SNI still carry the real
# name, so Traefik's router matches and the certificate validates normally.
#
# Verified before this was written, rather than assumed:
#
#   * against the healthy production stack it returns 200 with a valid
#     certificate;
#   * with a hostname no router matches it returns 404, so `curl -f` fails —
#     which is exactly the shape of the 4c outage, and the proof that this gate
#     would have caught it;
#   * the same probe on port 80 returns 301 even for a host no router matches,
#     because the http->https redirect is configured on the ENTRYPOINT and runs
#     before routing. A port-80 probe would therefore have passed straight
#     through the 4c outage. It is not a usable gate, and that is why this one
#     speaks TLS.
edge_healthy() {
  curl -fsS -o /dev/null --max-time 10 \
    --resolve "${EDGE_HOST}:443:127.0.0.1" \
    "https://${EDGE_HOST}/web/login" 2>/dev/null
}

edge_ok=false
edge_deadline=$(( SECONDS + EDGE_TIMEOUT ))
while (( SECONDS < edge_deadline )); do
  if edge_healthy; then edge_ok=true; break; fi
  sleep 3
done

if [[ "$edge_ok" != true ]]; then
  # DELIBERATELY NO ROLLBACK HERE.
  #
  # Odoo has already proven itself healthy on the new image, so re-pinning the
  # previous tag cannot fix a broken edge — it would just be a second unplanned
  # change made while somebody is trying to diagnose the first, and it would
  # leave production running older code for a fault that has nothing to do with
  # the code. The right response is to fail loudly and hand over the evidence.
  log "EDGE CHECK FAILED: Odoo is healthy, but ${EDGE_HOST} does not serve through Traefik"
  log "the image is fine — do NOT roll it back; this is the proxy or the routing"
  log ""
  log "check, in order:"
  log "  1. is the odoo container attached to the 'web' network"
  log "  2. is Traefik running, and is its docker provider alive"
  log "  3. does EDGE_HOST still match the Host() rule in docker-compose.yml"
  log ""
  # Diagnostics stay on STDOUT, unlike the rollback path above which sends
  # container logs to stderr. Both streams end up in the same Cloud Build log,
  # but they are flushed independently, so mixing them reorders the output —
  # the first run of this block printed the Traefik logs underneath the heading
  # of the section that follows them. When the whole point is to hand a human a
  # readable trail, the ordering is part of the diagnostic.
  log "--- traefik logs ---"
  docker compose logs --tail=50 traefik 2>&1 | sed 's/^/    /' || true
  log "--- routers Traefik currently knows about ---"
  # 0 routers here is the signature of the 4c failure: Traefik alive and
  # answering, but its docker provider dead, so nothing is routed anywhere.
  curl -fsS --max-time 5 http://127.0.0.1:8080/api/rawdata 2>/dev/null \
    | python3 -c 'import json,sys; print("    routers:", len(json.load(sys.stdin).get("routers",{})))' 2>/dev/null \
    || log "    (dashboard unreachable — Traefik itself is likely the problem)"
  die "deploy of ${SHA} is live on Odoo but not reachable at ${EDGE_HOST}"
fi

log "HEALTHY on ${SHA} (odoo + edge)"
docker image prune -f >/dev/null 2>&1 || true
exit 0
