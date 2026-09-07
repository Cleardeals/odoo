"""Tests for the cleardeals.pubsub publisher model."""

from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase


class TestCleardealsPublisher(TransactionCase):
    """Unit tests for ``cleardeals.pubsub`` publish methods.

    All google-cloud-pubsub calls are patched out so these tests run without
    the library installed and without a live GCP / emulator connection.
    """

    def setUp(self):
        super().setUp()
        self.publisher = self.env['cleardeals.pubsub']

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _mock_client(self, message_id='test-msg-id-001'):
        """Return a pre-configured mock PublisherClient."""
        client = MagicMock()
        future = MagicMock()
        future.result.return_value = message_id
        client.publish.return_value = future
        client.topic_path.side_effect = (
            lambda project, topic: f'projects/{project}/topics/{topic}'
        )
        return client, future

    # ── publish_async ─────────────────────────────────────────────────────────

    @patch.dict('os.environ', {'PUBSUB_PROJECT_ID': 'test-project'})
    @patch('odoo.addons.cleardeals_pubsub.models.pubsub_publisher._get_publisher_client')
    @patch('odoo.addons.cleardeals_pubsub.models.pubsub_publisher._PUBSUB_AVAILABLE', True)
    def test_publish_async_enqueues_message(self, mock_get_client):
        """publish_async() calls client.publish() and registers a callback."""
        client, future = self._mock_client()
        mock_get_client.return_value = client

        self.publisher.publish_async('wa-events', {'type': 'test'})

        client.publish.assert_called_once()
        call_kwargs = client.publish.call_args
        self.assertIn(b'"type": "test"', call_kwargs.kwargs.get('data', b''))
        future.add_done_callback.assert_called_once()

    @patch.dict('os.environ', {'PUBSUB_PROJECT_ID': 'test-project'})
    @patch('odoo.addons.cleardeals_pubsub.models.pubsub_publisher._get_publisher_client')
    @patch('odoo.addons.cleardeals_pubsub.models.pubsub_publisher._PUBSUB_AVAILABLE', True)
    def test_publish_async_passes_attributes(self, mock_get_client):
        """publish_async() forwards attributes as keyword arguments."""
        client, future = self._mock_client()
        mock_get_client.return_value = client

        self.publisher.publish_async(
            'wa-events',
            {'type': 'test'},
            attributes={'source': 'leads', 'version': '1'},
        )

        _, kwargs = client.publish.call_args
        self.assertEqual(kwargs.get('source'), 'leads')
        self.assertEqual(kwargs.get('version'), '1')

    @patch('odoo.addons.cleardeals_pubsub.models.pubsub_publisher._PUBSUB_AVAILABLE', False)
    def test_publish_async_noop_when_library_missing(self):
        """publish_async() silently returns when library is not installed."""
        # Should not raise — returns None
        result = self.publisher.publish_async('wa-events', {'type': 'test'})
        self.assertIsNone(result)

    @patch.dict('os.environ', {'PUBSUB_PROJECT_ID': 'test-project'})
    @patch('odoo.addons.cleardeals_pubsub.models.pubsub_publisher._get_publisher_client')
    @patch('odoo.addons.cleardeals_pubsub.models.pubsub_publisher._PUBSUB_AVAILABLE', True)
    def test_publish_async_logs_on_enqueue_failure(self, mock_get_client):
        """publish_async() catches exceptions from client.publish() and logs them."""
        client = MagicMock()
        client.topic_path.return_value = 'projects/test-project/topics/wa-events'
        client.publish.side_effect = RuntimeError('connection refused')
        mock_get_client.return_value = client

        # Must not propagate the exception to the caller
        self.publisher.publish_async('wa-events', {'type': 'test'})

    # ── publish_sync ──────────────────────────────────────────────────────────

    @patch.dict('os.environ', {'PUBSUB_PROJECT_ID': 'test-project'})
    @patch('odoo.addons.cleardeals_pubsub.models.pubsub_publisher._get_publisher_client')
    @patch('odoo.addons.cleardeals_pubsub.models.pubsub_publisher._PUBSUB_AVAILABLE', True)
    def test_publish_sync_returns_message_id(self, mock_get_client):
        """publish_sync() returns the message ID from the server."""
        client, future = self._mock_client(message_id='sync-msg-42')
        mock_get_client.return_value = client

        msg_id = self.publisher.publish_sync('wa-events', {'type': 'test'}, timeout=5)

        self.assertEqual(msg_id, 'sync-msg-42')
        future.result.assert_called_once_with(timeout=5)

    @patch('odoo.addons.cleardeals_pubsub.models.pubsub_publisher._PUBSUB_AVAILABLE', True)
    def test_publish_sync_raises_in_evented_context(self):
        """publish_sync() raises RuntimeError when odoo.evented is True."""
        import odoo
        original_evented = getattr(odoo, 'evented', False)
        try:
            odoo.evented = True
            with self.assertRaises(RuntimeError):
                self.publisher.publish_sync('wa-events', {'type': 'test'})
        finally:
            odoo.evented = original_evented

    @patch('odoo.addons.cleardeals_pubsub.models.pubsub_publisher._PUBSUB_AVAILABLE', False)
    def test_publish_sync_noop_when_library_missing(self):
        """publish_sync() returns empty string when library is not installed."""
        result = self.publisher.publish_sync('wa-events', {'type': 'test'})
        self.assertEqual(result, '')

    # ── _encode_payload ───────────────────────────────────────────────────────

    def test_encode_payload_coerces_non_serialisable_values(self):
        """_encode_payload() coerces datetime/Decimal/etc. to str via default=str."""
        from datetime import datetime
        payload = {'ts': datetime(2024, 1, 1, 12, 0, 0)}
        data = self.publisher._encode_payload(payload)
        self.assertIn(b'2024-01-01', data)

    def test_encode_payload_returns_utf8_bytes(self):
        """_encode_payload() returns bytes with non-ASCII characters."""
        payload = {'name': 'محمد'}
        data = self.publisher._encode_payload(payload)
        self.assertIsInstance(data, bytes)
        self.assertIn('محمد'.encode('utf-8'), data)
