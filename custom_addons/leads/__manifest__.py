{
    'name': "Lead Scoring",
    'version': '1.0',
    'depends': ['base', 'web'],  # Added 'web' for UI components like kanban and list views
    'author': "Nirat Patel",
    'category': 'Sales',
    'description': "Manages ML-based lead scoring for RMs.",
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_config_parameter_data.xml',
        'views/lead_score_menu.xml',  # Added menu file
        'views/lead_score_views.xml',
        'views/lead_score_bq_wizard_views.xml',
        'views/whatsapp_response_views.xml',
        'views/whatsapp_response_inherit_views.xml',
    ],
}