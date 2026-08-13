"""Outbound messaging — send_message / send_first_message / templates.

Part of the ``wa.conversation`` model — see wa_conversation.py for the base
definition (fields, constraints, inbound push dispatcher).
"""
import json
import logging
import uuid

from odoo import api, fields, models
from odoo.exceptions import UserError
from . import interakt_client
from .wa_conversation import _TOPIC_WA_REQUESTS

_logger = logging.getLogger(__name__)

# WhatsApp interactive-list length caps. Interakt rejects the entire message with
# a 400 when any is exceeded, so we validate before publishing rather than letting
# the send fail downstream. Kept in sync with shared/interakt.py on the platform.
WA_LIST_BUTTON_MAX = 20
WA_LIST_SECTION_TITLE_MAX = 24
WA_LIST_ROW_TITLE_MAX = 24
WA_LIST_ROW_DESC_MAX = 72

# WhatsApp media size caps, in bytes (Meta Cloud API limits).
#
# Two reasons to enforce these as early as possible:
#  1. Interakt accepts the send, then WhatsApp rejects the oversized media
#     asynchronously — and that failure webhook carries no reason, so the RM
#     just sees "Failed" with no explanation.
#  2. Every upload is read into memory and base64-encoded (~3.5x the file size)
#     before it reaches the filestore, so an 80 MB video blows the Odoo worker's
#     memory limit and recycles the worker mid-request — which can drop
#     in-flight Pub/Sub publishes (see the lost assign of 2026-07-28).
WA_MEDIA_MAX_BYTES = {
    'image':     5 * 1024 * 1024,
    'video':    16 * 1024 * 1024,
    'audio':    16 * 1024 * 1024,
    'document': 100 * 1024 * 1024,
}

# ── Quick property-details share ─────────────────────────────────────────────
#
# The RM-triggered twin of the initial-nudge workflow's second message.  The
# workflow only sends that card when the buyer taps "View Property Details";
# this lets an RM send the same card on demand — on a recommended lead, or after
# a call.
#
# The variable contract below MUST stay in step with the workflow's msg_2, or
# the manual card and the automatic one render differently for the same
# property.  Source of truth:
#   cleardeals-whatsapp-platform/services/workflow-engine/configs/
#       initial_nudge_property.yaml  (step msg_2, vars block)
#
# Template name and language are config parameters, not constants: Meta keeps
# reclassifying this copy as Marketing, so the wording gets reworked and
# resubmitted under a new name.  Swapping templates must not need a redeploy.
_PARAM_QUICK_SHARE_TEMPLATE = 'wa_communication.quick_share_template'
_PARAM_QUICK_SHARE_LANGUAGE = 'wa_communication.quick_share_template_language'
_DEFAULT_QUICK_SHARE_TEMPLATE = 'quick_details_share_odoo_w8'
_DEFAULT_QUICK_SHARE_LANGUAGE = 'hi'

# Header var 1 — the property's primary image. Same GCS asset the workflow falls
# back to, so a property with no photo looks identical either way.
QUICK_SHARE_IMAGE_FALLBACK = (
    'https://storage.googleapis.com/cleardeals-wa-assets/'
    'initial_nudge_unassigned/fallback_media_property.jpeg'
)

# Body vars 1-7, in template order.  Each entry is
# (key in the actor snapshot's ``property`` dict, human label, fallback).
# An empty fallback means the value is required — Interakt rejects a blank
# variable outright, so we catch it here and tell the RM which field to fill.
QUICK_SHARE_BODY_VARS = (
    ('name',         'Project name',   ''),
    ('locality',     'Locality',       ''),
    ('type_label',   'Property type',  ''),
    ('size',         'Size',           ''),
    ('furnishing',   'Furnishing',     ''),
    ('link',         'Property link',  ''),
    ('tour_360_url', '360° tour link', 'https://www.cleardeals.in/buy'),
)

# Mime prefixes WhatsApp refuses for the Document type ("mp4 is not supported
# for Document media") — these must be sent as their own media kind.
WA_DOCUMENT_FORBIDDEN_MIME_PREFIXES = ('video/', 'image/', 'audio/')

# Interakt: "fileName value can be at max 100 characters" — it rejects the whole
# send otherwise. A filename is only a label (unlike a list row title, where
# truncating would change the question the buyer is asked), so we trim instead
# of refusing an otherwise valid file. Mirrors FILENAME_MAX in shared/interakt.py.
WA_FILENAME_MAX = 100


def wa_clamp_filename(name: str) -> str:
    """Shorten *name* to Interakt's cap, preserving the extension.

    The extension drives how WhatsApp renders the document, so it is kept even
    when the stem has to be cut.
    """
    name = (name or '').strip()
    if len(name) <= WA_FILENAME_MAX:
        return name
    stem, dot, ext = name.rpartition('.')
    if dot and 0 < len(ext) <= 10:
        keep = WA_FILENAME_MAX - len(ext) - 1
        if keep > 0:
            return '%s.%s' % (stem[:keep], ext)
    return name[:WA_FILENAME_MAX]


def wa_media_kind_for_mimetype(mimetype: str) -> str:
    """Map a mimetype to the WhatsApp media kind whose cap applies."""
    mt = (mimetype or '').lower()
    if mt.startswith('image/'):
        return 'image'
    if mt.startswith('video/'):
        return 'video'
    if mt.startswith('audio/'):
        return 'audio'
    return 'document'


def wa_format_bytes(n: int) -> str:
    """Human-readable size for user-facing errors."""
    n = n or 0
    mb = n / (1024 * 1024)
    return '%.1f MB' % mb if mb >= 0.1 else '%d KB' % (n / 1024)


def wa_media_size_cap(kind: str) -> int:
    """Byte cap for *kind*, falling back to the document cap."""
    return WA_MEDIA_MAX_BYTES.get(
        (kind or 'document').lower(), WA_MEDIA_MAX_BYTES['document'])


def wa_check_media(kind: str, size_bytes: int, mimetype: str = '') -> str:
    """Return a user-facing error for an unsendable attachment, else ''.

    Checks the size cap for *kind* and rejects mime/kind combinations WhatsApp
    refuses outright.
    """
    kind = (kind or 'document').lower()
    if kind == 'document' and (mimetype or '').lower().startswith(
            WA_DOCUMENT_FORBIDDEN_MIME_PREFIXES):
        real = wa_media_kind_for_mimetype(mimetype)
        return ("WhatsApp does not accept %s files as a Document. "
                "Use the %s button instead." % (mimetype, real.title()))
    cap = wa_media_size_cap(kind)
    if size_bytes and size_bytes > cap:
        return ("This %s is %s — WhatsApp allows at most %s. "
                "Please compress it or share a link instead."
                % (kind, wa_format_bytes(size_bytes), wa_format_bytes(cap)))
    return ''


class WaConversation(models.Model):
    _inherit = 'wa.conversation'

    _WINDOWED_KINDS = frozenset({'freetext', 'image', 'video', 'document', 'audio', 'list'})

    def send_message(
        self,
        body: str = '',
        kind: str = 'freetext',
        template_name: str = '',
        template_language: str = '',
        initiator: str = 'rm',
        request_id: str = '',
        workflow_slug: str = '',
        step_id: str = '',
        enrollment_id: str = '',
        media_url: str = '',
        media_filename: str = '',
        body_values: list | None = None,
        header_values: list | None = None,
    ) -> 'models.Model':
        """Send a WA message from this conversation.

        Creates a queued ``wa.message`` and publishes a send request to the
        ``cd-prod-odoo-wa-requests`` Pub/Sub topic.  The WA bridge sends the
        actual WA message and delivers status receipts back via the inbound
        push path.

        The publish is deferred until after the current SQL transaction
        commits so that a rollback does not trigger a spurious WA send.

        :param body:           Message text (required for freetext kind).
        :param kind:           Message kind — one of the ``wa.message.kind`` values.
        :param template_name:  Template name (required when kind='template').
        :param initiator:      Who is sending — 'rm' (default) or 'workflow'.
        :param request_id:     OdooWaRequest UUID for tracking.
        :param workflow_slug:  Workflow context for automated sends.
        :param step_id:        Workflow step for automated sends.
        :param enrollment_id:  Enrollment UUID for automated sends.
        :param media_url:      Public media URL (image/video/document/audio).
        :param media_filename: Filename hint for documents.
        :param body_values:    Template body variable substitutions.
        :param header_values:  Template header variable substitutions.
        :return:               The newly created ``wa.message`` record.
        :raises UserError:     If the conversation has no phone number, or if the
                               24h free-text window is closed for a non-template kind.
        """
        self.ensure_one()
        if not self.phone_number:
            raise UserError(
                "Cannot send — this conversation has no phone number."
            )

        # Ownership gate: an RM may only send on a chat assigned to them.
        # Managers can send on any chat; system/workflow sends bypass the gate.
        if initiator == 'rm':
            self._assert_can_send()

        # Hard-block non-template sends when the 24h window is closed.
        if kind in self._WINDOWED_KINDS and initiator == 'rm':
            self._compute_window_state()
            if self.window_state == 'closed':
                raise UserError(
                    "The 24-hour WhatsApp window is closed for this contact. "
                    "You can only send template messages until the customer replies."
                )

        import uuid as _uuid
        # Always produce a valid UUID request_id: the bridge stores it in
        # WaSendPayload.enrollment_id and echoes it back on OdooWaEvent so
        # Odoo can correlate status receipts with this wa.message record.
        effective_request_id = request_id if request_id else str(_uuid.uuid4())

        # File the send into the conversation's active inquiry segment (flag-gated).
        # The RM is the source of truth for which property a free-text send is about
        # and sets it via the inbox banner; we honour the current active segment, or
        # bootstrap one for the linked lead if none is active yet.
        send_seg = False
        if self._owa_segments_enabled():
            send_seg = self.active_segment_id or self._owa_ensure_segment(
                inquiry=self.lead_id or None, started_by='rm')

        wa_msg = self.env['wa.message'].create({
            'conversation_id': self.id,
            'direction': 'outbound',
            'initiator': initiator,
            'kind': kind,
            'body': body,
            'template_name': template_name or False,
            'media_url': media_url or False,
            'media_filename': media_filename or False,
            'request_id': effective_request_id,
            'workflow_slug': workflow_slug or False,
            'step_id': step_id or False,
            'enrollment_id': enrollment_id or False,
            'lead_id': self.lead_id.id if self.lead_id else False,
            'segment_id': send_seg.id if send_seg else False,
            'sender_name': self.env.user.name if initiator == 'rm' else None,
            'status': 'queued',
            'occurred_at': fields.Datetime.now(),
        })

        # Bump the conversation to the top of the "recent" list and preview the
        # message we just sent — WhatsApp-style (your own reply is the last line).
        last_at, preview = self._owa_conversation_tail(self)
        self.sudo().write({'last_message_at': last_at, 'last_message_preview': preview})

        topic = self.env['ir.config_parameter'].sudo().get_param(
            _TOPIC_WA_REQUESTS, 'cd-prod-odoo-wa-requests'
        )
        # Payload matches OdooWaRequest (shared/models.py in the WA platform).
        request_data = {
            'request_type': 'send',
            'request_id': effective_request_id,
            'phone': self.phone_number,
            'kind': kind,
            'message_text': body or None,
            'template_name': template_name or None,
            'template_language': template_language or None,
            'media_url': media_url or None,
            'media_filename': media_filename or None,
            'body_values': body_values or [],
            'header_values': header_values or [],
            'rm_odoo_id': self.env.uid,
            'rm_name': self.env.user.name if self.env.user else None,
        }

        # Defer publish until after the transaction commits.
        def _publish():
            self.env['cleardeals.pubsub'].publish_async(topic, request_data)

        self.env.cr.postcommit.add(_publish)

        self.env['wa.event.log'].sudo()._log(
            event_type='wa_message_outbound',
            direction='outbound',
            topic=topic,
            payload={
                'phone': self.phone_number,
                'kind': kind,
                'message_text': (body or '')[:100],
                'request_id': effective_request_id,
                'wa_message_id': wa_msg.id,
            },
            status='processed',
        )
        return wa_msg

    def send_list_message(
        self,
        body: str,
        button_text: str,
        sections: list,
        request_id: str = '',
    ) -> 'models.Model':
        """Send an interactive WhatsApp LIST message (RM manual send).

        ``sections`` is ``[{"title", "rows": [{"id","title","description"}]}]``.
        Validated like any non-template send: requires ownership + an open 24h
        window (interactive lists are not templates).  Stores the list structure
        on the wa.message as ``list_payload`` so the bubble can render it, and
        publishes an OdooWaRequest with kind='list'.

        :raises UserError: no phone, closed window, or an empty/oversized list.
        """
        self.ensure_one()
        if not self.phone_number:
            raise UserError("Cannot send — this conversation has no phone number.")
        self._assert_can_send()

        # Validate the list shape up front so the RM gets a clear error instead of
        # a silent platform-side drop.  Mirrors the platform's Interakt limits.
        clean_sections = self._owa_normalize_list_sections(sections)
        if not clean_sections:
            raise UserError("Add at least one list item (with a title) before sending.")
        n_rows = sum(len(s['rows']) for s in clean_sections)
        if n_rows > 10:
            raise UserError("A WhatsApp list can have at most 10 items in total.")
        self._owa_assert_list_limits(button_text, clean_sections)

        # List messages need an open 24h window (they are not templates).
        self._compute_window_state()
        if self.window_state == 'closed':
            raise UserError(
                "The 24-hour WhatsApp window is closed for this contact. "
                "You can only send template messages until the customer replies."
            )

        effective_request_id = request_id or str(uuid.uuid4())
        button_text = (button_text or 'Menu').strip()

        send_seg = False
        if self._owa_segments_enabled():
            send_seg = self.active_segment_id or self._owa_ensure_segment(
                inquiry=self.lead_id or None, started_by='rm')

        list_payload = {'button': button_text, 'sections': clean_sections}
        wa_msg = self.env['wa.message'].create({
            'conversation_id': self.id,
            'direction': 'outbound',
            'initiator': 'rm',
            'kind': 'list',
            'body': body or '',
            'list_payload': json.dumps(list_payload),
            'request_id': effective_request_id,
            'lead_id': self.lead_id.id if self.lead_id else False,
            'segment_id': send_seg.id if send_seg else False,
            'sender_name': self.env.user.name,
            'status': 'queued',
            'occurred_at': fields.Datetime.now(),
        })

        # Bump + preview the sent list (WhatsApp-style tail refresh).
        last_at, preview = self._owa_conversation_tail(self)
        self.sudo().write({'last_message_at': last_at, 'last_message_preview': preview})

        topic = self.env['ir.config_parameter'].sudo().get_param(
            _TOPIC_WA_REQUESTS, 'cd-prod-odoo-wa-requests'
        )
        request_data = {
            'request_type': 'send',
            'request_id': effective_request_id,
            'phone': self.phone_number,
            'kind': 'list',
            'message_text': body or None,
            'list_button_text': button_text,
            'list_sections': clean_sections,
            'rm_odoo_id': self.env.uid,
            'rm_name': self.env.user.name if self.env.user else None,
        }

        def _publish():
            self.env['cleardeals.pubsub'].publish_async(topic, request_data)

        self.env.cr.postcommit.add(_publish)

        self.env['wa.event.log'].sudo()._log(
            event_type='wa_message_outbound',
            direction='outbound',
            topic=topic,
            payload={
                'phone': self.phone_number,
                'kind': 'list',
                'message_text': (body or '')[:100],
                'request_id': effective_request_id,
                'wa_message_id': wa_msg.id,
                'list_rows': n_rows,
            },
            status='processed',
        )
        return wa_msg

    @staticmethod
    def _owa_assert_list_limits(button_text: str, clean_sections: list) -> None:
        """Enforce WhatsApp's interactive-list length caps before we publish.

        Interakt rejects the WHOLE message with a 400 if any of these is exceeded
        (e.g. "'title' is a required string which maximum of 24 characters in each
        JSON of 'rows' array"), so catching it here turns a silent failed send into
        an actionable message naming the offending row.

        We reject rather than truncate: silently clipping "Liked & Want Another
        visit with family" to "Liked & Want Another vis" would ship a different
        question to the buyer than the RM wrote.
        """
        button = (button_text or 'Menu').strip()
        if len(button) > WA_LIST_BUTTON_MAX:
            raise UserError(
                "The list button text is %d characters — WhatsApp allows at most %d.\n\n“%s”"
                % (len(button), WA_LIST_BUTTON_MAX, button)
            )
        for section in clean_sections:
            s_title = section.get('title') or ''
            if len(s_title) > WA_LIST_SECTION_TITLE_MAX:
                raise UserError(
                    "A list section title is %d characters — WhatsApp allows at most %d.\n\n“%s”"
                    % (len(s_title), WA_LIST_SECTION_TITLE_MAX, s_title)
                )
            for row in section.get('rows') or []:
                title = row.get('title') or ''
                if len(title) > WA_LIST_ROW_TITLE_MAX:
                    raise UserError(
                        "This list item is %d characters — WhatsApp allows at most %d:\n\n"
                        "“%s”\n\nPlease shorten it and send again."
                        % (len(title), WA_LIST_ROW_TITLE_MAX, title)
                    )
                desc = row.get('description') or ''
                if len(desc) > WA_LIST_ROW_DESC_MAX:
                    raise UserError(
                        "A list item description is %d characters — WhatsApp allows at "
                        "most %d:\n\n“%s”"
                        % (len(desc), WA_LIST_ROW_DESC_MAX, desc)
                    )

    @staticmethod
    def _owa_normalize_list_sections(sections: list) -> list:
        """Drop empty rows/sections and coerce to the wire shape.

        Keeps only rows with a non-blank title; auto-fills a row id when absent
        (the id is echoed back as the buyer's reply, so it must be present).
        """
        out = []
        counter = 0
        for idx, section in enumerate(sections or []):
            if not isinstance(section, dict):
                continue
            rows = []
            for row in section.get('rows', []) or []:
                if not isinstance(row, dict):
                    continue
                title = (row.get('title') or '').strip()
                if not title:
                    continue
                counter += 1
                clean = {
                    'id': (row.get('id') or '').strip() or f'row_{counter}',
                    'title': title,
                }
                desc = (row.get('description') or '').strip()
                if desc:
                    clean['description'] = desc
                rows.append(clean)
            if rows:
                out.append({
                    'title': (section.get('title') or f'Section {idx + 1}').strip(),
                    'rows': rows,
                })
        return out

    def mark_as_read(self) -> None:
        """Reset the unread counter for this conversation."""
        self.ensure_one()
        self.write({'unread_count': 0})

    @api.model
    def fetch_templates(self, template_name: str | None = None) -> list[dict]:
        """Fetch APPROVED WhatsApp templates live from Interakt for the picker.

        Odoo holds the Interakt API key (system params) and queries the
        Get-All-Templates endpoint on demand — there is no local cache. Each
        returned template carries its rendered skeleton (header/body/footer),
        button labels, and an ordered list of ``{{N}}`` variable slots so the
        RM can fill them before sending.

        :raises UserError: if the key is unset or Interakt is unreachable.
        """
        return interakt_client.fetch_templates(self.env, template_name=template_name)

    # ------------------------------------------------------------------
    # Quick property-details share
    # ------------------------------------------------------------------

    @api.model
    def _quick_share_template(self) -> tuple:
        """Configured (template_name, language) for the quick-share card."""
        Param = self.env['ir.config_parameter'].sudo()
        name = (Param.get_param(
            _PARAM_QUICK_SHARE_TEMPLATE, _DEFAULT_QUICK_SHARE_TEMPLATE) or '').strip()
        lang = (Param.get_param(
            _PARAM_QUICK_SHARE_LANGUAGE, _DEFAULT_QUICK_SHARE_LANGUAGE) or '').strip()
        if not name:
            raise UserError(
                "No quick-share template is configured. Ask an administrator to "
                "set the '%s' system parameter." % _PARAM_QUICK_SHARE_TEMPLATE)
        return name, (lang or _DEFAULT_QUICK_SHARE_LANGUAGE)

    @api.model
    def _quick_share_values(self, lead) -> tuple:
        """Build (body_values, header_values) for *lead*'s property.

        Reuses ``leads.new._wa_actor_snapshot()`` — the very same helper that
        fills the workflow's event payload — rather than reading
        ``property.base`` again.  That is what guarantees the manual card and
        the automatic one show identical text: the snapshot already composes
        ``type_label`` ("3 BHK Apartment") and strips the "[tag]" suffix from
        the project name, and neither rule has to be restated here.

        :raises UserError: if the lead has no property, or a required field on
                           that property is blank.  Interakt rejects a template
                           with an empty variable, so catching it here turns a
                           silent failed send into something the RM can fix.
        """
        if not lead or not lead.exists():
            raise UserError(
                "This conversation isn't linked to an inquiry yet. Link or "
                "create one before sharing property details.")
        if not lead.property_base_id:
            raise UserError(
                "This inquiry has no property linked, so there are no details "
                "to share. Set the property on the inquiry first.")

        prop = lead.sudo()._wa_actor_snapshot()['property']

        body_values, missing = [], []
        for key, label, fallback in QUICK_SHARE_BODY_VARS:
            value = (prop.get(key) or '').strip()
            if not value:
                value = fallback
            if not value:
                missing.append(label)
            body_values.append(value)

        if missing:
            raise UserError(
                "%s is missing on this property, and WhatsApp will not accept a "
                "template with a blank field.\n\nFill it in on the property "
                "record, then share the details.\n\nMissing: %s"
                % (missing[0], ', '.join(missing)))

        header_values = [(prop.get('image_url') or '').strip()
                         or QUICK_SHARE_IMAGE_FALLBACK]
        return body_values, header_values

    def send_property_details(self) -> 'models.Model':
        """Send the property-details card for this conversation's inquiry.

        The RM-facing twin of the initial-nudge workflow's msg_2.  Goes out
        through the ordinary :meth:`send_message` template path, so it inherits
        the ownership gate, the queued ``wa.message``, the post-commit publish
        and the audit-log entry.  A closed 24h window is not a blocker — this is
        a template.

        :returns: the queued ``wa.message``.
        """
        self.ensure_one()
        template_name, language = self._quick_share_template()
        body_values, header_values = self._quick_share_values(self.lead_id)
        return self.send_message(
            kind='template',
            template_name=template_name,
            template_language=language,
            body_values=body_values,
            header_values=header_values,
        )

    @api.model
    def send_property_details_for_lead(self, lead_id: int) -> int:
        """Share property details from the lead form, conversation or not.

        Mirrors :meth:`send_first_message` for the case where the lead has never
        been messaged: create/claim the conversation, then send.

        :returns: the ``wa.conversation`` id, so the caller can load the thread.
        """
        # Guard before int(): a missing id used to surface as a raw
        # "int() argument must be ... not 'NoneType'" TypeError, which tells the
        # RM nothing and looks like a server fault rather than a stale form.
        if not lead_id:
            raise UserError(
                "Save this inquiry before sharing property details.")
        lead = self.env['leads.new'].browse(int(lead_id))
        if not lead.exists():
            raise UserError("Inquiry not found.")
        # Validate before touching anything, so a property with a missing field
        # doesn't leave a freshly-created empty conversation behind.
        body_values, header_values = self._quick_share_values(lead)
        template_name, language = self._quick_share_template()

        if not lead.phone:
            raise UserError(
                "This inquiry has no phone number, so there is nowhere to send "
                "the details.")

        # Resolve by PHONE, not by lead: a buyer asking about three properties
        # has three inquiries but one WhatsApp thread, and only the first of them
        # is the thread's anchor.  Searching by lead_id would miss the thread for
        # the other two and start a second conversation on the same number.
        full_phone = ('91' + lead.phone) if len(lead.phone) == 10 else lead.phone
        conv = self.sudo()._get_or_create_for_phone(full_phone)
        if not conv.lead_id:
            conv.write({'lead_id': lead.id})
        if not conv.assigned_user_id:
            # Nobody owns this chat yet — whoever sends the first message does.
            conv.write({'assigned_user_id': self.env.uid})

        # File the send under THIS inquiry's span before sending.  Without it
        # send_message inherits whatever span happens to be active — which, on a
        # thread that has already discussed another property, tags the card with
        # the wrong property and attributes it to the wrong inquiry.  The RM is
        # explicitly acting on this lead, so that is the span this belongs to.
        conv._owa_ensure_segment(inquiry=lead, started_by='rm')

        # Send as the acting user: the ownership gate must judge them, not sudo.
        as_user = self.browse(conv.id)
        as_user.invalidate_recordset(['active_segment_id'])
        as_user.send_message(
            kind='template',
            template_name=template_name,
            template_language=language,
            body_values=body_values,
            header_values=header_values,
        )
        return conv.id

    @api.model
    def send_first_message(
        self,
        phone: str,
        lead_id: int | None = None,
        template_name: str = '',
        template_language: str = '',
        body_values: list | None = None,
        header_values: list | None = None,
    ) -> int:
        """Start a new WA conversation and send the first outbound template.

        Called from the lead tab when a lead has no existing ``wa.conversation``.
        Creates (or retrieves) the conversation record, links the lead, auto-claims
        the chat for the sending RM, then sends the template via the normal
        outbound path.

        The ownership gate in :meth:`send_message` is satisfied because we write
        ``assigned_user_id`` *before* calling it — whoever fires the first shot
        owns the conversation going forward (no Interakt handshake needed here
        because the chat does not yet exist on the platform; the first template
        message itself creates it there).

        :param phone:              Raw phone from the lead record (10 or 12 digits).
        :param lead_id:            ``leads.new`` id to link. Optional.
        :param template_name:      Interakt-approved template name (required).
        :param template_language:  Template language code, e.g. ``'en'``.
        :param body_values:        Ordered ``{{N}}`` substitution values.
        :param header_values:      Ordered header variable substitutions.
        :returns:                  The ``wa.conversation`` id so the caller can
                                   load the thread immediately.
        :raises UserError:         Missing phone/template, or send failure.
        """
        if not phone:
            raise UserError(
                "A phone number is required to start a WhatsApp conversation.")
        if not template_name:
            raise UserError(
                "A template message is required for the first outreach.")

        # Normalise to 12-digit E.164 (without '+').
        full_phone = ('91' + phone) if len(phone) == 10 else phone

        # Get or create the conversation record (idempotent).
        conv = self.sudo()._get_or_create_for_phone(full_phone)

        # Link the lead if provided and not already set.
        if lead_id and not conv.lead_id:
            conv.sudo().write({'lead_id': lead_id})

        # Auto-claim: whoever sends the first message owns the chat.
        # Write directly — no Interakt assignment handshake needed because the
        # conversation doesn't exist on the platform yet.
        if not conv.assigned_user_id:
            conv.sudo().write({'assigned_user_id': self.env.uid})

        # Standard outbound path.  Ownership gate passes because env.uid is now
        # the assigned_user_id.
        conv.send_message(
            kind='template',
            template_name=template_name,
            template_language=template_language,
            body_values=body_values or [],
            header_values=header_values or [],
        )
        return conv.id
