"""Pin the bus contract that the live WhatsApp UI depends on.

`wa.message` broadcasts on a `bus.bus` channel; three OWL components subscribe
to it and refresh themselves when it fires (the Inbox, the lead form's WhatsApp
tab, and the Message Log). Nothing else connects the two sides — the channel
name and the event name are matched by string, across a Python/JavaScript
boundary that no type checker or import graph spans.

That makes this a silent-failure contract in both directions:

* Rename the channel or event here and every live view stops updating. The
  server stays healthy, rows are written correctly, and the only symptom is
  that the UI quietly goes static — the same class of failure as a missing
  websocket asset bundle, which took a day to find.
* Drop the broadcast from `create` or `write` and new messages, or their
  delivery receipts, never appear until someone reloads the page by hand.

The existing suite only ever patches `_sendone` OUT to keep other tests quiet,
so until now nothing asserted that it is called at all. These tests fail loudly
on a one-sided rename, which is the whole point.

Any change here must be made together with the `busService.subscribe(...)`
calls in `static/src/{inbox,lead_tab,message_log}/`.
"""

from unittest.mock import patch

from odoo.tests import tagged

from .common import WaTransactionCase

#: The exact strings the OWL components subscribe to. Keep in step with
#: `static/src/inbox/wa_inbox.js` and its two sibling components.
CHANNEL = 'wa_message_log'
EVENT = 'wa_message_update'


@tagged('post_install', '-at_install', 'wa_communication')
class TestMessageBusContract(WaTransactionCase):
    """The server half of the live-update contract."""

    def setUp(self):
        super().setUp()
        self.conv = self.make_conversation()

    def _capture_sendone(self):
        """Patch `bus.bus._sendone` and return the list it records into."""
        calls = []

        def _record(self_bus, target, notification_type, message):
            calls.append((target, notification_type, message))

        patcher = patch.object(
            type(self.env['bus.bus']), '_sendone', _record, create=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    def test_create_broadcasts_on_the_subscribed_channel(self):
        """A new message must announce itself, or the inbox never shows it."""
        calls = self._capture_sendone()

        self.make_message(self.conv)

        wa_calls = [c for c in calls if c[0] == CHANNEL]
        self.assertTrue(
            wa_calls,
            "wa.message.create did not broadcast on %r. Every live WhatsApp "
            "view subscribes to that channel; without this notification new "
            "messages only appear on a manual page reload." % CHANNEL,
        )
        self.assertEqual(
            wa_calls[0][1], EVENT,
            "The event name must stay %r — the OWL components match it by "
            "string, so a rename here silently stops every live view." % EVENT,
        )

    def test_status_write_broadcasts(self):
        """Delivery receipts drive the unread badges and the ticks."""
        msg = self.make_message(self.conv)
        calls = self._capture_sendone()

        msg.write({'status': 'delivered'})

        self.assertTrue(
            [c for c in calls if c[0] == CHANNEL and c[1] == EVENT],
            "A status write did not broadcast. Receipts would stop moving in "
            "the UI even though the row is correct in the database.",
        )

    def test_non_status_write_does_not_broadcast(self):
        """Only status changes are worth waking every open client for.

        This is the guard on the fix for the 15 Sep CPU saturation: the channel
        is global, so one broadcast costs a refresh in every open Inbox at once.
        Widening the trigger to all writes would multiply that cost — and the
        client-side debounce reduces the blast radius without removing it.
        """
        msg = self.make_message(self.conv)
        calls = self._capture_sendone()

        msg.write({'sender_name': 'Renamed'})

        self.assertFalse(
            [c for c in calls if c[0] == CHANNEL],
            "A non-status write broadcast to every open client. Only status "
            "changes should — see the class docstring.",
        )

    def test_batch_create_broadcasts_once(self):
        """A batch insert is one event, not one per row.

        `create` is `@api.model_create_multi` and broadcasts on the recordset,
        so importing or backfilling many messages wakes each client once rather
        than once per message. Losing this would turn a backfill into an
        accidental denial of service against the RMs' browsers.
        """
        calls = self._capture_sendone()

        self.env['wa.message'].sudo().create([{
            'conversation_id': self.conv.id,
            'direction': 'inbound',
            'initiator': 'buyer',
            'kind': 'text_reply',
            'status': 'delivered',
            'occurred_at': '2026-01-01 10:00:00',
        } for _ in range(5)])

        self.assertEqual(
            len([c for c in calls if c[0] == CHANNEL]), 1,
            "A 5-record batch create produced %d broadcasts; expected exactly "
            "one." % len([c for c in calls if c[0] == CHANNEL]),
        )

    def test_broadcast_failure_never_breaks_the_write(self):
        """Persisting the message matters more than live-updating it.

        The broadcast is deliberately wrapped in a bare except. This test is
        what makes that defensible rather than merely convenient: it proves the
        message still lands when the bus is unavailable.
        """
        def _boom(*args, **kwargs):
            raise RuntimeError('bus is down')

        with patch.object(type(self.env['bus.bus']), '_sendone', _boom):
            msg = self.make_message(self.conv)

        self.assertTrue(
            msg.exists(),
            "A bus failure rolled back the message. The write path must "
            "survive the notification path.",
        )
