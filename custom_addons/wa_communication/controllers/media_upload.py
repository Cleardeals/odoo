"""Media upload endpoint for WhatsApp RM sends.

Accepts a multipart file POST, creates a public ir.attachment, and returns a
fully-qualified public URL so Interakt's servers can fetch the media.

URL base resolution (first non-empty wins):
1. ``wa_communication.media_public_base_url`` — a dedicated override.  Set this
   to a public tunnel (e.g. an ngrok / cloudflared URL → ``make wa-tunnel``)
   for **local** testing of image/video/document sends without changing the
   global ``web.base.url`` (which would break login redirects in dev).
2. ``web.base.url`` — the normal production value (real public domain).
"""

import base64
import logging
import re
from urllib.parse import quote

from odoo import http
from odoo.http import request

from ..models.wa_conversation_outbound import (
    wa_check_media,
    wa_format_bytes,
    wa_media_size_cap,
)

_logger = logging.getLogger(__name__)

# Multipart framing (headers, boundaries) adds a little to the raw file size, so
# the Content-Length pre-check allows a small margin before rejecting.
_MULTIPART_OVERHEAD_BYTES = 8 * 1024


class WaMediaUploadController(http.Controller):

    @http.route(
        "/wa/media/upload",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def upload(self, **kwargs):
        # ── Guard 1: pre-parse ────────────────────────────────────────────────
        # Reject on Content-Length BEFORE touching request.httprequest.files —
        # that attribute is what makes werkzeug parse the body and spool it to a
        # temp file. ``kind`` therefore travels as a QUERY parameter, so we can
        # pick the right cap without reading the body at all.
        kind = (request.httprequest.args.get("kind") or "document").lower()
        cap = wa_media_size_cap(kind)
        declared = request.httprequest.content_length or 0
        if declared > cap + _MULTIPART_OVERHEAD_BYTES:
            _logger.info(
                "wa_media_upload: rejected %s upload of %s (cap %s) before parsing",
                kind, wa_format_bytes(declared), wa_format_bytes(cap),
            )
            return request.make_json_response(
                {"error": "This %s is %s — WhatsApp allows at most %s. "
                          "Please compress it or share a link instead."
                          % (kind, wa_format_bytes(declared), wa_format_bytes(cap))},
                status=413,
            )

        file = request.httprequest.files.get("file")
        if not file:
            return request.make_json_response({"error": "no file"}, status=400)

        original_filename = file.filename or "attachment"
        # Strip path components and sanitise for use in a URL segment.
        # Keep only alphanumerics, dots, dashes and underscores; replace
        # everything else (including spaces) with underscores.
        safe_filename = re.sub(r"[^\w.\-]", "_", original_filename.lstrip("/\\"))
        mimetype = file.content_type or "application/octet-stream"

        # ── Guard 2: post-parse, pre-read ─────────────────────────────────────
        # Measure via seek/tell (no bytes into RAM) for the cases guard 1 can't
        # cover: a missing or understated Content-Length. Still ahead of the
        # base64 encode and the ir.attachment create, so an oversized file never
        # reaches the filestore.
        try:
            file.seek(0, 2)
            actual = file.tell()
            file.seek(0)
        except (OSError, ValueError):  # non-seekable stream — fall back to the header
            actual = declared

        error = wa_check_media(kind, actual, mimetype)
        if error:
            _logger.info(
                "wa_media_upload: rejected %r (%s, kind=%s, %s): %s",
                original_filename, mimetype, kind, wa_format_bytes(actual), error,
            )
            return request.make_json_response({"error": error}, status=413)

        data = base64.b64encode(file.read()).decode()

        attachment = request.env["ir.attachment"].sudo().create({
            "name":     original_filename,   # human-readable name in Odoo
            "datas":    data,
            "mimetype": mimetype,
            "public":   True,
        })

        ICP = request.env["ir.config_parameter"].sudo()
        base_url = (
            ICP.get_param("wa_communication.media_public_base_url", "")
            or ICP.get_param("web.base.url", "")
        ).rstrip("/")

        if not base_url.startswith(("http://", "https://")):
            _logger.warning(
                "wa_media_upload: base_url=%r is not absolute — Interakt will not "
                "be able to fetch media. Set wa_communication.media_public_base_url "
                "to a public tunnel for local testing.",
                base_url,
            )

        # URL uses the sanitised filename (no spaces, safe for HTTP headers).
        public_url = f"{base_url}/web/content/{attachment.id}/{quote(safe_filename)}"

        _logger.info(
            "wa_media_upload: id=%s original=%r safe=%r url=%s",
            attachment.id, original_filename, safe_filename, public_url,
        )
        return request.make_json_response({
            "url":  public_url,
            "id":   attachment.id,
            "name": original_filename,
        })
