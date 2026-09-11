"""Push-handler behaviour when a Postgres concurrency error interrupts it.

``_process_odoo_wa_event`` used to catch ``SerializationFailure`` and return,
on the assumption that it meant "a duplicate delivery of this same event
already did the work". That assumption is wrong: a serialisation failure means
*this* transaction lost a write race, and the competing write is normally
ordinary traffic on the same ``wa_conversation`` row (``unread_count``,
``last_message_at``) rather than a second copy of the event.

Swallowing it also defeated the retry Odoo already provides —
``service.model.retrying()`` rolls back and re-runs the whole request up to 5
times for exactly these errors. Catching it meant the event was dropped
silently: no error log, no retry, nothing applied.

Live consequence: an ``assignment_confirmed`` lost this way left conversation
918238268187 with ``assignment_pending`` still set and reassignment request #36
stuck in ``confirming`` (2026-08-05), even though Interakt had accepted the
handover.
"""

import psycopg2
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'wa_communication')
class TestEventConcurrencyErrors(TransactionCase):
    """Concurrency errors must reach Odoo's retry; real bugs must still be logged."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Conv = cls.env['wa.conversation']
        cls.conv = cls.Conv.create({'phone_number': '919800009001'})

    def _event(self):
        return {
            'event_type': 'assignment_confirmed',
            'phone': self.conv.phone_number,
            'rm_odoo_id': self.env.uid,
            'request_id': 'test-correlation-id',
            'success': True,
        }

    def _errors_logged(self):
        return self.env['wa.event.log'].sudo().search_count(
            [('event_type', '=', 'odoo_wa_assignment_confirmed_error')])

    # ── Concurrency errors propagate ─────────────────────────────────────────

    def test_serialization_failure_is_reraised(self):
        """The exact failure that stranded request #36."""
        with patch.object(
            type(self.Conv), '_handle_odoo_assignment_confirmed',
            side_effect=psycopg2.errors.SerializationFailure(
                'could not serialize access due to concurrent update'),
        ):
            with self.assertRaises(psycopg2.errors.SerializationFailure):
                self.Conv._process_odoo_wa_event(self._event(), 'msg-1')

    def test_deadlock_is_reraised(self):
        with patch.object(
            type(self.Conv), '_handle_odoo_assignment_confirmed',
            side_effect=psycopg2.errors.DeadlockDetected('deadlock detected'),
        ):
            with self.assertRaises(psycopg2.errors.DeadlockDetected):
                self.Conv._process_odoo_wa_event(self._event(), 'msg-2')

    def test_lock_not_available_is_reraised(self):
        with patch.object(
            type(self.Conv), '_handle_odoo_assignment_confirmed',
            side_effect=psycopg2.errors.LockNotAvailable('lock not available'),
        ):
            with self.assertRaises(psycopg2.errors.LockNotAvailable):
                self.Conv._process_odoo_wa_event(self._event(), 'msg-3')

    def test_concurrency_error_is_not_logged_as_a_handler_failure(self):
        """Re-raising must bypass the generic handler, not fall through to it.

        Otherwise the event would be recorded as a permanent failure *and* the
        exception swallowed — the worst of both.
        """
        before = self._errors_logged()
        with patch.object(
            type(self.Conv), '_handle_odoo_assignment_confirmed',
            side_effect=psycopg2.errors.SerializationFailure('boom'),
        ):
            with self.assertRaises(psycopg2.errors.SerializationFailure):
                self.Conv._process_odoo_wa_event(self._event(), 'msg-4')
        self.assertEqual(self._errors_logged(), before,
                         "a retryable error is not a handler failure")

    # ── Genuine handler bugs are still contained ─────────────────────────────

    def test_ordinary_exception_is_still_swallowed_and_logged(self):
        """Non-retryable errors must NOT start propagating.

        Guards the other direction: a bug in one handler must not reject the
        Pub/Sub push and cause endless redelivery of a poison message.
        """
        before = self._errors_logged()
        with patch.object(
            type(self.Conv), '_handle_odoo_assignment_confirmed',
            side_effect=ValueError('handler bug'),
        ):
            # Must not raise.
            self.Conv._process_odoo_wa_event(self._event(), 'msg-5')
        self.assertEqual(self._errors_logged(), before + 1,
                         "the failure is recorded for diagnosis")

    def test_successful_event_still_processes(self):
        """The happy path is untouched."""
        self.Conv._process_odoo_wa_event(self._event(), 'msg-6')
        self.conv.invalidate_recordset()
        self.assertFalse(self.conv.assignment_pending)
        self.assertEqual(self.conv.assigned_user_id.id, self.env.uid)
