"""Owning an inquiry on a number is enough to read its chat.

The scoping rule has always been "see the chats for your inquiries; you can only
*reply* once the chat is assigned to you".  But the two ownership paths it
checked were both *stored links from the chat back to a lead* — the anchor
``lead_id``, and the per-message inquiry tag.  A brand-new inquiry has neither:
no message is tagged with it, and the chat stays anchored to whichever inquiry
came first on that number.

So an RM opening a lead they had just created saw an empty WhatsApp tab on a
number with months of history, with nothing to explain it.  That got worse once
a lead could not leave "Lead" without an outbound message: the tab looked empty,
sending was refused, and the status was locked, with no visible cause.

What this grants is read-only.  Replying is still gated by ``_can_send`` on
assignment, so the RM sees the thread with the "This chat is assigned to X —
request assignment to reply" banner, exactly as they do for a chat that already
carries one of their inquiries.
"""

from odoo.tests import tagged

from .common import WaTransactionCase


@tagged('post_install', '-at_install', 'wa_communication')
class TestThreadOwnLeadVisibility(WaTransactionCase):

    def _chat_owned_by_someone_else(self, phone):
        """A chat on *phone*, assigned to another RM, anchored to their lead."""
        other = self.make_user()
        theirs = self.make_lead(phone=phone, user_id=other.id)
        conv = self.make_conversation(
            phone_number='91%s' % phone,
            assigned_user_id=other.id, lead_id=theirs.id)
        self.make_message(conv, direction='inbound', lead_id=theirs.id)
        self.make_message(conv, direction='outbound', initiator='rm',
                          kind='template', status='sent', lead_id=theirs.id)
        return conv, other

    # ── The fix ──────────────────────────────────────────────────────────────

    def test_new_inquiry_on_the_number_can_read_the_chat(self):
        """The reported bug: a fresh inquiry, nothing in the chat points to it."""
        rm = self.make_user()
        phone = self._uniq_phone()[2:]
        conv, _other = self._chat_owned_by_someone_else(phone)
        self.make_lead(phone=phone, user_id=rm.id)   # created after the chat

        thread = self.Conv.with_user(rm).get_thread(conv.id)

        self.assertNotIn('error', thread)
        self.assertEqual(len(thread['messages']), 2)

    def test_reading_does_not_grant_replying(self):
        """Read-only: the banner and Request assignment are the way in."""
        rm = self.make_user()
        phone = self._uniq_phone()[2:]
        conv, _other = self._chat_owned_by_someone_else(phone)
        self.make_lead(phone=phone, user_id=rm.id)

        self.assertFalse(conv.with_user(rm)._can_send())

    def test_twelve_digit_chat_phone_matches_a_ten_digit_lead(self):
        """Chats store 91XXXXXXXXXX; leads store the 10 digits."""
        rm = self.make_user()
        phone = self._uniq_phone()[2:]
        conv, _other = self._chat_owned_by_someone_else(phone)
        lead = self.make_lead(phone=phone, user_id=rm.id)

        self.assertEqual(conv.phone_number, '91%s' % lead.phone)
        self.assertNotIn('error', self.Conv.with_user(rm).get_thread(conv.id))

    # ── The boundary still holds ─────────────────────────────────────────────

    def test_rm_with_no_inquiry_on_the_number_is_still_refused(self):
        """This widens ownership, not visibility in general."""
        rm = self.make_user()
        conv, _other = self._chat_owned_by_someone_else(self._uniq_phone()[2:])

        self.assertIn('error', self.Conv.with_user(rm).get_thread(conv.id))

    def test_an_inquiry_on_a_different_number_grants_nothing(self):
        rm = self.make_user()
        conv, _other = self._chat_owned_by_someone_else(self._uniq_phone()[2:])
        self.make_lead(phone=self._uniq_phone()[2:], user_id=rm.id)

        self.assertIn('error', self.Conv.with_user(rm).get_thread(conv.id))

    def test_someone_elses_inquiry_on_the_number_grants_nothing(self):
        """Ownership is the test, not the phone number."""
        rm = self.make_user()
        third = self.make_user()
        phone = self._uniq_phone()[2:]
        conv, _other = self._chat_owned_by_someone_else(phone)
        self.make_lead(phone=phone, user_id=third.id)

        self.assertIn('error', self.Conv.with_user(rm).get_thread(conv.id))
