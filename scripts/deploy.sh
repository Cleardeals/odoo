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
