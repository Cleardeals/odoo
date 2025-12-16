# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
import time

class PortalLeadTestCase(TransactionCase):
    """
    Base Fixture for Portal Leads.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        
        # Unique suffix for this test run
        cls.suffix = str(int(time.time()))

        cls.rm_user = cls.env['res.users'].create({
            'name': f'Test RM {cls.suffix}',
            'login': f'test_rm_{cls.suffix}',
            'email': f'rm_{cls.suffix}@test.com',
        })

        cls.naresh_user = cls.env['res.users'].create({
            'name': 'Naresh Rojiya',
            'login': f'naresh_{cls.suffix}',
            'email': f'naresh_{cls.suffix}@test.com'
        })

        # Create Property with UNIQUE IDs
        cls.mb_id = f'MB_{cls.suffix}'
        cls.hsg_id = f'HSG_{cls.suffix}'
        cls.acres_id = f'99_{cls.suffix}'
        cls.olx_id = f'OLX_{cls.suffix}'

        cls.test_property = cls.env['property.inventory'].create({
            'property_tag': f'TEST-PROP-{cls.suffix}',
            'bhk': '3 BHK',
            'location': 'Test Location',
            'city': 'Test City',
            'rm_user_id': cls.rm_user.id,
            'is_active': True,
            'property_link': f'https://test.com/property/TEST-PROP-{cls.suffix}',
            
            'magicbricks_id': cls.mb_id,
            'housing_id': cls.hsg_id,
            'ninety_nine_acres_id': cls.acres_id,
            'olx_id': cls.olx_id
        })

    def create_portal_lead(self, **kwargs):
        """Helper with dynamic defaults."""
        values = {
            'name': 'Test Lead',
            'phone': '9876543210',
            'email': 'test@example.com',
            'portal_name': 'MagicBricks',
            'portal_property_id': self.mb_id, # Dynamic default
            'state': 'new'
        }
        values.update(kwargs)
        return self.env['leads.new'].create(values)