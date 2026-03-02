from odoo.tests import tagged

from .test_property_common import PropertyInventoryTestCase


@tagged("post_install", "-at_install")
class TestPropertySuggestionIntegration(PropertyInventoryTestCase):
    """Test integration between  properties and suggestions"""

    def test_01_property_cascade_delete_suggestions(self):
        """Deleting property should delete cascade delete suggestions."""
        prop = self.create_property()
        sugg1 = self.create_suggestion(property_rec=prop)
        sugg2 = self.create_suggestion(property_rec=prop)

        sugg_ids = [sugg1.id, sugg2.id]

        prop.unlink()

        remaining = self.env["property.lead.suggestion"].search(
            [
                ("id", "in", sugg_ids),
            ],
        )

        self.assertEqual(
            len(remaining),
            0,
            "Suggestions should be deleted when property is deleted",
        )

    def test_02_suggestion_one2many_relationship(self):
        """Property should have accesss to suggestions via one2many."""
        prop = self.create_property()
        sugg1 = self.create_suggestion(property_rec=prop)
        sugg2 = self.create_suggestion(property_rec=prop)

        prop.invalidate_recordset(["suggestion_ids"])

        self.assertEqual(len(prop.suggestion_ids), 2)
        self.assertIn(sugg1, prop.suggestion_ids)
        self.assertIn(sugg2, prop.suggestion_ids)

    def test_03_multiple_properties_suggestion_isolation(self):
        """Each property's suggestions should be isolated."""
        prop1 = self.create_property()
        prop2 = self.create_property()

        sugg1 = self.create_suggestion(property_rec=prop1)
        sugg2 = self.create_suggestion(property_rec=prop1)
        sugg3 = self.create_suggestion(property_rec=prop2)

        prop1.invalidate_recordset(["suggestion_ids"])
        prop2.invalidate_recordset(["suggestion_ids"])

        self.assertEqual(len(prop1.suggestion_ids), 2)
        self.assertEqual(len(prop2.suggestion_ids), 1)
        self.assertNotIn(sugg3, prop1.suggestion_ids)
        self.assertNotIn(sugg1, prop2.suggestion_ids)
