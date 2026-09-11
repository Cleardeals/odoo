# ==============================================================================
# Cleardeals — Odoo 19 Dev Script (Windows PowerShell)
# ==============================================================================
# Mirrors the Makefile for Windows users.
#
# First-time setup — allow local scripts to run (once per machine):
#   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
#
# Usage:
#   .\make.ps1 help
#   .\make.ps1 up
#   .\make.ps1 logs
#   .\make.ps1 update leads
#   .\make.ps1 update leads,properties
# ==============================================================================

param(
    [string]$Command = "help",
    [string]$Module  = ""
)

$DC      = @("compose", "-f", "docker-compose.dev.yml")
$DB_NAME = "cleardeals_19_dev"

function dc { docker @DC @args }

switch ($Command) {

    # ── Help ──────────────────────────────────────────────────────────────────
    "help" {
        Write-Host ""
        Write-Host "Cleardeals Odoo 19 — Dev Stack" -ForegroundColor Cyan
        Write-Host "════════════════════════════════════════════════════════════════════"
        Write-Host "  Windows (.\make.ps1)                Mac / Linux (make)"
        Write-Host "────────────────────────────────────────────────────────────────────"
        Write-Host "  .\make.ps1 up                       make up"
        Write-Host "  .\make.ps1 down                     make down"
        Write-Host "  .\make.ps1 build                    make build"
        Write-Host "  .\make.ps1 restart                  make restart"
        Write-Host "  .\make.ps1 restart-odoo             make restart-odoo"
        Write-Host "  .\make.ps1 status                   make status"
        Write-Host "────────────────────────────────────────────────────────────────────"
        Write-Host "  .\make.ps1 logs                     make logs"
        Write-Host "  .\make.ps1 logs-odoo                make logs-odoo"
        Write-Host "  .\make.ps1 logs-db                  make logs-db"
        Write-Host "────────────────────────────────────────────────────────────────────"
        Write-Host "  .\make.ps1 shell                    make shell"
        Write-Host "  .\make.ps1 odoo-shell               make odoo-shell"
        Write-Host "  .\make.ps1 psql                     make psql"
        Write-Host "────────────────────────────────────────────────────────────────────"
        Write-Host "  .\make.ps1 update leads             make update MODULE=leads"
        Write-Host "  .\make.ps1 update leads,props       make update MODULE=leads,props"
        Write-Host "  .\make.ps1 migrate-db               make migrate-db"
        Write-Host "  .\make.ps1 wipe                     make wipe"
        Write-Host "════════════════════════════════════════════════════════════════════"
        Write-Host "  Mac/Linux one-time setup: install GNU make (brew install make)"
        Write-Host ""
    }

    # ── Stack lifecycle ───────────────────────────────────────────────────────
    "up"            { dc up -d }
    "down"          { dc down }
    "build"         { dc up -d --build --force-recreate odoo }
    "restart"       { dc restart }
    "restart-odoo"  { dc restart odoo }
    "status"        { dc ps }

    # ── Logs ──────────────────────────────────────────────────────────────────
    "logs"          { dc logs -f }
    "logs-odoo"     { dc logs -f odoo }
    "logs-db"       { dc logs -f db }

    # ── Shells ────────────────────────────────────────────────────────────────
    "shell"         { dc exec odoo bash }
    "odoo-shell"    { dc exec odoo python3 /usr/bin/odoo shell -d $DB_NAME }
    "psql"          { dc exec db psql -U odoo -d $DB_NAME }

    # ── Module update ─────────────────────────────────────────────────────────
    "update" {
        # Accept module as: .\make.ps1 update leads
        #                   .\make.ps1 update leads,properties
        if (-not $Module) {
            Write-Host "ERROR: MODULE is required. Usage: .\make.ps1 update <module>" -ForegroundColor Red
            exit 1
        }
        dc exec odoo python3 /usr/bin/odoo -d $DB_NAME -u $Module --stop-after-init
    }

    # ── One-time DB migration ─────────────────────────────────────────────────
    "migrate-db" {
        Write-Host "→ Creating database $DB_NAME in the Docker container..."
        dc exec db createdb -U odoo $DB_NAME 2>$null
        Write-Host "→ Dumping from local Postgres (127.0.0.1:5432) and restoring into Docker..."
        $env:PGPASSWORD = "odoo"
        pg_dump -U odoo -h 127.0.0.1 -p 5432 $DB_NAME | dc exec -T db psql -U odoo -d $DB_NAME
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        Write-Host "✓ Migration complete. Run: .\make.ps1 up" -ForegroundColor Green
    }

    # ── Wipe ──────────────────────────────────────────────────────────────────
    "wipe" {
        Write-Host "⚠  This will destroy .\odoo-dev-db-data and .\odoo-dev-web-data" -ForegroundColor Yellow
        $confirm = Read-Host "    Type 'yes' to confirm"
        if ($confirm -ne "yes") {
            Write-Host "Aborted." -ForegroundColor Red
            exit 1
        }
        dc down
        Remove-Item -Recurse -Force odoo-dev-db-data  -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force odoo-dev-web-data -ErrorAction SilentlyContinue
        Write-Host "✓ Dev data wiped." -ForegroundColor Green
    }

    default {
        Write-Host "Unknown command: $Command. Run .\make.ps1 help" -ForegroundColor Red
        exit 1
    }
}
