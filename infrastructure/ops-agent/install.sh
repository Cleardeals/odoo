#!/usr/bin/env bash
# infrastructure/ops-agent/install.sh
#
# Installs infrastructure/ops-agent/config.yaml onto this VM and restarts the
# Ops Agent. Run as root.
#
# This does NOT touch Odoo, Postgres or Traefik. The worst case is that the Ops
# Agent stops, which costs observability and nothing else — so it is safe to run
# outside a maintenance window. Even so, it validates before applying and rolls
# back automatically if the agent does not come back.

set -euo pipefail

SRC="${SRC:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.yaml}"
DST="${DST:-/etc/google-cloud-ops-agent/config.yaml}"
ENGINE=/opt/google-cloud-ops-agent/libexec/google_cloud_ops_agent_engine

die() { echo "ops-agent: FATAL: $*" >&2; exit 1; }
ok()  { echo "ops-agent: $*"; }

[[ "$(id -u)" -eq 0 ]] || die "must run as root"
[[ -r "$SRC" ]]        || die "config not readable: $SRC"
[[ -x "$ENGINE" ]]     || die "ops agent engine not found at $ENGINE — is the agent installed?"

# ── Validate BEFORE touching the live file ────────────────────────────────────
# The engine renders the merged configuration and runs its startup checks. A
# malformed config fails here rather than after the agent has been stopped.
tmp_out="$(mktemp -d)"
trap 'rm -rf "$tmp_out"' EXIT
"$ENGINE" -in "$SRC" -out "$tmp_out" -logs "$tmp_out" >/dev/null 2>&1 \
  || die "config failed validation — not installing"
ok "candidate config validated"

# ── Install, keeping a timestamped backup ─────────────────────────────────────
backup="${DST}.$(date -u +%Y%m%d-%H%M%S).bak"
if [[ -f "$DST" ]]; then
  cp -a "$DST" "$backup"
  ok "backed up existing config to $backup"
fi
install -m 0644 "$SRC" "$DST"
ok "installed $SRC -> $DST"

# ── Restart, and roll back if it does not come up ────────────────────────────
systemctl restart google-cloud-ops-agent
sleep 8

if ! systemctl is-active --quiet google-cloud-ops-agent; then
  echo "ops-agent: agent did NOT come back — rolling back" >&2
  if [[ -f "$backup" ]]; then
    install -m 0644 "$backup" "$DST"
    systemctl restart google-cloud-ops-agent || true
  fi
  die "rolled back to the previous config"
fi

ok "agent active"

# ── Prove it is actually shipping, not merely running ────────────────────────
# The agent ran "active" for months while silently dropping everything, so
# "is-active" is not evidence of anything on its own.
errs="$(journalctl -u google-cloud-ops-agent-opentelemetry-collector \
        --since '1 min ago' --no-pager 2>/dev/null \
        | grep -ci 'PermissionDenied' || true)"
[[ "$errs" == "0" ]] || die "agent is running but reporting PermissionDenied ($errs) — check the VM service account"

ok "no permission errors; container logs should appear in Cloud Logging shortly"
