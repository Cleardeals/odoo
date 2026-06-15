# Naming — Odoo Python + OWL

Names reveal intent. A reader should know what a thing is and why it exists
without reading its definition. In this stack the conventions are stricter
than generic clean-code because Odoo *infers behaviour from name shape*.

---

## Python / Odoo conventions

| Kind | Convention | Example |
|------|-----------|---------|
| Variable / function | `snake_case`, verb+noun for functions | `active_customers`, `calculate_window_expiry()` |
| Boolean | `is_` / `has_` / `can_` / `should_` predicate | `is_active`, `has_open_window`, `can_send` |
| Collection / recordset | plural noun | `leads`, `message_ids`, `valid_phones` |
| Module-level constant | `UPPER_SNAKE_CASE`, leading `_` if private | `_STATUS_RANK`, `_TOPIC_WA_REQUESTS`, `MAX_RETRY_COUNT` |
| Class / model class | `PascalCase` noun | `WaConversation`, `WaConversationSegment` |
| Model `_name` | dotted lowercase domain noun | `wa.conversation`, `leads.new`, `property.base` |
| Private helper / internal method | leading `_`, module prefix | `_owa_ensure_segment`, `_wa_build_event` |

### Odoo field-name shape is mandatory
Odoo and every reader rely on these suffixes — never deviate:

```python
lead_id      = fields.Many2one('leads.new')        # singular record  → _id
message_ids  = fields.One2many('wa.message', ...)  # collection       → _ids
inquiry_ids  = fields.Many2many('leads.new', ...)  # collection       → _ids
is_active    = fields.Boolean()                    # predicate        → is_
```

### Odoo method-name shape signals intent to the framework
```python
def _compute_window_state(self): ...   # @api.depends compute → _compute_<field>
def _onchange_phone(self): ...         # @api.onchange       → _onchange_<field>
def _check_phone_unique(self): ...     # @api.constrains     → _check_<rule>
def _owa_resolve_lead(self, ...): ...  # private helper, module-prefixed
```

### Match the module's existing prefix
Consistency beats personal preference. This repo already establishes:
- `wa_communication` private helpers: `_owa_*` (e.g. `_owa_get_conversation`,
  `_owa_canonical_wa_phone`).
- The `leads.new` event publisher: `_wa_*` (e.g. `_wa_build_event`,
  `_wa_schedule_publish`).
- Module-private topic/config keys: `_TOPIC_*`, `_INBOUND_AUDIENCE_KEY`.

A new helper in `wa_conversation.py` is `_owa_<verb>`, not `helper2` or
`do_thing`.

---

## Kill meaningless names

```python
# ❌ reveals nothing
data = self._fetch()
res = self._process(data)
vals2 = {...}
tmp = self._calc()

# ✅ specific to the domain
thread = self.get_thread(conversation_id)
attribution = self._owa_resolve_segment(quoted_src, lead)
create_vals = {...}
window_expiry = self._owa_compute_window_expiry(occurred_at)
```

`vals` is acceptable as an Odoo idiom for a create/write dict *when there is
exactly one*. The moment there are two, name them (`create_vals`,
`conv_vals`) — never `vals2`.

---

## OWL / JavaScript conventions

| Kind | Convention | Example |
|------|-----------|---------|
| Variable / function | `camelCase`, verb+noun for functions | `activeConversation`, `formatDayLabel()` |
| Boolean | `is`/`has`/`can` predicate | `isOwner`, `hasUnread`, `canSend` |
| Component class | `PascalCase` | `ChatThread`, `WaInbox` |
| Reactive state | `useState` object, named by concern | `datePill`, `composer`, `thread` |
| Constant | `UPPER_SNAKE` or `camelCase` const | `SCROLL_DEBOUNCE_MS` |

```javascript
// ❌
const d = useState({ v: false });
function fmt(x) { ... }

// ✅
const datePill = useState({ label: "", visible: false });
function formatDayLabel(occurredAt) { ... }
```

---

## The test for a good name

Read the call site aloud. If it reads like a sentence describing the
domain, the name is good:

```python
if conv._owa_segments_enabled():
    segment = conv._owa_ensure_segment(inquiry=lead, started_by='auto_suggested')
```

> "If this conversation has segments enabled, ensure a segment for the lead's
> inquiry, started by an automatic signal." — needs no comment.
