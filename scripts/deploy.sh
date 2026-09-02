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

# Phase 4 moves the application to /opt/odoo. Until then this is the live path.
APP_DIR="${APP_DIR:-/home/cdgcphub/odoo-project}"
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

cd "$APP_DIR" || die "app dir not found: $APP_DIR"

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
git fetch --quiet origin
git reset --hard --quiet "$SHA" || die "commit $SHA not found after fetch"

# ── Config from Secret Manager into tmpfs ─────────────────────────────────────
log "rendering config"
bash scripts/render_odoo_conf.sh || die "config render failed — refusing to start Odoo with no config"

# ── Swap the image ────────────────────────────────────────────────────────────
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
while (( SECONDS < deadline )); do
  if healthy; then
    log "HEALTHY on ${SHA}"
    docker image prune -f >/dev/null 2>&1 || true
    exit 0
  fi
  sleep 5
done

# ── Rollback ──────────────────────────────────────────────────────────────────
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
