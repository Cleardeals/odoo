---
name: cleardeals-owl-components
description: >
  Designs, builds, and maintains production-quality OWL (Odoo Web Library)
  components for the Cleardeals custom component library (cleardeals_ui addon).
  Use this skill whenever the user wants to: build a new reusable UI component,
  convert an existing Python-generated HTML field into an OWL widget, add a
  component to the cleardeals_ui library, register a custom field widget,
  work with OWL lifecycle hooks, manage component state, fetch data inside a
  component, or review existing OWL component code for correctness.
  Trigger on: "build a component", "convert this HTML field to OWL",
  "create a widget", "add to component library", "OWL component",
  "reusable widget", "custom field widget", "cleardeals_ui",
  "make this reusable", "build the UI properly", "component library",
  or any request to create or improve frontend UI code in the Odoo project.
  Always use this skill for any OWL work — it contains the architecture
  decisions, the Odoo-specific integration patterns, the Cleardeals conventions,
  and the safety rules that p</description>
<file>/Users/cleardealstech/Documents/GitHub/odoo/.github/skills/cleardeals-owl-components/SKILL.md</file>
---

# Cleardeals OWL Component Library

You build production-quality, reusable OWL components for the Cleardeals
Odoo CRM. Every component you produce must be safe to deploy without
touching Odoo's own source files, immediately reusable across all custom
addons, and written to a standard that a new developer can understand
without needing the original author to explain it.

Full OWL reference docs are in `references/`. Read the relevant file
before writing any non-trivial component code.

---

## The core principle

Stop generating HTML in Python. Pass data to a component and let the
component decide how to render it.

The old pattern (never do this for new work):
```python
# Python model — anti-pattern
def _compute_timeline_html(self):
    rows_html = f"<tr style='background:{row_bg};'>..."  # 200 lines of f-strings
```

The correct pattern:
```xml
<!-- XML view — data only, no presentation logic -->
<field name="site_visit_ids" widget="cleardeals_timeline"/>
```
```js
// OWL component — owns all rendering
import { Component, signal, onWillStart } from "@odoo/owl";
import { props, types as t } from "@odoo/owl";

export class CleardealsTimeline extends Component {
    static template = "cleardeals_ui.Timeline";
    props = props({ record: t.object() });
}
```

---

## Architecture: the cleardeals_ui addon

All custom components live in a single dedicated addon. Other addons
declare it as a dependency and use its widgets — they never define
their own UI primitives.

```
custom_addons/
  cleardeals_ui/
    __manifest__.py
    static/
      src/
        components/
          timeline/
            timeline.js
            timeline.xml
            timeline.scss
        widgets/                ← field widgets (widget="..." in XML views)
          status_badge/
            status_badge.js
            status_badge.xml
          kpi_card/
            kpi_card.js
            kpi_card.xml
        index.js                ← imports all components to trigger registration
    views/                      ← no Python models needed for pure UI
```

**Naming convention:**
- Template names: `cleardeals_ui.ComponentName`  (e.g. `cleardeals_ui.Timeline`)
- Widget registry keys: `cleardeals_` prefix  (e.g. `cleardeals_timeline`)
- JS class names: `Cleardeals` prefix  (e.g. `CleardealsTimeline`)
- CSS classes: `cd-` prefix  (e.g. `cd-timeline`, `cd-status-badge`)

**`__manifest__.py` assets block:**
```python
'assets': {
    'web.assets_backend': [
        'cleardeals_ui/static/src/index.js',
        'cleardeals_ui/static/src/**/*.js',
        'cleardeals_ui/static/src/**/*.xml',
        'cleardeals_ui/static/src/**/*.scss',
    ],
},
```

---

## OWL reference index

All reference files are in `references/`. Read them when building anything
in that topic area. This is not optional — the patterns in this skill
are derived from those docs.

| Topic | Reference file | Key things covered |
|-------|---------------|-------------------|
| Library overview | [`overview.md`](references/overview.md) | All exports: Component, signal, hooks, plugins, registries |
| App and roots | [`app.md`](references/app.md) | `new App()`, `createRoot`, mounting, dev mode |
| Component class | [`component.md`](references/component.md) | Lifecycle, sub-components, `status()` helper |
| Props | [`props.md`](references/props.md) | `props()` function, schema, defaults, validation |
| Reactivity | [`reactivity.md`](references/reactivity.md) | `signal`, `computed`, `proxy`, `effect`, collection signals |
| Template syntax | [`template_syntax.md`](references/template_syntax.md) | All directives: `t-out`, `t-if`, `t-foreach`, `t-model`, `t-call`, etc. |
| Hooks | [`hooks.md`](references/hooks.md) | `useEffect`, `useListener`, `useApp`, all lifecycle hooks |
| Event handling | [`event_handling.md`](references/event_handling.md) | `t-on-*`, modifiers (`.stop`, `.prevent`, `.passive`, `.synthetic`) |
| Form bindings | [`form_bindings.md`](references/form_bindings.md) | `t-model` with input, checkbox, select, radio; modifiers |
| Refs (DOM access) | [`refs.md`](references/refs.md) | Signal-based refs, `t-ref`, multi-ref with `Resource` |
| Slots | [`slots.md`](references/slots.md) | Default slot, named slots, `t-call-slot`, `t-set-slot`, scoped slots |
| Error handling | [`error_handling.md`](references/error_handling.md) | `onError` hook, `ErrorBoundary` pattern |
| Plugins | [`plugins.md`](references/plugins.md) | `Plugin` class, `plugin()`, `providePlugins`, shared state |
| Resources & Registries | [`resources_and_registries.md`](references/resources_and_registries.md) | `Resource`, `Registry`, sequencing, `useResource` |
| Types & validation | [`types_validation.md`](references/types_validation.md) | `types` validators, `validateType`, `assertType` |
| Utils | [`utils.md`](references/utils.md) | `EventBus`, `batched`, `whenReady` |
| Concurrency model | [`concurrency_model.md`](references/concurrency_model.md) | Async rendering, virtual DOM, patching phases |
| Precompiling templates | [`precompiling_templates.md`](references/precompiling_templates.md) | Ahead-of-time template compilation (not used in Odoo context) |

---

## Component anatomy

Every component is exactly three files. Read [`component.md`](references/component.md).

```js
// timeline.js
import { Component, signal, onWillStart } from "@odoo/owl";
import { props, types as t } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class CleardealsTimeline extends Component {
    static template = "cleardeals_ui.Timeline";
    static components = { /* sub-components if any */ };

    // props() declares and validates all props. Read references/props.md.
    // Use types (t.*) for runtime validation in dev mode.
    myProps = props({
        "visits": t.array(t.object()),
        "readonly?": t.boolean(),
    }, { readonly: false });

    // Reactive state — changes to signal values re-render automatically.
    // Read references/reactivity.md.
    isExpanded = signal(false);

    // setup() is the ONLY place to call hooks. Read references/hooks.md.
    setup() {
        this.orm = useService("orm");

        // Async data loading before first render. Read references/component.md#willstart.
        onWillStart(async () => {
            this.extraData = await this.orm.searchRead(...);
        });
    }

    toggle() {
        this.isExpanded.set(!this.isExpanded());
    }
}

// Field widget descriptor — needed for widget="cleardeals_timeline" in XML views
export const cleardealstimelineField = {
    component: CleardealsTimeline,
    supportedTypes: ["one2many"],
    extractProps: ({ options }) => ({ options }),
};

registry.category("fields").add("cleardeals_timeline", cleardealstimelineField);
```

```xml
<!-- timeline.xml — template syntax reference: references/template_syntax.md -->
<templates>
    <t t-name="cleardeals_ui.Timeline">
        <!-- t-out: safe text output. t-out with markup() for trusted HTML. -->
        <!-- t-foreach requires t-key — omitting it breaks component identity -->
        <div class="cd-timeline">
            <t t-foreach="myProps.visits" t-as="visit" t-key="visit.id">
                <!-- Event handling: references/event_handling.md -->
                <div t-on-click="() => this.toggle()" class="cd-timeline__row">
                    <span t-out="visit.date"/>
                    <!-- Slots for customisable content: references/slots.md -->
                </div>
            </t>
        </div>
    </t>
</templates>
```

---

## Reactivity patterns

Read [`reactivity.md`](references/reactivity.md) for the full system.

### Signals (preferred for simple values)

```js
// A signal holds a single reactive value.
count = signal(0);
count();           // read
count.set(1);      // write — triggers re-render

// Collection signals detect mutations (push, splice, etc.)
items = signal.Array([]);
items().push({ id: 1, name: "Lead" });  // detected, re-renders
```

**Critical:** plain `signal()` is reference-based — mutating `.push()` on a
plain `signal([])` is NOT detected. Use `signal.Array()` for arrays,
`signal.Object()` for objects, `signal.Set()`, `signal.Map()`.

### Computed values (derived state)

```js
// Lazily recomputed only when dependencies change.
// Read references/reactivity.md#computed-values.
total = computed(() => this.items().length + this.extra());
total();  // read — triggers recompute if stale
```

### proxy (for complex nested state)

```js
// proxy makes a whole object tree reactive.
// Use this when you have deeply nested state.
// Read references/reactivity.md#proxy.
setup() {
    this.state = proxy({ isLoading: false, leads: [], error: null });
}

async load() {
    this.state.isLoading = true;    // → re-render
    this.state.leads = await ...;   // → re-render
    this.state.isLoading = false;   // → re-render
}
```

---

## Props patterns

Read [`props.md`](references/props.md) and [`types_validation.md`](references/types_validation.md).

```js
import { props, types as t } from "@odoo/owl";

// Typed props with defaults — validated in dev mode
myProps = props({
    "title": t.string(),               // required string
    "count?": t.number(),              // optional number
    "items?": t.array(t.object()),     // optional array of objects
    "onSelect?": t.func(),             // optional callback
    "status?": t.union(
        t.literal("new"),
        t.literal("assigned"),
        t.literal("failed"),
    ),
}, {
    count: 0,           // default for optional props only
    items: [],
});

// Access in methods and template via this.myProps.*
get title() { return this.myProps.title; }
```

**Rule:** Never name the props field `props` — it shadows OWL's built-in
`props` function. Use a descriptive name like `myProps`, `config`, etc.

---

## Hooks patterns

Read [`hooks.md`](references/hooks.md).

### useEffect — reactive side effects

```js
import { useEffect } from "@odoo/owl";

setup() {
    // Runs immediately and re-runs whenever reactive dependencies change.
    // Return value is called before each re-run (cleanup).
    useEffect(() => {
        const handler = () => { ... };
        window.addEventListener("resize", handler);
        return () => window.removeEventListener("resize", handler);
    });
}
```

`useEffect` is automatically cleaned up when the component is destroyed.
Prefer it over manual `onMounted` + `onWillUnmount` pairs for reactive effects.

### useListener — declarative DOM listeners

```js
import { useListener } from "@odoo/owl";

setup() {
    // Attaches to an element signal (ref) and removes listener on destroy.
    // Read references/hooks.md#uselistener.
    useListener(this.myRef, "click", this.onClick);
}
```

---

## DOM references

Read [`refs.md`](references/refs.md).

```js
// Signal-based refs (OWL 3 style)
inputRef = signal(null);  // null when unmounted, HTMLElement when mounted

// In template:
// <input t-ref="this.inputRef"/>

focusInput() {
    this.inputRef()?.focus();
}
```

For refs inside loops (multiple elements), use `Resource`:
```js
import { Resource } from "@odoo/owl";

rows = new Resource({ name: "timeline-rows" });
// In template: <div t-foreach="..." t-ref="this.rows"/>
// this.rows.items() → reactive list of all mounted elements
```

---

## Event handling

Read [`event_handling.md`](references/event_handling.md).

```xml
<!-- Basic handler -->
<button t-on-click="this.save">Save</button>

<!-- With args -->
<button t-on-click="() => this.select(item.id)">Select</button>

<!-- With event object -->
<input t-on-input="ev => this.onInput(ev)"/>

<!-- Modifiers: stop propagation, prevent default -->
<form t-on-submit.prevent="this.submit">...</form>
<div t-on-click.stop="this.handleClick">...</div>

<!-- .passive for scroll/touch — never call preventDefault -->
<div t-on-scroll.passive="this.onScroll">...</div>

<!-- .synthetic for large lists — one handler on document.body -->
<li t-foreach="this.leads()" t-as="lead" t-key="lead.id"
    t-on-click.synthetic="() => this.open(lead.id)">
```

---

## Form inputs (t-model)

Read [`form_bindings.md`](references/form_bindings.md).

```js
// Bind a signal to an input — no manual event handler needed
searchText = signal("");
selectedColor = signal("red");
isActive = signal(false);
```

```xml
<input t-model="this.searchText"/>           <!-- text input -->
<textarea t-model="this.notes"/>             <!-- textarea -->
<input type="checkbox" t-model="this.isActive"/>
<select t-model="this.selectedColor">
    <option value="red">Red</option>
    <option value="blue">Blue</option>
</select>

<!-- Modifiers -->
<input t-model.lazy="this.searchText"/>     <!-- update on change, not on every keystroke -->
<input t-model.trim="this.name"/>           <!-- trim whitespace -->
<input t-model.number="this.amount"/>       <!-- parse to float -->
```

---

## Slots (composable components)

Read [`slots.md`](references/slots.md).

Use slots to build generic container components (modals, cards, panels)
where the content is provided by the parent.

```xml
<!-- CleardealsCard template — defines named slots -->
<t t-name="cleardeals_ui.Card">
    <div class="cd-card">
        <div class="cd-card__header">
            <t t-call-slot="header">Default Header</t>
        </div>
        <div class="cd-card__body">
            <t t-call-slot="default"/>
        </div>
    </div>
</t>
```

```xml
<!-- Usage — content renders in parent's context, not card's -->
<CleardealsCard>
    <t t-set-slot="header">Lead: <t t-out="this.lead.name"/></t>
    <p>Some body content</p>
</CleardealsCard>
```

---

## Error handling

Read [`error_handling.md`](references/error_handling.md).

Without `onError`, any rendering crash destroys the entire Odoo application.
Wrap any component that fetches external data or runs complex logic in an
error boundary.

```js
// CleardealsErrorBoundary.js
import { Component, signal, onError, xml } from "@odoo/owl";

export class CleardealsErrorBoundary extends Component {
    static template = "cleardeals_ui.ErrorBoundary";
    static components = {};

    hasError = signal(false);
    errorMessage = signal("");

    setup() {
        onError((err) => {
            this.hasError.set(true);
            this.errorMessage.set(err.message || "An unexpected error occurred.");
        });
    }
}
```

```xml
<t t-name="cleardeals_ui.ErrorBoundary">
    <t t-if="this.hasError()">
        <div class="cd-error-boundary">
            <span t-out="this.errorMessage()"/>
        </div>
    </t>
    <t t-else="" t-call-slot="default"/>
</t>
```

**Rule:** Wrap every data-fetching component in `<CleardealsErrorBoundary>`.
Do not let fetch errors propagate to the Odoo root and kill the whole UI.

**Rule:** Errors from event handlers (e.g. button clicks) are NOT caught by
`onError`. Wrap async event handlers in try/catch and update an error signal.

---

## Plugins (shared state across components)

Read [`plugins.md`](references/plugins.md).

Use plugins instead of passing deeply nested props or duplicating `orm`
calls across sibling components.

```js
// Define once
import { Plugin, signal, onWillDestroy } from "@odoo/owl";

export class LeadSelectionPlugin extends Plugin {
    selectedIds = signal.Set(new Set());

    select(id) { this.selectedIds().add(id); }
    deselect(id) { this.selectedIds().delete(id); }
    isSelected(id) { return this.selectedIds().has(id); }
}
```

```js
// Use anywhere in the subtree
import { plugin } from "@odoo/owl";

class CleardealsLeadRow extends Component {
    selection = plugin(LeadSelectionPlugin);

    toggle() {
        const id = this.myProps.leadId;
        this.selection.isSelected(id)
            ? this.selection.deselect(id)
            : this.selection.select(id);
    }
}
```

Provide at the right scope — app-level for global state, component-level
for feature-scoped state:
```js
// Component-level — destroyed with the component
setup() {
    providePlugins([LeadSelectionPlugin]);
}
```

---

## Odoo integration patterns

### Pattern 1 — Field widget (replaces a `fields.Html` computed field)

Read [`overview.md`](references/overview.md) for registry categories.

**Step 1 — Remove the Python computed field.**
Delete the `fields.Html` field and its `_compute_` method from the Python model.

**Step 2 — Build the component.**
```js
import { Component, signal, onWillStart } from "@odoo/owl";
import { props, types as t } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";

export class CleardealsTimeline extends Component {
    static template = "cleardeals_ui.Timeline";

    myProps = props({ ...standardFieldProps });  // id, name, readonly, record

    setup() {
        this.orm = useService("orm");
    }

    get visits() {
        return this.myProps.record.data[this.myProps.name].records || [];
    }
}

export const cleardealstimelineField = {
    component: CleardealsTimeline,
    supportedTypes: ["one2many"],
    extractProps: ({ options }) => ({ options }),
};

registry.category("fields").add("cleardeals_timeline", cleardealstimelineField);
```

**Step 3 — Update the XML view.**
```xml
<!-- Before: Python-generated HTML blob -->
<field name="overall_timeline_html" widget="html" readonly="1"/>

<!-- After: OWL component -->
<field name="site_visit_ids" widget="cleardeals_timeline"/>
```

### Pattern 2 — Standalone view widget (no field backing)

```js
import { Component, signal, onWillStart } from "@odoo/owl";
import { props, types as t } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class CleardealsKpiCard extends Component {
    static template = "cleardeals_ui.KpiCard";

    myProps = props({
        "title": t.string(),
        "model": t.string(),
        "domain?": t.array(),
    }, { domain: [] });

    count = signal(0);
    isLoading = signal(true);

    setup() {
        this.orm = useService("orm");

        onWillStart(async () => {
            const result = await this.orm.searchCount(
                this.myProps.model,
                this.myProps.domain,
            );
            this.count.set(result);
            this.isLoading.set(false);
        });
    }
}

registry.category("view_widgets").add("cleardeals_kpi_card", {
    component: CleardealsKpiCard,
});
```

```xml
<widget name="cleardeals_kpi_card"
    title="'New Leads Today'"
    model="'leads.new'"
    domain="[['create_date', '>=', today]]"
/>
```

### Pattern 3 — Fetching Odoo data inside a component

Always use the `orm` service — never raw `fetch()` to Odoo's internal
endpoints. The service handles CSRF, session management, and error routing.

```js
setup() {
    this.orm = useService("orm");

    onWillStart(async () => {
        this.leads = await this.orm.searchRead(
            "leads.new",
            [["state", "=", "new"]],
            ["name", "phone", "user_id", "create_date"],
            { limit: 50, order: "create_date desc" },
        );
        this.total = await this.orm.searchCount("leads.new", []);
        await this.orm.call("leads.new", "action_assign", [[this.recordId]]);
    });
}
```

### Pattern 4 — Accessing the current form record's data

```js
// Field values
this.myProps.record.data["state"]          // → "new"
this.myProps.record.data["user_id"]        // → { id: 6, display_name: "Aneri" }

// Field metadata
this.myProps.record.fields["state"]        // → { type: "selection", selection: [...] }

// Write back — triggers save
await this.myProps.record.update({ state: "assigned" });

// Record ID
this.myProps.record.resId                  // → 83508
```

---

## Safety rules — never break the codebase

**Rule 1 — Never touch Odoo core files.**
All components live under `custom_addons/cleardeals_ui/`. Never edit
files under `addons/` or `odoo/`. Your registrations add to the registry
without overriding Odoo's own entries.

**Rule 2 — Always declare props with the `props()` function.**
Use typed validators (`t.string()`, `t.number()`, `t.array()`, etc.) from
`types_validation.md`. Undeclared or untyped props fail silently in
production and loudly in dev mode.

**Rule 3 — t-key is required in every t-foreach.**
Missing `t-key` causes full list rebuilds on every re-render and corrupts
component identity — `onMounted`/`onWillUnmount` fire on the wrong elements.

**Rule 4 — Clean up every side effect.**
Use `useEffect` with a cleanup return value, or pair `onMounted`/`onWillUnmount`
for every listener. Use `useListener` for declarative listener management.
Every `createRoot` must call `root.destroy()` before the target element
is removed from the DOM.

**Rule 5 — Never mutate props.**
Props belong to the parent. Copy into a local signal in `setup()` and
mutate only that copy.

**Rule 6 — Async operations go in onWillStart, not bare in setup().**
`setup()` is synchronous. Wrap all `await` calls inside
`onWillStart(async () => {...})`.

**Rule 7 — Use t-out, never t-out with untrusted raw HTML.**
`t-out` is safe (HTML-escaped) by default. Passing a `markup()` string
to `t-out` renders raw HTML — only do this for content explicitly
sanitized and wrapped by the Python layer. Never on user input.

**Rule 8 — Errors from event handlers are NOT caught by onError.**
Wrap async button/click handlers in try/catch and update a local error
signal. Only rendering and lifecycle errors propagate to `onError`.

**Rule 9 — Use .passive on scroll and touch handlers.**
Never call `preventDefault()` in a `.passive` handler — the browser will
ignore it and log a warning. See `event_handling.md`.

---

## Component checklist (pre-push)

```
□ static template name matches t-name in the XML file exactly
□ props() declared with typed validators for every prop
□ Props field is NOT named "props" (shadows the OWL function)
□ t-key provided in every t-foreach loop
□ Every DOM listener has a matching cleanup (useEffect return, or useListener)
□ Every createRoot has a paired root.destroy() call
□ Async data loading is inside onWillStart, not bare in setup()
□ Component is registered in the correct registry category:
    - "fields"        → for widget="..." on a <field> tag
    - "view_widgets"  → for <widget name="..."/> standalone
□ Data-fetching components are wrapped in <CleardealsErrorBoundary>
□ cleardeals_ui __manifest__.py assets block includes all new files
□ Any addon using the component declares cleardeals_ui in its depends
□ No Python computed Html field left behind that the new widget replaced
□ Tested in browser dev mode: component renders, data loads, no console errors
□ OWL DevTools browser extension confirms correct component tree and props
```
