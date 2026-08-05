"""OdooWaEvent handlers — status receipts, replies, enrollments, workflow sync.

Part of the ``wa.conversation`` model — see wa_conversation.py for the base
definition (fields, constraints, inbound push dispatcher).
"""
import json
import logging

from datetime import timedelta

import psycopg2

from odoo import api, fields, models
from .wa_conversation import (
    _INTERAKT_KIND_TO_ODOO,
    _FAILURE_CODE_TO_STATUS,
    _max_status,
    _parse_iso_dt,
)

_logger = logging.getLogger(__name__)

# Postgres concurrency errors that Odoo's service.model.retrying() will re-run
# the whole request for.  Kept identical to that module's
# PG_CONCURRENCY_EXCEPTIONS_TO_RETRY so we never swallow something Odoo would
# have recovered from on its own.
_PG_CONCURRENCY_ERRORS = (
    psycopg2.errors.LockNotAvailable,
    psycopg2.errors.SerializationFailure,
    psycopg2.errors.DeadlockDetected,
)


def _parse_special_inbound(raw_body):
    """Detect a shared LOCATION or CONTACT payload from an inbound message body.

    Interakt delivers these as a JSON blob in the message text (a location is a
    dict with ``latitude``/``longitude``; a contact is a list of vCards), so we
    detect by SHAPE rather than trusting the content-type string.  Returns a
    ``(kind, clean_body, maps_url)`` tuple, or ``None`` when the body is ordinary
    text — so a normal reply that merely looks like JSON is never misclassified.

    * location → clean_body = "Name\\nAddress"; maps_url = the shared url or a
      Google Maps link built from lat/long.
    * contact  → clean_body = "Name · +phone" (one line per contact); maps_url = ''.
    """
    if not raw_body:
        return None
    stripped = raw_body.strip()
    if not stripped or stripped[0] not in '{[':
        return None
    try:
        data = json.loads(stripped)
    except (ValueError, TypeError):
        return None

    # ── List reply: {"type":"list_reply","list_reply":{"id","title","description"}} ──
    # A buyer tapped a row in an interactive list we sent.  WhatsApp shows just
    # the picked row's title as the reply bubble — so store that, not the JSON.
    if isinstance(data, dict) and data.get('type') == 'list_reply':
        lr = data.get('list_reply') or {}
        title = (lr.get('title') or '').strip()
        if title:
            return 'list_reply', title, ''

    # ── Location: {"latitude": .., "longitude": .., "name": .., "address": ..} ──
    if isinstance(data, dict) and 'latitude' in data and 'longitude' in data:
        name = (data.get('name') or '').strip()
        address = (data.get('address') or '').strip()
        lat, lng = data.get('latitude'), data.get('longitude')
        clean = '\n'.join(p for p in (name, address) if p) or 'Shared location'
        url = (data.get('url') or '').strip()
        if not url and lat is not None and lng is not None:
            url = f'https://www.google.com/maps?q={lat},{lng}'
        return 'location', clean, url

    # ── Contact: [{"name": {..}, "phones": [{"phone": ..}], "vcard": ..}, ..] ──
    if isinstance(data, list) and data and isinstance(data[0], dict) and (
        'vcard' in data[0] or 'phones' in data[0] or 'name' in data[0]
    ):
        lines = []
        for card in data:
            if not isinstance(card, dict):
                continue
            nm = card.get('name')
            if isinstance(nm, dict):
                display = (
                    nm.get('formattedName') or nm.get('formatted_name')
                    or ' '.join(
                        str(nm.get(k, '')).strip()
                        for k in ('firstName', 'middleName', 'lastName')
                        if nm.get(k)
                    )
                ).strip()
            else:
                display = str(nm or '').strip()
            phones = card.get('phones') or []
            phone = ''
            if isinstance(phones, list) and phones and isinstance(phones[0], dict):
                phone = (phones[0].get('phone') or '').strip()
            line = ' · '.join(p for p in (display, phone) if p)
            if line:
                lines.append(line)
        if lines:
            return 'contact', '\n'.join(lines), ''

    return None

class WaConversation(models.Model):
    _inherit = 'wa.conversation'

    @api.model
    def _process_odoo_wa_event(self, event: dict, pubsub_message_id: str) -> None:
        """Dispatch an OdooWaEvent to its specific handler.

        :param event:             Decoded OdooWaEvent payload dict.
        :param pubsub_message_id: GCP message ID for the audit log.
        """
        event_type = event.get('event_type', '')
        _ODOO_WA_HANDLERS = {
            'message_sent':            self._handle_odoo_message_sent,
            'message_delivered':       self._handle_odoo_message_delivered,
            'message_read':            self._handle_odoo_message_read,
            'message_failed':          self._handle_odoo_message_failed,
            'lead_replied':            self._handle_odoo_lead_replied,
            'ambiguous_reply':         self._handle_odoo_ambiguous_reply,
            'permanent_failure':       self._handle_odoo_permanent_failure,
            'retry_exhausted':         self._handle_odoo_permanent_failure,
            'enrollment_created':      self._handle_odoo_enrollment_created,
            'enrollment_completed':    self._handle_odoo_enrollment_completed,
            'enrollment_step_changed': self._handle_odoo_enrollment_step_changed,
            # Chat assignment confirmation from the platform (Interakt result:true)
            'assignment_confirmed':     self._handle_odoo_assignment_confirmed,
            # Workflow registry sync — routes to wa.workflow model
            'workflow.registry.synced': self._handle_workflow_registry_synced,
            # Workflow toggle ACK — WA platform confirms toggle was applied
            'workflow.synced':          self._handle_workflow_synced,
        }
        handler = _ODOO_WA_HANDLERS.get(event_type)
        # Log every OdooWaEvent to the webhook log BEFORE dispatching so that
        # even failed or unknown events leave an audit trail.  ``trace_id`` is
        # filled automatically from the request context.
        #
        # IMPORTANT — do NOT set the conversation_id / message_id / lead_id FK
        # links here.  Populating a FK on this pre-dispatch INSERT makes Postgres
        # take a FOR KEY SHARE lock on the referenced wa_conversation row; the
        # handler below then upgrades it to FOR UPDATE (see the lock-first comment
        # in _handle_odoo_lead_replied), so two concurrent deliveries for the same
        # conversation each hold KEY SHARE and deadlock on the mutual upgrade.
        # The payload JSON already carries wa_message_id / phone / enrollment_id
        # for correlation, so the links add no query power worth a deadlock.
        try:
            self.env['wa.event.log'].sudo()._log(
                event_type=f'odoo_wa_{event_type}' if event_type else 'odoo_wa_unknown',
                direction='inbound',
                pubsub_message_id=pubsub_message_id,
                payload=event,
                status='processed',
            )
        except Exception:
            pass  # never let audit logging break event processing
        try:
            if handler:
                # Savepoint isolates the handler's DB work.  If the handler
                # raises any exception (including DeadlockDetected), the
                # savepoint rolls back cleanly — leaving the outer transaction
                # in a usable state so the error-log INSERT below can succeed.
                with self.env.cr.savepoint():
                    handler(event, pubsub_message_id)
            else:
                _logger.debug(
                    "wa_push: unhandled OdooWaEvent type=%r message=%s",
                    event_type, pubsub_message_id,
                )
        except _PG_CONCURRENCY_ERRORS:
            # A serialisation failure means THIS transaction lost a write race —
            # it does NOT mean another worker already applied this event.  The
            # competing write is usually ordinary traffic on the same
            # wa_conversation row (unread_count, last_message_at), not a
            # duplicate delivery of the same event.
            #
            # So this must never be swallowed.  Odoo already wraps the request in
            # service.model.retrying(), which rolls back and re-runs it up to 5
            # times with exponential backoff; re-raising is what hands the event
            # to that machinery.  Catching it here defeated the retry and dropped
            # the event silently — an assignment_confirmed lost this way left the
            # chat pending and its reassignment request stuck in 'confirming'
            # forever (conversation 918238268187, request #36, 2026-08-05).
            #
            # Re-raising from inside an except block bypasses the sibling
            # handlers below, so this does not get logged as a handler failure.
            _logger.info(
                "wa_push: serialisation failure on type=%r message=%s — "
                "re-raising for Odoo's retry",
                event_type, pubsub_message_id,
            )
            raise
        except Exception as exc:
            _logger.exception(
                "wa_push: OdooWaEvent handler failed for type=%r message=%s",
                event_type, pubsub_message_id,
            )
            try:
                self.env['wa.event.log'].sudo()._log(
                    event_type=f'odoo_wa_{event_type}_error',
                    direction='inbound',
                    pubsub_message_id=pubsub_message_id,
                    payload={'error': str(exc), 'event': event},
                    status='failed',
                    error_message=str(exc),
                )
            except Exception:
                pass

    @staticmethod
    def _owa_failure_status(failure_code: int | None) -> str:
        """Map an Interakt error code to a ``wa.message.status`` value."""
        return _FAILURE_CODE_TO_STATUS.get(failure_code, 'failed')

    def _owa_resolve_quoted_context(self, conv, template_replied_to, event):
        """Resolve the message a buyer reply refers to (swipe / button reply).

        Returns ``(quoted_body, quoted_sender, src_record_or_None)`` so the inbound
        bubble can show the quoted snippet WhatsApp-style and link to it.  Order:
          1. ``source_message_id`` (Interakt id of the quoted message) → match the
             exact ``wa.message`` by ``wa_message_id`` — works for ANY kind
             (template, RM free-text, media, buyer message), not just templates.
          2. ``template_replied_to`` → most recent earlier outbound message with
             that template name.
          3. Platform-supplied ``quoted_body`` / ``source_message_text``.
        """
        def _snippet(src):
            text = (
                (src.template_body or '').strip()
                or (src.body or '').strip()
                or (src.template_header or '').strip()
                or (src.media_filename or '').strip()
                or (src.template_name or '')
                or (f'[{src.kind}]' if src.kind else '')
            )
            sender = src.sender_name or (
                conv.lead_id.name if src.direction == 'inbound' and conv.lead_id else 'You'
            )
            return (text[:140] or None), sender

        # 1. Exact reference by Interakt message id (any message kind).
        source_message_id = event.get('source_message_id')
        if source_message_id:
            src = conv.message_ids.filtered(
                lambda m: m.wa_message_id == source_message_id
            )[:1]
            if src:
                body, sender = _snippet(src)
                return body, sender, src

        # 2. Template-name match (button replies, or when no id is supplied).
        if template_replied_to:
            orig = conv.message_ids.filtered(
                lambda m: m.direction == 'outbound'
                and m.template_name == template_replied_to
            ).sorted('occurred_at')
            if orig:
                body, sender = _snippet(orig[-1])
                return body, sender, orig[-1]

        # 3. Platform-supplied quoted text fallback (no linkable record).
        q_body = event.get('quoted_body') or event.get('source_message_text')
        if q_body:
            return q_body, (event.get('quoted_sender') or 'You'), None

        return None, None, None

    @staticmethod
    def _owa_template_content_vals(event: dict, msg) -> dict:
        """Extract rendered template content from a status event into write vals.

        wa-sender enriches ``message_delivered``/``message_read`` events with the
        template body/header/footer/buttons rendered from Interakt's
        ``raw_template`` (placeholders substituted).  Persist them so the chat
        bubble shows the real message text instead of just the template name.
        Only fills ``body`` when the message doesn't already carry text.
        """
        rendered_body = event.get('rendered_body')
        if (rendered_body is None and not event.get('template_buttons')
                and not event.get('header_media_url')):
            return {}
        vals = {}
        # 'body' is immutable (append-only); render into the dedicated
        # template_body field instead and only when not already populated.
        if rendered_body and not (msg.template_body or '').strip():
            vals['template_body'] = rendered_body
        header = event.get('rendered_header')
        if header:
            vals['template_header'] = header
        # Header media (image/video/document/audio) — only fill blanks so a later
        # status event can't clobber an already-populated header.
        header_media_url = event.get('header_media_url')
        if header_media_url and not msg.template_header_media_url:
            vals['template_header_media_url'] = header_media_url
            vals['template_header_media_type'] = event.get('header_media_type') or False
        footer = event.get('template_footer')
        if footer:
            vals['template_footer'] = footer
        buttons = event.get('template_buttons')
        if buttons:
            vals['template_buttons'] = buttons
        return vals

    def _owa_create_outbound_stub(self, event: dict, *, status: str,
                                  extra_vals: dict | None = None):
        """Create a fresh outbound ``wa.message`` for a status event whose row
        does not exist yet (workflow-initiated send, or a status webhook that
        arrived before ``message_sent``).

        Locks the conversation row FOR UPDATE *before* the FK insert so two
        concurrent status events for the same conversation cannot deadlock on a
        FOR-KEY-SHARE → FOR-UPDATE upgrade (see the lead_replied handler).

        The row is created with the given ``status`` so no receipt/cost is lost
        when events are processed out of order; a later ``message_sent`` finds it
        by ``wa_message_id`` and enriches it (``_max_status`` prevents downgrade).
        """
        phone         = event.get('phone', '')
        wa_message_id = event.get('wa_message_id') or ''
        request_id    = event.get('request_id') or ''
        actor_id      = event.get('actor_id')
        actor_type    = event.get('actor_type', '')
        workflow_slug = event.get('workflow_slug') or False
        template_name = event.get('template_name') or False
        step_id       = event.get('step_id') or False
        enrollment_id = event.get('enrollment_id') or False
        occurred_at   = _parse_iso_dt(event.get('occurred_at', ''))
        initiator     = 'workflow' if workflow_slug or enrollment_id or step_id else 'rm'
        # ``kind`` is immutable once written, and a delivered/read stub can't be
        # re-typed later — infer 'template' from any rendered template content the
        # status event carries, so an out-of-order template send isn't frozen as
        # 'freetext'.
        is_template   = bool(
            template_name or event.get('rendered_body') or event.get('template_buttons')
        )
        kind          = 'template' if is_template else 'freetext'

        conv = self._owa_get_conversation(phone)
        # Lock-first: mirror the lead_replied deadlock guard.
        self.env.cr.execute(
            'SELECT id FROM wa_conversation WHERE id = %s FOR UPDATE', (conv.id,)
        )
        conv.invalidate_recordset()
        lead = self._owa_resolve_lead(actor_id, actor_type, phone)
        seg  = conv._owa_ensure_segment(inquiry=lead, started_by='auto_suggested')
        create_vals = {
            'conversation_id':   conv.id,
            'wa_message_id':     wa_message_id or False,
            'request_id':        request_id or False,
            'direction':         'outbound',
            'initiator':         initiator,
            'kind':              kind,
            'template_name':     template_name,
            'workflow_slug':     workflow_slug,
            'step_id':           step_id,
            'enrollment_id':     enrollment_id,
            'lead_id':           lead.id if lead else False,
            'segment_id':        seg.id if seg else False,
            'platform_actor_id': actor_id or 0,
            'status':            status,
            'status_updated_at': fields.Datetime.now(),
            'occurred_at':       occurred_at,
        }
        if event.get('rendered_body'):
            create_vals['template_body'] = event['rendered_body']
        if event.get('rendered_header'):
            create_vals['template_header'] = event['rendered_header']
        if event.get('header_media_url'):
            create_vals['template_header_media_url'] = event['header_media_url']
            create_vals['template_header_media_type'] = event.get('header_media_type') or False
        if event.get('template_footer'):
            create_vals['template_footer'] = event['template_footer']
        if event.get('template_buttons'):
            create_vals['template_buttons'] = event['template_buttons']
        create_vals.update(extra_vals or {})
        msg = self.env['wa.message'].sudo().create(create_vals)
        conv.sudo().write({'last_message_at': occurred_at})
        return msg

    def _handle_odoo_message_sent(self, event: dict, pubsub_message_id: str) -> None:
        """Handle message_sent — outbound message accepted by Interakt.

        If a ``wa.message`` already exists for this ``request_id`` (created by
        :meth:`send_message` when the RM initiated the send), update it.
        Otherwise create a new record (workflow-initiated send).
        """
        wa_message_id  = event.get('wa_message_id') or ''
        request_id     = event.get('request_id') or ''
        step_id        = event.get('step_id') or False
        enrollment_id  = event.get('enrollment_id') or False

        msg = self._owa_find_message(
            wa_message_id=wa_message_id,
            request_id=request_id,
            enrollment_id=enrollment_id,
            step_id=step_id,
        )
        if msg:
            # RM-initiated send: update the queued record created by send_message().
            # Never move status backwards — a redelivered message_sent must not
            # downgrade a row already marked delivered/read.
            vals = {
                'wa_message_id':   wa_message_id or msg.wa_message_id,
                'status':          _max_status(msg.status, 'sent'),
                'status_updated_at': fields.Datetime.now(),
            }
            # Backfill workflow context onto a row that was created ahead of this
            # event (an out-of-order delivered/read stub, which carries the
            # enrollment/step but not the slug/template).  Only fill blanks, and
            # only from values the event actually supplies — for RM sends the
            # event has no workflow_slug, so these stay empty.
            workflow_slug = event.get('workflow_slug')
            template_name = event.get('template_name')
            if workflow_slug and not msg.workflow_slug:
                vals['workflow_slug'] = workflow_slug
                vals['initiator'] = 'workflow'
            if template_name and not msg.template_name:
                # ``kind`` is immutable; the stub already inferred 'template' from
                # the delivered event's rendered content, so only the name is
                # backfilled here.
                vals['template_name'] = template_name
            vals.update(self._owa_template_content_vals(event, msg))
            msg.write(vals)
        else:
            # Workflow-initiated send: Odoo never created a wa.message for this.
            # (A workflow send carries the true inquiry as actor_id → lead, so the
            # stub helper opens/activates that inquiry's segment.)
            self._owa_create_outbound_stub(event, status='sent')

    def _handle_odoo_message_delivered(
        self, event: dict, pubsub_message_id: str
    ) -> None:
        """Handle message_delivered — update status and record delivery cost."""
        wa_message_id = event.get('wa_message_id') or ''
        request_id    = event.get('request_id') or ''
        enrollment_id = event.get('enrollment_id') or ''
        step_id       = event.get('step_id') or ''
        cost_inr      = event.get('cost_inr') or 0.0
        occurred_at   = _parse_iso_dt(event.get('occurred_at', ''))
        cost_vals     = {
            'cost_inr':             cost_inr,
            'cost_whatsapp_inr':    event.get('cost_whatsapp_inr') or 0.0,
            'cost_interakt_markup': event.get('cost_interakt_markup') or 0.0,
        }

        msg = self._owa_find_message(
            wa_message_id=wa_message_id,
            request_id=request_id,
            enrollment_id=enrollment_id,
            step_id=step_id,
        )
        if msg:
            # delivered_at/cost are always recorded, but status only advances —
            # a late/redelivered delivered event must not knock a read row back.
            vals = {
                'status':          _max_status(msg.status, 'delivered'),
                'delivered_at':    occurred_at,
                'status_updated_at': fields.Datetime.now(),
                **cost_vals,
            }
            vals.update(self._owa_template_content_vals(event, msg))
            msg.write(vals)
        elif enrollment_id or step_id:
            # Out-of-order: the delivered receipt beat message_sent for a
            # WORKFLOW send (which has no request_id-keyed queued row).  Create
            # the row now carrying delivered+cost so nothing is lost; a later
            # message_sent finds it by wa_message_id and only enriches it.
            # RM-manual sends are deliberately excluded (they own a queued row
            # keyed by request_id that this event cannot match → would duplicate).
            self._owa_create_outbound_stub(
                event, status='delivered',
                extra_vals={'delivered_at': occurred_at, **cost_vals},
            )
        else:
            _logger.warning(
                "wa_push: message_delivered — no wa.message found and no "
                "enrollment/step to safely create one; receipt dropped "
                "(wa_message_id=%r request_id=%r)",
                wa_message_id, request_id,
            )

    def _handle_odoo_message_read(self, event: dict, pubsub_message_id: str) -> None:
        """Handle message_read — update status to read."""
        wa_message_id = event.get('wa_message_id') or ''
        request_id    = event.get('request_id') or ''
        enrollment_id = event.get('enrollment_id') or ''
        step_id       = event.get('step_id') or ''
        occurred_at   = _parse_iso_dt(event.get('occurred_at', ''))

        msg = self._owa_find_message(
            wa_message_id=wa_message_id,
            request_id=request_id,
            enrollment_id=enrollment_id,
            step_id=step_id,
        )
        if msg:
            # seen_at is always recorded; status advances to read (and stays there
            # even if an out-of-order delivered event follows).
            vals = {
                'status':          _max_status(msg.status, 'read'),
                'seen_at':         occurred_at,
                'status_updated_at': fields.Datetime.now(),
            }
            # Fallback: if delivered was missed, the read event may carry cost —
            # fill only what the message is still missing (never overwrite).
            if not msg.cost_inr and event.get('cost_inr'):
                vals.update({
                    'cost_inr':             event.get('cost_inr') or 0.0,
                    'cost_whatsapp_inr':    event.get('cost_whatsapp_inr') or 0.0,
                    'cost_interakt_markup': event.get('cost_interakt_markup') or 0.0,
                })
            vals.update(self._owa_template_content_vals(event, msg))
            msg.write(vals)
        elif enrollment_id or step_id:
            # Out-of-order read receipt for a workflow send — see the delivered
            # handler for why RM-manual sends are excluded.  Carry any cost the
            # read event brought so the stub isn't created cost-less.
            extra = {'seen_at': occurred_at}
            if event.get('cost_inr'):
                extra.update({
                    'cost_inr':             event.get('cost_inr') or 0.0,
                    'cost_whatsapp_inr':    event.get('cost_whatsapp_inr') or 0.0,
                    'cost_interakt_markup': event.get('cost_interakt_markup') or 0.0,
                })
            self._owa_create_outbound_stub(event, status='read', extra_vals=extra)
        else:
            _logger.warning(
                "wa_push: message_read — no wa.message found and no "
                "enrollment/step to safely create one; receipt dropped "
                "(wa_message_id=%r request_id=%r)",
                wa_message_id, request_id,
            )

    def _handle_odoo_message_failed(self, event: dict, pubsub_message_id: str) -> None:
        """Handle message_failed — update status using the Interakt error code."""
        wa_message_id  = event.get('wa_message_id') or ''
        request_id     = event.get('request_id') or ''
        failure_code   = event.get('failure_code')
        failure_reason = event.get('failure_reason') or ''
        new_status     = self._owa_failure_status(failure_code)

        msg = self._owa_find_message(wa_message_id=wa_message_id, request_id=request_id)
        if msg:
            msg.write({
                'status':          new_status,
                'status_updated_at': fields.Datetime.now(),
                # Persist the descriptive failure detail so the dashboard shows
                # the real reason instead of just the status label.
                'failure_code':    str(failure_code) if failure_code is not None else msg.failure_code,
                'failure_reason':  failure_reason or msg.failure_reason,
            })
            _logger.info(
                "wa_push: message_failed — wa_message_id=%r code=%s reason=%r status→%s",
                wa_message_id, failure_code, failure_reason, new_status,
            )
        else:
            _logger.warning(
                "wa_push: message_failed — no wa.message found for "
                "wa_message_id=%r request_id=%r",
                wa_message_id, request_id,
            )

    def _handle_odoo_lead_replied(self, event: dict, pubsub_message_id: str) -> None:
        """Handle lead_replied — buyer sent a message; create wa.message + notify RM.

        Reads as a sequence: dedup → resolve conv/lead → lock → resolve the quoted
        context → drop companion duplicates → attribute a segment → persist the
        message → refresh the conversation → self-heal ownership → notify.  Each
        step's mechanics live in a named ``_owa_*`` helper below.
        """
        phone           = event.get('phone', '')
        wa_message_id   = event.get('wa_message_id') or ''
        actor_id        = event.get('actor_id')
        actor_type      = event.get('actor_type', '')
        rm_odoo_id      = event.get('rm_odoo_id')
        message_text    = event.get('message_text') or ''
        button_reply_id = event.get('button_reply_id')
        template_replied_to = (
            event.get('source_template_name', '')
            or event.get('template_name', '')
            or event.get('original_template_name', '')
        )
        occurred_at     = _parse_iso_dt(event.get('occurred_at', ''))
        # Media fields forwarded from the WA platform
        media_url       = event.get('media_url') or False
        media_filename  = event.get('media_filename') or False
        # Map Interakt message_content_type → Odoo kind.  A known type maps to
        # its real kind; an UNRECOGNISED type (new Interakt content type) is
        # stored as 'unknown' — never mislabelled as a text reply.  Only when
        # the platform sent no message_kind at all (older events) do we fall
        # back to the button/text heuristic.
        interakt_kind   = event.get('message_kind') or ''
        if interakt_kind:
            kind = _INTERAKT_KIND_TO_ODOO.get(interakt_kind, 'unknown')
            if kind == 'unknown':
                _logger.warning(
                    "wa_push: lead_replied — unmapped Interakt message_content_type=%r "
                    "stored as kind='unknown' (phone=%s wa_message_id=%s)",
                    interakt_kind, phone, wa_message_id,
                )
        else:
            kind = 'button_reply' if button_reply_id else 'text_reply'

        # Deduplicate by wa_message_id, with the button/CTA-collision twist.
        store_wa_message_id, quoted_src_from_collision, is_duplicate = (
            self._owa_resolve_inbound_dedup(wa_message_id, button_reply_id, message_text)
        )
        if is_duplicate:
            return

        conv = self._owa_get_conversation(phone)
        lead = self._owa_resolve_lead(actor_id, actor_type, phone)

        # Prefer event-supplied rm_odoo_id; fall back to the RM already assigned
        # on the lead so that existing assignments are honoured without re-assigning.
        if not rm_odoo_id and lead and lead.user_id:
            rm_odoo_id = lead.user_id.id

        # Lock the conversation row BEFORE creating wa.message.  The FK
        # insert acquires FOR KEY SHARE on wa_conversation; if we also need
        # FOR UPDATE afterwards (to write last_message_at), both workers end
        # up holding KEY SHARE while waiting for the other's upgrade →
        # deadlock.  Locking first avoids that upgrade path entirely.
        self.env.cr.execute(
            'SELECT id FROM wa_conversation WHERE id = %s FOR UPDATE',
            (conv.id,)
        )
        conv.invalidate_recordset()

        # For media messages, caption may arrive as literal "None" from Interakt.
        body = message_text if message_text != 'None' else ''
        # Location / contact payloads arrive as a JSON blob in the body — detect
        # by shape and replace the blob with human-readable text (and, for a
        # location, a Maps link stored in media_url) so the bubble isn't raw JSON.
        special = _parse_special_inbound(body)
        if special:
            kind, body, special_url = special
            if special_url and not media_url:
                media_url = special_url
        # Resolve the quoted/swipe context so the bubble can show what the buyer
        # replied to (WhatsApp-style), matched to the referenced template.
        quoted_body, quoted_sender, quoted_src = self._owa_resolve_quoted_context(
            conv, template_replied_to, event,
        )
        # Fall back to the collision-detected template (button/CTA reply) when no
        # explicit message_context reference was supplied.
        if not quoted_src and quoted_src_from_collision:
            quoted_src = quoted_src_from_collision
            if not quoted_body:
                quoted_body = (
                    (quoted_src.template_body or '').strip()
                    or (quoted_src.body or '').strip()
                    or (quoted_src.template_header or '').strip()
                    or quoted_src.template_name
                    or ''
                )[:140] or False
                quoted_sender = quoted_sender or quoted_src.sender_name or 'You'

        # Skip the button-tap "companion" duplicate — an existing reply with the
        # same (quoted source, body) but the COMPLEMENTARY kind (button vs text).
        if self._owa_is_companion_duplicate(conv, quoted_src, body, kind):
            return

        inbound_seg = self._owa_attribute_inbound_segment(conv, quoted_src, lead)

        self.env['wa.message'].sudo().create({
            'conversation_id':   conv.id,
            'wa_message_id':     store_wa_message_id or False,
            'direction':         'inbound',
            'initiator':         'buyer',
            'kind':              kind,
            'body':              body,
            'media_url':         media_url,
            'media_filename':    media_filename,
            'template_replied_to': template_replied_to or False,
            'quoted_body':       quoted_body or False,
            'quoted_sender':     quoted_sender or False,
            'quoted_message_id': quoted_src.id if quoted_src else False,
            'lead_id':           lead.id if lead else False,
            'segment_id':        inbound_seg.id if inbound_seg else False,
            'platform_actor_id': actor_id or 0,
            'status':            'delivered',
            'occurred_at':       occurred_at,
        })

        window_expires_at = self._owa_inbound_window_expiry(event, occurred_at)
        conv_vals = {'unread_count': conv.unread_count + 1}
        # Derive the inbox tail (preview + timestamp) from the ACTUAL latest
        # message, not the one we just processed.  Webhooks can arrive out of
        # order (or within the same second), so blindly writing this message's
        # body would let an older message clobber a newer one in the list.
        last_at, preview = self._owa_conversation_tail(conv)
        conv_vals['last_message_at'] = last_at
        conv_vals['last_message_preview'] = preview
        if window_expires_at:
            conv_vals['window_expires_at'] = window_expires_at
        if lead and not conv.lead_id:
            conv_vals['lead_id'] = lead.id
        conv.sudo().write(conv_vals)

        # Self-heal: if this is a migrated lead messaging first and nobody owns the
        # chat yet, hand it to the lead's RM (establishes ownership on both sides).
        self._owa_autoassign_to_lead_rm(conv, lead)

        # Notify the chat owner, or fan out to managers when nobody owns it.
        self._owa_notify_reply(conv, lead, phone, rm_odoo_id, actor_id, message_text)

    def _owa_conversation_tail(self, conv):
        """Return ``(last_message_at, preview)`` from the conversation's latest
        non-system message (either direction), ordered by ``occurred_at`` then
        ``id`` so ties and out-of-order deliveries resolve the same way the thread
        renders them.  Falls back to the current stored values when empty."""
        latest = self.env['wa.message'].sudo().search(
            [('conversation_id', '=', conv.id), ('kind', '!=', 'system')],
            order='occurred_at desc, id desc', limit=1,
        )
        if not latest:
            return conv.last_message_at, conv.last_message_preview or ''
        # Prefer the plain body; fall back to rendered/template text so an
        # outbound template (empty body until enriched) still previews sensibly.
        preview = (
            latest.body
            or latest.template_body
            or latest.template_name
            or ''
        )
        return latest.occurred_at, preview[:100]

    def _owa_resolve_inbound_dedup(self, wa_message_id, button_reply_id, message_text):
        """Resolve the storage id and button-collision source for an inbound reply.

        Returns ``(store_wa_message_id, collision_src, is_duplicate)``.  When
        ``is_duplicate`` is True the caller must drop the event.

        A quick-reply tap reuses the TEMPLATE's outbound Interakt id as the
        reply's message id (the gateway sets it for click→template correlation).
        Naively deduping on that id finds the OUTBOUND template row and silently
        drops EVERY button reply (and makes a second, different-button tap look
        like a duplicate of the first).  Detect that case: when the id only
        matches an OUTBOUND message, that message IS the one being replied to —
        store the reply under a distinct id derived from the button so each tap
        is recorded, and return it as the quoted original (``collision_src``).
        """
        store_wa_message_id = wa_message_id
        collision_src = None
        if not wa_message_id:
            return store_wa_message_id, collision_src, False

        existing = self._owa_find_message(wa_message_id=wa_message_id)
        if existing and existing.direction == 'inbound':
            _logger.debug("wa_push: lead_replied duplicate wa_message_id=%s", wa_message_id)
            return store_wa_message_id, collision_src, True
        if existing and existing.direction == 'outbound':
            collision_src = existing
            suffix = (button_reply_id or message_text or 'reply').strip().replace(' ', '_')[:40]
            store_wa_message_id = f"{wa_message_id}:r:{suffix}"
            # Re-dedup on the synthetic id so Pub/Sub redelivery of the same
            # tap doesn't create a second row.
            if self._owa_find_message(wa_message_id=store_wa_message_id):
                _logger.debug(
                    "wa_push: lead_replied duplicate synthetic id=%s", store_wa_message_id
                )
                return store_wa_message_id, collision_src, True
        return store_wa_message_id, collision_src, False

    def _owa_is_companion_duplicate(self, conv, quoted_src, body, kind) -> bool:
        """True when *this* inbound reply is the button-tap "companion" of an
        already-recorded reply — and must be dropped as a duplicate bubble.

        A quick-reply tap emits TWO inbound events from Interakt: the button
        CLICK (whose id is the template's outbound id → ``kind='button_reply'``)
        and a companion ``message_received`` TEXT (its own id, same
        message_context → ``kind='text_reply'``).  The platform's click-shadow is
        meant to collapse them but is time-windowed (~4s) and can miss on a
        redelivery / out-of-order batch, so BOTH reach us with different
        wa_message_ids → the id-based dedup can't catch it → two identical
        bubbles.

        The two halves of a real pair share the same (quoted source, body) but
        are of **complementary kinds** — exactly one button_reply and one
        text_reply.  That is the reliable, time- AND order-independent signature
        of a companion: drop the incoming reply only when an existing inbound
        with the same (quoted source, body) but the *opposite* kind is present.
        Whichever half arrives first is recorded; the second finds its complement
        and is dropped — so it holds regardless of which Interakt delivers first.

        Because the match is scoped by *body*, distinct buttons on one template
        (different labels) never cross-collapse: tapping A, B and C yields three
        bubbles no matter how their six webhooks interleave.  And because it
        requires the *opposite* kind, two messages of the SAME kind are never a
        pair — two genuine swipe text-replies ("Hi", "Hi") to the same message
        are both text_reply and both shown.  (The previous version keyed on
        (quoted source, body) alone, so a repeated identical swipe-reply — a real
        buyer message — was silently dropped.)  Runs under the conversation's
        FOR UPDATE lock (held by the caller), so concurrent deliveries serialize.
        """
        if not quoted_src:
            return False
        # The kind that, if already present for the same (quoted source, body),
        # makes THIS reply the second half of a companion pair.
        companion_kind = {
            'button_reply': 'text_reply',
            'text_reply': 'button_reply',
        }.get(kind)
        if not companion_kind:
            return False
        twin = self.env['wa.message'].sudo().search([
            ('conversation_id', '=', conv.id),
            ('direction', '=', 'inbound'),
            ('quoted_message_id', '=', quoted_src.id),
            ('body', '=', body),
            ('kind', '=', companion_kind),
        ], limit=1)
        if twin:
            _logger.info(
                "wa_push: lead_replied companion duplicate skipped "
                "(conv=%s quoted=%s body=%r kind=%s existing=%s existing_kind=%s)",
                conv.id, quoted_src.id, body[:40], kind, twin.id, companion_kind,
            )
            return True
        return False

    def _owa_attribute_inbound_segment(self, conv, quoted_src, lead):
        """Resolve the inquiry segment an inbound reply files into (flag-gated).

        Dormant (returns ``False``) when segments are off.  Otherwise:
          * a reply that QUOTES a prior message is a deterministic signal — file
            it under THAT message's inquiry, even when the quoted message predates
            segments (use its ``lead_id``) or belongs to another property.  This
            does NOT flip the RM's active context (``activate=False``) — switching
            is a separate, RM-driven action;
          * a plain reply inherits the conversation's active segment;
          * with no segment yet, bootstrap one for the resolved inquiry.
        """
        if not conv._owa_segments_enabled():
            return False
        if quoted_src and quoted_src.segment_id:
            return quoted_src.segment_id
        if quoted_src and quoted_src.lead_id:
            return conv._owa_ensure_segment(
                inquiry=quoted_src.lead_id, started_by='auto_suggested', activate=False)
        if conv.active_segment_id:
            return conv.active_segment_id
        return conv._owa_ensure_segment(inquiry=lead, started_by='system')

    @staticmethod
    def _owa_inbound_window_expiry(event, occurred_at):
        """Window expiry for an inbound reply: the platform value when supplied,
        else ``occurred_at + 24h`` (``None`` when neither is available)."""
        raw = event.get('window_expires_at')
        if raw:
            try:
                return _parse_iso_dt(raw)
            except Exception:
                return None
        return occurred_at + timedelta(hours=24) if occurred_at else None

    def _owa_notify_reply(self, conv, lead, phone, rm_odoo_id, actor_id, message_text):
        """Notify the chat's owner of an inbound reply (persistent + live).

        Routes to the assigned RM if the chat is assigned, else the lead's routed
        RM as a fallback.  When nobody owns it (unknown number, or a lead with no
        RM), fan out to WhatsApp managers so the message isn't silently stranded.
        """
        recipient_id = self._owa_chat_recipient(conv, rm_odoo_id)
        if not recipient_id:
            self._owa_notify_unrouted(conv, lead, phone, message_text)
            return
        lead_label = self._owa_lead_label(lead, phone)
        self._push_user_notification(
            recipient_id, 'lead_replied',
            title='%s replied on WhatsApp' % lead_label,
            # Keep the actual reply text in the body so the RM can judge
            # urgency at a glance without opening the lead.
            body=(message_text[:160] if message_text else 'New WhatsApp reply'),
            payload={
                'actor_id':  actor_id,
                'lead_id':   lead.id if lead else None,
                'lead_name': lead.name if lead else '',
                'phone':     phone,
                'suppress_key': phone,
            },
        )

    def _handle_odoo_ambiguous_reply(
        self, event: dict, pubsub_message_id: str
    ) -> None:
        """Handle ambiguous_reply — reply unroutable; create wa.message + notify RM."""
        phone          = event.get('phone', '')
        wa_message_id  = event.get('wa_message_id') or ''
        actor_id       = event.get('actor_id')
        actor_type     = event.get('actor_type', '')
        rm_odoo_id     = event.get('rm_odoo_id')
        message_text   = event.get('message_text') or ''
        occurred_at    = _parse_iso_dt(event.get('occurred_at', ''))

        if wa_message_id and self._owa_find_message(wa_message_id=wa_message_id):
            return

        conv = self._owa_get_conversation(phone)
        lead = self._owa_resolve_lead(actor_id, actor_type, phone)

        # Lock BEFORE create — same deadlock prevention as _handle_odoo_lead_replied.
        self.env.cr.execute(
            'SELECT id FROM wa_conversation WHERE id = %s FOR UPDATE',
            (conv.id,)
        )
        conv.invalidate_recordset()

        self.env['wa.message'].sudo().create({
            'conversation_id':   conv.id,
            'wa_message_id':     wa_message_id or False,
            'direction':         'inbound',
            'initiator':         'buyer',
            'kind':              'text_reply',
            'body':              message_text,
            'lead_id':           lead.id if lead else False,
            'platform_actor_id': actor_id or 0,
            'status':            'delivered',
            'occurred_at':       occurred_at,
        })

        conv.sudo().write({'last_message_at': occurred_at, 'unread_count': conv.unread_count + 1})

        # Self-heal ownership for a migrated lead messaging first (no-op if owned).
        self._owa_autoassign_to_lead_rm(conv, lead)

        # Notify the chat's owner (assigned RM, else routed RM fallback).
        recipient_id = self._owa_chat_recipient(conv, rm_odoo_id)
        if recipient_id:
            lead_label = self._owa_lead_label(lead, phone)
            self._push_user_notification(
                recipient_id, 'ambiguous_reply',
                title='%s sent a message that needs review' % lead_label,
                # Show the actual text so the RM can judge urgency at a glance.
                body=(message_text[:160] if message_text
                      else 'Unroutable WhatsApp reply — open the chat to review.'),
                payload={
                    'actor_id':  actor_id,
                    'lead_id':   lead.id if lead else None,
                    'lead_name': lead.name if lead else '',
                    'phone':     phone,
                    'suppress_key': phone,
                },
            )
        else:
            # No RM to route to — surface to managers for triage.
            self._owa_notify_unrouted(conv, lead, phone, message_text)

    def _handle_odoo_permanent_failure(
        self, event: dict, pubsub_message_id: str
    ) -> None:
        """Handle permanent_failure and retry_exhausted — update status + notify RM."""
        wa_message_id  = event.get('wa_message_id') or ''
        request_id     = event.get('request_id') or ''
        actor_id       = event.get('actor_id')
        actor_type     = event.get('actor_type', '')
        rm_odoo_id     = event.get('rm_odoo_id')
        failure_code   = event.get('failure_code')
        failure_reason = event.get('failure_reason') or 'Send failed'
        phone          = event.get('phone', '')
        event_type     = event.get('event_type', '')
        new_status     = self._owa_failure_status(failure_code)

        msg = self._owa_find_message(wa_message_id=wa_message_id, request_id=request_id)
        if msg:
            msg.write({
                'status': new_status,
                'status_updated_at': fields.Datetime.now(),
                'failure_code':   str(failure_code) if failure_code is not None else msg.failure_code,
                'failure_reason': failure_reason or msg.failure_reason,
            })

        lead = self._owa_resolve_lead(actor_id, actor_type, phone)

        # The failed send belongs to the chat's owner. Derive the conversation
        # from the message (or by phone) so an assigned chat notifies the
        # assignee rather than the lead's routed RM.
        conv = msg.conversation_id if msg else self._owa_get_conversation(phone)
        recipient_id = self._owa_chat_recipient(conv, rm_odoo_id)

        # Central notification to the RM (persistent + live popup).
        if recipient_id:
            lead_label = self._owa_lead_label(lead, phone)
            detail = (failure_reason or 'the message could not be sent').strip()
            body = ('Your WhatsApp message to %s couldn\'t be delivered (%s). '
                    'Reach out another way so the conversation isn\'t dropped.'
                    % (lead_label, detail))
            self._push_user_notification(
                recipient_id, 'permanent_failure',
                title='Your message to %s didn\'t go through' % lead_label,
                body=body[:200],
                payload={
                    'actor_id':  actor_id,
                    'lead_id':   lead.id if lead else None,
                    'lead_name': lead.name if lead else '',
                    'phone':     phone,
                    'suppress_key': phone,
                },
            )

    def _handle_odoo_enrollment_created(
        self, event: dict, pubsub_message_id: str
    ) -> None:
        """Handle enrollment_created — system pill + wa.enrollment record."""
        phone         = event.get('phone', '')
        actor_id      = event.get('actor_id')
        actor_type    = event.get('actor_type', '')
        workflow_slug = event.get('workflow_slug') or ''
        enrollment_id = event.get('enrollment_id') or ''
        occurred_at   = _parse_iso_dt(event.get('occurred_at', ''))

        # Idempotency guard — Pub/Sub delivers at-least-once; skip if a system
        # pill for this enrollment_id already exists (duplicate delivery or push
        # subscription misconfiguration).
        if enrollment_id and self.env['wa.message'].sudo().search(
            [('enrollment_id', '=', enrollment_id), ('kind', '=', 'system')],
            limit=1,
        ):
            _logger.info(
                "wa_push: enrollment_created duplicate skipped enrollment_id=%s message=%s",
                enrollment_id, pubsub_message_id,
            )
            return

        conv = self._owa_get_conversation(phone)
        self.env.cr.execute(
            'SELECT id FROM wa_conversation WHERE id = %s FOR UPDATE',
            (conv.id,)
        )

        lead = self._owa_resolve_lead(actor_id, actor_type, phone)

        self.env['wa.message'].sudo().create({
            'conversation_id': conv.id,
            'direction':       'outbound',
            'initiator':       'system',
            'kind':            'system',
            'body':            f'Enrolled in workflow: {workflow_slug}',
            'workflow_slug':   workflow_slug or False,
            'enrollment_id':   enrollment_id or False,
            'lead_id':         lead.id if lead else False,
            'platform_actor_id': actor_id or 0,
            'status':          'enrolled',
            'occurred_at':     occurred_at,
        })

        # Track enrollment lifecycle for the Active Enrollments KPI.
        if enrollment_id:
            self.env['wa.enrollment'].sudo()._get_or_create(
                enrollment_id=enrollment_id,
                workflow_slug=workflow_slug,
                lead=lead,
                phone=phone,
                platform_actor_id=actor_id or 0,
                started_at=occurred_at,
            )

    def _handle_odoo_enrollment_completed(
        self, event: dict, pubsub_message_id: str
    ) -> None:
        """Handle enrollment_completed — system pill + mark wa.enrollment complete."""
        phone         = event.get('phone', '')
        actor_id      = event.get('actor_id')
        actor_type    = event.get('actor_type', '')
        workflow_slug = event.get('workflow_slug') or ''
        enrollment_id = event.get('enrollment_id') or ''
        occurred_at   = _parse_iso_dt(event.get('occurred_at', ''))

        # Idempotency guard — skip if a 'completed' system pill already exists.
        if enrollment_id and self.env['wa.message'].sudo().search(
            [
                ('enrollment_id', '=', enrollment_id),
                ('kind', '=', 'system'),
                ('body', 'like', 'Workflow completed:'),
            ],
            limit=1,
        ):
            _logger.info(
                "wa_push: enrollment_completed duplicate skipped enrollment_id=%s message=%s",
                enrollment_id, pubsub_message_id,
            )
            return

        conv = self._owa_get_conversation(phone)
        lead = self._owa_resolve_lead(actor_id, actor_type, phone)

        self.env['wa.message'].sudo().create({
            'conversation_id': conv.id,
            'direction':       'outbound',
            'initiator':       'system',
            'kind':            'system',
            'body':            f'Workflow completed: {workflow_slug}',
            'workflow_slug':   workflow_slug or False,
            'enrollment_id':   enrollment_id or False,
            'lead_id':         lead.id if lead else False,
            'platform_actor_id': actor_id or 0,
            'status':          'enrollment_completed',
            'occurred_at':     occurred_at,
        })

        # Mark enrollment as completed so it drops from the Active Enrollments count.
        if enrollment_id:
            enroll = self.env['wa.enrollment'].sudo().search(
                [('enrollment_id', '=', enrollment_id)], limit=1
            )
            if enroll:
                enroll.write({'state': 'completed', 'completed_at': occurred_at})

    def _handle_odoo_enrollment_step_changed(
        self, event: dict, pubsub_message_id: str
    ) -> None:
        """Handle enrollment_step_changed — no state change needed, debug log only.

        Step transitions are high-frequency and do not change the enrollment
        lifecycle state (active → completed).  Logged at DEBUG level only.
        """
        _logger.debug(
            "wa_push: enrollment_step_changed — enrollment_id=%r step_id=%r",
            event.get('enrollment_id'), event.get('step_id'),
        )

    def _handle_workflow_registry_synced(
        self, event: dict, pubsub_message_id: str
    ) -> None:
        """Handle workflow.registry.synced — upsert the wa.workflow registry.

        Delegates to :meth:`wa.workflow._process_registry_sync_event`.
        """
        self.env['wa.workflow'].sudo()._process_registry_sync_event(
            event, pubsub_message_id
        )

    def _handle_workflow_synced(
        self, event: dict, pubsub_message_id: str
    ) -> None:
        """Handle workflow.synced — WA platform ACK after applying a toggle.

        Published by the odoo-bridge service on the ``wa-workflow-sync`` topic
        after it processes a ``workflow.toggled`` control event.  Delegates to
        :meth:`wa.workflow._process_workflow_synced_event`.
        """
        self.env['wa.workflow'].sudo()._process_workflow_synced_event(
            event, pubsub_message_id
        )
