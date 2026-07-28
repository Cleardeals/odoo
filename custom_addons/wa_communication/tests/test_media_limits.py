"""WhatsApp media size/type caps.

Regression cover for the 2026-07-28 staging incident: RMs sent 37-86 MB videos.
Interakt accepted each send, then WhatsApp rejected the oversized media
asynchronously via a failure webhook carrying NO reason — so the RM only saw
"Failed" with no explanation. The same uploads spiked Odoo worker memory past
``limit_memory_soft`` (each upload is buffered and base64-encoded in RAM),
recycling workers mid-request, which is how an in-flight Pub/Sub assign publish
was silently lost.
"""

from odoo.tests import TransactionCase, tagged

from ..models.wa_conversation_outbound import (
    WA_MEDIA_MAX_BYTES,
    wa_check_media,
    wa_format_bytes,
    wa_media_kind_for_mimetype,
    wa_media_size_cap,
)

MB = 1024 * 1024


@tagged('post_install', '-at_install', 'wa_communication')
class TestMediaLimits(TransactionCase):

    # ── The real files from the incident ──────────────────────────────────────

    def test_oversized_videos_from_incident_are_rejected(self):
        """The three videos that actually failed in staging."""
        for name, size_mb in [
            ('WhatsApp Video 2026-04-14', 76.74),
            ('VID_20260406_165511_00_006', 37.17),
            ('WhatsApp Video 2026-03-17', 85.79),
        ]:
            err = wa_check_media('video', int(size_mb * MB), 'video/mp4')
            self.assertTrue(err, "%s (%s MB) must be rejected" % (name, size_mb))
            self.assertIn('16.0 MB', err, "the error states the WhatsApp cap")

    def test_video_that_succeeded_is_still_allowed(self):
        """The 10.14 MB video delivered fine — it must not be blocked."""
        self.assertEqual(wa_check_media('video', int(10.14 * MB), 'video/mp4'), '')

    def test_mp4_sent_as_document_is_rejected(self):
        """Interakt: 'mp4 is not supported for Document media' (message 417)."""
        err = wa_check_media('document', 8 * MB, 'video/mp4')
        self.assertTrue(err)
        self.assertIn('Video', err, "the error names the button to use instead")

    # ── Boundaries ────────────────────────────────────────────────────────────

    def test_exactly_at_cap_is_allowed(self):
        for kind, cap in WA_MEDIA_MAX_BYTES.items():
            mime = 'application/pdf' if kind == 'document' else '%s/x' % kind
            self.assertEqual(
                wa_check_media(kind, cap, mime), '',
                "%s of exactly %s must pass" % (kind, wa_format_bytes(cap)))

    def test_one_byte_over_cap_is_rejected(self):
        for kind, cap in WA_MEDIA_MAX_BYTES.items():
            mime = 'application/pdf' if kind == 'document' else '%s/x' % kind
            self.assertTrue(
                wa_check_media(kind, cap + 1, mime),
                "%s of cap+1 must be rejected" % kind)

    def test_each_kind_has_its_own_cap(self):
        self.assertEqual(wa_media_size_cap('image'), 5 * MB)
        self.assertEqual(wa_media_size_cap('video'), 16 * MB)
        self.assertEqual(wa_media_size_cap('audio'), 16 * MB)
        self.assertEqual(wa_media_size_cap('document'), 100 * MB)

    def test_unknown_kind_falls_back_to_document_cap(self):
        self.assertEqual(wa_media_size_cap('sticker'), 100 * MB)
        self.assertEqual(wa_media_size_cap(''), 100 * MB)

    # ── Mime → kind mapping (drives the cap and the document guard) ───────────

    def test_mimetype_maps_to_kind(self):
        self.assertEqual(wa_media_kind_for_mimetype('image/png'), 'image')
        self.assertEqual(wa_media_kind_for_mimetype('video/mp4'), 'video')
        self.assertEqual(wa_media_kind_for_mimetype('audio/ogg'), 'audio')
        self.assertEqual(wa_media_kind_for_mimetype('application/pdf'), 'document')
        self.assertEqual(wa_media_kind_for_mimetype(''), 'document')

    def test_pdf_as_document_is_fine(self):
        self.assertEqual(wa_check_media('document', 50 * MB, 'application/pdf'), '')

    def test_zero_size_is_not_rejected_by_the_cap(self):
        """An unknown size (0) must not be treated as oversized."""
        self.assertEqual(wa_check_media('video', 0, 'video/mp4'), '')

    def test_format_bytes_is_human_readable(self):
        self.assertEqual(wa_format_bytes(16 * MB), '16.0 MB')
        self.assertEqual(wa_format_bytes(5 * MB), '5.0 MB')
