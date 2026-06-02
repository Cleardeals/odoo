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
        wa-tunnel wa-media-url

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

# ── Wipe ──────────────────────────────────────────────────────────────────────
wipe:
	@echo "⚠  This will destroy ./odoo-dev-db-data and ./odoo-dev-web-data"
	@read -p "    Type 'yes' to confirm: " confirm && [ "$$confirm" = "yes" ]
	$(DC) down
	rm -rf odoo-dev-db-data odoo-dev-web-data
	@echo "✓ Dev data wiped."
