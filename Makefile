# ==============================================================================
# Cleardeals — Odoo 19 Dev Makefile
# ==============================================================================
# All targets operate on the local dev stack (docker-compose.dev.yml).
# Run `make help` to see available commands.
#
# Usage examples:
#   make up
#   make logs
#   make update MODULE=leads
#   make shell
# ==============================================================================

DC      = docker compose -f docker-compose.dev.yml
DB_NAME = cleardeals_19_dev

.PHONY: help up down build restart restart-odoo status \
        logs logs-odoo logs-db \
        shell odoo-shell psql \
        update migrate-db wipe \
        wa-tunnel wa-media-url wa-interakt wa-config

# ── Default target ─────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "Cleardeals Odoo 19 — Dev Stack"
	@echo "════════════════════════════════════════════════════════════════════"
	@echo "  Mac / Linux (make)                  Windows (.\make.ps1)"
	@echo "────────────────────────────────────────────────────────────────────"
	@echo "  make up                             .\make.ps1 up"
	@echo "  make down                           .\make.ps1 down"
	@echo "  make build                          .\make.ps1 build"
	@echo "  make restart                        .\make.ps1 restart"
	@echo "  make restart-odoo                   .\make.ps1 restart-odoo"
	@echo "  make status                         .\make.ps1 status"
	@echo "────────────────────────────────────────────────────────────────────"
	@echo "  make logs                           .\make.ps1 logs"
	@echo "  make logs-odoo                      .\make.ps1 logs-odoo"
	@echo "  make logs-db                        .\make.ps1 logs-db"
	@echo "────────────────────────────────────────────────────────────────────"
	@echo "  make shell                          .\make.ps1 shell"
	@echo "  make odoo-shell                     .\make.ps1 odoo-shell"
	@echo "  make psql                           .\make.ps1 psql"
	@echo "────────────────────────────────────────────────────────────────────"
	@echo "  make update MODULE=leads            .\make.ps1 update leads"
	@echo "  make update MODULE=leads,props      .\make.ps1 update leads,props"
	@echo "  make migrate-db                     .\make.ps1 migrate-db"
	@echo "  make wipe                           .\make.ps1 wipe"
	@echo "────────────────────────────────────────────────────────────────────"
	@echo "  make wa-tunnel                      (public cloudflared tunnel for WA media)"
	@echo "  make wa-media-url URL=https://…     (set/clear WA media base URL)"
	@echo "  make wa-interakt                    (set TEST Interakt key — hidden prompt)"
	@echo "  make wa-config                      (show WA params + Pub/Sub env, key masked)"
	@echo "════════════════════════════════════════════════════════════════════"
	@echo "  Windows one-time setup:"
	@echo "    Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser"
	@echo ""

# ── Stack lifecycle ────────────────────────────────────────────────────────────
up:
	$(DC) up -d

down:
	$(DC) down

build:
	$(DC) up -d --build --force-recreate odoo

restart:
	$(DC) restart

restart-odoo:
	$(DC) restart odoo

status:
	$(DC) ps

# ── Logs ──────────────────────────────────────────────────────────────────────
logs:
	$(DC) logs -f

logs-odoo:
	$(DC) logs -f odoo

logs-db:
	$(DC) logs -f db

# ── Shells ────────────────────────────────────────────────────────────────────
shell:
	$(DC) exec odoo bash

odoo-shell:
	$(DC) exec odoo python3 /usr/bin/odoo shell -d $(DB_NAME)

psql:
	$(DC) exec db psql -U odoo -d $(DB_NAME)

# ── Module update ─────────────────────────────────────────────────────────────
# Usage: make update MODULE=leads
#        make update MODULE=leads,properties
update:
ifndef MODULE
	$(error MODULE is required. Usage: make update MODULE=my_module)
endif
	$(DC) exec odoo python3 /usr/bin/odoo \
		-d $(DB_NAME) -u $(MODULE) --stop-after-init

# ── One-time DB migration ──────────────────────────────────────────────────────
# Copies cleardeals_19_dev from your Mac Postgres (port 5432) into the
# Docker Postgres container. Safe to run only once on a fresh container.
migrate-db:
	@echo "→ Creating database $(DB_NAME) in the Docker container..."
	$(DC) exec db createdb -U odoo $(DB_NAME) || true
	@echo "→ Dumping from Mac Postgres and restoring into Docker..."
	PGPASSWORD=odoo pg_dump -U odoo -h 127.0.0.1 -p 5432 $(DB_NAME) \
		| $(DC) exec -T db psql -U odoo -d $(DB_NAME)
	@echo "✓ Migration complete. Run: make up"

# ── WhatsApp media local testing ───────────────────────────────────────────────
# Interakt fetches image/video/document media over a PUBLIC URL, so localhost is
# unreachable. `make wa-tunnel` opens a tunnel to the local Odoo (port 8069) and
# points the WA media controller at it via the
# `wa_communication.media_public_base_url` system parameter — WITHOUT touching
# the global `web.base.url` (which would break login redirects in dev).
#
# Uses **cloudflared** (not ngrok): ngrok free allows only ONE static domain /
# online tunnel per account, which you already use for the webhook-gateway
# tunnel — sharing it makes media requests land on the wrong service (FastAPI
# 404). cloudflared quick-tunnels are free, need no account, and mint a fresh
# unique https://*.trycloudflare.com URL per run, so they never collide.
#
# Leave the tunnel running while you test sends. Ctrl-C stops it (the param is
# left set; clear it with `make wa-media-url URL=` when done).
wa-tunnel:
	@command -v cloudflared >/dev/null 2>&1 || { \
		echo "✗ cloudflared not found. Install it (does NOT collide with your ngrok"; \
		echo "  webhook tunnel): brew install cloudflared"; exit 1; }
	@echo "→ Starting cloudflared quick tunnel to http://localhost:8069 …"
	@pkill -f "cloudflared tunnel --url http://localhost:8069" 2>/dev/null || true
	@cloudflared tunnel --url http://localhost:8069 > /tmp/wa-cloudflared.log 2>&1 &
	@for i in $$(seq 1 20); do \
		URL=$$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/wa-cloudflared.log 2>/dev/null | head -1); \
		[ -n "$$URL" ] && break; sleep 1; \
	done; \
	if [ -z "$$URL" ]; then echo "✗ Could not read cloudflared URL (see /tmp/wa-cloudflared.log)"; exit 1; fi; \
	echo "→ Public URL: $$URL"; \
	$(MAKE) --no-print-directory wa-media-url URL=$$URL; \
	echo ""; \
	echo "✓ Tunnel live. Keep this terminal open while testing media sends."; \
	echo "  Press Ctrl-C to stop the tunnel."; \
	trap 'pkill -f "cloudflared tunnel --url http://localhost:8069" 2>/dev/null || true; echo; echo "✓ Tunnel stopped."' INT TERM; \
	tail -f /tmp/wa-cloudflared.log

# Set (or clear) the media public base URL system parameter.
# Usage: make wa-media-url URL=https://abcd-12-34.ngrok-free.app
#        make wa-media-url URL=            (clears it → falls back to web.base.url)
wa-media-url:
	@printf "%s\n" \
		"env['ir.config_parameter'].sudo().set_param('wa_communication.media_public_base_url', '$(URL)')" \
		"env.cr.commit()" \
		"print('✓ wa_communication.media_public_base_url =', repr(env['ir.config_parameter'].sudo().get_param('wa_communication.media_public_base_url')))" \
		| $(DC) exec -T odoo python3 /usr/bin/odoo shell -d $(DB_NAME) --no-http 2>/dev/null

# ── Interakt credentials (dev DB only) ────────────────────────────────────────
# Odoo holds its own copy of the Interakt key, separate from the platform's
# Kubernetes secret: interakt_client.py reads
# `wa_communication.interakt_api_key` from ir.config_parameter to drive the live
# Send-Template picker. Both copies must point at the SAME account or the picker
# lists templates the sender cannot actually send.
#
# The key is read from a PROMPT with echo off, never as `make wa-interakt KEY=…`.
# A make variable lands in ~/.zsh_history, in `ps` output for the duration of the
# command, and in any terminal-sharing session. It is piped straight into the
# odoo shell's stdin and never appears in a file or an argv.
#
# Use the TEST account key here. This target refuses to run against anything but
# the dev compose stack, so it cannot touch production by mistake.
wa-interakt:
	@echo "→ Setting Interakt credentials in $(DB_NAME) (dev stack only)."
	@echo "  Use the TEST account key. Input is hidden."
	@printf "  Interakt API key: "; \
	stty -echo 2>/dev/null; read APIKEY; stty echo 2>/dev/null; echo ""; \
	if [ -z "$$APIKEY" ]; then echo "✗ Empty key — nothing changed."; exit 1; fi; \
	BASE="$${BASE:-https://api.interakt.ai}"; \
	printf "%s\n" \
	  "icp = env['ir.config_parameter'].sudo()" \
	  "icp.set_param('wa_communication.interakt_api_key', '''$$APIKEY''')" \
	  "icp.set_param('wa_communication.interakt_base_url', '$$BASE')" \
	  "env.cr.commit()" \
	  "k = icp.get_param('wa_communication.interakt_api_key') or ''" \
	  "print('OK  interakt_base_url =', icp.get_param('wa_communication.interakt_base_url'))" \
	  "print('OK  interakt_api_key  =', (k[:4] + '…' + k[-4:]) if len(k) > 8 else '(set)')" \
	  | $(DC) exec -T odoo python3 /usr/bin/odoo shell -d $(DB_NAME) --no-http 2>/dev/null

# The topic parameters are printed because leaving them out made this target
# useless at the one job it has. It reported the container env only — GCP_ENV,
# PUBSUB_PROJECT_ID, PUBSUB_EMULATOR_HOST — and passed green while all six
# `wa_communication.topic_*` rows in the dev database still read `cd-prod-*`.
# Those parameters are a SECOND, independent route to production: the topic name
# comes from ir.config_parameter, not from GCP_ENV, and the module ships
# `cd-prod-*` as its defaults, so every fresh install starts pointed at them.
# Locally you are saved only by accident — the emulator holds `cd-local-*` only,
# so the publish dies with "404 Topic not found". Unset PUBSUB_EMULATOR_HOST and
# the same publish reaches real customers.
wa-config: ## Show the WA system parameters (API key masked) and the Pub/Sub topics
	@printf "%s\n" \
	  "icp = env['ir.config_parameter'].sudo()" \
	  "k = icp.get_param('wa_communication.interakt_api_key') or ''" \
	  "print('interakt_api_key       =', (k[:4] + '…' + k[-4:]) if len(k) > 8 else ('(unset)' if not k else '(set)'))" \
	  "print('interakt_base_url      =', icp.get_param('wa_communication.interakt_base_url') or '(unset)')" \
	  "print('media_public_base_url  =', icp.get_param('wa_communication.media_public_base_url') or '(unset)')" \
	  "names = ['actor_events','customer_events','nudge_events','odoo_wa_requests','property_events','visit_events']" \
	  "vals = dict((n, icp.get_param('wa_communication.topic_' + n) or '(unset)') for n in names)" \
	  "print('')" \
	  "print('-- Pub/Sub topics, from ir.config_parameter --')" \
	  "[print('  topic_%-17s = %s' % (n, vals[n])) for n in names]" \
	  "print('  topic_%-17s = %s  (alias; env-derived at publish time)' % ('workflow_control', icp.get_param('wa_communication.topic_workflow_control') or '(unset)'))" \
	  "bad = sorted(n for n in names if 'cd-prod' in vals[n])" \
	  "print('')" \
	  "print(('DANGER: topic parameter(s) pointing at PRODUCTION: ' + ', '.join(bad)) if bad else 'OK: no topic parameter points at cd-prod-*')" \
	  "bad and print('        A publish from this stack can reach real customers. Set them to cd-local-* first.')" \
	  | $(DC) exec -T odoo python3 /usr/bin/odoo shell -d $(DB_NAME) --no-http 2>/dev/null
	@echo "── container env (must be the emulator for safe testing) ──"
	@$(DC) exec -T odoo sh -c 'echo "  GCP_ENV=$$GCP_ENV"; echo "  PUBSUB_PROJECT_ID=$$PUBSUB_PROJECT_ID"; echo "  PUBSUB_EMULATOR_HOST=$$PUBSUB_EMULATOR_HOST"'

# ── Wipe ──────────────────────────────────────────────────────────────────────
wipe:
	@echo "⚠  This will destroy ./odoo-dev-db-data and ./odoo-dev-web-data"
	@read -p "    Type 'yes' to confirm: " confirm && [ "$$confirm" = "yes" ]
	$(DC) down
	rm -rf odoo-dev-db-data odoo-dev-web-data
	@echo "✓ Dev data wiped."
