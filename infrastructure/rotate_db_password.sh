#!/usr/bin/env bash
# infrastructure/rotate_db_password.sh
#
# Rotates the Postgres role password to whatever is CURRENTLY the latest version
# of the odoo-db-password secret. Run as root on the VM.
#
# The new password is generated and stored in Secret Manager BEFORE this runs,
# from an operator workstation — deliberately. The VM's service account holds
# secretAccessor only: it can read secrets, not create versions. That is correct
# least privilege and worth keeping, so this script reads rather than writes.
#
# THE TRAP THIS EXISTS TO AVOID.
#
# Changing POSTGRES_PASSWORD in docker-compose.yml does NOTHING to an existing
# database. That variable is read only by initdb, on an EMPTY data directory —
# verified against postgres:17: a container restarted on an existing data dir
# with NO POSTGRES_PASSWORD at all starts cleanly and still authenticates.
#
# So editing the compose file and restarting looks like a rotation, closes the
# ticket, and leaves the old password in force. Only ALTER ROLE rotates it.
#
# WHY IT MATTERS HERE. The password is `odoo`, committed in docker-compose.yml
# in a PUBLIC repository — and in git history forever. Deleting the line is not
# a fix; only changing the credential is.
#
# THE WINDOW. Existing pooled connections survive ALTER ROLE; new ones fail
# until Odoo restarts. Kept to seconds by doing both back to back here.

set -euo pipefail

OLD_PW="${1:?usage: rotate_db_password.sh <current-password>}"
APP_DIR="${APP_DIR:-/opt/odoo}"
DB_CONTAINER="${DB_CONTAINER:-odoo-project-db-1}"
ODOO_CONTAINER="${ODOO_CONTAINER:-odoo-project-odoo-1}"
SECRET="${SECRET:-odoo-db-password}"
DB_USER="${DB_USER:-odoo}"
DB_NAME="${DB_NAME:-odoo_db}"

die() { echo "rotate: FATAL: $*" >&2; exit 1; }
ok()  { echo "rotate: $*"; }

[[ "$(id -u)" -eq 0 ]] || die "must run as root"
docker inspect "$DB_CONTAINER"   >/dev/null 2>&1 || die "no container $DB_CONTAINER"
docker inspect "$ODOO_CONTAINER" >/dev/null 2>&1 || die "no container $ODOO_CONTAINER"

# ── Read the new password that was already stored ────────────────────────────
NEW_PW="$(gcloud secrets versions access latest --secret="$SECRET" 2>/dev/null)" \
  || die "cannot read secret $SECRET"
[[ -n "$NEW_PW" ]] || die "secret $SECRET is empty"
[[ "$NEW_PW" != "$OLD_PW" ]] || die "the secret still holds the OLD password — store the new one first"
case "$NEW_PW" in
  *%*|*\'*|*\"*|*\\*|*\`*|*\$*) die "the stored password contains a character unsafe for the ini file or shell" ;;
esac
ok "new password read from Secret Manager (${#NEW_PW} chars, no unsafe characters)"

# ── Verify the OLD password works, before changing anything ──────────────────
# Verified from the ODOO container, not inside Postgres. This matters: the
# image ships pg_hba with
#     local all all              trust
#     host  all all 127.0.0.1/32 trust
#     host  all all all          scram-sha-256
# so ANY password succeeds over loopback or the unix socket. A check run inside
# the database container proves nothing — it passed with a deliberately wrong
# password during testing. Only a connection from another host on the network
# exercises scram-sha-256, which is the path Odoo itself uses.
docker exec -e PW="$OLD_PW" -e U="$DB_USER" -e D="$DB_NAME" "$ODOO_CONTAINER" python3 -c '"'"'
import os, sys, psycopg2
try:
    psycopg2.connect(host="db", user=os.environ["U"], password=os.environ["PW"],
                     dbname=os.environ["D"], connect_timeout=5).close()
except Exception:
    sys.exit(1)
'"'"' 2>/dev/null || die "the supplied current password does not authenticate over the network — refusing to proceed"
ok "current password verified over scram-sha-256, the path Odoo uses"

# ── Rotate, render and restart back to back ──────────────────────────────────
docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d postgres \
  -c "ALTER ROLE \"$DB_USER\" WITH PASSWORD '$NEW_PW'" >/dev/null \
  || die "ALTER ROLE failed — the old password is still in force and nothing has changed"
ok "ALTER ROLE done"

cd "$APP_DIR"
bash scripts/render_odoo_conf.sh >/dev/null \
  || die "config render failed AFTER the password changed. Odoo cannot reconnect until this succeeds — re-run scripts/render_odoo_conf.sh"
docker compose up -d --force-recreate odoo >/dev/null 2>&1 || die "could not restart Odoo"
ok "Odoo restarted"

# ── Prove it, against the database, not just the process ─────────────────────
for _ in $(seq 1 30); do
  if docker exec "$ODOO_CONTAINER" curl -fsS --max-time 5 \
       "http://localhost:8069/web/health?db_server_status=1" 2>/dev/null | grep -q '"status": *"pass"'; then
    ok "Odoo is authenticating to Postgres with the new password"
    ok "the value committed in git is now worthless"
    exit 0
  fi
  sleep 5
done
die "Odoo did not become healthy. Roll back with: ALTER ROLE \"$DB_USER\" WITH PASSWORD '<old>', then re-render and restart."
