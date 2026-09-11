"""Shared fixtures, factory helpers, and Pub/Sub mocking for wa_communication.

Every wa_communication test should build on one of the bases here so the suite
stays consistent and a breaking change in one model surfaces the same way
everywhere:

* :class:`WaTransactionCase` — model / business-logic tests (fast, no HTTP).
* :class:`WaHttpCase`        — controller / end-to-end push tests.

Both provide:

* Deterministic, collision-free record creation via :meth:`_uniq`.
* Factory helpers (:meth:`make_user`, :meth:`make_conversation`,
  :meth:`make_lead`, :meth:`make_message`) that fill required fields with sane
  defaults so individual tests only specify what they actually care about.
* :meth:`mock_pubsub` — a context manager that swaps ``cleardeals.pubsub``'s
  ``publish_async`` for a capture list **and** flushes deferred post-commit
  callbacks, so a test can assert on exactly what would have been published to
  GCP without ever touching the network.

Why this matters
----------------
``send_message`` (and several handlers) defer the real Pub/Sub publish to
``cr.postcommit`` so a rolled-back transaction never emits a spurious WA send.
In a ``TransactionCase`` the transaction is never committed, so those callbacks
would otherwise never run. :meth:`mock_pubsub` runs them on exit, which is the
only way to observe the published payload in a test.

See ``.claude/skills/writing-odoo-tests`` for the full conventions.
"""

import contextlib
import time

from odoo.tests import HttpCase, TransactionCase, new_test_user

# Dotted path to the model class whose ``publish_async`` we patch.  All
# outbound publishing in this module routes through ``cleardeals.pubsub``.
PUBSUB_MODEL = 'cleardeals.pubsub'

# Group XML ids used across the suite.
GROUP_USER = 'base.group_user'
GROUP_WA_MANAGER = 'wa_communication.group_wa_manager'


class _WaFactoryMixin:
    """Factory helpers shared by the transaction- and HTTP-based bases."""

    # A per-class monotonic counter guarantees unique logins / phone numbers
    # even when many records are created inside a single test method.
    _seq = 0

    @classmethod
    def _uniq(cls, prefix: str = '') -> str:
        """Return a process-unique token, e.g. ``'phone_1717490000_3'``."""
        cls._seq += 1
        return '%s%d_%d' % (prefix, int(time.time()), cls._seq)

    @classmethod
    def _uniq_phone(cls) -> str:
        """Return a unique 12-digit E.164-without-plus WA phone number."""
        cls._seq += 1
        # 91 + 10 digits; pad the counter so it stays 10 digits wide.
        return '91%010d' % (9000000000 + cls._seq)

    # ── Users ────────────────────────────────────────────────────────────────

    @classmethod
    def make_user(cls, manager: bool = False, **kw):
        """Create a test user; pass ``manager=True`` for a WA manager."""
        groups = GROUP_USER
        if manager:
            groups = '%s,%s' % (GROUP_USER, GROUP_WA_MANAGER)
        login = kw.pop('login', cls._uniq('wa_user_'))
        # An email is mandatory for assignment flows (Interakt agent id).
        kw.setdefault('email', '%s@example.com' % login)
        return new_test_user(cls.env, login=login, groups=groups, **kw)

    # ── Leads ────────────────────────────────────────────────────────────────

    def make_lead(self, **vals):
        """Create a minimal ``leads.new`` record.

        Lead create hooks publish Pub/Sub events, but those are deferred to
        ``cr.postcommit`` and never fire inside a TransactionCase unless
        explicitly flushed — so this is safe to call without a pubsub mock.
        """
        source = self.env['leads.new']._get_or_create_source(
            vals.pop('source', 'TestSource'))
        base = {
            'name': vals.pop('name', self._uniq('Lead ')),
            'source_id': source.id,
        }
        base.update(vals)
        return self.env['leads.new'].with_context(
            automated_lead_creation=True).create(base)

    # ── Conversations ────────────────────────────────────────────────────────

    def make_conversation(self, **vals):
        """Create a ``wa.conversation``.

        Defaults ``assigned_user_id`` to the *current* user so RM ``send_message``
        passes the ownership gate out of the box.  Pass ``assigned_user_id=False``
        for an unassigned conversation, or another user's id to test gating.
        """
        base = {
            'phone_number': vals.pop('phone_number', self._uniq_phone()),
        }
        if 'assigned_user_id' not in vals:
            base['assigned_user_id'] = self.env.uid
        base.update(vals)
        return self.env['wa.conversation'].create(base)

    def make_message(self, conv, **vals):
        """Create a ``wa.message`` on ``conv`` with sensible defaults.

        Defaults to an inbound buyer text so callers testing serialisation /
        stats only override the fields under test.
        """
        base = {
            'conversation_id': conv.id,
            'direction': vals.pop('direction', 'inbound'),
            'initiator': vals.pop('initiator', 'buyer'),
            'kind': vals.pop('kind', 'text_reply'),
            'status': vals.pop('status', 'delivered'),
            'occurred_at': vals.pop('occurred_at', '2026-01-01 10:00:00'),
        }
        base.update(vals)
        return self.env['wa.message'].sudo().create(base)

    # ── Pub/Sub capture ──────────────────────────────────────────────────────

    @contextlib.contextmanager
    def mock_pubsub(self):
        """Capture ``publish_async`` calls and flush deferred post-commit work.

        Usage::

            with self.mock_pubsub() as published:
                conv.send_message(body='hi')
            self.assertEqual(published[-1].topic_payload['request_type'], 'send')

        ``published`` is a list of :class:`_Published` records, each exposing
        ``.topic`` and ``.payload``.  On exit the manager runs
        ``cr.postcommit`` so deferred publishes are observed.
        """
        captured = []

        def _fake_publish(model_self, topic, payload):
            captured.append(_Published(topic, payload))

        from unittest.mock import patch
        pubsub_cls = type(self.env[PUBSUB_MODEL])
        with patch.object(pubsub_cls, 'publish_async', _fake_publish):
            yield captured
            # Flush deferred publishes scheduled via cr.postcommit.add(...).
            self.env.cr.postcommit.run()


class _Published:
    """A single captured ``publish_async`` call (topic + payload)."""

    __slots__ = ('topic', 'payload')

    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload

    def __repr__(self):  # pragma: no cover - debugging aid
        return '<Published topic=%r payload=%r>' % (self.topic, self.payload)


class WaTransactionCase(_WaFactoryMixin, TransactionCase):
    """Base for model / business-logic tests in wa_communication."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Conv = cls.env['wa.conversation']
        cls.Msg = cls.env['wa.message']


class WaHttpCase(_WaFactoryMixin, HttpCase):
    """Base for controller / HTTP push tests in wa_communication."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Conv = cls.env['wa.conversation']
        cls.Msg = cls.env['wa.message']
