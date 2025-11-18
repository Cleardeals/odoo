{
    'name': "Cleardeals Dashboards", 
    'version': '1.0',
    'summary': 'Central hub for Cleardeals dashboards and KPIs', 
    'category': 'Productivity/Dashboard', 
    'author': 'Nirat Patel',
    'depends': [
        'base', 'leads', 'lead_suggestor'
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',

        'views/lead_assignment_views.xml',
        'views/property_daily_stat_views.xml',
        'views/lead_suggestion_dashboard_views.xml',
        'views/renewal_dashboard_views.xml',
        'views/renewal_template_stats_views.xml',
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
}
