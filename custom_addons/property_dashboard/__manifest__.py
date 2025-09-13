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
            'property_dashboard/static/src/dashboard.js',
            'property_dashboard/static/src/dashboard.xml',
        ],
    },
    'application': True,
    'installable': True,
}