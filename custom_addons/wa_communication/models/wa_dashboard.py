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

    def _outbound_domain(self, dt_from, dt_to, workflow_slug=None):
        """ORM domain for non-system outbound messages in the given window."""
        domain = [
            ('direction', '=', 'outbound'),
            ('kind', '!=', 'system'),
            ('occurred_at', '>=', dt_from),
            ('occurred_at', '<', dt_to),
        ]
        if workflow_slug:
            domain.append(('workflow_slug', '=', workflow_slug))
        return domain

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

    # --- Public API -------------------------------------------------------

    @api.model
    def get_metrics(self, date_from=None, date_to=None, workflow_slug=None):
        """Return headline KPI metrics for the dashboard header cards.

        Computes counts for the current period and a comparison to the
        preceding period of equal duration.

        :param date_from:     Start of window (inclusive). ISO string.
        :param date_to:       End of window (exclusive). ISO string.
        :param workflow_slug: Filter to one workflow. Empty string = all.
        :returns: Dict with keys: sent, delivered, read, failed,
                  active_enrollments, replied, delivery_rate, read_rate,
                  reply_rate, failed_breakdown, trend, date_from, date_to.
        """
        dt_from = self._parse_date(date_from)
        dt_to   = self._parse_date(date_to) if date_to else datetime.utcnow()
        wf_slug = (workflow_slug or '').strip() or None

        # Previous period: same duration, shifted back
        delta        = dt_to - dt_from
        dt_prev_from = dt_from - delta
        dt_prev_to   = dt_from

        WaMsg = self.env['wa.message'].sudo()
        base  = self._outbound_domain(dt_from, dt_to, wf_slug)

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
        ]
        if wf_slug:
            inbound_domain.append(('workflow_slug', '=', wf_slug))
        replied = WaMsg.search_count(inbound_domain)

        # Active enrollments — current snapshot, not bounded to date range
        enroll_domain = [('state', '=', 'active')]
        if wf_slug:
            enroll_domain.append(('workflow_slug', '=', wf_slug))
        active_enrollments = self.env['wa.enrollment'].sudo().search_count(enroll_domain)

        # --- Previous period ---
        prev_base    = self._outbound_domain(dt_prev_from, dt_prev_to, wf_slug)
        prev_sent    = WaMsg.search_count(prev_base + [('status', 'not in', ['queued'])])
        prev_failed  = WaMsg.search_count(prev_base + [('status', 'in', _FAILED_STATUSES)])
        prev_replied = WaMsg.search_count([
            ('direction', '=', 'inbound'),
            ('initiator', '=', 'buyer'),
            ('occurred_at', '>=', dt_prev_from),
            ('occurred_at', '<', dt_prev_to),
        ] + ([('workflow_slug', '=', wf_slug)] if wf_slug else []))

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
            'date_from': dt_from.isoformat(),
            'date_to':   dt_to.isoformat(),
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
    def get_hourly_volume(self, date_from=None, date_to=None, workflow_slug=None):
        """Return per-hour sent/failed counts for the bar chart.

        Uses a single raw SQL query for efficiency.  Results cover all
        hours in the window, ordered ascending.

        Preconditions:
            - ``date_from`` and ``date_to`` define the window.
            - ``workflow_slug`` (optional) filters to one workflow.

        :returns: List of dicts: [{hour (int), hour_label (str), sent, failed}].
        """
        dt_from = self._parse_date(date_from)
        dt_to   = self._parse_date(date_to) if date_to else datetime.utcnow()
        wf_slug = (workflow_slug or '').strip() or None

        wf_clause = "AND workflow_slug = %s" if wf_slug else ""
        params = [dt_from, dt_to]
        if wf_slug:
            params.append(wf_slug)

        self.env.cr.execute(
            f"""
            SELECT
                EXTRACT(HOUR FROM occurred_at)::int AS hour,
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
            GROUP BY EXTRACT(HOUR FROM occurred_at)
            ORDER BY hour
            """,
            params,
        )
        return [
            {
                'hour':       row[0],
                'hour_label': f"{row[0]:02d}",
                'sent':       row[1],
                'failed':     row[2],
            }
            for row in self.env.cr.fetchall()
        ]

    @api.model
    def get_recent_failures(self, limit=20, workflow_slug=None):
        """Return the most recent delivery failures for the Failures table.

        :param limit:         Maximum rows (default 20).
        :param workflow_slug: Optional workflow filter.
        :returns: List of dicts ordered by occurred_at desc. Each dict:
                  {id, lead_id, lead_name, phone, workflow_name,
                   failure_reason, failure_status, occurred_at}.
        """
        wf_slug = (workflow_slug or '').strip() or None
        domain = [
            ('direction', '=', 'outbound'),
            ('status',    'in', _FAILED_STATUSES),
            ('kind',      '!=', 'system'),
        ]
        if wf_slug:
            domain.append(('workflow_slug', '=', wf_slug))

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
                'failure_reason': _FAILURE_LABELS.get(msg.status, msg.status),
                'failure_status': msg.status,
                'occurred_at':    msg.occurred_at.isoformat() if msg.occurred_at else '',
            })
        return rows
