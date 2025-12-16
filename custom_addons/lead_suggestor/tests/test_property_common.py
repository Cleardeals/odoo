# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase
from datetime import date, timedelta
import time

class PropertyInventoryTestCase(TransactionCase):
    """
    Base test case with common setup for property inventory tests.
    Provides reusable fixtures and helper methods. 
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()


        # Generate unique identifiers to avoid conflicts

        cls.timestamp = str(int(time.time()))

        # Create test RM user
        cls.rm_user = cls.env['res.users'].create({
            'name': 'Test RM',
            'login': f'test_rm_{cls.timestamp}',
            'email': f'test_rm_{cls.timestamp}@example.com',
        })

        # Assign Internal user group
        group_internal = cls.env.ref('base.group_user')
        group_internal.write({'user_ids': [(4, cls.rm_user.id)]})

        # Create a Second RM for testing assignments
        cls.rm_user2 = cls.env['res.users'].create({
            'name': 'Second RM', 
            'login': f'second_rm_{cls.timestamp}',
            'email': f'rm2_{cls.timestamp}@test.com',
        })

        group_internal.write({'user_ids': [(4, cls.rm_user2.id)]})

    def create_property(self, **kwargs):
        """Helper to create Property Inventory with sensible defaults."""
        timestamp = str(int(time.time() * 1000))

        values = {
            'property_tag': f'TEST-PROP-{timestamp}',
            'rm_user_id': self.rm_user.id,
            'is_active': True,
            'service_expiry_date': date.today() + timedelta(days=30),
            'welcome_call_date': date.today(),
            'bhk': '3 BHK',
            'location': 'Test Location',
            'city': 'Test City',
            'property_link': 'https://test.com/property',
        }
        values.update(kwargs)
        return self.env['property.inventory'].create(values)
    

    def create_suggestion(self, property_rec=None, **kwargs):
        """Helper to create a suggestion with defaults."""
        if property_rec is None:
            property_rec = self.create_property()
        
        timestamp = str(int(time.time() * 1000))
        values = {
            'property_inventory_id': property_rec.id,
            'suggested_lead_phone': f'98765{timestamp[-5:]}',  # Unique phone
            'lead_name': 'Test Lead',
            'original_property_tag': 'OLD-PROP-001',
            'original_property_similarity': 85.0,
            'generation_date': date.today(),
            'contact_type': 'New',
            'status': 'new',
        }
        values.update(kwargs)
        return self.env['property.lead.suggestion'].create(values)