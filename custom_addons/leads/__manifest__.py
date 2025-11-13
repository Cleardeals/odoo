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
        'data/new_portal_lead_cron.xml',
        'data/pull_leads_cron.xml',

        # Wizard Views
        'views/lead_score_bq_wizard_views.xml',
        'views/lead_csv_import_wizard_views.xml', 

        # Model Views
        'views/lead_score_views.xml',
        # NO, not here: 'views/whatsapp_response_views.xml',
        'views/whatsapp_response_inherit_views.xml',
        

        # Menu items (Load parent menu first)
        'views/lead_score_menu.xml', # <-- MOVED UP. This defines the parent menu.
        'views/new_portal_lead_views.xml',

        # NOW load the child menu
        'views/whatsapp_response_views.xml', # <-- NOW this will work.
    ],

    'assets': {
        'web.assets_backend': [
            'lead_suggestor/static/src/js/whatsapp_action.js',
            'leads/static/src/js/leads_list_controller.js',
        ],
    },
}

