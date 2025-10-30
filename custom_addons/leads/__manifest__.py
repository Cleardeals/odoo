{
    'name': "Lead Scoring",
    'version': '1.0',
    'depends': ['base', 'web', 'mail'], # 'crm' is NOT needed
    'author': "Nirat Patel",
    'category': 'Sales',
    'description': "Manages ML-based lead scoring and CSV lead imports for RMs.",
    'data': [
        # Security (Load First)
        'security/security.xml',
        'security/ir.model.access.csv',

        # Data
        'data/ir_config_parameter_data.xml',
        'data/lead_score_cron.xml',

        # Wizard Views (Load before models that use them)
        'views/lead_score_bq_wizard_views.xml',
        'views/lead_csv_import_wizard_views.xml', # <-- Correct path

        # Model Views (Load before menus)
        'views/lead_score_views.xml',
        'views/whatsapp_response_views.xml',
        'views/whatsapp_response_inherit_views.xml',
        'views/imported_lead_views.xml', 

        # Menu items (Load Last)
        'views/lead_score_menu.xml', # <-- Must be last
    ],
}

