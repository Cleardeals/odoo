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
        update migrate-db wipe

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

# ── Wipe ──────────────────────────────────────────────────────────────────────
wipe:
	@echo "⚠  This will destroy ./odoo-dev-db-data and ./odoo-dev-web-data"
	@read -p "    Type 'yes' to confirm: " confirm && [ "$$confirm" = "yes" ]
	$(DC) down
	rm -rf odoo-dev-db-data odoo-dev-web-data
	@echo "✓ Dev data wiped."
