from odoo.tests import tagged
from .test_property_common import PropertyInventoryTestCase

@tagged('post_install', '-at_install')
class TestSuggestionCounts(PropertyInventoryTestCase):
    """Test suggestion count computation on properties"""

    def test_01_initial_counts_zero(self):
        """New property should have zero suggestions."""
        prop = self.create_property()
        self.assertEqual(prop.suggestion_count, 0)
        self.assertEqual(prop.new_suggestion_count, 0)

    def test_02_total_count_increases(self):
        """Total count should increase when suggestions added."""
        prop = self.create_property()

        self.create_suggestion(property_rec=prop, status = 'new')
        prop.invalidate_recordset()
        self.assertEqual(prop.suggestion_count, 1)

        self.create_suggestion(property_rec=prop, status = 'contacted')
        prop.invalidate_recordset()
        self.assertEqual(prop.suggestion_count, 2)

    def test_03_new_count_only_counts_new_status(self):
        """New count should only include suggestions with 'new' status."""
        prop = self.create_property()

        self.create_suggestion(property_rec=prop, status = 'new')
        self.create_suggestion(property_rec=prop, status='new')
        self.create_suggestion(property_rec=prop, status='contacted')
        self.create_suggestion(property_rec=prop, status='converted')

        prop.invalidate_recordset()

        self.assertEqual(prop.suggestion_count, 4)
        self.assertEqual(prop.new_suggestion_count, 2)

    def test_04_counts_update_on_status_change(self):
        """Counts should update when suggestion status changes."""
        prop = self.create_property()

        sugg1 = self.create_suggestion(property_rec=prop, status = 'new')
        sugg2 = self.create_suggestion(property_rec=prop, status = 'new')
        
        prop.invalidate_recordset()
        self.assertEqual(prop.new_suggestion_count, 2)
        self.assertEqual(prop.suggestion_count, 2)

        sugg1.status = 'contacted'

        prop.invalidate_recordset()

        self.assertEqual(prop.new_suggestion_count, 1)
        self.assertEqual(prop.suggestion_count, 2)

    def test_05_multiple_properties_independent_counts(self):
        """Each property should maintain independent suggestions counts."""
        prop1 = self.create_property()
        prop2 = self.create_property()

        self.create_suggestion(property_rec=prop1, status = 'new')
        self.create_suggestion(property_rec=prop1, status = 'contacted')
        self.create_suggestion(property_rec=prop2, status = 'new')
        self.create_suggestion(property_rec=prop2, status = 'new')

        prop1.invalidate_recordset()
        prop2.invalidate_recordset()

        self.assertEqual(prop1.suggestion_count, 2)
        self.assertEqual(prop1.new_suggestion_count, 1)
        self.assertEqual(prop2.suggestion_count, 2)
        self.assertEqual(prop2.new_suggestion_count, 2)

    