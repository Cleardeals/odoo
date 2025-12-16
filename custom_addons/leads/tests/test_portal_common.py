# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase

class PortalLeadTestCase(TransactionCase):
    """
    Base Fixture for Portal Leads.
    Sets up RMs, a fully populated Test Property, and Helper methods.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # 1. Create RMs
        cls.rm_user = cls.env['res.users'].create({
            'name': 'Test RM',
            'login': 'test_rm_portal',
            'email': 'rm@test.com'
        })

        cls.naresh_user = cls.env['res.users'].create({
            'name': 'Naresh Rojiya',
            'login': 'naresh_rojiya',
            'email': 'naresh@test.com'
        })

        # 2. Create Property

        cls.test_property = cls.env['property.inventory'].create({
            'property_tag': 'TEST-PROP-001',
            'bhk': '3 BHK',
            'location': 'Test Location',
            'city': 'Test City',
            'rm_user_id': cls.rm_user.id,
            'is_active': True,  
            'property_link': 'https://test.com/property/TEST-PROP-001',
            
            # Portal IDs matching the helper
            'magicbricks_id': 'MB123456',
            'housing_id': '18495761',
            'ninety_nine_acres_id': 'A85673352',
            'olx_id': '1822292696'
        })

    def create_portal_lead(self, **kwargs):
        """Helper to create a lead with safe defaults."""
        values = {
            'name': 'Test Lead',
            'phone': '9876543210',
            'email': 'test@example.com',
            'portal_name': 'MagicBricks',
            'portal_property_id': 'MB123456',
            'state': 'new'
        }
        values.update(kwargs)
        return self.env['leads.new'].create(values)

    def create_lead_for_source(self, source, **kwargs):
        """Helper to create leads for specific sources."""
        source_map = {
            'MagicBricks': 'MB123456',
            'Housing.com': '18495761',
            '99acres': 'A85673352',
            'OLX': '1822292696'
        }
        portal_id = source_map.get(source)
        if not portal_id:
            raise ValueError(f"Unknown source: {source}")
        
        return self.create_portal_lead(
            portal_name=source, 
            portal_property_id=portal_id, 
            **kwargs
        )