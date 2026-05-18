"""
cleardeals.pubsub — GCP Pub/Sub publisher service.

AbstractModel (no database table).  Inherit or call via
``self.env['cleardeals.pubsub']`` from any model that needs to publish events.

Environment variables
---------------------
PUBSUB_PROJECT_ID
    Required.  GCP project ID (e.g. ``cleardeals-prod``).

PUBSUB_EMULATOR_HOST
    Optional.  When set (e.g. ``host.docker.internal:8085``) the
    google-cloud-pubsub library routes every RPC to the local emulator
    instead of GCP.  Set automatically by docker-compose.dev.yml.

Usage
-----
From an ORM hook or request handler (fire-and-forget)::

    self.env['cleardeals.pubsub'].publish_async(
        'wa-events',
        {'type': 'lead.status_changed', 'lead_id': self.id},
        attributes={'source': 'leads'},
    )

From a cron method (blocking, max 30 s)::

    msg_id = self.env['cleardeals.pubsub'].publish_sync(
        'wa-events',
        {'type': 'daily_digest'},
    )
"""

import json
import logging
import os
import threading
from typing import Optional

from odoo import models

_logger = logging.getLogger(__name__)

# ── Library presence check ────────────────────────────────────────────────────

try:
    from google.cloud import pubsub_v1  # noqa: F401 — used in _get_publisher_client()
    _PUBSUB_AVAILABLE = True
except ImportError:
    _PUBSUB_AVAILABLE = False
    _logger.warning(
        'cleardeals_pubsub: google-cloud-pubsub is not installed.  '
        'All publish calls will be no-ops.  '
        'Install it with: pip install google-cloud-pubsub'
    )

# ── Process-level singleton ───────────────────────────────────────────────────
# In PreforkServer each WorkerHTTP/WorkerCron is a separate OS process.
# In threaded mode (workers=0) all request-threads share one process.
# The lock guards the double-checked init in the threaded case only.

_publisher_client = None
_publisher_lock = threading.Lock()


def _get_publisher_client():
    """Return (or lazily create) the module-level PublisherClient.

    ``pubsub_v1.PublisherClient()`` is thread-safe and automatically uses the
    local emulator when ``PUBSUB_EMULATOR_HOST`` is set in the environment.
    """
    global _publisher_client
    if not _PUBSUB_AVAILABLE:
        return None
    if _publisher_client is None:
        with _publisher_lock:
            if _publisher_client is None:
                from google.cloud import pubsub_v1
                _publisher_client = pubsub_v1.PublisherClient()
    return _publisher_client


# ── Model ─────────────────────────────────────────────────────────────────────

class CleardealsPublisher(models.AbstractModel):
    _name = 'cleardeals.pubsub'
    _description = 'Cleardeals GCP Pub/Sub Publisher'

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _pubsub_project_id(self) -> str:
        """Return the GCP project ID from the environment.

        Raises:
            EnvironmentError: If ``PUBSUB_PROJECT_ID`` is not set.
        """
        project_id = os.environ.get('PUBSUB_PROJECT_ID', '').strip()
        if not project_id:
            raise EnvironmentError(
                'PUBSUB_PROJECT_ID is not set.  '
                'Add it to docker-compose.yml (or the host environment) '
                'before using cleardeals.pubsub methods.'
            )
        return project_id

    def _topic_path(self, topic_id: str) -> str:
        """Build the fully-qualified Pub/Sub topic path.

        Returns an empty string when the library is unavailable (so callers
        do not need to check ``_PUBSUB_AVAILABLE`` separately).
        """
        client = _get_publisher_client()
        if client is None:
            return ''
        return client.topic_path(self._pubsub_project_id(), topic_id)

    @staticmethod
    def _encode_payload(payload: dict) -> bytes:
        """JSON-encode *payload* to UTF-8 bytes.

        Non-serialisable values are coerced to ``str`` via ``default=str`` so
        that common Odoo types (``datetime``, ``Decimal``, recordsets) do not
        raise ``TypeError``.
        """
        return json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8')

    @staticmethod
    def _make_publish_callback(topic_id: str):
        """Return a done-callback that logs the result of an async publish."""
        def _callback(future):
            try:
                msg_id = future.result(timeout=5)
                _logger.debug(
                    'cleardeals.pubsub: published to %s  msg_id=%s', topic_id, msg_id
                )
            except Exception:
                _logger.exception(
                    'cleardeals.pubsub: async publish to %s failed', topic_id
                )
        return _callback

    # ── Public API ────────────────────────────────────────────────────────────

    def publish_async(
        self,
        topic_id: str,
        payload: dict,
        attributes: Optional[dict] = None,
    ) -> None:
        """Publish a message without blocking for the server acknowledgement.

        **Safe to call from ORM hooks** (``write``, ``create``, computed
        fields) and HTTP request handlers.  The google-cloud-pubsub library
        batches and sends the RPC in its own ``BatchThread``; Odoo's request
        thread is never blocked.  Delivery errors are caught by the future
        callback and logged at ERROR level.

        Args:
            topic_id:   Short topic name (e.g. ``'wa-events'``).  The full
                        ``projects/{project}/topics/{name}`` path is built
                        from ``PUBSUB_PROJECT_ID``.
            payload:    JSON-serialisable dict.  Non-serialisable values are
                        coerced to ``str``.
            attributes: Optional flat ``str → str`` dict of Pub/Sub message
                        attributes (max 100 entries, values ≤ 1 024 bytes).
        """
        if not _PUBSUB_AVAILABLE:
            _logger.debug(
                'cleardeals.pubsub.publish_async: no-op (google-cloud-pubsub not installed)'
            )
            return

        try:
            client = _get_publisher_client()
            topic_path = self._topic_path(topic_id)
            data = self._encode_payload(payload)
            future = client.publish(topic_path, data=data, **(attributes or {}))
            future.add_done_callback(self._make_publish_callback(topic_id))
        except Exception:
            _logger.exception(
                'cleardeals.pubsub.publish_async: failed to enqueue message for topic %s',
                topic_id,
            )

    def publish_sync(
        self,
        topic_id: str,
        payload: dict,
        attributes: Optional[dict] = None,
        timeout: int = 30,
    ) -> str:
        """Publish a message and block until the server acknowledges it.

        **Intended for cron workers only** (``limit_time_real_cron=0`` in
        ``odoo.conf`` removes the wall-time limit for cron jobs).

        This method MUST NOT be called from a GeventServer context because
        blocking the current greenlet stalls the entire event loop and causes
        request timeouts.  A ``RuntimeError`` is raised if ``odoo.evented``
        is ``True`` to catch this at development time.

        For ORM hooks and request handlers use :meth:`publish_async` instead.

        Args:
            topic_id:   Short topic name (e.g. ``'wa-events'``).
            payload:    JSON-serialisable dict.
            attributes: Optional flat ``str → str`` message attributes.
            timeout:    Seconds to wait for the server acknowledgement before
                        raising ``google.api_core.exceptions.TimeoutError``.

        Returns:
            str: The published message ID returned by GCP.
        """
        # Local import to avoid a circular dependency at module load time.
        import odoo  # noqa: PLC0415

        if getattr(odoo, 'evented', False):
            raise RuntimeError(
                'cleardeals.pubsub.publish_sync() was called from the '
                'GeventServer context (odoo.evented is True).  '
                'This blocks the gevent event loop and causes request timeouts.  '
                'Use publish_async() for request handlers and ORM hooks.'
            )

        if not _PUBSUB_AVAILABLE:
            _logger.warning(
                'cleardeals.pubsub.publish_sync: no-op (google-cloud-pubsub not installed)'
            )
            return ''

        client = _get_publisher_client()
        topic_path = self._topic_path(topic_id)
        data = self._encode_payload(payload)
        future = client.publish(topic_path, data=data, **(attributes or {}))
        message_id: str = future.result(timeout=timeout)
        _logger.info(
            'cleardeals.pubsub.publish_sync: published to %s  msg_id=%s',
            topic_id,
            message_id,
        )
        return message_id
