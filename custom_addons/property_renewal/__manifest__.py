# -*- coding: utf-8 -*-
{
    'name': "Property Renewal",
    'summary': """
        Track automated outreach and responses for property renewals.
    """,
    'description': """
        Provides a dedicated interface for Relationship Managers to monitor
        WhatsApp conversations with owners of expired properties.
    """,
    'author': "Nirat Patel",
    'category': 'Real Estate',
    'version': '1.0.0',
    # Any module necessary for this one to work correctly
    'depends': ['base', 'property_listings'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/renewal_message_views.xml',
        'views/renewal_message_menus.xml',
    ],
    'application': True,

    # DEPRECATED — never install. Kept in the tree so the image-contents gate
    # in cloudbuild.yaml still matches, and so history is not rewritten, but
    # `installable: False` keeps it out of the Apps list and out of the derived
    # module list the CD test gate installs.
    'installable': False,
}
