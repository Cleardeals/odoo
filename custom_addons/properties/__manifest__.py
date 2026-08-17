{
    "name": "Properties",
    "version": "19.0.1.7.0",
    "summary": "Central property inventory synced from the Cleardeals website API.",
    "description": """
        Standalone property module that serves as the single source of truth for
        all property data across the Cleardeals Odoo system.

        - Syncs from api.cleardeals.cc every 3 hours (API-sourced fields only).
        - One-time migration from property.inventory (portal IDs, expiry dates).
        - Managers can manually edit BQ-origin and Odoo-managed fields.
        - RMs have read-only access.
        - Expiry cleanup cron marks properties inactive when service expires.
        - Full REST CRUD API under /api/v1/properties.
    """,
    "author": "Cleardeals Tech",
    "category": "Real Estate",
    "license": "LGPL-3",
    "depends": [
        "base",
        "web",
        "mail",
    ],
    "data": [
        # Security — must come first so groups exist before access rules
        "security/property_security.xml",
        "security/ir.model.access.csv",
        # Scheduled actions / cron jobs
        "data/property_cron.xml",
        # Views & menus
        "views/property_base_views.xml",
        "views/property_menus.xml",
    ],
    "controllers": [
        "controllers/controllers.py",
        "controllers/webhooks.py",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
