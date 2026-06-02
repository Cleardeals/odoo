"""wa.message.log — server-side analytics model for the Message Log client action.

No database table (_auto = False).  All public methods accept plain Python
arguments and return JSON-serialisable dicts that the OWL component consumes
via orm.call().

Usage from OWL::

    const { rows, totals } = await this.orm.call(
        'wa.message.log', 'get_messages', [],
        {
            date_from: '2026-05-01',
            date_to:   '2026-05-02',
            direction: '',          // '' = all
            kind:      '',          // '' = all, 'button_reply', 'template', etc.
            search:    '',          // free-text: phone or lead name
            workflow:  '',          // workflow slug or ''
            template:  '',          // template name or ''
            limit:     100,
            offset:    0,
        }
    );
"""

import logging
from datetime import datetime, timezone

import pytz

from odoo import api, fields, models

_logger = logging.getLogger(__name__)
_IST = pytz.timezone('Asia/Kolkata')

_FAILED_STATUSES = [
    'failed', 'meta_blocked', 'invalid_number',
    'opted_out', 'rate_limited', 'template_error', 'expired',
]

# Maps kind values to the "Type" label shown in the UI
_KIND_LABEL = {
    'template':     'Template',
    'freetext':     'Free Text',
    'button_reply': 'CTA Reply',
    'text_reply':   'Text',
    'image':        'Image',
    'document':     'Document',
    'video':        'Video',
    'audio':        'Audio',
    'system':       'System',
    'unknown':      'Unknown',
}

# Maps status to a badge colour hint used by the frontend
_STATUS_COLOR = {
    'queued':         'warning',
    'sent':           'warning',
    'delivered':      'success',
    'read':           'info',
    'failed':         'danger',
    'meta_blocked':   'danger',
    'invalid_number': 'danger',
    'opted_out':      'danger',
    'rate_limited':   'danger',
    'template_error': 'danger',
    'skipped':        'secondary',
    'expired':        'secondary',
}


class WaMessageLog(models.Model):
    """Read-only analytics model for the Message Log client action.

    All methods are @api.model — they take plain keyword arguments and return
    JSON-serialisable structures.  No database table.
    """

    _name = 'wa.message.log'
    _description = 'WA Message Log Analytics'
    _auto = False   # no database table

    # ──────────────────────────────────────────────────────────────────────
    # Public RPC methods
    # ──────────────────────────────────────────────────────────────────────

    @api.model
    def get_messages(
        self,
        date_from: str = '',
        date_to: str = '',
        direction: str = '',
        kind: str = '',
        search: str = '',
        workflow: str = '',
        template: str = '',
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """Return a page of messages and summary totals for the Message Log UI.

        :returns: {
            'rows':   list of row dicts,
            'total':  total matching record count,
            'totals': summary stat dict,
        }
        """
        domain = self._build_domain(
            date_from=date_from,
            date_to=date_to,
            direction=direction,
            kind=kind,
            search=search,
            workflow=workflow,
            template=template,
        )

        WaMsg = self.env['wa.message']
        total = WaMsg.search_count(domain)
        records = WaMsg.search(
            domain,
            limit=limit,
            offset=offset,
            order='occurred_at desc, id desc',
        )

        rows = [self._format_row(r) for r in records]
        totals = self._compute_totals(domain)

        return {'rows': rows, 'total': total, 'totals': totals}

    @api.model
    def get_message_detail(self, message_id: int) -> dict:
        """Return the full detail dict for a single wa.message row.

        Used by the expandable row panel in the Message Log.
        """
        msg = self.env['wa.message'].browse(message_id)
        if not msg.exists():
            return {}
        return self._format_detail(msg)

    @api.model
    def get_webhook_events(
        self,
        date_from: str = '',
        date_to: str = '',
        search: str = '',
        event_type_filter: str = '',
        limit: int = 200,
        offset: int = 0,
    ) -> dict:
        """Return raw webhook events for the Webhook Log developer panel.

        Reads from wa.event.log (immutable audit table) and joins wa.message
        for the lead name / phone when available.

        :returns: { 'rows': list, 'total': int }
        """
        domain = self._build_event_log_domain(
            date_from=date_from,
            date_to=date_to,
            search=search,
            event_type_filter=event_type_filter,
        )
        EventLog = self.env['wa.event.log']
        total = EventLog.search_count(domain)
        records = EventLog.search(domain, limit=limit, offset=offset,
                                  order='create_date desc')

        rows = []
        for r in records:
            rows.append({
                'id':                 r.id,
                'event_type':         r.event_type or '',
                'direction':          r.direction or '',
                'topic':              r.topic or '',
                'pubsub_message_id':  r.pubsub_message_id or '',
                'status':             r.status or '',
                'error_message':      r.error_message or '',
                'payload':            r.payload or '',
                'create_date':        self._fmt_dt(r.create_date),
            })

        return {'rows': rows, 'total': total}

    @api.model
    def get_workflows(self) -> list:
        """Return distinct workflow slugs for the Workflow filter dropdown."""
        self.env.cr.execute(
            "SELECT DISTINCT workflow_slug FROM wa_message "
            "WHERE workflow_slug IS NOT NULL AND workflow_slug != '' "
            "ORDER BY workflow_slug LIMIT 100"
        )
        return [row[0] for row in self.env.cr.fetchall()]

    @api.model
    def get_templates(self) -> list:
        """Return distinct template names for the Template filter dropdown."""
        self.env.cr.execute(
            "SELECT DISTINCT template_name FROM wa_message "
            "WHERE template_name IS NOT NULL AND template_name != '' "
            "ORDER BY template_name LIMIT 100"
        )
        return [row[0] for row in self.env.cr.fetchall()]

    # ──────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────

    def _build_domain(
        self,
        date_from: str,
        date_to: str,
        direction: str,
        kind: str,
        search: str,
        workflow: str,
        template: str,
    ) -> list:
        domain = []

        if date_from:
            domain.append(('occurred_at', '>=', self._parse_date(date_from)))
        if date_to:
            domain.append(('occurred_at', '<=', self._parse_date(date_to, end=True)))
        if direction:
            domain.append(('direction', '=', direction))

        # kind filter: "cta" maps to button_reply; "failed" is a status group
        if kind == 'failed':
            domain.append(('status', 'in', _FAILED_STATUSES))
        elif kind:
            domain.append(('kind', '=', kind))

        if workflow:
            domain.append(('workflow_slug', '=', workflow))
        if template:
            domain.append(('template_name', '=', template))

        if search:
            domain += [
                '|',
                ('conversation_id.phone_number', 'ilike', search),
                ('lead_id.name', 'ilike', search),
            ]

        return domain

    def _build_event_log_domain(
        self,
        date_from: str,
        date_to: str,
        search: str,
        event_type_filter: str,
    ) -> list:
        domain = []
        if date_from:
            domain.append(('create_date', '>=', self._parse_date(date_from)))
        if date_to:
            domain.append(('create_date', '<=', self._parse_date(date_to, end=True)))
        if event_type_filter:
            domain.append(('event_type', '=', event_type_filter))
        if search:
            domain.append(('payload', 'ilike', search))
        return domain

    def _compute_totals(self, domain: list) -> dict:
        """Compute the summary stats bar values."""
        WaMsg = self.env['wa.message']
        total   = WaMsg.search_count(domain)
        inbound = WaMsg.search_count(domain + [('direction', '=', 'inbound')])
        cta     = WaMsg.search_count(domain + [('kind', '=', 'button_reply')])
        failed  = WaMsg.search_count(domain + [('status', 'in', _FAILED_STATUSES)])

        groups = WaMsg._read_group(
            domain=domain,
            groupby=[],
            aggregates=['cost_inr:sum'],
        )
        total_cost = 0.0
        if groups:
            try:
                total_cost = float(groups[0]['cost_inr:sum'] or 0.0)
            except (TypeError, KeyError, IndexError):
                total_cost = 0.0

        return {
            'total':      total,
            'inbound':    inbound,
            'cta':        cta,
            'failed':     failed,
            'total_cost': round(total_cost or 0.0, 2),
        }

    def _format_row(self, msg) -> dict:
        """Format a wa.message record for the message log table row."""
        lead = msg.lead_id
        conv = msg.conversation_id
        phone = conv.phone_number if conv else ''

        # Extract failure error code from raw_payload if available
        failure_code = ''
        failure_label = ''
        if msg.status in _FAILED_STATUSES:
            raw = msg.raw_payload or {}
            failure_code = str(raw.get('error_code', '') or raw.get('code', ''))
            failure_label = self._failure_label(msg.status, failure_code)

        # Workflow display: slug + step
        workflow_display = ''
        if msg.workflow_slug:
            workflow_display = msg.workflow_slug
            if msg.step_id:
                workflow_display += f'\n{msg.step_id}'

        return {
            'id':               msg.id,
            'direction':        msg.direction,
            'kind':             msg.kind,
            'kind_label':       _KIND_LABEL.get(msg.kind, msg.kind),
            'lead_id':          lead.id if lead else None,
            'lead_name':        lead.name if lead else '',
            'phone':            phone,
            'body':             (msg.body or '')[:120],            'media_url':        msg.media_url or '',            'template_name':    msg.template_name or '',
            'workflow_slug':    msg.workflow_slug or '',
            'workflow_display': workflow_display,
            'status':           msg.status,
            'status_color':     _STATUS_COLOR.get(msg.status, 'secondary'),
            'failure_label':    failure_label,
            'failure_code':     failure_code,
            'occurred_at':      self._fmt_dt(msg.occurred_at),
            'cost_inr':         msg.cost_inr or 0.0,
        }

    def _format_detail(self, msg) -> dict:
        """Format the full detail dict for the expanded row panel."""
        return {
            'id':                  msg.id,
            'wa_id':               f'WA-{msg.id}',
            'direction':           msg.direction,
            'kind':                msg.kind,
            'kind_label':          _KIND_LABEL.get(msg.kind, msg.kind),
            'received_at':         self._fmt_dt(msg.occurred_at),
            'delivered_at':        self._fmt_dt(msg.delivered_at),
            'seen_at':             self._fmt_dt(msg.seen_at),
            'button_text':         msg.body or '',
            'button_type':         msg.kind if msg.kind == 'button_reply' else '',
            'template_replied_to': msg.template_replied_to or msg.template_name or '',
            'media_url':           msg.media_url or '',
            'media_filename':      msg.media_filename or '',
            'whatsapp_cost':       f'\u20b9{msg.cost_inr:.4f}' if msg.cost_inr else '',
            'interakt_markup':     '',
            'actual_cost':         f'\u20b9{msg.cost_inr:.4f}' if msg.cost_inr else '',
            'workflow':            msg.workflow_slug or '',
            'step_id':             msg.step_id or '',
            'enrollment_id':       msg.enrollment_id or '',
            'raw_payload':         msg.raw_payload or {},
            'wa_message_id':       msg.wa_message_id or '',
            'request_id':          msg.request_id or '',
            'lead_id':             msg.lead_id.id if msg.lead_id else None,
            'lead_name':           (msg.lead_id.name
                                    if msg.lead_id else ''),
            'status':              msg.status,
        }

    @staticmethod
    def _failure_label(status: str, code: str) -> str:
        labels = {
            'meta_blocked':   'Meta Blocked',
            'invalid_number': 'Invalid Number',
            'opted_out':      'Opted Out',
            'rate_limited':   'Rate Limited',
            'template_error': 'Template Error',
            'expired':        'Expired',
            'failed':         'Failed',
        }
        label = labels.get(status, status)
        if code:
            label += f'\nerr: {code}'
        return label

    @staticmethod
    def _fmt_dt(dt) -> str:
        if not dt:
            return ''
        if isinstance(dt, datetime):
            # Convert naive UTC to IST (+5:30) for display
            utc_dt = dt.replace(tzinfo=timezone.utc)
            ist_dt = utc_dt.astimezone(_IST)
            return ist_dt.strftime('%d %b %H:%M')
        return str(dt)

    @staticmethod
    def _parse_date(value: str, end: bool = False) -> str:
        """Normalise a date/datetime string for domain comparison."""
        if not value:
            return ''
        value = value.strip()
        # If only a date (YYYY-MM-DD) append time
        if len(value) == 10:
            return f'{value} 23:59:59' if end else f'{value} 00:00:00'
        return value
