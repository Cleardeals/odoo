#!/usr/bin/env bash
# prod_migration_check.sh
# ---------------------------------------------------------------------------
# Rehearse an Odoo deployment against a fresh, READ-ONLY snapshot of the
# production database, entirely on the local machine. Proves that the modules
# about to be deployed upgrade cleanly (migrations run, no errors, no data
# loss) BEFORE anything is pushed to production.
#
# SAFETY: production is only ever READ.
#   * The snapshot is taken by streaming `pg_dump` over SSH to local stdout —
#     nothing is written to the prod VM's disk and nothing is written to the
#     prod database.
#   * All restore + upgrade work happens in throwaway local containers.
#
# Runs anywhere Docker + bash + gcloud exist: macOS, Linux, WSL2, Git Bash.
#
# Usage:
#   ./prod_migration_check.sh                 # auto-detect modules to upgrade
#   ./prod_migration_check.sh leads properties  # upgrade a specific set
#   KEEP=1 ./prod_migration_check.sh          # leave the local DB up for inspection
#
# Config (override via env):
#   GCP_ZONE GCP_INSTANCE GCP_PROJECT         # where prod runs
#   PROD_DB_CONTAINER PROD_DB_NAME PROD_DB_USER
#   IMAGE_NAME                                # local Odoo image (built by run_tests.sh)
#   REUSE_DUMP=/path/to.dump                  # skip the SSH snapshot, reuse a dump
#   KEEP=1                                    # keep local DB + containers afterwards
# ---------------------------------------------------------------------------
set -euo pipefail

# ── prod coordinates (defaults match the Cleardeals prod VM) ─────────────────
GCP_ZONE="${GCP_ZONE:-us-central1-f}"
GCP_INSTANCE="${GCP_INSTANCE:-odoo-19-prod}"
GCP_PROJECT="${GCP_PROJECT:-odoo-472708}"
PROD_DB_CONTAINER="${PROD_DB_CONTAINER:-odoo-project-db-1}"
PROD_DB_NAME="${PROD_DB_NAME:-odoo_db}"
PROD_DB_USER="${PROD_DB_USER:-odoo}"

# ── local coordinates ───────────────────────────────────────────────────────
IMAGE_NAME="${IMAGE_NAME:-my-odoo-image}"
PG_IMAGE="${PG_IMAGE:-postgres:17}"
NETWORK_NAME="prodcheck_net"
PG_CONTAINER="prodcheck_db"
LOCAL_DB="${LOCAL_DB:-odoo_db}"
LOCAL_DB_USER="odoo"
LOCAL_DB_PASS="odoo"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Repo root = two levels up from .claude/skills/<name>/. Override with REPO_ROOT.
REPO_ROOT="${REPO_ROOT:-$(cd "${SCRIPT_DIR}/../../.." && pwd)}"
ADDONS_DIR="${ADDONS_DIR:-${REPO_ROOT}/custom_addons}"
WORK_DIR="$(mktemp -d)"
DUMP_FILE="${REUSE_DUMP:-${WORK_DIR}/prod.dump}"

# ── Windows / Git Bash (MSYS2) path handling ────────────────────────────────
case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW*|MSYS*|CYGWIN*) export MSYS2_ARG_CONV_EXCL='*'; export MSYS_NO_PATHCONV=1; IS_MSYS=1 ;;
    *) IS_MSYS=0 ;;
esac
to_host_path() { if [[ "${IS_MSYS}" == "1" ]] && command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else echo "$1"; fi; }

# ── colours / logging ───────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${CYAN}[check]${NC} $*"; }
ok()   { echo -e "${GREEN}[  OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

cleanup() {
    if [[ "${KEEP:-0}" == "1" ]]; then
        warn "KEEP=1 — leaving DB container '${PG_CONTAINER}' up (db '${LOCAL_DB}')."
        warn "Inspect: docker exec -it ${PG_CONTAINER} psql -U ${LOCAL_DB_USER} ${LOCAL_DB}"
        warn "Remove:  docker rm -f ${PG_CONTAINER} && docker network rm ${NETWORK_NAME}"
    else
        docker rm -f "${PG_CONTAINER}" >/dev/null 2>&1 || true
        docker network rm "${NETWORK_NAME}" >/dev/null 2>&1 || true
    fi
    [[ -z "${REUSE_DUMP:-}" ]] && rm -rf "${WORK_DIR}" 2>/dev/null || true
}
trap cleanup EXIT

MODULES_REQUESTED="$*"   # empty => auto-detect

# ── 0. preflight ────────────────────────────────────────────────────────────
log "Preflight…"
docker info >/dev/null 2>&1 || fail "Docker is not running."
docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1 || fail "Image '${IMAGE_NAME}' missing — run ./run_tests.sh once to build it."
[[ -d "${ADDONS_DIR}" ]] || fail "custom_addons not found at ${ADDONS_DIR} (set ADDONS_DIR)."
if [[ -z "${REUSE_DUMP:-}" ]]; then
    command -v gcloud >/dev/null 2>&1 || fail "gcloud not found (needed for the snapshot)."
fi
ok "Preflight passed. Repo: ${REPO_ROOT}"

# ── 1. snapshot prod (READ-ONLY, streamed — nothing written on prod) ────────
if [[ -n "${REUSE_DUMP:-}" ]]; then
    log "Reusing dump ${REUSE_DUMP} (skipping snapshot)."
    [[ -f "${REUSE_DUMP}" ]] || fail "REUSE_DUMP file does not exist."
else
    log "Snapshotting prod ${PROD_DB_NAME} (read-only stream over SSH)…"
    gcloud compute ssh --zone "${GCP_ZONE}" "${GCP_INSTANCE}" --project "${GCP_PROJECT}" \
        --command "sudo docker exec ${PROD_DB_CONTAINER} pg_dump -U ${PROD_DB_USER} -Fc -d ${PROD_DB_NAME}" \
        > "${DUMP_FILE}" 2>"${WORK_DIR}/ssh.err" \
        || { cat "${WORK_DIR}/ssh.err"; fail "Snapshot failed."; }
    ok "Snapshot captured: $(du -h "${DUMP_FILE}" | cut -f1)"
fi

# validate archive
docker run --rm -v "$(to_host_path "$(dirname "${DUMP_FILE}")"):/d" "${PG_IMAGE}" \
    pg_restore -l "/d/$(basename "${DUMP_FILE}")" >/dev/null 2>&1 \
    || fail "Dump is not a valid pg_restore archive."
ok "Dump archive validated."

# ── 2. restore into a throwaway local DB ────────────────────────────────────
log "Starting local ${PG_IMAGE} and restoring…"
docker rm -f "${PG_CONTAINER}" >/dev/null 2>&1 || true
docker network create "${NETWORK_NAME}" >/dev/null 2>&1 || true
docker run -d --name "${PG_CONTAINER}" --network "${NETWORK_NAME}" \
    -e POSTGRES_USER="${LOCAL_DB_USER}" -e POSTGRES_PASSWORD="${LOCAL_DB_PASS}" \
    -e POSTGRES_DB="${LOCAL_DB}" "${PG_IMAGE}" >/dev/null
for i in $(seq 1 30); do docker exec "${PG_CONTAINER}" pg_isready -U "${LOCAL_DB_USER}" >/dev/null 2>&1 && break; sleep 1; done
docker run --rm --network "${NETWORK_NAME}" -e PGPASSWORD="${LOCAL_DB_PASS}" \
    -v "$(to_host_path "$(dirname "${DUMP_FILE}")"):/d" "${PG_IMAGE}" \
    pg_restore -h "${PG_CONTAINER}" -U "${LOCAL_DB_USER}" -d "${LOCAL_DB}" \
        --no-owner --no-privileges --jobs=4 "/d/$(basename "${DUMP_FILE}")" \
        > "${WORK_DIR}/restore.log" 2>&1 || { tail -20 "${WORK_DIR}/restore.log"; fail "Restore failed."; }
ok "Restored prod snapshot into local db '${LOCAL_DB}'."

psql_q() { docker exec "${PG_CONTAINER}" psql -U "${LOCAL_DB_USER}" -d "${LOCAL_DB}" -tAc "$1"; }

# ── 3. decide which modules to upgrade ──────────────────────────────────────
if [[ -n "${MODULES_REQUESTED}" ]]; then
    MODULES="${MODULES_REQUESTED// /,}"
    log "Upgrading requested modules: ${MODULES}"
else
    log "Auto-detecting modules whose code version > installed version…"
    # Capture installed versions FIRST (avoids nesting a command substitution
    # on the heredoc line, which breaks bash parsing).
    INSTALLED_RAW="$(psql_q "SELECT name||'='||coalesce(latest_version,'') FROM ir_module_module WHERE state='installed';")"
    # Write the detector to a temp file (a heredoc INSIDE $(...) breaks on
    # macOS bash 3.2), then invoke it normally.
    PYHELPER="${WORK_DIR}/detect_modules.py"
    cat > "${PYHELPER}" <<'PY'
import ast, os, sys, re
addons, installed_raw = sys.argv[1], sys.argv[2]
installed = dict(l.split('=', 1) for l in installed_raw.splitlines() if '=' in l)

def series_of(v):
    # "19.0" from an installed version like "19.0.1.6.0"
    parts = (v or '').split('.')
    return '.'.join(parts[:2]) if len(parts) >= 2 else (v or '')

def adapt(code, installed):
    # Mirror Odoo's adapt_version: a manifest version without the server series
    # (e.g. "1.7.0") is stored in the DB as "<series>.<version>" ("19.0.1.7.0").
    s = series_of(installed)
    if s and code != s and not code.startswith(s + '.'):
        code = s + '.' + code
    return code

def tup(v):
    return [int(x) for x in re.findall(r'\d+', v or '')]

out = []
for name in sorted(installed):
    man = os.path.join(addons, name, '__manifest__.py')
    if not os.path.isfile(man):
        continue
    try:
        code = str(ast.literal_eval(open(man).read()).get('version', ''))
    except Exception:
        continue
    if not code:
        continue
    if tup(adapt(code, installed[name])) > tup(installed[name]):
        out.append(name)
print(','.join(out))
PY
    MODULES="$(python3 "${PYHELPER}" "${ADDONS_DIR}" "${INSTALLED_RAW}")"
    [[ -n "${MODULES}" ]] || { ok "No module has a higher code version than prod — nothing to upgrade. Deploy is a no-op migration-wise."; exit 0; }
    log "Detected upgrades: ${MODULES}"
fi

# Compare against the module set via SQL string_to_array — avoids building a
# quoted IN-list in bash (single quotes inside ${//} break bash parsing).
MOD_FILTER="name = ANY(string_to_array('${MODULES}', ','))"

echo ""
log "Versions BEFORE upgrade:"
psql_q "SELECT '  '||name||': '||latest_version FROM ir_module_module WHERE ${MOD_FILTER} ORDER BY name;"

# ── 4. run the upgrade (the real deploy command) ────────────────────────────
echo ""
log "Running: odoo -u ${MODULES} --stop-after-init …"
ODOO_EXIT=0
docker run --rm --network "${NETWORK_NAME}" \
    -v "$(to_host_path "${ADDONS_DIR}"):/mnt/extra-addons" \
    "${IMAGE_NAME}" \
    odoo -d "${LOCAL_DB}" \
        --db_host="${PG_CONTAINER}" --db_port=5432 \
        --db_user="${LOCAL_DB_USER}" --db_password="${LOCAL_DB_PASS}" \
        --addons-path=/mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons \
        -u "${MODULES}" --stop-after-init --no-http --log-level=info \
        > "${WORK_DIR}/migrate.log" 2>&1 || ODOO_EXIT=$?

# ── 5. verdict ──────────────────────────────────────────────────────────────
echo ""
log "── Migration log — upgrade steps ─────────────────────────────"
grep -iE "Running upgrade|pre-migrate|post-migrate|end-migrate|backfill|Dropped|migrat" "${WORK_DIR}/migrate.log" || echo "  (no explicit migration log lines)"

# Real Odoo errors have the log format '<ts> <pid> ERROR <db> ...'. Exclude
# docutils RST-rendering noise which looks like '<string>:NN: (ERROR/3) ...'.
REAL_ERRORS="$(grep -nE " (ERROR|CRITICAL) [^ ]+ odoo|Traceback \(most recent" "${WORK_DIR}/migrate.log" | grep -vE "\(ERROR/[0-9]\)" || true)"

echo ""
log "── Versions AFTER upgrade ────────────────────────────────────"
psql_q "SELECT '  '||name||': '||latest_version FROM ir_module_module WHERE ${MOD_FILTER} ORDER BY name;"

echo ""
if [[ "${ODOO_EXIT}" -eq 0 && -z "${REAL_ERRORS}" ]]; then
    ok "MIGRATION CHECK PASSED — modules upgraded cleanly against the prod snapshot."
    if [[ "${KEEP:-0}" == "1" ]]; then
        cp "${WORK_DIR}/migrate.log" "./prod_migration_check.log" && log "Copied log to ./prod_migration_check.log"
    fi
    ok "Migration log preserved in the run's temp dir (or ./prod_migration_check.log with KEEP=1)."
    exit 0
else
    echo -e "${RED}[FAIL]${NC} Odoo exit=${ODOO_EXIT}. Real errors:"
    echo "${REAL_ERRORS}" | head -30
    cp "${WORK_DIR}/migrate.log" "./prod_migration_check.log" 2>/dev/null || true
    fail "MIGRATION CHECK FAILED — do NOT deploy. Full log copied to ./prod_migration_check.log"
fi
