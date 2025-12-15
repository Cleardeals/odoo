# -*- coding: utf-8 -*-
{
    'name': "Property Listings",
    'version': '1.0',
    'depends': ['base'],
    'author': "Nirat Patel",
    'category': 'Real Estate',
    'summary': "Manage a portfolio of real estate properties.",
    'description': """
        A module to manage adding and viewing details of the onboarded properties with cleardeals
    """,
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/property_listing_views.xml',
        'views/property_listing_menus.xml',
        'views/property_import_wizard_views.xml',
        'data/scheduled_actions.xml', # The cron job for expiring listings
    ],
    'application': True,
}