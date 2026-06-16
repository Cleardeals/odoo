# SOLID & Structure — Odoo models and OWL components

SOLID maps cleanly onto Odoo if you read "class" as "model" and "interface"
as "the ORM / a service model". The goal is the same: one reason to change,
extension without modification, depend on abstractions.

---

## Single Responsibility — one model, one job

Odoo makes SRP easy: split responsibilities across models and let `_inherit`
compose them. This repo already does this well — follow the pattern.

```
✅ Separated responsibilities in wa_communication:
  wa.conversation          — the thread + its lifecycle
  wa.conversation.segment  — inquiry attribution within a thread
  wa.message               — the append-only message log
  wa.lead.event.publisher  — _inherit='leads.new', publishes Pub/Sub events
  cleardeals.notification  — persistent notifications (separate addon)
```

A god model with `create_user()`, `send_email()`, `generate_report()`, and
`validate_password()` all on it is the smell. Each verb is a different reason
to change → a different home (a service model, a mixin, or another addon).

**When a model passes ~15 methods spanning unrelated concerns**, split it:
move the cohesive cluster onto a `_inherit` extension file (as
`wa_lead_event_publisher.py` extends `leads.new`) or a dedicated model.

---

## Open/Closed — extend via dispatch, not by editing a chain

```python
# ❌ must edit this method for every new event type
def _process_odoo_wa_event(self, event):
    if event['event_type'] == 'message_sent': ...
    elif event['event_type'] == 'message_read': ...
    elif event['event_type'] == 'lead_replied': ...
    # ...keep appending

# ✅ a dispatch table — adding a handler doesn't modify the router
_EVENT_HANDLERS = {
    'message_sent':   '_handle_odoo_message_sent',
    'message_read':   '_handle_odoo_message_read',
    'lead_replied':   '_handle_odoo_lead_replied',
}

def _process_odoo_wa_event(self, event):
    handler = getattr(self, self._EVENT_HANDLERS.get(event['event_type'], ''), None)
    if not handler:
        return self._owa_log_unknown_event(event)
    handler(event, ...)
```

New behaviour = a new handler + a table row. The router is closed for
modification.

---

## Dependency Inversion — depend on `self.env`, not concretes

Odoo's `self.env['model.name']` *is* the injected abstraction. Code already
gets dependency inversion for free — don't undermine it by hardcoding.

```python
# ❌ hardcoded magic that needs a code deploy to change
FALLBACK_RM = 'Pratham Bhandari'

# ✅ depend on configuration, resolved at runtime
rm_login = self.env['ir.config_parameter'].sudo().get_param(
    'leads.fallback_rm_login')
```

Hardcoded RM names, topic strings, or thresholds inline are concrete
dependencies. Lift them to `ir.config_parameter`, a Selection of module
constants, or a config model so behaviour changes without a deploy.

---

## OWL component cleanliness

| Rule | In OWL |
|------|--------|
| One component, one concern | `ChatThread` renders the thread; it does not also own inbox routing |
| State lives in `useState` | not in instance fields mutated ad hoc |
| Side effects in lifecycle hooks | `onWillStart` / `onMounted` / `onWillUnmount` — clear timers on unmount |
| No business logic as HTML in Python | pass plain data to the component; let it render (see `cleardeals-owl-components` skill) |
| Names reveal intent | `datePill`, `onThreadScroll()`, not `s`, `handler()` |

```javascript
// ✅ effect set up and torn down deliberately
setup() {
    this.datePill = useState({ label: "", visible: false });
    this._dateHideTimer = null;
    onWillUnmount(() => clearTimeout(this._dateHideTimer));
}
```

A component that fetches data, owns routing, formats dates, AND manages a
modal is a god component — split it, exactly as you would a god model.

---

## Liskov & Interface Segregation, the Odoo reading

- **Liskov:** an `_inherit` override must honour the base method's contract.
  If `write()` is overridden to reject immutable fields, it must still return
  the super result and still let lifecycle fields through — a subtype that
  breaks callers' expectations is the violation.
- **Interface Segregation:** don't force a model to implement hooks it
  doesn't need. Compose small mixins (`mail.thread`, a custom
  `_inherit` extension) rather than one fat base that every model must
  satisfy.
