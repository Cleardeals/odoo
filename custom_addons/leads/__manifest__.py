{
    "name": "Lead Scoring",
    "version": "1.6.0",
    "depends": ["base", "web", "mail", "lead_suggestor", "properties"],
    "author": "Nirat Patel",
    "category": "Sales",
    "description": "Manages ML-based lead scoring and CSV lead imports for RMs.",
    "data": [
        # 1. Security (Always First)
        "security/security.xml",
        "security/ir.model.access.csv",
        # 2. Data
        "data/ir_config_parameter_data.xml",
        "data/lead_source_data.xml",
        "data/lead_source_default_rm_sync.xml",
        "data/lead_site_visit_status_data.xml",
        "data/lead_score_cron.xml",
        "data/new_portal_lead_cron.xml",
        "data/pull_leads_cron.xml",
        "data/webhook_cron.xml",
        "data/olx_account_cron.xml",
        "data/olx_accounts_data.xml",
        # 3. Wizard Views
        "views/lead_score_bq_wizard_views.xml",
        "views/lead_csv_import_wizard_views.xml",
        "views/lead_migration_wizard_views.xml",
        "views/lead_recompute_wizard_views.xml",
        "views/lead_bulk_reassign_wizard_views.xml",
        # 4. Model Views (Defines Actions) -- [MOVED UP]
        "views/lead_score_views.xml",
        "views/leads_bde_views.xml",
        # 5. Menus (Uses Actions defined above) -- [MOVED DOWN]
        "views/lead_score_menu.xml",
        # 6. Other Views (May depend on Menus)
        "views/whatsapp_response_views.xml",
        "views/whatsapp_response_inherit_views.xml",
        "views/lead_source_views.xml",
        "views/lead_site_visit_wizard_views.xml",
        "views/lead_site_visit_views.xml",
        "views/new_portal_lead_views.xml",
        # Reassignment Log (menu depends on lead_score_menu.xml)
        "views/lead_reassignment_log_views.xml",
        # OLX Account management
        "views/lead_olx_account_views.xml",
        # Property form extension (tab added by this module)
        "views/property_base_inherit_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "lead_suggestor/static/src/js/whatsapp_action.js",
            "leads/static/src/js/leads_list_controller.js",
            "leads/static/src/js/site_visit_calendar.js",
            "leads/static/src/xml/site_visit_calendar.xml",
            # Property Activity Widget
            "leads/static/src/css/property_activity_widget.css",
            "leads/static/src/js/property_activity_widget.js",
            "leads/static/src/xml/property_activity_widget.xml",
        ],
    },
    "license": "LGPL-3",
}
