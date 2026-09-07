#!/usr/bin/env bash
# scripts/phase4c_move.sh
#
# Moves the application out of a personal home directory.
#
#     /home/cdgcphub/odoo-project  ->  /opt/odoo
#
# Run as root on the VM, with the stack DOWN, inside the Phase 4c window.
#
# WHY THIS MOVE EXISTS. Three separate outage-class problems have come from the
# application living in someone's home directory:
#
#   1. `git` refused to operate on a repo owned by another user ("detected
#      dubious ownership") and killed a production deploy.
#   2. Under OS Login the interactive user is tech_cleardeals_in, which cannot
#      even `cd` into /home/cdgcphub — it is mode 750. A manual command there
#      failed silently and ran in the wrong directory.
#   3. The location is why the addons were bind-mounted in the first place,
#      which is what made the image tag a lie and rollback a fiction.
#
# /opt is root:root 755, so /opt/odoo is traversable by every account. That
# alone fixes all three.
#
# WHAT THIS SCRIPT DELIBERATELY DOES NOT DO: chown anything.
#
# The data directories carry ownership that must survive exactly —
# odoo-db-data is drwx------ dnsmasq:root (a container uid that maps to an
# unrelated host name), odoo-web-data is messagebus:messagebus. `mv` preserves
# all of it because /opt and /home are the SAME filesystem, so this is an atomic
# rename, not a copy. A `cp -a` here would rewrite ownership and Postgres would
# refuse to start.
#
# The directory itself is already mode 775, so once its parent is 755 instead of
# 750, nothing else needs changing. Tidying ownership into a deploy group is a
# separate, later change — not a rider on a migration.
#
# ROLLBACK: mv /opt/odoo /home/cdgcphub/odoo-project
# The deploy pipeline resolves either path, so it keeps working both ways.

set -euo pipefail

OLD="${OLD_DIR:-/home/cdgcphub/odoo-project}"
NEW="${NEW_DIR:-/opt/odoo}"

die() { echo "phase4c: FATAL: $*" >&2; exit 1; }
ok()  { echo "phase4c: $*"; }

[[ "$(id -u)" -eq 0 ]] || die "must run as root"

# ── Preconditions, all of them, before touching anything ──────────────────────
[[ -d "$OLD/.git" ]] || die "no checkout at $OLD"
[[ ! -e "$NEW"    ]] || die "$NEW already exists — refusing to overwrite"

running="$(docker ps -q | wc -l | tr -d ' ')"
[[ "$running" == "0" ]] || die "$running containers still running — run 'docker compose down' first, or a live Postgres will have its data directory renamed underneath it"

# Same filesystem means mv is a rename. Across filesystems it becomes a
# copy+delete: slow, and it rewrites ownership on the data directories.
src_fs="$(df --output=source "$OLD" | tail -1)"
dst_fs="$(df --output=source "$(dirname "$NEW")" | tail -1)"
[[ "$src_fs" == "$dst_fs" ]] || die "$OLD ($src_fs) and $(dirname "$NEW") ($dst_fs) are different filesystems; mv would copy and rewrite ownership"

ok "preconditions OK: checkout present, target free, 0 containers, same filesystem ($src_fs)"

# ── Record what must survive, so the move can be proven rather than assumed ───
before_owner="$(stat -c '%U:%G' "$OLD/odoo-db-data")"
before_mode="$(stat -c '%a'    "$OLD/odoo-db-data")"
before_head="$(git -c safe.directory='*' -C "$OLD" rev-parse HEAD)"
before_du="$(du -s "$OLD" | cut -f1)"
ok "before: odoo-db-data ${before_owner} mode ${before_mode}, HEAD ${before_head:0:11}, ${before_du} blocks"

# ── The move ─────────────────────────────────────────────────────────────────
mv "$OLD" "$NEW"
ok "moved $OLD -> $NEW"

# ── Prove nothing changed but the path ───────────────────────────────────────
after_owner="$(stat -c '%U:%G' "$NEW/odoo-db-data")"
after_mode="$(stat -c '%a'    "$NEW/odoo-db-data")"
after_head="$(git -c safe.directory='*' -C "$NEW" rev-parse HEAD)"
after_du="$(du -s "$NEW" | cut -f1)"

[[ "$after_owner" == "$before_owner" ]] || die "odoo-db-data ownership changed: $before_owner -> $after_owner"
[[ "$after_mode"  == "$before_mode"  ]] || die "odoo-db-data mode changed: $before_mode -> $after_mode"
[[ "$after_head"  == "$before_head"  ]] || die "git HEAD changed: $before_head -> $after_head"
[[ "$after_du"    == "$before_du"    ]] || die "size changed: $before_du -> $after_du blocks"

ok "verified: ownership, mode, git HEAD and size all identical"
ok "done. bring the stack up with: cd $NEW && docker compose up -d"
