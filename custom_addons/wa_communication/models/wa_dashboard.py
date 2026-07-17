"""WA Dashboard — server-side analytics methods for the WA Dashboard client action.

All public methods accept plain arguments and return JSON-serialisable dicts.
There is no database table — this is a pure analytics utility model.

Example call from the OWL dashboard component::

    const metrics = await this.orm.call(
        'wa.dashboard', 'get_metrics', [],
        { date_from: '2026-05-01', date_to: '2026-05-02', workflow_slug: '' }
    );
"""

import logging
from datetime import datetime, date

from odoo import api, models

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module : wa_communication
# Model  : wa.dashboard
# Purpose: Provides all metric data for the WA Dashboard OWL client action.
#          No database table (_auto = False). Pure @api.model analytics.
# Owner  : Cleardeals Tech
# ---------------------------------------------------------------------------

_FAILED_STATUSES = [
    'failed', 'meta_blocked', 'invalid_number', 'opted_out',
    'rate_limited', 'template_error', 'expired',
]

_FAILURE_LABELS = {
    'failed':         'Failed',
    'meta_blocked':   'Meta Blocked',
    'invalid_number': 'Invalid Number',
    'opted_out':      'Opted Out',
    'rate_limited':   'Rate Limited',
    'template_error': 'Template Error',
    'expired':        'Expired',
}

# Human-readable descriptions per Interakt/Meta error code, used as a fallback
# reason when a failed message carries a code but no forwarded reason text.
# Mirrors the platform's wa-sender _CODE_TO_STATUS classification.
_FAILURE_CODE_LABELS = {
    '131026': 'Undeliverable — invalid number or the recipient has an outdated WhatsApp.',
    '131049': 'Undeliverable — blocked by Meta ecosystem health checks.',
    '131047': 'Re-engagement required — the 24-hour window is closed.',
    '131053': 'Media upload/format error — check the header media URL and type.',
    '130429': 'Rate limit reached — too many messages sent too quickly.',
    '130472': 'Recipient is in a Meta A/B experiment and did not receive the message.',
    '368':    'Temporarily blocked by Meta for policy reasons.',
    '132000': 'Template error — parameter count or format does not match the approved template.',
    '132001': 'Template error — the template does not exist or is not approved for this language.',
    '131052': 'Invalid phone number — could not be delivered.',
}

# Fallback reason per internal status when neither a reason nor a known code exists.
_STATUS_REASON_FALLBACK = {
    'failed':         'Delivery failed.',
    'meta_blocked':   'Blocked by Meta — message could not be delivered.',
    'invalid_number': 'Invalid phone number.',
    'opted_out':      'Recipient opted out of messages.',
    'rate_limited':   'Rate limit reached.',
    'template_error': 'Template error.',
    'expired':        'The 24-hour messaging window expired before sending.',
}


class WaDashboard(models.Model):
    """Read-only analytics model for the WA Dashboard.

    All methods are ``@api.model`` — they take plain keyword arguments and
    return JSON-serialisable structures.  No database table.

    Date arguments are ISO 8601 strings (``"2026-05-01"`` or
    ``"2026-05-01T00:00:00"``).  All times are interpreted as UTC.
    """

    _name = 'wa.dashboard'
    _description = 'WA Dashboard Analytics'
    _auto = False  # no database table

    # --- Private helpers --------------------------------------------------

    @staticmethod
    def _parse_date(val) -> datetime:
        """Parse an ISO 8601 date/datetime string to a naive UTC datetime.

        :param val: ISO string, date, or datetime.
        :returns:   Naive UTC datetime.
        :raises ValueError: If the value cannot be parsed.
        """
        if not val:
            return datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        if isinstance(val, datetime):
            return val.replace(tzinfo=None)
        if isinstance(val, date):
            return datetime(val.year, val.month, val.day)
        val = str(val).strip()
        for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
            try:
                return datetime.strptime(val[:19], fmt)
            except ValueError:
                continue
        raise ValueError(f"Cannot parse date: {val!r}")

    def _outbound_domain(self, dt_from, dt_to, workflow_slugs=None):
        """ORM domain for non-system outbound messages in the given window."""
        domain = [
            ('direction', '=', 'outbound'),
            ('kind', '!=', 'system'),
            ('occurred_at', '>=', dt_from),
            ('occurred_at', '<', dt_to),
        ]
        return domain + self._slug_domain(workflow_slugs or [])

    @staticmethod
    def _pct_change(current, previous):
        """Return % change from previous to current, or None if previous is 0."""
        if not previous:
            return None
        return round((current - previous) / previous * 100, 1)

    @staticmethod
    def _rate(numerator, denominator):
        """Return percentage rate, defaulting to 0.0 when denominator is 0."""
        if not denominator:
            return 0.0
        return round(numerator / denominator * 100, 1)

    @staticmethod
    def _slug_domain(slugs):
        """Return an ORM domain fragment for workflow_slug filtering."""
        if not slugs:
            return []
        if len(slugs) == 1:
            return [('workflow_slug', '=', slugs[0])]
        return [('workflow_slug', 'in', list(slugs))]

    @staticmethod
    def _sql_slug_clause(wf_slugs, params):
        """Append slug values to *params* and return a SQL WHERE fragment."""
        if not wf_slugs:
            return ''
        if len(wf_slugs) == 1:
            params.append(wf_slugs[0])
            return 'AND workflow_slug = %s'
        params.extend(wf_slugs)
        ph = ', '.join(['%s'] * len(wf_slugs))
        return f'AND workflow_slug IN ({ph})'

    # --- Public API -------------------------------------------------------

    @api.model
    def get_metrics(self, date_from=None, date_to=None, workflow_slug=None, workflow_slugs=None):
        """Return headline KPI metrics for the dashboard header cards.

        Computes counts for the current period and a comparison to the
        preceding period of equal duration.

        :param date_from:      Start of window (inclusive). ISO string.
        :param date_to:        End of window (exclusive). ISO string.
        :param workflow_slug:  Legacy single-slug filter (backward compat).
        :param workflow_slugs: Multi-slug filter list (preferred).
        :returns: Dict with keys: sent, delivered, read, failed,
                  active_enrollments, replied, delivery_rate, read_rate,
                  reply_rate, failed_breakdown, trend, date_from, date_to,
                  comparison_from, comparison_to.
        """
        dt_from = self._parse_date(date_from)
        dt_to   = self._parse_date(date_to) if date_to else datetime.utcnow()

        # Normalise slugs: accept legacy single string or new list
        slugs = [s for s in (workflow_slugs or []) if s]
        if not slugs and workflow_slug:
            slugs = [str(workflow_slug).strip()]
        slugs = [s for s in slugs if s]

        # Previous period: same duration, shifted back
        delta        = dt_to - dt_from
        dt_prev_from = dt_from - delta
        dt_prev_to   = dt_from

        WaMsg = self.env['wa.message'].sudo()
        base  = self._outbound_domain(dt_from, dt_to, slugs)

        # --- Current period ---
        sent      = WaMsg.search_count(base + [('status', 'not in', ['queued'])])
        delivered = WaMsg.search_count(base + [('status', 'in', ['delivered', 'read'])])
        read      = WaMsg.search_count(base + [('status', '=', 'read')])
        failed    = WaMsg.search_count(base + [('status', 'in', _FAILED_STATUSES)])

        # Failed breakdown by sub-status (only statuses that actually occurred)
        failed_breakdown = {}
        for status in _FAILED_STATUSES:
            n = WaMsg.search_count(base + [('status', '=', status)])
            if n:
                failed_breakdown[_FAILURE_LABELS[status]] = n

        # Inbound buyer replies in window
        inbound_domain = [
            ('direction', '=', 'inbound'),
            ('initiator', '=', 'buyer'),
            ('occurred_at', '>=', dt_from),
            ('occurred_at', '<', dt_to),
        ] + self._slug_domain(slugs)
        replied = WaMsg.search_count(inbound_domain)

        # Active enrollments — current snapshot, not bounded to date range
        enroll_domain = [('state', '=', 'active')] + self._slug_domain(slugs)
        active_enrollments = self.env['wa.enrollment'].sudo().search_count(enroll_domain)

        # --- Previous period ---
        prev_base    = self._outbound_domain(dt_prev_from, dt_prev_to, slugs)
        prev_sent    = WaMsg.search_count(prev_base + [('status', 'not in', ['queued'])])
        prev_failed  = WaMsg.search_count(prev_base + [('status', 'in', _FAILED_STATUSES)])
        prev_replied = WaMsg.search_count([
            ('direction', '=', 'inbound'),
            ('initiator', '=', 'buyer'),
            ('occurred_at', '>=', dt_prev_from),
            ('occurred_at', '<', dt_prev_to),
        ] + self._slug_domain(slugs))

        return {
            'sent':               sent,
            'delivered':          delivered,
            'read':               read,
            'failed':             failed,
            'replied':            replied,
            'active_enrollments': active_enrollments,
            'delivery_rate':      self._rate(delivered, sent),
            'read_rate':          self._rate(read, sent),
            'reply_rate':         self._rate(replied, sent),
            'failed_breakdown':   failed_breakdown,
            'trend': {
                'sent':    self._pct_change(sent, prev_sent),
                'failed':  self._pct_change(failed, prev_failed),
                'replied': self._pct_change(replied, prev_replied),
            },
            'date_from':        dt_from.isoformat(),
            'date_to':          dt_to.isoformat(),
            'comparison_from':  dt_prev_from.isoformat(),
            'comparison_to':    dt_prev_to.isoformat(),
        }

    @api.model
    def get_workflow_health(self, date_from=None, date_to=None):
        """Return per-workflow KPI rows for the Workflow Health table.

        :param date_from: Start of window. ISO string.
        :param date_to:   End of window. ISO string.
        :returns: List of dicts ordered by workflow name. Each dict:
                  {id, slug, name, is_active, sent, delivery_rate, failed}.
        """
        dt_from = self._parse_date(date_from)
        dt_to   = self._parse_date(date_to) if date_to else datetime.utcnow()

        workflows = self.env['wa.workflow'].sudo().search([], order='name')
        WaMsg = self.env['wa.message'].sudo()

        rows = []
        for wf in workflows:
            base = [
                ('direction', '=', 'outbound'),
                ('kind', '!=', 'system'),
                ('workflow_slug', '=', wf.slug),
                ('occurred_at', '>=', dt_from),
                ('occurred_at', '<', dt_to),
            ]
            sent      = WaMsg.search_count(base + [('status', 'not in', ['queued'])])
            delivered = WaMsg.search_count(base + [('status', 'in', ['delivered', 'read'])])
            failed    = WaMsg.search_count(base + [('status', 'in', _FAILED_STATUSES)])
            rows.append({
                'id':            wf.id,
                'slug':          wf.slug,
                'name':          wf.name,
                'is_active':     wf.is_active,
                'sent':          sent,
                'delivery_rate': self._rate(delivered, sent),
                'failed':        failed,
            })
        return rows

    @api.model
    def get_hourly_volume(
        self, date_from=None, date_to=None,
        workflow_slug=None, workflow_slugs=None, time_range='12h',
    ):
        """Return time-bucketed sent/failed counts for the line chart.

        Groups by hour for short ranges (12h/24h/custom ≤3 days) and by day
        for longer ranges (7d/30d/custom >3 days).  Results are ordered
        ascending by bucket timestamp.

        :param date_from:      Start of window. ISO string.
        :param date_to:        End of window. ISO string.
        :param workflow_slug:  Legacy single-slug filter (backward compat).
        :param workflow_slugs: Multi-slug filter list.
        :param time_range:     '12h' | '24h' | '7d' | '30d' | 'custom'.
        :returns: List of dicts: [{hour (int), hour_label (str), sent, failed}].
        """
        dt_from = self._parse_date(date_from)
        dt_to   = self._parse_date(date_to) if date_to else datetime.utcnow()

        # Normalise slugs
        wf_slugs = [s for s in (workflow_slugs or []) if s]
        if not wf_slugs and workflow_slug:
            wf_slugs = [str(workflow_slug).strip()]
        wf_slugs = [s for s in wf_slugs if s]

        # Choose time-bucket granularity
        if time_range in ('7d', '30d'):
            bucket = 'day'
        elif time_range == 'custom':
            delta_days = max(1, (dt_to - dt_from).days)
            bucket = 'day' if delta_days > 3 else 'hour'
        else:
            bucket = 'hour'  # 12h, 24h

        params = [dt_from, dt_to]
        wf_clause = self._sql_slug_clause(wf_slugs, params)

        self.env.cr.execute(
            f"""
            SELECT
                DATE_TRUNC('{bucket}', occurred_at) AS bucket_time,
                SUM(CASE WHEN status NOT IN (
                    'failed','meta_blocked','invalid_number','opted_out',
                    'rate_limited','template_error','expired'
                ) THEN 1 ELSE 0 END)::int AS sent,
                SUM(CASE WHEN status IN (
                    'failed','meta_blocked','invalid_number','opted_out',
                    'rate_limited','template_error','expired'
                ) THEN 1 ELSE 0 END)::int AS failed
            FROM wa_message
            WHERE direction = 'outbound'
              AND kind != 'system'
              AND occurred_at >= %s
              AND occurred_at < %s
              {wf_clause}
            GROUP BY DATE_TRUNC('{bucket}', occurred_at)
            ORDER BY bucket_time
            """,
            params,
        )
        result = []
        for i, row in enumerate(self.env.cr.fetchall()):
            bucket_time = row[0]
            if bucket_time is None:
                label = ''
            elif bucket == 'day':
                label = bucket_time.strftime('%Y-%m-%d')
            else:
                label = bucket_time.strftime('%Y-%m-%dT%H:00:00')
            result.append({
                'hour':       i,
                'hour_label': label,
                'sent':       row[1] or 0,
                'failed':     row[2] or 0,
            })
        return result

    @api.model
    def get_recent_failures(self, limit=20, workflow_slug=None, workflow_slugs=None):
        """Return the most recent delivery failures for the Failures table.

        :param limit:          Maximum rows (default 20).
        :param workflow_slug:  Legacy single-slug filter (backward compat).
        :param workflow_slugs: Multi-slug filter list.
        :returns: List of dicts ordered by occurred_at desc. Each dict:
                  {id, lead_id, lead_name, phone, workflow_name,
                   failure_reason, failure_status, occurred_at}.
        """
        slugs = [s for s in (workflow_slugs or []) if s]
        if not slugs and workflow_slug:
            slugs = [str(workflow_slug).strip()]
        slugs = [s for s in slugs if s]
        domain = [
            ('direction', '=', 'outbound'),
            ('status',    'in', _FAILED_STATUSES),
            ('kind',      '!=', 'system'),
        ] + self._slug_domain(slugs)

        failures = self.env['wa.message'].sudo().search(
            domain, order='occurred_at desc', limit=int(limit)
        )
        rows = []
        for msg in failures:
            lead = msg.lead_id
            rows.append({
                'id':             msg.id,
                'lead_id':        lead.id if lead else False,
                'lead_name':      lead.name if lead else '',
                'phone':          msg.conversation_id.phone_number if msg.conversation_id else '',
                'workflow_name':  msg.workflow_slug or '',
                # Short category label for the coloured badge …
                'failure_label':  _FAILURE_LABELS.get(msg.status, msg.status.replace('_', ' ').title()),
                # … and the descriptive, human-readable reason for the detail text.
                'failure_reason': self._owa_failure_detail(msg),
                'failure_code':   msg.failure_code or '',
                'failure_status': msg.status,
                'occurred_at':    msg.occurred_at.isoformat() if msg.occurred_at else '',
            })
        return rows

    @staticmethod
    def _owa_failure_detail(msg) -> str:
        """The most descriptive failure reason available for a failed message.

        Priority: the platform-forwarded reason text → a per-code description →
        a per-status fallback → the status itself.  Never returns an empty string.
        """
        reason = (msg.failure_reason or '').strip()
        if reason and reason.lower() != 'send failed':
            return reason
        code = (msg.failure_code or '').strip()
        if code and code in _FAILURE_CODE_LABELS:
            return _FAILURE_CODE_LABELS[code]
        return _STATUS_REASON_FALLBACK.get(msg.status, reason or msg.status.replace('_', ' ').title())
