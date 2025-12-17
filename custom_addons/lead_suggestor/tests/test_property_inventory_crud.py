# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.exceptions import ValidationError
from odoo.tools import mute_logger
from .test_property_common import PropertyInventoryTestCase
from datetime import date, timedelta
import psycopg2

@tagged('post_install', '-at_install')
class TestPropertyInventoryCRUD(PropertyInventoryTestCase):
    """
    Tests Basic CRUD operations for the property.inventory model.
    """

    def test_01_create_property_with_required_fields(self):
        """Should create property with minimum required fields."""
        prop = self.create_property()

        self.assertTrue(prop.id)
        self.assertTrue(prop.property_tag)
        self.assertTrue(prop.is_active)

    def test_02_property_tag_required(self):
        """Property tag field should be required (DB Constraint)."""
        # We expect an IntegrityError because the field is NOT NULL in the database
        with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.IntegrityError):
            self.env['property.inventory'].create({
                'is_active': True,
                'rm_user_id': self.rm_user.id
                # Missing 'property_tag'
            })

    def test_03_property_tag_unique_constraint(self):
        """Property tag should be unique across all properties."""
        tag = f"UNIQUE-TAG-{self.timestamp}"
        
        # 1. Create first property
        self.create_property(property_tag=tag)

        # 2. Try to create duplicate (Should fail)
        with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.IntegrityError):
            self.create_property(property_tag=tag)

    def test_04_default_is_active(self):
        """New Properties should default to active."""
        prop = self.create_property()
        self.assertTrue(prop.is_active)

    def test_05_rm_user_assignment(self):
        """Should correctly assign RM user to property."""
        prop = self.create_property(rm_user_id=self.rm_user.id)
        self.assertEqual(prop.rm_user_id, self.rm_user)

    def test_06_optional_fields_storage(self):
        """Should correctly store optional property details."""
        prop = self.create_property(
            owner_name='John Doe',
            owner_phone='9876543210',
            bhk='2 BHK',
            location='Sample Location',
            city='Ahmedabad',
            property_link='https://example.com/property/123',
        )

        self.assertEqual(prop.owner_name, 'John Doe')
        self.assertEqual(prop.owner_phone, '9876543210')
        self.assertEqual(prop.bhk, '2 BHK')
        self.assertEqual(prop.location, 'Sample Location')
        self.assertEqual(prop.city, 'Ahmedabad')
        self.assertEqual(prop.property_link, 'https://example.com/property/123')

    def test_07_portal_ids_storage(self):
        """Should correctly store all portal IDs."""
        prop = self.create_property(
            magicbricks_id='MB12345',
            housing_id='HSG67890',
            ninety_nine_acres_id='99ACR11223',
            olx_id='OLX44556',
        )

        self.assertEqual(prop.magicbricks_id, 'MB12345')
        self.assertEqual(prop.housing_id, 'HSG67890')
        self.assertEqual(prop.ninety_nine_acres_id, '99ACR11223')
        self.assertEqual(prop.olx_id, 'OLX44556')

    def test_08_property_ordering(self):
        """Properties should be ordered by service_expiry_date ascending."""
        # 1. Create properties with different expiry dates
        prop1 = self.create_property(
            service_expiry_date=date.today() + timedelta(days=30)
        )
        prop2 = self.create_property(
            service_expiry_date=date.today() + timedelta(days=10)
        )
        prop3 = self.create_property(
            service_expiry_date=date.today() + timedelta(days=20)
        )
        
        # 2. Search (which triggers the _order)
        # We restrict the search to just these 3 to avoid interference from other tests
        props = self.env['property.inventory'].search([
            ('id', 'in', [prop1.id, prop2.id, prop3.id])
        ])
        
        # 3. Assert Order: prop2 (10 days) -> prop3 (20 days) -> prop1 (30 days)
        self.assertEqual(props[0], prop2)
        self.assertEqual(props[1], prop3)
        self.assertEqual(props[2], prop1)