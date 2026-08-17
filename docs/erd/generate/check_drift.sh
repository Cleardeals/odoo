#!/usr/bin/env bash
# check_drift.sh — fail if the schema changed but the ER diagram was not updated.
#
# Compares a live database's ER-diagram surface (in-scope tables and the foreign
# keys between them, per fingerprint.sql) against the committed baseline in
# schema-fingerprint.txt.
#
# This is the enforcement half of the ERD SOP: it is cheap (one SQL query, no
# diagram rendering), it runs in CI, and it names exactly what changed.
#
# Usage
#   ./check_drift.sh                       # against an already-running database
#   ./check_drift.sh --update              # accept current schema as the new baseline
#
# Connection (env vars, with defaults for the throwaway ERD stack):
#   PGHOST     default 127.0.0.1
#   PGPORT     default 5432
#   PGUSER     default odoo
#   PGPASSWORD default odoo
#   PGDATABASE default erd
#
# In CI, point it at the database the test job already built:
#   PGDATABASE=odoo_test_db PGPORT=5432 ./check_drift.sh
#
# Exit codes
#   0  no drift (or baseline updated with --update)
#   1  drift detected — regenerate the diagram, see SOP.md
#   2  could not run (no psql, no database, missing files)

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASELINE="${HERE}/schema-fingerprint.txt"
QUERY="${HERE}/fingerprint.sql"

export PGHOST="${PGHOST:-127.0.0.1}"
export PGPORT="${PGPORT:-5432}"
export PGUSER="${PGUSER:-odoo}"
export PGPASSWORD="${PGPASSWORD:-odoo}"
export PGDATABASE="${PGDATABASE:-erd}"

UPDATE=0
[[ "${1:-}" == "--update" ]] && UPDATE=1

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

die() { echo -e "${RED}[erd-drift] $*${NC}" >&2; exit 2; }

command -v psql > /dev/null 2>&1 \
  || die "psql not found. Install the PostgreSQL client, or run this inside a container that has it."
[[ -f "${QUERY}" ]]    || die "missing ${QUERY}"
[[ -f "${BASELINE}" ]] || die "missing ${BASELINE} (run with --update to create it)"

psql -tAc 'SELECT 1' > /dev/null 2>&1 \
  || die "cannot connect to ${PGUSER}@${PGHOST}:${PGPORT}/${PGDATABASE}"

# Confirm this really is an Odoo database with our modules, otherwise the
# fingerprint would come back near-empty and "no drift" would be meaningless.
INSTALLED=$(psql -tAc "
  SELECT count(*) FROM ir_module_module
  WHERE state='installed'
    AND name IN ('leads','properties','wa_communication','cleardeals_pubsub',
                 'cleardeals_notification','cleardeals_ui','cleardeals_dashboards');
" 2>/dev/null || echo 0)

if [[ "${INSTALLED}" -lt 5 ]]; then
  die "only ${INSTALLED}/7 custom modules are installed in '${PGDATABASE}'.
      Refusing to compare — a partial install would look like mass deletion."
fi

CURRENT="$(mktemp)"
trap 'rm -f "${CURRENT}"' EXIT

# The fingerprint intentionally counts non-audit columns, so it does NOT require
# the audit columns to have been dropped. Safe to run against any real database.
psql -tAf "${QUERY}" | sed '/^$/d' > "${CURRENT}"

if [[ ! -s "${CURRENT}" ]]; then
  die "fingerprint came back empty — check fingerprint.sql against this schema."
fi

if [[ "${UPDATE}" == "1" ]]; then
  cp "${CURRENT}" "${BASELINE}"
  echo -e "${GREEN}[erd-drift] baseline updated: $(wc -l < "${BASELINE}" | tr -d ' ') lines${NC}"
  echo "           Commit schema-fingerprint.txt together with the regenerated diagram."
  exit 0
fi

if diff -q "${BASELINE}" "${CURRENT}" > /dev/null 2>&1; then
  echo -e "${GREEN}[erd-drift] OK — schema matches the committed ER diagram ($(wc -l < "${BASELINE}" | tr -d ' ') entries).${NC}"
  exit 0
fi

echo -e "${RED}[erd-drift] SCHEMA DRIFT — the ER diagram is out of date.${NC}"
echo
echo "  - = in the committed diagram but no longer in the schema"
echo "  + = in the schema but not yet in the diagram"
echo
diff "${BASELINE}" "${CURRENT}" | grep -E '^[<>]' | sed 's/^</  -/; s/^>/  +/' || true
echo
echo -e "${YELLOW}  To fix: follow docs/erd/SOP.md — regenerate the diagram, then${NC}"
echo -e "${YELLOW}          ./check_drift.sh --update, and commit both.${NC}"
exit 1
