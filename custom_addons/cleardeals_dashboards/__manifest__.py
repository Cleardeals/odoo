{
    'name': "Cleardeals Dashboards", 
    'version': '1.0',
    'summary': 'Central hub for Cleardeals dashboards and KPIs', 
    'category': 'Productivity/Dashboard', 
    'author': 'Nirat Patel',
    'depends': [
        'base', 'leads'
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/lead_assignment_views.xml',
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