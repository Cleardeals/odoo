"""Dev-only seed + purge for the WhatsApp "By Property" dashboard.

The dev database has accumulated stale, pre-attribution test data, which makes
the per-property and WhatsApp-rescue numbers untrustworthy.  This module creates
a small, **correct, self-consistent** slice of data so the dashboard can be
hand-verified, and a matching purge so the demo rows can be wiped again.

NOT loaded by the addon (it lives under ``tools/`` and is referenced by no
manifest/__init__), so it never runs in production.  Everything created is tagged
so :func:`purge` only ever touches demo rows:

* properties — ``uuid`` / ``prop_id`` prefixed ``DEVSEED-``
* leads      — ``source`` = ``DEVSEED`` and ``phone`` prefixed ``9999000``
* convs      — ``phone_number`` prefixed ``919999`` (messages/segments cascade)

Run it from an Odoo shell against the **dev** database.  Use the **venv**
interpreter — the bare ``odoo`` on PATH may resolve to the system Python that
lacks the optional ``google-cloud-*`` deps and fails to boot the registry::

    docker exec -i odoo-dev-app /opt/odoo-venv/bin/python -m odoo shell \
        -d cleardeals_19_dev --no-http <<'PY'
    from odoo.addons.wa_communication.tools.dev_seed import seed
    print(seed(env))      # wipes any prior demo rows, then re-creates them
    env.cr.commit()
    PY

To remove just the demo data again::

    docker exec -i odoo-dev-app /opt/odoo-venv/bin/python -m odoo shell \
        -d cleardeals_19_dev --no-http <<'PY'
    from odoo.addons.wa_communication.tools.dev_seed import purge
    print(purge(env))
    env.cr.commit()
    PY

All times are placed within the last few hours so the dashboard's default
"Today" window shows the demo immediately (the rescue cards included).
"""

from datetime import timedelta

from odoo import fields

# ── markers used for both creation and purge ────────────────────────────────
_CONV_PREFIX = '919999'      # wa.conversation.phone_number
_LEAD_PREFIX = '9999000'     # leads.new.phone (10-digit)
_PROP_PREFIX = 'DEVSEED-'    # property.base.uuid / prop_id
_SOURCE = 'DEVSEED'


# ───────────────────────────────────────────────────────────────────────────
# Purge
# ───────────────────────────────────────────────────────────────────────────

def purge(env):
    """Delete every demo row created by :func:`seed`. Safe to run on any DB —
    it only matches the demo markers above. Returns a count summary."""
    Conv = env['wa.conversation'].sudo()
    Lead = env['leads.new'].sudo()
    Visit = env['lead.site.visit'].sudo()
    Prop = env['property.base'].sudo()

    convs = Conv.search([('phone_number', '=like', _CONV_PREFIX + '%')])
    leads = Lead.search([('phone', '=like', _LEAD_PREFIX + '%')])
    visits = Visit.search([('inquiry_id', 'in', leads.ids)]) if leads else Visit.browse()
    props = Prop.search([('uuid', '=like', _PROP_PREFIX + '%')])

    counts = {
        'conversations': len(convs),   # messages + segments cascade with these
        'visits': len(visits),
        'leads': len(leads),
        'properties': len(props),
    }

    # Order matters: visits reference property (restrict); conversations cascade
    # to messages/segments; leads referenced by visits (cascade) + convs (set null).
    visits.unlink()
    convs.unlink()
    leads.unlink()
    props.unlink()
    return {'purged': counts}


# ───────────────────────────────────────────────────────────────────────────
# Seed
# ───────────────────────────────────────────────────────────────────────────

def seed(env):
    """Wipe any prior demo rows and create a fresh, correct demo slice.

    Idempotent (it purges first), so you can re-run it any time.  Returns the
    ids of the created properties + a short description of each scenario.
    """
    purge(env)

    user = env.user
    now = fields.Datetime.now()
    source = env['leads.new'].sudo()._get_or_create_source(_SOURCE)
    st_completed = env.ref('leads.lead_site_visit_status_completed')
    st_scheduled = env.ref('leads.lead_site_visit_status_scheduled')
    st_rescheduled = env.ref('leads.lead_site_visit_status_rescheduled')
    st_cancelling = env.ref('leads.lead_site_visit_status_cancelling')
    st_noshow = env.ref('leads.lead_site_visit_status_did_not_show_up')

    seq = {'n': 0}

    # ── helpers ──────────────────────────────────────────────────────────────
    def make_property(n, name, tag):
        return env['property.base'].sudo().create({
            'name': name,
            'property_tag': tag,
            'uuid': '%s%d' % (_PROP_PREFIX, n),
            'prop_id': '%sP%d' % (_PROP_PREFIX, n),
            'rm_user_id': user.id,
        })

    def next_phone():
        seq['n'] += 1
        return '9999%06d' % seq['n']           # 10 digits, '9999000NNN' (matches purge)

    def make_lead(prop, phone, status='lead', inquiry_type='primary'):
        return env['leads.new'].with_context(automated_lead_creation=True).create({
            'name': '[DEMO] %s %s' % (prop.property_tag, phone),
            'source_id': source.id,
            'phone': phone,
            'property_base_id': prop.id,
            'user_id': user.id,
            'current_status': status,
            'inquiry_type': inquiry_type,
        })

    def make_conv(phone, lead=None):
        vals = {'phone_number': '91' + phone, 'assigned_user_id': user.id}
        if lead is not None:
            vals['lead_id'] = lead.id
        return env['wa.conversation'].sudo().create(vals)

    def msg(conv, lead, mins_ago, direction, initiator, kind='text_reply',
            cost=0.0, segment=None):
        vals = {
            'conversation_id': conv.id,
            'direction': direction,
            'initiator': initiator,
            'kind': kind,
            'status': 'read' if direction == 'outbound' else 'delivered',
            'cost_inr': cost,
            'occurred_at': now - timedelta(minutes=mins_ago),
            'body': 'Demo message',
        }
        if lead is not None:
            vals['lead_id'] = lead.id
        if segment is not None:
            vals['segment_id'] = segment.id
        return env['wa.message'].sudo().create(vals)

    def visit(lead, status, days_offset):
        return env['lead.site.visit'].sudo().create({
            'inquiry_id': lead.id,
            'status_id': status.id,
            'scheduled_datetime': now + timedelta(days=days_offset),
        })

    def reschedule(v, days_offset):
        """Drive the model's real reschedule flow (supersedes old, opens a new
        scheduled visit) and return the new active visit."""
        inq = v.inquiry_id
        v.write({'status_id': st_rescheduled.id,
                 'scheduled_datetime': now + timedelta(days=days_offset)})
        return env['lead.site.visit'].sudo().search(
            [('inquiry_id', '=', inq.id),
             ('status_id', '=', st_scheduled.id),
             ('active', '=', True)],
            order='id desc', limit=1)

    def drive(lead, *statuses):
        """Walk current_status through real writes, exercising the write-hook
        (entering ringing/busy/etc stamps hard_to_reach_since)."""
        for s in statuses:
            lead.current_status = s

    def stamp(lead, mins_ago):
        lead.with_context(wa_skip_htr=True).hard_to_reach_since = now - timedelta(minutes=mins_ago)

    # ── Properties ───────────────────────────────────────────────────────────
    p1 = make_property(1, 'Demo Greens', 'DEMO-GREENS')
    p2 = make_property(2, 'Demo Heights', 'DEMO-HEIGHTS')
    p3 = make_property(3, 'Demo Plaza', 'DEMO-PLAZA')
    p4 = make_property(4, 'Demo Riverside', 'DEMO-RIVER')
    p5 = make_property(5, 'Demo Skyline', 'DEMO-SKY')

    # ── P1 Demo Greens — engagement basics + status journeys ─────────────────
    a1 = make_lead(p1, next_phone())                                   # converting, 60s response
    c = make_conv(a1.phone, a1)
    msg(c, a1, 185, 'outbound', 'workflow', kind='template', cost=0.85)
    msg(c, a1, 180, 'inbound', 'buyer')
    msg(c, a1, 179, 'outbound', 'rm', kind='freetext', cost=0.85)
    visit(a1, st_completed, -1)

    a2 = make_lead(p1, next_phone())                                   # template, no reply
    msg(make_conv(a2.phone, a2), a2, 150, 'outbound', 'workflow', kind='template', cost=0.85)

    # status journey: lead → ringing → details shared (hook stamps htr at ringing)
    g1 = make_lead(p1, next_phone())
    cc = make_conv(g1.phone, g1)
    msg(cc, g1, 300, 'outbound', 'workflow', kind='template', cost=0.85)
    drive(g1, 'ringing', 'details_shared_of_property')
    msg(cc, g1, 120, 'inbound', 'buyer')                               # engaged, but no visit booked

    # status journey: lead → ringing → option not matching (lost, cohort only)
    g2 = make_lead(p1, next_phone())
    drive(g2, 'ringing', 'option_not_matching_requirements')
    msg(make_conv(g2.phone, g2), g2, 240, 'outbound', 'workflow', kind='template', cost=0.85)

    # ── P2 Demo Heights — the WhatsApp-rescue cohort ─────────────────────────
    b1 = make_lead(p2, next_phone())                                   # rescued AND closed
    stamp(b1, 200)
    cb = make_conv(b1.phone, b1)
    msg(cb, b1, 200, 'outbound', 'workflow', kind='template', cost=0.85)
    msg(cb, b1, 160, 'inbound', 'buyer')
    visit(b1, st_completed, -1)

    b2 = make_lead(p2, next_phone())                                   # rescued, not yet closed
    stamp(b2, 200)
    cb = make_conv(b2.phone, b2)
    msg(cb, b2, 200, 'outbound', 'workflow', kind='template', cost=0.85)
    msg(cb, b2, 160, 'inbound', 'buyer')
    visit(b2, st_scheduled, 2)

    b3 = make_lead(p2, next_phone())                                   # cohort, never re-engaged
    stamp(b3, 200)
    msg(make_conv(b3.phone, b3), b3, 200, 'outbound', 'workflow', kind='template', cost=0.85)

    # ── P3 Demo Plaza — slower response + a high-volume thread ───────────────
    c1 = make_lead(p3, next_phone())                                   # 120s response, no visit
    cc = make_conv(c1.phone, c1)
    msg(cc, c1, 92, 'outbound', 'rm', kind='freetext', cost=0.85)
    msg(cc, c1, 90, 'inbound', 'buyer')
    msg(cc, c1, 88, 'outbound', 'rm', kind='freetext')

    h1 = make_lead(p3, next_phone())                                   # busy thread, completed
    cc = make_conv(h1.phone, h1)
    for i in range(12):
        out = i % 2 == 0
        msg(cc, h1, 200 - i * 5,
            'outbound' if out else 'inbound',
            'rm' if out else 'buyer',
            kind='freetext' if out else 'text_reply',
            cost=0.85 if out else 0.0)
    visit(h1, st_completed, -1)

    # ── P4 Demo Riverside — visit cycles (reschedule + multiple visits) ──────
    r1 = make_lead(p4, next_phone())                                   # scheduled → rescheduled → completed
    cc = make_conv(r1.phone, r1)
    msg(cc, r1, 300, 'outbound', 'workflow', kind='template', cost=0.85)
    msg(cc, r1, 250, 'inbound', 'buyer')
    v = visit(r1, st_scheduled, 1)
    nv = reschedule(v, 3)                                              # old superseded, new scheduled
    if nv:
        nv.write({'status_id': st_completed.id})                      # final visit completed

    r2 = make_lead(p4, next_phone())                                   # two separate attempts: cancelled then completed
    cc = make_conv(r2.phone, r2)
    msg(cc, r2, 280, 'inbound', 'buyer')
    visit(r2, st_cancelling, -3)                                      # first attempt cancelled
    visit(r2, st_completed, -1)                                       # second attempt completed

    r3 = make_lead(p4, next_phone())                                   # scheduled but cancelled (no-visit)
    cc = make_conv(r3.phone, r3)
    msg(cc, r3, 200, 'outbound', 'workflow', kind='template', cost=0.85)
    drive(r3, 'ringing', 'site_visit_scheduled')
    v = visit(r3, st_scheduled, 2)
    v.write({'status_id': st_cancelling.id})                          # cancelled before visiting

    # ── P5 Demo Skyline — no-show, upcoming, completed ───────────────────────
    s1 = make_lead(p5, next_phone())                                   # no-show
    cc = make_conv(s1.phone, s1)
    msg(cc, s1, 180, 'inbound', 'buyer')
    visit(s1, st_noshow, -1)

    s2 = make_lead(p5, next_phone())                                   # upcoming scheduled only
    msg(make_conv(s2.phone, s2), s2, 120, 'inbound', 'buyer')
    visit(s2, st_scheduled, 3)

    s3 = make_lead(p5, next_phone())                                   # straightforward completed
    cc = make_conv(s3.phone, s3)
    msg(cc, s3, 150, 'outbound', 'rm', kind='freetext', cost=0.85)
    msg(cc, s3, 148, 'inbound', 'buyer')
    visit(s3, st_completed, -2)

    # ── One phone, THREE properties (multi-inquiry, incl. a segment split) ───
    shared = next_phone()
    m1 = make_lead(p1, shared, inquiry_type='primary')
    m2 = make_lead(p2, shared, inquiry_type='recommended')
    m3 = make_lead(p3, shared, inquiry_type='recommended')
    cm = make_conv(shared, m1)
    msg(cm, m1, 70, 'inbound', 'buyer')                               # → P1 via lead_id
    msg(cm, m2, 65, 'outbound', 'rm', kind='freetext', cost=0.85)     # → P2 via lead_id
    seg = env['wa.conversation.segment'].sudo().create({
        'conversation_id': cm.id, 'inquiry_id': m3.id, 'started_by': 'rm'})
    msg(cm, m1, 60, 'inbound', 'buyer', segment=seg)                  # lead_id=P1 but segment→P3
    visit(m1, st_completed, -1)
    visit(m2, st_scheduled, 2)

    # ── Unassigned bucket (messages with no resolved property) ───────────────
    cu = make_conv(next_phone())
    msg(cu, None, 45, 'inbound', 'buyer')
    msg(cu, None, 44, 'outbound', 'rm', kind='freetext', cost=0.85)

    return {
        'properties': {
            'Demo Greens': p1.id, 'Demo Heights': p2.id, 'Demo Plaza': p3.id,
            'Demo Riverside': p4.id, 'Demo Skyline': p5.id,
        },
        'scenarios': [
            'P1 Greens: converting lead (60s, completed) + no-reply + 2 status journeys '
            '(ringing→details-shared engaged, ringing→option-not-matching lost)',
            'P2 Heights: rescue cohort of 3 — rescued+closed, rescued+open, never-re-engaged',
            'P3 Plaza: 120s-response lead (no visit) + a 12-message busy thread (completed)',
            'P4 Riverside: reschedule chain → completed; two attempts (cancelled then completed); '
            'scheduled-then-cancelled (no visit)',
            'P5 Skyline: no-show; upcoming scheduled; completed',
            'One phone across 3 properties (Greens/Heights/Plaza), incl. a segment split',
            'Unassigned bucket (messages with no property)',
        ],
        'tip': 'Open WhatsApp → Dashboard → By Property. Default "Today" window shows it all; '
               'times render in IST.',
    }
