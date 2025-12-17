from odoo.tests import tagged
from datetime import date, timedelta
from unittest.mock import patch, MagicMock
from odoo import fields
from .test_property_common import PropertyInventoryTestCase

@tagged('post_install', '-at_install')
class TestPropertyInventoryCron(PropertyInventoryTestCase):
    """Test cron job operations for property inventory"""

    def test_01_cleanup_marks_expired_properties_inactive(self):
        """Cron should mark expired properties as inactive."""
        # Create poperty_tag that expires yesterday

        expired_prop = self.create_property(
            service_expiry_date = date.today() - timedelta(days=1),
            is_active = True
        )

        self.env['property.inventory']._cron_cleanup_expired_properties()

        expired_prop.invalidate_recordset()
        self.assertFalse(
            expired_prop.is_active,
            "Expired property should be marked inactive by cron."
        )

    def test_02_cleanup_keeps_active_properties_active(self):
        """Cron should not affect properties with future expiry"""
        active_prop = self.create_property(
            service_expiry_date = date.today() + timedelta(days=30),
            is_active = True
        )

        self.env['property.inventory']._cron_cleanup_expired_properties()

        active_prop.invalidate_recordset()
        self.assertTrue(
            active_prop.is_active,
            "Active property with future expiry should remain active."
        )  

    def test_03_cleanup_handles_multiple_expired(self):
        """Cron should handle multiple expired properties."""
        expired1 = self.create_property(
            service_expiry_date = date.today() - timedelta(days=5),
            is_active = True
        )

        expired2 = self.create_property(
            service_expiry_date = date.today() - timedelta(days=10),
            is_active = True
        )

        expired3 = self.create_property(
            service_expiry_date = date.today() - timedelta(days=1),
            is_active = True
        )

        self.env['property.inventory']._cron_cleanup_expired_properties()

        for prop in [expired1, expired2, expired3]:
            prop.invalidate_recordset()
            self.assertFalse(
                prop.is_active,
                f"Expired property {prop.property_tag} should be marked inactive by cron."
            )

    def test_04_cleanup_skips_already_inactive(self):
        """Cron should not affect already inactive properties."""
        inactive_prop = self.create_property(
            service_expiry_date = date.today() - timedelta(days=10),
            is_active = False
        )

        self.env['property.inventory']._cron_cleanup_expired_properties()

        inactive_prop.invalidate_recordset()
        self.assertFalse(
            inactive_prop.is_active,
            "Already inactive property should remain inactive after cron."
        )


    def test_05_cleanup_boundary_today(self):
        """Properties expiring today should remain active."""
        today_prop = self.create_property(
            service_expiry_date = date.today(),
            is_active = True
        )

        self.env['property.inventory']._cron_cleanup_expired_properties()

        today_prop.invalidate_recordset()
        self.assertTrue(
            today_prop.is_active,
            "Property expiring today should remain active after cron."
        )

    @patch('google.cloud.bigquery.Client')
    def test_06_sync_properties_handles_bigquery_error(self, mock_bq_client):
        """Sync cron should handle BigQuery connection errors gracefully."""
        mock_bq_client.side_effect = Exception("BigQuery connection failed")

        try:
            self.env['property.inventory']._cron_sync_properties()
        except Exception as e:
            self.fail(f"Cron should handles BQ errors gracefully: {e}")

