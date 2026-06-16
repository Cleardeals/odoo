# Functions & Single Responsibility — Odoo

A function does one thing. In Odoo that thing is often *orchestration* (an
event handler, a controller, a button action) — which is allowed to be a few
lines longer, provided each sub-step is a named helper that reads like a
sentence. The orchestrator stays a readable summary; the detail lives below.

---

## Size guidance

| Lines | Assessment | Action |
|-------|-----------|--------|
| 1–20 | Good | keep |
| 21–30 | Questionable | extract if it does >1 thing |
| 31–50 | Too long | split |
| 50+ | Critical | must refactor (see `odoo-refactor`) |

An orchestrating handler that is 30 lines of *named helper calls with no
inline logic* is fine. A 30-line method with three inlined sub-tasks is not.

---

## Extract sub-tasks — the Odoo handler pattern

```python
# ✅ The orchestrator reads as a summary; each step is a named helper.
def _handle_odoo_lead_replied(self, event, pubsub_message_id):
    store_id, quoted_collision = self._owa_dedup_inbound(event)
    if store_id is None:
        return                                    # duplicate — already handled
    conv = self._owa_get_conversation(event['phone'])
    lead = self._owa_resolve_lead(event.get('actor_id'), event.get('actor_type'), event['phone'])
    quoted = self._owa_resolve_quoted_context(conv, ..., event)
    segment = self._owa_segment_for_inbound(conv, lead, quoted)
    self._owa_create_inbound_message(conv, lead, segment, quoted, event, store_id)
    self._owa_autoassign_to_lead_rm(conv, lead)
    self._owa_notify_owner(conv, lead, event)
```

Each `_owa_*` helper does exactly one thing and is independently testable.
The handler's job is *sequence*, not *implementation*.

---

## Guard clauses over nested conditionals

Nesting beyond 3 levels is a smell. Invert with early returns.

```python
# ❌ arrow-shaped
def send(self):
    if self.phone_number:
        if self.window_state == 'open':
            if self._can_send():
                ...  # the actual work, buried 3 levels deep

# ✅ guard clauses — the work is at the top level
def send(self):
    if not self.phone_number:
        raise UserError("Cannot send — no phone number.")
    if self.window_state != 'open':
        raise UserError("The 24-hour window is closed.")
    if not self._can_send():
        raise UserError("You are not the owner of this chat.")
    ...  # the work, unindented and obvious
```

---

## Respect recordsets — no N+1

Odoo methods receive a *recordset* (`self` may be many records). Compute and
batch operations must not fire one query per record.

```python
# ❌ N+1 — a search per record
def _compute_inquiry_ids(self):
    for rec in self:
        rec.inquiry_ids = self.env['leads.new'].search(
            [('phone', '=', rec.phone)])

# ✅ when truly per-record, accept it; but prefer batching where the domain allows
def _compute_message_count(self):
    counts = dict(self.env['wa.message'].read_group(
        [('conversation_id', 'in', self.ids)],
        ['conversation_id'], ['conversation_id']))
    for rec in self:
        rec.message_count = counts.get(rec.id, 0)
```

`@api.model_create_multi` exists so you create in batch — honour it; don't
loop calling single-record logic that re-queries.

---

## Too many parameters → pass a record or a vals dict

Odoo gives you natural parameter objects: the record and the `vals` dict.

```python
# ❌ 7 positional args
def create_message(conv, direction, kind, body, lead, segment, status): ...

# ✅ build a vals dict (the Odoo idiom) — named at the call site
create_vals = {
    'conversation_id': conv.id,
    'direction': 'inbound',
    'kind': kind,
    'body': body,
    'lead_id': lead.id if lead else False,
    'segment_id': segment.id if segment else False,
    'status': 'delivered',
}
self.env['wa.message'].sudo().create(create_vals)
```

For OWL/JS helpers, the same rule: past 3 args, take an options object.

---

## Single Responsibility at the method level

If you find yourself writing a comment like `# --- now do the notification ---`
inside a method, that block wants to be its own helper. The comment is the
method name you haven't written yet.
