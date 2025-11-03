# -*- coding: utf-8 -*-
{
    'name': 'Lead Suggestor',
    'version': '1.0',
    'summary': 'Provides a dashboard for RMs to find suggested leads for their properties.',
    'description': """
        This module provides a dedicated dashboard for RMs (Relationship Managers)
        to see a list of their assigned properties.
        
        For each property, it displays a list of "Similar Leads" sourced
        from a BigQuery data pipeline. RMs can then contact these leads
        and log their feedback, converting cold properties into new opportunities.
    """,
    'author': 'Nirat Patel',
    'category': 'Operations',
    'depends': [
        'base', 
        'web',
    ],
    'data': [
        # Security
        'security/security.xml', 
        'security/ir.model.access.csv',
        
        # Cron Jobs for BQ Sync
        'data/ir_cron_data.xml',
        
        # Views
        'views/property_inventory_views.xml',
        'views/suggestion_feedback_wizard_views.xml',
        'views/suggestion_feedback_wizard_views.xml',
        'views/menus.xml',
        

    ],
    'assets': {
        'web.assets_backend': [
            'lead_suggestor/static/src/js/whatsapp_action.js'
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}


