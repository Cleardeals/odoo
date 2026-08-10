#!/usr/bin/env bash
# run_tests.sh — Run Odoo tests locally, mirroring the GitHub Actions workflow.
#
# Runs anywhere Docker + bash are available: macOS, Linux, Windows WSL2, and
# Windows Git Bash (MINGW64). The containers talk to each other over a private
# Docker bridge network, so no host ports are needed and nothing clashes with a
# local dev stack.
#
# Usage:
#   ./run_tests.sh                    # run all default modules
#   ./run_tests.sh leads              # run only the leads module
#   ./run_tests.sh leads properties   # run specific modules (space-separated)
#
# This runs the Python suites AND the OWL/Hoot browser suites: modules with
# static/tests ship a post_install HttpCase that drives /web/tests through
# headless Chromium (installed in the image by the Dockerfile).
#
# Prerequisites:
#   - Docker running (Docker Desktop on macOS/Windows; on Windows enable WSL2
#     integration or run from Git Bash).
#
# Environment variable overrides (all optional):
#   KEEP_DB    — "1" leaves the Postgres container running after the run
#   REBUILD    — "1" forces a fresh Docker image build even if one exists
#   LOG_LEVEL  — odoo log level (default: test)

set -euo pipefail

# ── Windows / Git Bash (MSYS2) compatibility ─────────────────────────────────
# Git Bash auto-rewrites arguments that look like Unix paths, turning an Odoo
# test tag such as "/leads" into "C:/Program Files/Git/leads" ("Invalid tag",
# 0 tests) and mangling volume/build paths. Detect MSYS/Cygwin and disable that
# conversion. On macOS, Linux, WSL2 and CI (uname is Darwin/Linux) IS_MSYS stays
# 0 and this is a complete no-op.
case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW*|MSYS*|CYGWIN*)
        IS_MSYS=1
        export MSYS2_ARG_CONV_EXCL='*'
        export MSYS_NO_PATHCONV=1
        ;;
    *)
        IS_MSYS=0
        ;;
esac

# to_host_path converts a POSIX path to the form Docker expects for -v sources
# and build contexts. On Git Bash that means a native Windows path (C:\...);
# everywhere else the path is already correct and is echoed unchanged.
to_host_path() {
    local p="$1"
    if [[ "${IS_MSYS}" == "1" ]] && command -v cygpath > /dev/null 2>&1; then
        cygpath -w "${p}"
    else
        echo "${p}"
    fi
}

# ── Configurable defaults ────────────────────────────────────────────────────
DB_USER="odoo"
DB_PASSWORD="odoo"
DB_NAME="odoo_test_db"
IMAGE_NAME="my-odoo-image"
CONTAINER_NAME="odoo_test_postgres"
# User-defined bridge network so the Odoo container can reach Postgres by
# container name. Bridge is Docker's default driver and behaves identically on
# Linux, macOS and Windows/WSL2 — unlike `--network host`, which is a Linux-only
# feature (opt-in beta, off by default, on Docker Desktop for Mac/Windows).
NETWORK_NAME="odoo_test_net"
# HTTP/gevent ports are internal to the Odoo container (the bridge network is
# not published to the host), so they are fixed constants and can never clash
# with a local dev server on the same numbers.
HTTP_PORT="${HTTP_PORT:-8069}"
GEVENT_PORT="${GEVENT_PORT:-8072}"
LOG_LEVEL="${LOG_LEVEL:-test}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Modules/tags to test — can be overridden by positional arguments
DEFAULT_MODULES="leads,lead_suggestor,cleardeals_dashboards,properties,cleardeals_pubsub,cleardeals_notification,cleardeals_ui,wa_communication"
DEFAULT_TAGS="/leads,/lead_suggestor,/cleardeals_dashboards,/properties,/cleardeals_pubsub,/cleardeals_notification,/cleardeals_ui,/wa_communication"

if [[ $# -gt 0 ]]; then
    # Build comma-separated lists from positional args
    IFS=',' MODULE_LIST="${*// /,}"
    unset IFS
    MODULES="${MODULE_LIST}"
    TAGS=$(echo "${MODULE_LIST}" | sed 's/,/,\//g; s/^/\//')
else
    MODULES="${DEFAULT_MODULES}"
    TAGS="${DEFAULT_TAGS}"
fi

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Colour

log()  { echo -e "${CYAN}[test]${NC} $*"; }
ok()   { echo -e "${GREEN}[  OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

# ── Cleanup handler ──────────────────────────────────────────────────────────
cleanup() {
    if [[ "${KEEP_DB:-0}" == "1" ]]; then
        warn "KEEP_DB=1 — leaving Postgres container '${CONTAINER_NAME}' running."
        warn "Inspect it with: docker exec -it ${CONTAINER_NAME} psql -U ${DB_USER} ${DB_NAME}"
        warn "Stop it with:    docker rm -f ${CONTAINER_NAME}"
        warn "(Network '${NETWORK_NAME}' is left in place; remove with: docker network rm ${NETWORK_NAME})"
    else
        log "Stopping and removing Postgres container…"
        docker rm -f "${CONTAINER_NAME}" 2>/dev/null || true
        # Remove the network only after its attached container is gone.
        docker network rm "${NETWORK_NAME}" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# ── 1. Check Docker is available ─────────────────────────────────────────────
log "Checking Docker…"
docker info > /dev/null 2>&1 || fail "Docker is not running. Please start Docker Desktop."
ok "Docker is running."

# ── 2. Build Odoo image ──────────────────────────────────────────────────────
if [[ "${REBUILD:-0}" == "1" ]] || ! docker image inspect "${IMAGE_NAME}" > /dev/null 2>&1; then
    log "Building Odoo Docker image '${IMAGE_NAME}'…"
    docker build -t "${IMAGE_NAME}" "$(to_host_path "${SCRIPT_DIR}")"
    ok "Image built."
else
    ok "Image '${IMAGE_NAME}' already exists (use REBUILD=1 to force a rebuild)."
fi

# ── 3. Start Postgres ────────────────────────────────────────────────────────
log "Starting Postgres container…"

# Remove any stale container with the same name
docker rm -f "${CONTAINER_NAME}" 2>/dev/null || true

# Ensure the user-defined bridge network exists (idempotent).
docker network create "${NETWORK_NAME}" > /dev/null 2>&1 || true

# Postgres joins the bridge network so Odoo reaches it by container name. No
# host port is published — the test run does not need one, which keeps the
# script clash-free on every platform.
docker run -d \
    --name "${CONTAINER_NAME}" \
    --network "${NETWORK_NAME}" \
    -e POSTGRES_USER="${DB_USER}" \
    -e POSTGRES_PASSWORD="${DB_PASSWORD}" \
    -e POSTGRES_DB="${DB_NAME}" \
    postgres:17

# ── 4. Wait for Postgres to be ready ─────────────────────────────────────────
log "Waiting for Postgres to be ready…"
MAX_RETRIES=30
RETRY=0
until docker exec "${CONTAINER_NAME}" pg_isready -U "${DB_USER}" > /dev/null 2>&1; do
    RETRY=$((RETRY + 1))
    if [[ ${RETRY} -ge ${MAX_RETRIES} ]]; then
        fail "Postgres did not become ready after ${MAX_RETRIES} attempts."
    fi
    sleep 1
done
ok "Postgres is ready."

# ── 5. Run Odoo tests ────────────────────────────────────────────────────────
log "Running tests for modules: ${MODULES}"
log "Test tags: ${TAGS}"
echo ""

# Host path for the addons bind-mount, in the form Docker expects on this OS.
ADDONS_SRC="$(to_host_path "${SCRIPT_DIR}/custom_addons")"

# docker run exits non-zero if Odoo reports test failures; capture it without
# tripping `set -e` so the summary below can report cleanly.
TEST_EXIT=0
docker run --rm \
    --network "${NETWORK_NAME}" \
    --shm-size=2g \
    -v "${ADDONS_SRC}:/mnt/extra-addons" \
    -e HOST="${CONTAINER_NAME}" \
    -e PORT=5432 \
    -e USER="${DB_USER}" \
    -e PASSWORD="${DB_PASSWORD}" \
    "${IMAGE_NAME}" \
    odoo -d "${DB_NAME}" \
        --db_host="${CONTAINER_NAME}" \
        --db_port=5432 \
        --db_user="${DB_USER}" \
        --db_password="${DB_PASSWORD}" \
        --http-port="${HTTP_PORT}" \
        --gevent-port="${GEVENT_PORT}" \
        --addons-path=/mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons \
        -i "${MODULES}" \
        --test-enable \
        --test-tags "${TAGS}" \
        --stop-after-init \
        --log-level="${LOG_LEVEL}" || TEST_EXIT=$?

echo ""
if [[ ${TEST_EXIT} -eq 0 ]]; then
    ok "All tests passed."
else
    fail "Tests finished with exit code ${TEST_EXIT} — check the output above for failures."
fi
