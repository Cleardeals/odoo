"""
Tests for property.base behaviours that had no direct coverage:

  * display_name — includes ``[property_tag]`` so same-project units differ.
  * name_search override — the leads-context flag broadens search across
    property_tag / location / name and bypasses the RM record rule.
  * action_manual_sync — manager button returns the right notification on both
    success and failure (the underlying cron is mocked; we test the wrapper).
"""

from unittest.mock import patch

from odoo.tests import tagged

from .test_property_common import PropertyBaseTestCase


@tagged("post_install", "-at_install")
class TestPropertyBaseMisc(PropertyBaseTestCase):

    # ------------------------------------------------------------------ #
    # display_name                                                         #
    # ------------------------------------------------------------------ #

    def test_display_name_includes_tag(self):
        prop = self.make_property(name="Tower A", property_tag="PREM")
        self.assertEqual(prop.display_name, "Tower A [PREM]")

    def test_display_name_without_tag(self):
        prop = self.make_property(name="Tower B", property_tag=False)
        self.assertEqual(prop.display_name, "Tower B")

    # ------------------------------------------------------------------ #
    # name_search override                                                 #
    # ------------------------------------------------------------------ #

    def test_name_search_for_lead_matches_location(self):
        """With the leads context flag, a property is found by its location."""
        prop = self.make_property(
            name="Quiet House", location=f"Bandra-{self.suffix}"
        )
        results = (
            self.env["property.base"]
            .with_context(search_all_properties_for_lead=True)
            .name_search(name=f"Bandra-{self.suffix}")
        )
        self.assertIn(prop.id, [r[0] for r in results])

    def test_name_search_for_lead_matches_tag(self):
        prop = self.make_property(property_tag=f"TAGX-{self.suffix}")
        results = (
            self.env["property.base"]
            .with_context(search_all_properties_for_lead=True)
            .name_search(name=f"TAGX-{self.suffix}")
        )
        self.assertIn(prop.id, [r[0] for r in results])

    # ------------------------------------------------------------------ #
    # action_manual_sync                                                   #
    # ------------------------------------------------------------------ #

    def test_manual_sync_success_notification(self):
        prop = self.make_property()
        model_cls = type(self.env["property.base"])
        with patch.object(model_cls, "_cron_sync_from_api", return_value=None):
            result = prop.action_manual_sync()
        self.assertEqual(result["tag"], "display_notification")
        self.assertEqual(result["params"]["type"], "success")
        self.assertFalse(result["params"]["sticky"])

    def test_manual_sync_failure_notification(self):
        prop = self.make_property()
        model_cls = type(self.env["property.base"])
        with patch.object(
            model_cls, "_cron_sync_from_api", side_effect=Exception("boom")
        ):
            result = prop.action_manual_sync()
        self.assertEqual(result["params"]["type"], "danger")
        self.assertTrue(result["params"]["sticky"])
