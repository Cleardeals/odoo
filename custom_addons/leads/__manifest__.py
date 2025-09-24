{
    'name': "Lead Scoring",
    'version': '1.0',
    'depends': ['base', 'web'],  # Added 'web' for UI components like kanban and list views
    'author': "Nirat Patel",
    'category': 'Sales',
    'description': "Manages ML-based lead scoring for RMs.",
    # In /mnt/extra-addons/custom/leads/__manifest__.py
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_config_parameter_data.xml',

        # Defines the wizard's action first, as other views depend on it.
        'views/lead_score_bq_wizard_views.xml',

        # Defines the main lead score views and actions, which use the wizard action.
        'views/lead_score_views.xml',

        # Loads all menu items last, as they depend on all the actions defined above.
        'views/lead_score_menu.xml',

        # Defines the views for the separate WhatsApp model.
        'views/whatsapp_response_views.xml',

        # Inherits from lead_score_views to add WhatsApp features.
        'views/whatsapp_response_inherit_views.xml',
    ],
}