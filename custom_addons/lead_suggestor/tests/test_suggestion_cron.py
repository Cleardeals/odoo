from odoo.tests import tagged
from unittest.mock import patch, MagicMock
from datetime import date, timedelta
from .test_property_common import PropertyInventoryTestCase

@tagged('post_install', '-at_install')
class TestSuggestionCron(PropertyInventoryTestCase):
    """
    Test cron job operaitons for suggestions with BigQuery mocking.
    """

    @patch('google.cloud.bigquery.Client')
    def test_01_cron_sync_creates_new_suggestions(self, mock_bq_client):
        """Cron should create new suggestions from BigQuery data."""

        prop = self.create_property(property_tag='CRON-PROP-001')

        mock_instance = mock_bq_client.return_value
        mock_query_job = MagicMock()
        mock_instance.query.return_value = mock_query_job

        # Create a mock BigQuery row
        from collections import namedtuple
        BQRow = namedtuple('Row', [
            'active_property_tag', 'suggested_lead_phone', 'lead_name',
            'original_property_tag', 'original_property_similarity',
            'generation_date', 'current_status'
        ])

        mock_rows = [
            BQRow(
                active_property_tag='CRON-PROP-001',
                suggested_lead_phone='9111111111',
                lead_name='Mock Lead',
                original_property_tag='OLD-PROP',
                original_property_similarity=0.85,
                generation_date=date.today(),
                current_status='New'
            )
        ]

        mock_query_job.result.return_value = mock_rows

        # Run cron
        self.env['property.lead.suggestion']._cron_sync_suggestions()

        # Verify suggestion was created
        suggestion = self.env['property.lead.suggestion'].search([
            ('suggested_lead_phone', '=', '9111111111'),
            ('property_base_id', '=', prop.id)
        ])

        self.assertTrue(suggestion, "Cron should create suggestion from BQ data")
        self.assertEqual(suggestion.lead_name, 'Mock Lead')
        self.assertEqual(suggestion.original_property_similarity, 85.0)

    
    @patch('google.cloud.bigquery.Client')
    def test_02_cron_sync_skips_duplicates(self, mock_bq_client):
        """Cron should not create duplicate suggestions. """
        prop = self.create_property(property_tag = "DUP-PROP-001")

        self.create_suggestion(
            property_rec=prop,
            suggested_lead_phone='9222222222'
        )

        mock_instance = mock_bq_client.return_value
        mock_query_job = MagicMock()
        mock_instance.query.return_value = mock_query_job

        from collections import namedtuple
        BQRow = namedtuple('Row', [
            'active_property_tag', 'suggested_lead_phone', 'lead_name',
            'original_property_tag', 'original_property_similarity',
            'generation_date', 'current_status'
        ])

        mock_rows = [
            BQRow(
                active_property_tag='DUP-PROP-001',
                suggested_lead_phone='9222222222',  # Duplicate phone
                lead_name='Duplicate Lead',
                original_property_tag='OLD-DUP-PROP',
                original_property_similarity=0.90,
                generation_date=date.today(),
                current_status='New'
            )
        ]

        mock_query_job.result.return_value = mock_rows

        # Count before CRON
        count_before = self.env['property.lead.suggestion'].search_count([
            ('suggested_lead_phone', '=', '9222222222'),
            ('property_base_id', '=', prop.id)
        ])

        # Run cron
        self.env['property.lead.suggestion']._cron_sync_suggestions()

        # Count after CRON
        count_after = self.env['property.lead.suggestion'].search_count([
            ('suggested_lead_phone', '=', '9222222222'),
            ('property_base_id', '=', prop.id)
        ])

        self.assertEqual(
            count_before, count_after,
            "Cron should not create duplicate suggestions for the same property and phone."
        )

    @patch('google.cloud.bigquery.Client')
    def test_03_cron_sync_skips_unknown_properties(self, mock_bq_client):
        """Cron should skip suggestions for non-existent properties."""

        mock_instance = mock_bq_client.return_value
        mock_query_job = MagicMock()
        mock_instance.query.return_value = mock_query_job

        from collections import namedtuple
        BQRow = namedtuple('Row', [
            'active_property_tag', 'suggested_lead_phone', 'lead_name',
            'original_property_tag', 'original_property_similarity',
            'generation_date', 'current_status'
        ])
        mock_rows = [
            BQRow(
                active_property_tag='NON-EXISTENT-PROP',
                suggested_lead_phone='9333333333',
                lead_name='Non-existent Prop Lead',
                original_property_tag='OLD-NON-EXISTENT',
                original_property_similarity=0.75,
                generation_date=date.today(),
                current_status='New'
            )
        ]

        mock_query_job.result.return_value = mock_rows

        # Run cron
        self.env['property.lead.suggestion']._cron_sync_suggestions()

        # Verify no suggestion was created
        suggestion = self.env['property.lead.suggestion'].search([
            ('suggested_lead_phone', '=', '9333333333')
        ])

        self.assertFalse(suggestion, "Cron should skip suggestions for unknown properties.")

    @patch('google.cloud.bigquery.Client')
    def test_04_cron_sync_handles_multiple_suggestions(self, mock_bq_client):
        """Cron should handle multiple suggestions in one run."""
        prop1 = self.create_property(property_tag='MULTI-PROP-001')
        prop2 = self.create_property(property_tag='MULTI-PROP-002')
        
        # Mock BigQuery with multiple rows
        mock_instance = mock_bq_client.return_value
        mock_query_job = MagicMock()
        mock_instance.query.return_value = mock_query_job
        
        from collections import namedtuple
        BQRow = namedtuple('Row', [
            'active_property_tag', 'suggested_lead_phone', 'lead_name',
            'original_property_tag', 'original_property_similarity',
            'generation_date', 'current_status'
        ])
        
        mock_rows = [
            BQRow('MULTI-PROP-001', '9444444444', 'Lead 1', 'OLD', 0.80, date.today(), 'New'),
            BQRow('MULTI-PROP-001', '9555555555', 'Lead 2', 'OLD', 0.85, date.today(), 'New'),
            BQRow('MULTI-PROP-002', '9666666666', 'Lead 3', 'OLD', 0.90, date.today(), 'New'),
        ]
        mock_query_job.result.return_value = mock_rows
        
        # Run cron
        self.env['property.lead.suggestion']._cron_sync_suggestions()
        
        # Verify all were created
        sugg1 = self.env['property.lead.suggestion'].search([
            ('property_base_id', '=', prop1.id)
        ])
        sugg2 = self.env['property.lead.suggestion'].search([
            ('property_base_id', '=', prop2.id)
        ])
        
        self.assertEqual(len(sugg1), 2)
        self.assertEqual(len(sugg2), 1)

    @patch('google.cloud.bigquery.Client')
    def test_05_cron_sync_handles_bigquery_error(self, mock_bq_client):
        """Cron should handle BigQuery errors gracefully."""
        mock_bq_client.side_effect = Exception("BigQuery connection error")

        try:
            self.env['property.lead.suggestion']._cron_sync_suggestions()
        except Exception as e:
            self.fail(f"Cron raised an exception on BigQuery error: {e}")

    
    @patch('google.cloud.bigquery.Client')
    def test_06_cron_sync_converts_similarity_percentage(self, mock_bq_client):
        """Cron should convert similarity from decimal to percentage."""
        prop = self.create_property(property_tag='PERCENT-PROP')

        mock_instance = mock_bq_client.return_value
        mock_query_job = MagicMock()
        mock_instance.query.return_value = mock_query_job

        from collections import namedtuple
        BQRow = namedtuple('Row', [
            'active_property_tag', 'suggested_lead_phone', 'lead_name',
            'original_property_tag', 'original_property_similarity',
            'generation_date', 'current_status'
        ])

        mock_rows = [
            BQRow(
                active_property_tag='PERCENT-PROP',
                suggested_lead_phone='9777777777',
                lead_name='Test',
                original_property_tag='OLD',
                original_property_similarity=0.856,  # Decimal format
                generation_date=date.today(),
                current_status='New'
            )
        ]

        mock_query_job.result.return_value = mock_rows

        # Run cron
        self.env['property.lead.suggestion']._cron_sync_suggestions()

        # Verify similarity converted to percentage
        suggestion = self.env['property.lead.suggestion'].search([
            ('suggested_lead_phone', '=', '9777777777')
        ])

        self.assertAlmostEqual(suggestion.original_property_similarity, 85.6, places=1)