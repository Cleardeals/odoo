{
    'name' : 'Property Dashboard',
    'version' : '1.0',
    'author' : 'Nirat Patel',
    'category' : 'Real Estate',
    'depends' : ['web', 'base', 'property_listings'],
    'data' : [
        'security/property_groups.xml',
        # 'security/ir.model.access.csv',
        'views/dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend':[
            'property_dashboard/static/src/property_dashboard/dashboard.js',
            'property_dashboard/static/src/property_dashboard/dashboard.xml',

            'property_dashboard/static/src/leads_dashboard/leads_dashboard.js',
            'property_dashboard/static/src/leads_dashboard/leads_dashboard.xml',
        ],
    },
    'application': True,
    'installable': True,
}