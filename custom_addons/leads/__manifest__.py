{
    'name': "Lead Scoring",
    'version': '1.0',
    'depends': ['base', 'property_listings'],
    'author': "Nirat Patel",
    'category': 'Sales',
    'description': "Manages ML-based lead scoring for RMs.",
    'data': [
        'security/ir.model.access.csv',
        'views/lead_score_views.xml',
    ],
    'application': True,
}