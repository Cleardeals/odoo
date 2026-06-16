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
from collections import defaultdict
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
                'failure_reason': _FAILURE_LABELS.get(msg.status, msg.status),
                'failure_status': msg.status,
                'occurred_at':    msg.occurred_at.isoformat() if msg.occurred_at else '',
            })
        return rows

    # ------------------------------------------------------------------
    # Per-property / per-inquiry engagement ("By Property" view)
    # ------------------------------------------------------------------
    #
    # All three methods below group on the *stored* attribution fields
    # ``effective_property_id`` / ``effective_inquiry_id`` on wa.message (Phase
    # 1a), never on the immutable ``lead_id``, so re-pointing a conversation
    # segment correctly moves the engagement.  Outcomes are read from the
    # canonical ``lead.site.visit`` model + its status flags — NOT the
    # ``current_status`` snapshot, which deliberately omits cancelled/no-show.

    # sort key -> row key (all "biggest / most-recent first")
    _PROPERTY_SORT_KEYS = {
        'messages':      'messages_total',
        'leads':         'leads_engaged',
        'reply_rate':    'reply_rate',
        'response':      'response_secs_median',
        'conversion':    'conversion_rate',
        'cost':          'cost',
        'last_activity': 'last_activity',
    }

    def _wa_window_messages(self, dt_from, dt_to, slugs=None, extra_domain=None):
        """Return non-system wa.message in ``[dt_from, dt_to)``, oldest first."""
        domain = [
            ('kind', '!=', 'system'),
            ('occurred_at', '>=', dt_from),
            ('occurred_at', '<', dt_to),
        ]
        if slugs:
            domain += self._slug_domain(slugs)
        if extra_domain:
            domain += extra_domain
        return self.env['wa.message'].sudo().search(
            domain, order='occurred_at asc, id asc')

    @staticmethod
    def _first_response_secs(msgs):
        """First-RM-reply latency in seconds for one inquiry's messages.

        ``msgs`` must be ordered oldest-first.  Returns the gap between the
        first buyer inbound and the first RM outbound that follows it, or
        ``None`` when the buyer never wrote or no RM reply followed (a reply
        that *precedes* the first inbound does not count).
        """
        first_buyer = None
        for m in msgs:
            if m.direction == 'inbound' and m.initiator == 'buyer' and m.occurred_at:
                first_buyer = m.occurred_at
                break
        if not first_buyer:
            return None
        for m in msgs:
            if (m.direction == 'outbound' and m.initiator == 'rm'
                    and m.occurred_at and m.occurred_at >= first_buyer):
                return (m.occurred_at - first_buyer).total_seconds()
        return None

    @staticmethod
    def _median(values):
        """Median of the non-None values, or ``None`` when there are none."""
        vals = sorted(v for v in values if v is not None)
        if not vals:
            return None
        n = len(vals)
        mid = n // 2
        if n % 2:
            return vals[mid]
        return (vals[mid - 1] + vals[mid]) / 2.0

    def _visit_state_by_inquiry(self, inquiry_ids):
        """Map inquiry id -> visit-state flags read from ``lead.site.visit``.

        ``{iid: {'done', 'open', 'cancelled', 'no_show'}}`` where ``done`` means
        the inquiry has at least one *completed* visit and ``open`` a
        scheduled/rescheduled one.  Counting is per inquiry, so a reschedule
        chain (several visit rows) is never double-counted by the caller.
        """
        res = {}
        ids = [i for i in inquiry_ids if i]
        if not ids:
            return res
        visits = self.env['lead.site.visit'].sudo().search(
            [('inquiry_id', 'in', ids)])
        for v in visits:
            d = res.setdefault(v.inquiry_id.id, {
                'done': False, 'open': False, 'cancelled': False, 'no_show': False,
            })
            s = v.status_id
            if s.is_completed_status:
                d['done'] = True
            elif s.is_scheduled_status or s.is_reschedule_status:
                d['open'] = True
            elif s.is_no_show_status:
                d['no_show'] = True
            elif s.is_cancelled_status:
                d['cancelled'] = True
        return res

    def _sort_property_rows(self, rows, sort):
        """Sort engagement rows by the requested key (biggest/most-recent first).

        ``None`` values sort last: numeric keys fall back to ``-1`` and the
        string ``last_activity`` to ``''`` so the mixed list never raises.
        """
        key = self._PROPERTY_SORT_KEYS.get(sort, 'messages_total')
        numeric = key != 'last_activity'

        def _sk(row):
            val = row.get(key)
            if val is None:
                return -1 if numeric else ''
            return val

        return sorted(rows, key=_sk, reverse=True)

    @api.model
    def get_property_engagement(
        self, date_from=None, date_to=None, workflow_slugs=None,
        search='', sort='messages', limit=100, offset=0,
    ):
        """Ranked WhatsApp engagement per property over the window.

        One row per property (plus a single ``Unassigned`` bucket for messages
        with no resolved property).  Each row carries activity (messages,
        in/out, leads engaged, reply rate, median first-response, cost,
        last activity) and outcomes from ``lead.site.visit``
        (visits scheduled/done, conversion rate).

        :returns: ``{rows, total, date_from, date_to}`` — ``rows`` already
                  sorted + paged, ``total`` is the pre-paging count.
        """
        dt_from = self._parse_date(date_from)
        dt_to   = self._parse_date(date_to) if date_to else datetime.utcnow()
        slugs   = [s for s in (workflow_slugs or []) if s]

        props = {}

        def _acc(pid):
            return props.setdefault(pid, {
                'messages': 0, 'inbound': 0, 'outbound': 0, 'cost': 0.0,
                'last': None, 'inquiries': set(), 'replied_inq': set(),
                'msgs_by_inq': defaultdict(list),
            })

        for m in self._wa_window_messages(dt_from, dt_to, slugs):
            pid = m.effective_property_id.id if m.effective_property_id else False
            iid = m.effective_inquiry_id.id if m.effective_inquiry_id else False
            a = _acc(pid)
            a['messages'] += 1
            if m.direction == 'inbound':
                a['inbound'] += 1
                if m.initiator == 'buyer' and iid:
                    a['replied_inq'].add(iid)
            elif m.direction == 'outbound':
                a['outbound'] += 1
            a['cost'] += m.cost_inr or 0.0
            if m.occurred_at and (a['last'] is None or m.occurred_at > a['last']):
                a['last'] = m.occurred_at
            if iid:
                a['inquiries'].add(iid)
                a['msgs_by_inq'][iid].append(m)

        # Outcomes — one batched lead.site.visit read across all engaged inquiries.
        all_inq = set()
        for a in props.values():
            all_inq |= a['inquiries']
        visit_state = self._visit_state_by_inquiry(all_inq)

        # Property display names — one batched browse.
        names = {}
        real_ids = [pid for pid in props if pid]
        if real_ids:
            for p in self.env['property.base'].sudo().browse(real_ids):
                names[p.id] = (
                    p.display_name or p.property_tag or ('Property %s' % p.id))

        rows = []
        for pid, a in props.items():
            engaged = a['inquiries']
            n_engaged = len(engaged)
            done = sum(
                1 for iid in engaged if visit_state.get(iid, {}).get('done'))
            scheduled = sum(
                1 for iid in engaged if visit_state.get(iid, {}).get('open'))
            latencies = [
                self._first_response_secs(a['msgs_by_inq'][iid]) for iid in engaged]
            rows.append({
                'property_id':          pid or False,
                'property_name':        names.get(pid, 'Unassigned') if pid else 'Unassigned',
                'messages_total':       a['messages'],
                'inbound':              a['inbound'],
                'outbound':             a['outbound'],
                'leads_engaged':        n_engaged,
                'replied':              len(a['replied_inq']),
                'reply_rate':           self._rate(len(a['replied_inq']), n_engaged),
                'response_secs_median': self._median(latencies),
                'cost':                 round(a['cost'], 2),
                'last_activity':        a['last'].isoformat() if a['last'] else None,
                'visits_scheduled':     scheduled,
                'visits_done':          done,
                'conversion_rate':      self._rate(done, n_engaged),
            })

        if search:
            needle = search.strip().lower()
            rows = [
                r for r in rows
                if r['property_id'] and needle in (r['property_name'] or '').lower()]

        rows = self._sort_property_rows(rows, sort)
        total = len(rows)
        if limit:
            rows = rows[int(offset):int(offset) + int(limit)]
        return {
            'rows':      rows,
            'total':     total,
            'date_from': dt_from.isoformat(),
            'date_to':   dt_to.isoformat(),
        }

    @api.model
    def get_inquiry_engagement(self, property_id, date_from=None, date_to=None):
        """Per-inquiry drill-down rows for one property over the window.

        :returns: list of dicts (lead name/phone, inquiry_type, message counts,
                  first-response latency, cost, last activity, latest site-visit
                  state, and ``conversation_id`` for UI navigation), sorted by
                  message volume.  Unknown / falsy ``property_id`` -> ``[]``.
        """
        if not property_id:
            return []
        dt_from = self._parse_date(date_from)
        dt_to   = self._parse_date(date_to) if date_to else datetime.utcnow()

        msgs = self._wa_window_messages(
            dt_from, dt_to,
            extra_domain=[('effective_property_id', '=', int(property_id))])

        by_inq = defaultdict(list)
        for m in msgs:
            iid = m.effective_inquiry_id.id if m.effective_inquiry_id else False
            by_inq[iid].append(m)

        inquiry_ids = [iid for iid in by_inq if iid]
        inq_map = {
            i.id: i for i in self.env['leads.new'].sudo().browse(inquiry_ids)}
        visit_state = self._visit_state_by_inquiry(inquiry_ids)

        # Latest visit per inquiry (for the status label) — one batched read.
        latest_visit = {}
        if inquiry_ids:
            for v in self.env['lead.site.visit'].sudo().search(
                    [('inquiry_id', 'in', inquiry_ids)],
                    order='scheduled_datetime desc, id desc'):
                latest_visit.setdefault(v.inquiry_id.id, v)

        rows = []
        for iid, mlist in by_inq.items():
            inq = inq_map.get(iid)
            conv = next((m.conversation_id for m in mlist if m.conversation_id), False)
            last = max((m.occurred_at for m in mlist if m.occurred_at), default=None)
            lv = latest_visit.get(iid)
            rows.append({
                'inquiry_id':     iid or False,
                'lead_name':      inq.name if inq else 'Unassigned',
                'phone':          (conv.phone_number if conv
                                   else (inq.phone if inq else '')) or '',
                'inquiry_type':   inq.inquiry_type if inq else '',
                'messages_total': len(mlist),
                'inbound':        sum(1 for m in mlist if m.direction == 'inbound'),
                'outbound':       sum(1 for m in mlist if m.direction == 'outbound'),
                'response_secs':  self._first_response_secs(mlist),
                'cost':           round(sum(m.cost_inr or 0.0 for m in mlist), 2),
                'last_activity':  last.isoformat() if last else None,
                'visit_status':   lv.status_id.name if lv else '',
                'visit_date':     (lv.scheduled_datetime.isoformat()
                                   if lv and lv.scheduled_datetime else None),
                'visit_done':     visit_state.get(iid, {}).get('done', False),
                'conversation_id': conv.id if conv else False,
            })

        rows.sort(key=lambda r: r['messages_total'], reverse=True)
        return rows

    @api.model
    def get_whatsapp_rescue(self, date_from=None, date_to=None, property_id=None):
        """The WhatsApp-rescue metric — overall + per-property.

        Of leads the RM could not reach by phone (the *cohort*: inquiries whose
        ``hard_to_reach_since`` falls in the window), how many re-engaged on
        WhatsApp and then booked a site visit.

        **Strict, sequence-based attribution (a proxy, not proof — no call logs
        exist):** an inquiry is *rescued* only when, in order, it became
        hard-to-reach (``T_stuck``), the **buyer** then replied on WhatsApp
        (``T_wa > T_stuck``), and a ``lead.site.visit`` was **booked after** that
        reply (``create_date > T_wa``).  Requiring the visit to be booked after
        the WA reply is what prevents crediting WhatsApp for a later RM call.
        ``rescued_to_visit`` further requires that visit to be *completed*.

        :returns: ``{overall, per_property, date_from, date_to, note}`` where
                  each bucket carries cohort / rescue_engaged / rescued /
                  rescued_to_visit counts + the two derived rates.
        """
        dt_from = self._parse_date(date_from)
        dt_to   = self._parse_date(date_to) if date_to else datetime.utcnow()

        cohort_domain = [
            ('hard_to_reach_since', '>=', dt_from),
            ('hard_to_reach_since', '<', dt_to),
        ]
        if property_id:
            cohort_domain.append(('property_base_id', '=', int(property_id)))
        cohort = self.env['leads.new'].sudo().search(cohort_domain)

        overall = {
            'cohort': 0, 'rescue_engaged': 0, 'rescued': 0, 'rescued_to_visit': 0}
        per_property = {}
        if not cohort:
            return self._rescue_payload(overall, per_property, dt_from, dt_to)

        cohort_ids = cohort.ids

        # First buyer WA reply per cohort inquiry (grouped on effective_inquiry_id).
        first_reply = {}
        for m in self.env['wa.message'].sudo().search([
            ('effective_inquiry_id', 'in', cohort_ids),
            ('direction', '=', 'inbound'),
            ('initiator', '=', 'buyer'),
        ], order='occurred_at asc, id asc'):
            iid = m.effective_inquiry_id.id
            if iid not in first_reply and m.occurred_at:
                first_reply[iid] = m.occurred_at

        # Site visits per cohort inquiry (for progression + completion).
        visits_by_inq = defaultdict(list)
        for v in self.env['lead.site.visit'].sudo().search(
                [('inquiry_id', 'in', cohort_ids)]):
            visits_by_inq[v.inquiry_id.id].append(v)

        for lead in cohort:
            pid = lead.property_base_id.id or False
            pp = per_property.setdefault(pid, {
                'cohort': 0, 'rescue_engaged': 0, 'rescued': 0, 'rescued_to_visit': 0})
            overall['cohort'] += 1
            pp['cohort'] += 1

            t_stuck = lead.hard_to_reach_since
            t_wa = first_reply.get(lead.id)
            if not (t_wa and t_stuck and t_wa > t_stuck):
                continue
            overall['rescue_engaged'] += 1
            pp['rescue_engaged'] += 1

            booked_after = [
                v for v in visits_by_inq.get(lead.id, [])
                if v.create_date and v.create_date > t_wa]
            if not booked_after:
                continue
            overall['rescued'] += 1
            pp['rescued'] += 1
            if any(v.status_id.is_completed_status for v in booked_after):
                overall['rescued_to_visit'] += 1
                pp['rescued_to_visit'] += 1

        return self._rescue_payload(overall, per_property, dt_from, dt_to)

    def _rescue_payload(self, overall, per_property, dt_from, dt_to):
        """Attach derived rates and the honesty note to the rescue buckets."""
        def _with_rates(d):
            return {
                **d,
                'rescue_engagement_rate':   self._rate(d['rescue_engaged'], d['cohort']),
                'wa_attributed_close_rate': self._rate(d['rescued_to_visit'], d['rescued']),
            }
        return {
            'overall':      _with_rates(overall),
            'per_property': {pid: _with_rates(v) for pid, v in per_property.items()},
            'date_from':    dt_from.isoformat(),
            'date_to':      dt_to.isoformat(),
            'note': (
                'Sequence/recency proxy, not proven causation: a lead counts as '
                'WhatsApp-rescued when, after the RM could not reach it by phone, '
                'the buyer replied on WhatsApp and only then booked a site visit. '
                'No call logs exist, so attribution is by ordering.'
            ),
        }
