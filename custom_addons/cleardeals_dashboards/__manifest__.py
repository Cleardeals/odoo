{
    'name': "Cleardeals Dashboards",
    'version': '19.0.1.0',
    'summary': 'Central hub for Cleardeals dashboards and KPIs',
    'category': 'Productivity/Dashboard',
    'author': 'Nirat Patel',
    'depends': [
        'base', 
        'leads', 
        'lead_suggestor',
        'mail'
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',

        # Views must be loaded BEFORE Menus in Odoo 19
        'views/lead_assignment_views.xml',
        'views/active_template_stats_views.xml',
        'views/property_daily_stat_views.xml',
        'views/lead_suggestion_dashboard_views.xml',
        'views/renewal_dashboard_views.xml',
        'views/renewal_template_stats_views.xml',
        'views/lead_scoring_views.xml',
        'views/lead_scoring_stats_views.xml',
        'views/new_lead_dashboard_views.xml',
        'views/new_lead_template_stats_views.xml',
        
        # Menus loaded last
        'views/menus.xml',
    ],
    'external_dependencies': {
        'python': [
            'google-cloud-bigquery',
            'google-auth',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3', # Recommended to specify license in Odoo 19
}