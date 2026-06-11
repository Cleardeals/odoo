#!/usr/bin/env bash
# run_tests.sh — Run Odoo tests locally, mirroring the GitHub Actions workflow.
#
# Usage:
#   ./run_tests.sh                    # run all tagged modules
#   ./run_tests.sh leads              # run only the leads module
#   ./run_tests.sh leads properties   # run specific modules (space-separated)
#
# Prerequisites:
#   - Docker running
#   (Ports no longer need to be free — the script auto-picks free ones. A
#    running local dev stack on 5432/8069/8072 will no longer cause a clash.)
#
# Environment variable overrides (all optional):
#   DB_PORT      — host port for Postgres (default: first free port from 5432)
#   HTTP_PORT    — host port for Odoo HTTP (default: first free port from 8069)
#   GEVENT_PORT  — host port for Odoo websockets/longpolling
#                  (default: first free port from HTTP_PORT+2)
#   KEEP_DB      — if set to "1", the Postgres container is left running after tests
#   REBUILD      — if set to "1", forces a fresh Docker image build even if one exists
#   LOG_LEVEL    — odoo log level (default: test)
#
# Any port you set explicitly is honoured as-is; only unset ports are
# auto-selected. This matters because the test container uses host networking,
# so Odoo would otherwise fight a running dev instance for 8069/8072.

set -euo pipefail

# ── Free-port detection ──────────────────────────────────────────────────────
# port_in_use returns success (0) if something is already listening on the
# given TCP port. Uses bash's /dev/tcp so it needs no external tools and works
# the same on macOS and the Linux CI runner.
port_in_use() {
    local p="$1"
    if (exec 3<>"/dev/tcp/127.0.0.1/${p}") 2>/dev/null; then
        exec 3>&- 3<&- 2>/dev/null || true
        return 0
    fi
    return 1
}

# find_free_port echoes the first free TCP port at or above the start value.
find_free_port() {
    local p="$1"
    while port_in_use "${p}"; do
        p=$((p + 1))
    done
    echo "${p}"
}

# ── Configurable defaults ────────────────────────────────────────────────────
# Ports default to the first free port at/above the conventional one, so a
# running local dev stack (Postgres on 5432, Odoo on 8069/8072) does not clash.
DB_PORT="${DB_PORT:-$(find_free_port 5432)}"
HTTP_PORT="${HTTP_PORT:-$(find_free_port 8069)}"
GEVENT_PORT="${GEVENT_PORT:-$(find_free_port $((HTTP_PORT + 2)))}"
DB_USER="odoo"
DB_PASSWORD="odoo"
DB_NAME="odoo_test_db"
IMAGE_NAME="my-odoo-image"
CONTAINER_NAME="odoo_test_postgres"
LOG_LEVEL="${LOG_LEVEL:-test}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Modules/tags to test — can be overridden by positional arguments
DEFAULT_MODULES="leads,lead_suggestor,cleardeals_dashboards,properties"
DEFAULT_TAGS="/leads,/lead_suggestor,/cleardeals_dashboards,/properties"

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
        warn "Stop it manually with: docker rm -f ${CONTAINER_NAME}"
    else
        log "Stopping and removing Postgres container…"
        docker rm -f "${CONTAINER_NAME}" 2>/dev/null || true
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
    docker build -t "${IMAGE_NAME}" "${SCRIPT_DIR}"
    ok "Image built."
else
    ok "Image '${IMAGE_NAME}' already exists (use REBUILD=1 to force a rebuild)."
fi

# ── 3. Start Postgres ────────────────────────────────────────────────────────
log "Starting Postgres container on port ${DB_PORT}…"

# Remove any stale container with the same name
docker rm -f "${CONTAINER_NAME}" 2>/dev/null || true

docker run -d \
    --name "${CONTAINER_NAME}" \
    -e POSTGRES_USER="${DB_USER}" \
    -e POSTGRES_PASSWORD="${DB_PASSWORD}" \
    -e POSTGRES_DB="${DB_NAME}" \
    -p "${DB_PORT}:5432" \
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
log "Ports — Postgres: ${DB_PORT}, HTTP: ${HTTP_PORT}, gevent: ${GEVENT_PORT}"
echo ""

docker run --rm \
    --network host \
    -v "${SCRIPT_DIR}/custom_addons:/mnt/extra-addons" \
    -e HOST=localhost \
    -e PORT="${DB_PORT}" \
    -e USER="${DB_USER}" \
    -e PASSWORD="${DB_PASSWORD}" \
    "${IMAGE_NAME}" \
    odoo -d "${DB_NAME}" \
        --db_host=localhost \
        --db_port="${DB_PORT}" \
        --db_user="${DB_USER}" \
        --db_password="${DB_PASSWORD}" \
        --http-port="${HTTP_PORT}" \
        --gevent-port="${GEVENT_PORT}" \
        --addons-path=/mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons \
        -i "${MODULES}" \
        --test-enable \
        --test-tags "${TAGS}" \
        --stop-after-init \
        --log-level="${LOG_LEVEL}"

# docker run exits with non-zero if Odoo reports test failures
TEST_EXIT=$?

echo ""
if [[ ${TEST_EXIT} -eq 0 ]]; then
    ok "All tests passed."
else
    fail "Tests finished with exit code ${TEST_EXIT} — check the output above for failures."
fi
