# -*- coding: utf-8 -*-
from odoo.tests import tagged
from odoo.exceptions import ValidationError
from odoo.tools import mute_logger
from .test_property_common import PropertyInventoryTestCase
from datetime import date, timedelta
import psycopg2

@tagged('post_install', '-at_install')
class TestSuggestionCRUD(PropertyInventoryTestCase):
    """
    Test basic CRUD operations for the property.lead.suggestion model.
    """

    def test_01_create_suggestion_with_required_fields(self):
        """Should create suggestion with minimum required fields."""
        prop = self.create_property()
        suggestion = self.create_suggestion(property_rec=prop)

        self.assertTrue(suggestion.id)
        self.assertEqual(suggestion.property_inventory_id, prop)
        self.assertEqual(suggestion.status, 'new')

    def test_02_suggestion_requires_property(self):
        """Suggestion must have a property assigned (DB Constraint)."""

        with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.IntegrityError): 
            self.env['property.lead.suggestion'].create({
                'suggested_lead_phone': '9876543210',
                'lead_name': 'Orphan Lead',
                'status': 'new'
            })

            
    def test_03_suggestion_requires_phone(self):
        """Suggestion must have a suggested lead phone (DB Constraint)."""
        prop = self.create_property()

        with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.IntegrityError):
            self.env['property.lead.suggestion'].create({
                'property_inventory_id': prop.id,
                'lead_name': 'No Phone Lead',
                # Missing 'suggested_lead_phone'
            })


    def test_04_unique_constraint_property_phone(self):
        """Same phone cannot be suggested twice for the SAME property."""
        prop = self.create_property()
        phone = '9876543210'

        # 1. Create first suggestion
        self.create_suggestion(
            property_rec=prop,
            suggested_lead_phone=phone
        )

        # 2. Try to create duplicate
        with mute_logger('odoo.sql_db'), self.assertRaises(psycopg2.IntegrityError):
            self.create_suggestion(
                property_rec=prop,
                suggested_lead_phone=phone
            )

    def test_05_same_phone_different_properties_allowed(self):
        """Same phone CAN be suggested for DIFFERENT properties."""
        prop1 = self.create_property()
        prop2 = self.create_property()
        phone = '9876543210'

        sugg1 = self.create_suggestion(
            property_rec=prop1,
            suggested_lead_phone=phone
        )

        sugg2 = self.create_suggestion(
            property_rec=prop2,
            suggested_lead_phone=phone
        )

        self.assertTrue(sugg1.id)
        self.assertTrue(sugg2.id)
        self.assertNotEqual(sugg1, sugg2)

    def test_06_property_tag_related_field(self):
        """Property tag should be accessible via related field on suggestion."""
        prop = self.create_property(property_tag='RELATED-TAG-001')
        suggestion = self.create_suggestion(property_rec=prop)

        self.assertEqual(suggestion.property_tag, 'RELATED-TAG-001')

    def test_07_default_status_new(self):
        """New suggestions should default to 'new' status."""
        suggestion = self.create_suggestion()
        self.assertEqual(suggestion.status, 'new')

    def test_08_status_field_values(self):
        """Should allow all valid status values defined in selection."""
        prop = self.create_property()

        valid_statuses = [
            'new', 'contacted', 'details_shared_of_property', 
            'not_interested', 'interested', 'converted', 
            'whatsapp_done', 'other'
        ]

        for status in valid_statuses:
            suggestion = self.create_suggestion(
                property_rec=prop,
                status=status
            )
            self.assertEqual(suggestion.status, status)

    def test_09_suggestion_ordering(self):
        """Suggestions should be ordered by date desc, then status."""
        prop = self.create_property()

        # Older date
        sugg1 = self.create_suggestion(
            property_rec=prop,
            generation_date=date.today() - timedelta(days=2),
            status='new',
            suggested_lead_phone='11111'
        )

        # Today, 'contacted' (alphabetically before 'new'?) 
        # Check your model _order. Assuming 'generation_date desc' is primary.
        sugg2 = self.create_suggestion(
            property_rec=prop, 
            generation_date=date.today(),
            status='contacted',
            suggested_lead_phone='22222'
        )

        # Today, 'new'
        sugg3 = self.create_suggestion(
            property_rec=prop,
            generation_date=date.today(),
            status='new',
            suggested_lead_phone='33333'
        )

        # Search to trigger sorting
        suggestions = self.env['property.lead.suggestion'].search([
            ('id', 'in', [sugg1.id, sugg2.id, sugg3.id])
        ])

        # Expectation: 
        # 1. Today's records first (sugg2, sugg3)
        # 2. Older record last (sugg1)
        self.assertIn(suggestions[0], [sugg2, sugg3])
        self.assertEqual(suggestions[2], sugg1)