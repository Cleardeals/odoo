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

_logger = logging.getLogger(__name__)


class WaMediaUploadController(http.Controller):

    @http.route(
        "/wa/media/upload",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def upload(self, **kwargs):
        file = request.httprequest.files.get("file")
        if not file:
            return request.make_json_response({"error": "no file"}, status=400)

        original_filename = file.filename or "attachment"
        # Strip path components and sanitise for use in a URL segment.
        # Keep only alphanumerics, dots, dashes and underscores; replace
        # everything else (including spaces) with underscores.
        safe_filename = re.sub(r"[^\w.\-]", "_", original_filename.lstrip("/\\"))
        mimetype = file.content_type or "application/octet-stream"
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
