# custom_addons/cleardeals_ui

> **Last updated:** 2026-05-21 · **Addon version:** 1.0.0 · **Odoo version:** 19.0

Central OWL component library for all Cleardeals custom addons. Every
reusable frontend primitive — field widgets, view widgets, and generic UI
components — lives here. Other addons consume them; they never define their
own primitives.

---

## Why this addon exists

Before `cleardeals_ui`, each feature addon reinvented its own badge, pill, and
status indicator. They diverged in colour, shape, and DOM structure. Changing
the brand colour meant 12 files across 6 addons.

`cleardeals_ui` solves this the same way Odoo solved it in the `web` addon: one
source of truth for the component, one place to fix a bug, one place to change
a style. Every downstream addon inherits the fix automatically on the next
browser reload.

**Rule:** If you are writing a reusable OWL component, it goes here. If it is
only ever used in one addon and has no design system significance, it can stay
in that addon.

---

## Dependency declaration

Any addon that uses a `cleardeals_ui` component must list this addon as a
dependency in its `__manifest__.py`:

```python
'depends': ['web', 'cleardeals_ui'],
```

Odoo's asset bundler will then include `cleardeals_ui`'s JS, XML, and SCSS in
the backend bundle before your addon's assets are loaded.

---

## Directory layout

```
cleardeals_ui/
├── __init__.py           # Empty Python package marker (no models)
├── __manifest__.py       # Odoo manifest — metadata + asset glob registration
├── README.md             # This file
└── static/
    └── src/
        ├── index.js      # Barrel — re-exports every public symbol
        ├── core/         # Generic UI primitives (no registry, no field binding)
        ├── fields/       # Field widgets  → widget="cd_*" in XML views
        │   └── status_badge/
        │       ├── status_badge.js     ← component class + descriptor
        │       ├── status_badge.xml    ← OWL template
        │       └── status_badge.scss   ← scoped styles
        └── widgets/      # Standalone view widgets → <widget name="cd_*"/>
```

### The three categories

| Directory | Registry key | XML usage | When to use |
|---|---|---|---|
| `core/` | None — pure OWL component | `<CdComponent .../>` inside another component's template | Generic UI primitives: spinners, empty states, confirm dialogs, etc. |
| `fields/` | `"fields"` | `<field name="x" widget="cd_*"/>` in a form/list view | Anything bound to a model field that needs custom rendering |
| `widgets/` | `"view_widgets"` | `<widget name="cd_*"/>` in a form view | Standalone display areas that are NOT backed by a single field |

### Asset registration

The manifest registers three globs for `web.assets_backend`:

```python
'web.assets_backend': [
    'cleardeals_ui/static/src/**/*.js',
    'cleardeals_ui/static/src/**/*.xml',
    'cleardeals_ui/static/src/**/*.scss',
],
```

**Implication:** Every new file you add under `static/src/` is automatically
included in the bundle. You do not need to edit `__manifest__.py` when adding
a new component.

---

## How to add a new component

Follow these five steps exactly. Any deviation from this structure will cause
the component to either not register or not render.

### Step 1 — Choose the right category

- Does it bind to a model field and appear via `widget="..."` in an XML view?
  → `fields/`
- Does it appear in a view but is NOT backed by a single field?
  → `widgets/`
- Is it a pure UI primitive reused inside other components' templates?
  → `core/`

### Step 2 — Create the directory

```
static/src/<category>/<component_name>/
```

Use `snake_case` for the directory name. Example: `static/src/fields/phone_link/`.

### Step 3 — Create three files

Every component consists of exactly three co-located files:

#### `<name>.js` — the component

```js
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component } from "@odoo/owl";

/**
 * CdMyWidget — field widget
 *
 * One-sentence description of what this renders.
 *
 * Basic usage:
 *   <field name="my_field" widget="cd_my_widget"/>
 *
 * With options:
 *   <field name="my_field" widget="cd_my_widget" options="{'some_opt': 'value'}"/>
 *
 * Props (beyond standardFieldProps):
 * @prop {string} [myProp]  Description of the prop.
 *
 * @extends Component
 */
export class CdMyWidget extends Component {
    static template = "cleardeals_ui.MyWidget";   // must match t-name in .xml
    static props = {
        ...standardFieldProps,
        myProp: { type: String, optional: true },
    };
    static defaultProps = {
        myProp: undefined,
    };

    // computed properties / event handlers here
}

/**
 * Field widget descriptor registered under the key "cd_my_widget".
 *
 * @type {import("@web/views/fields/field").FieldDefinition}
 */
export const cdMyWidgetField = {
    component: CdMyWidget,
    displayName: _t("My Widget"),
    supportedTypes: ["char"],             // field types this widget accepts
    supportedOptions: [],                 // options surfaced in Studio
    extractProps: ({ options }) => ({
        myProp: options.my_prop,
    }),
};

// Self-registers on module load — no import needed elsewhere to activate it.
registry.category("fields").add("cd_my_widget", cdMyWidgetField);
```

Key rules for the JS file:
- Class name: `CdPascalCase` (prefixed with `Cd`)
- Template name: `cleardeals_ui.PascalCase` (must be unique across Odoo)
- Registry key: `"cd_snake_case"` (must be unique across all loaded addons)
- `static props` spreads `standardFieldProps` for field widgets — never omit this
- `static defaultProps` must list every optional prop
- Both the class and the descriptor are **named exports** (no default export)
- `registry.add(...)` runs at module level (self-registering — not inside a function)

#### `<name>.xml` — the OWL template

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">

    <!--
        cleardeals_ui.MyWidget
        ──────────────────────
        One-sentence description.
        Document any non-obvious template logic here.
    -->
    <t t-name="cleardeals_ui.MyWidget">
        <!-- your markup -->
    </t>

</templates>
```

Key rules for the XML file:
- The `t-name` must exactly match `static template` in the JS file
- Use Bootstrap utility classes for layout/colour whenever possible — do not
  invent custom structural CSS
- Use `t-if="displayValue"` or similar to hide the widget when there is
  nothing to show (avoids empty badge shells in the DOM)

#### `<name>.scss` — the styles

```scss
/**
 * <name>.scss
 * ───────────
 * Styles for the Cd<Name> component.
 * Explain any non-obvious colour/sizing choices here.
 */

.cd-my-widget {
    // styles
}
```

Key rules for the SCSS file:
- CSS class prefix: `cd-` for all Cleardeals classes
- Use BEM modifiers: `cd-my-widget--modifier-name`
- Scope everything under `.cd-<component-name>` — never add global overrides
- Delegate sizing/shape to Bootstrap utility classes; only add what Bootstrap
  cannot provide

### Step 4 — Re-export from `index.js`

Open `static/src/index.js` and add a named re-export:

```js
// ── fields ──────────────────────────────────────────────────────────────────
export { CdStatusBadge, cdStatusBadgeField } from "./fields/status_badge/status_badge";
export { CdMyWidget, cdMyWidgetField }       from "./fields/my_widget/my_widget";
```

This is required so other JS modules can do:

```js
import { CdMyWidget } from "@cleardeals_ui/index";
```

> **Note:** Registration happens automatically when the module is bundled —
> you do not need to import the component anywhere just to register it. The
> re-export in `index.js` is only for modules that need to programmatically
> reference the class (e.g. to extend it or compose it).

### Step 5 — Verify

After adding the files, install or upgrade `cleardeals_ui` in Odoo:

```bash
docker exec odoo-dev-app odoo \
    --addons-path=/mnt/extra-addons/custom \
    -d cleardeals_19_dev \
    -u cleardeals_ui \
    --stop-after-init
```

Then open the Odoo backend and check the browser console for JS errors. A
missing template reference or a typo in the registry key will surface here.

---

## How to use a component from another addon

### Using a field widget in an XML view

```xml
<!-- Simple — no colour -->
<field name="state" widget="cd_status_badge"/>

<!-- With a colour field -->
<field name="state" widget="cd_status_badge" options="{'color_field': 'color'}"/>
```

The `widget="cd_status_badge"` attribute is resolved against the `"fields"`
registry. The component is loaded automatically because `cleardeals_ui` is in
your addon's `depends`.

### Importing a component class in JS

Only needed when you are extending or composing a `cleardeals_ui` component
inside your own OWL component:

```js
import { CdStatusBadge } from "@cleardeals_ui/index";
```

The `@cleardeals_ui/` path alias is resolved by Odoo's asset bundler — no
webpack config needed.

---

## Component reference

### `cd_status_badge` — Status Badge

**File:** `static/src/fields/status_badge/`  
**Supported field types:** `selection`, `char`  
**Registry key:** `"cd_status_badge"` (fields registry)

Renders a pill badge showing the display value of a `selection` or `char`
field. For `selection` fields the stored key is automatically mapped to its
human-readable label. The badge is invisible when the field value is falsy.

**Props (view options):**

| Option | Type | Required | Description |
|---|---|---|---|
| `color_field` | `field` (integer) | No | Name of an integer field (0–11) that drives the badge colour class |

**Colour palette (0–11):**

| Index | Colour | Semantic use |
|---|---|---|
| 0 | Blue | Default / New |
| 1 | Orange | Warm / Pending |
| 2 | Green | Done / Confirmed |
| 3 | Red | Failed / Cancelled |
| 4 | Purple | Premium / Special |
| 5 | Pink | Hot lead |
| 6 | Teal | In progress |
| 7 | Yellow | Caution / Under review |
| 8 | Grey | Inactive / Archived |
| 9 | Indigo | Scheduled |
| 10 | Magenta | Flagged |
| 11 | Emerald | Closed-won |

**Example with colour-driven badge:**

In the model, add a `color` integer field:

```python
color = fields.Integer(string="Color", default=0)
```

In the view:

```xml
<field name="state"  widget="cd_status_badge" options="{'color_field': 'color'}"/>
<field name="color"  invisible="1"/>
```

In a `write` or `_compute_color` method, set `color` to the appropriate
palette index whenever `state` changes.

---

## Naming conventions

| Thing | Convention | Example |
|---|---|---|
| Component class | `CdPascalCase` | `CdStatusBadge` |
| Descriptor export | `cdCamelCaseField` / `cdCamelCaseWidget` | `cdStatusBadgeField` |
| Template name | `cleardeals_ui.PascalCase` | `cleardeals_ui.StatusBadge` |
| Registry key | `"cd_snake_case"` | `"cd_status_badge"` |
| CSS base class | `cd-kebab-case` | `cd-status-badge` |
| CSS modifier | `cd-kebab-case--modifier` | `cd-status-badge--color-0` |
| JS filename | `snake_case.js` | `status_badge.js` |
| Directory | `snake_case/` | `status_badge/` |

**Rationale for the `cd_` / `cd-` prefix:** Odoo loads all addons into a single
JS bundle and a single CSS namespace. Without a prefix, a class named
`"status_badge"` could collide with another addon or a future Odoo core
component. The `cd_` prefix namespaces every Cleardeals symbol.

---

## OWL conventions used in this library

This library targets **Odoo 19's bundled OWL version**. Do not import from
`owl` directly — always import from `@odoo/owl`:

```js
import { Component, useState, useRef } from "@odoo/owl";
```

| Pattern | Correct | Wrong |
|---|---|---|
| Reactive state | `useState({})` | `signal({})` |
| DOM reference | `useRef("el")` | `signal(null)` |
| Props declaration | `static props = {...}` | `props()` function |
| Default props | `static defaultProps = {...}` | inline defaults in destructuring |
| Module declaration | None needed | `/** @odoo-module **/` (removed in Odoo 19) |
| Translations | `_t("string")` from `@web/core/l10n/translation` | raw string literals |

---

## Installing / upgrading

**First install:**

```bash
docker exec odoo-dev-app odoo \
    --addons-path=/mnt/extra-addons/custom \
    -d cleardeals_19_dev \
    -i cleardeals_ui \
    --stop-after-init
```

**After adding or changing a component:**

JS, XML, and SCSS changes are picked up on the next browser hard-reload
(`Cmd+Shift+R`) when Odoo is running with `ODOO_DEV=all` (the default in the
dev container). You do not need to restart the server for pure frontend changes.

**After modifying `__manifest__.py`:**

Restart the Odoo container or run `-u cleardeals_ui`.

---

## Troubleshooting

**Badge renders with no text**

The field value is falsy (empty string, `False`, or `None`). This is intentional
— the component hides itself when there is nothing to display. Check your data.

**Badge renders but no colour**

Either `color_field` is not set in the view options, or the `color` field on the
record is `0` (which maps to blue — this is correct behaviour, not an error).

**`widget="cd_status_badge"` causes "field not found" error in the view**

The `cleardeals_ui` addon is not in the `depends` list of the addon that owns
the view, or `cleardeals_ui` is not installed on this database. Run the install
command above.

**New component not appearing / JS error "template not found"**

1. Check that the `t-name` in the XML file exactly matches `static template`
   in the JS class (case-sensitive).
2. Hard-reload the browser (`Cmd+Shift+R`) to flush the asset cache.
3. Check the browser console for the exact error — it will name the missing
   template.

**Changes to SCSS not appearing**

Odoo 19 compiles SCSS server-side and caches the result. Run:

```
Settings → Technical → User Interface → Assets → Clear cache
```

Or add `?debug=assets` to the URL which forces recompilation on every request.

---

## Related files

| File | Purpose |
|---|---|
| [static/src/index.js](static/src/index.js) | Barrel — all public exports |
| [static/src/fields/status_badge/status_badge.js](static/src/fields/status_badge/status_badge.js) | `CdStatusBadge` class |
| [static/src/fields/status_badge/status_badge.xml](static/src/fields/status_badge/status_badge.xml) | `cleardeals_ui.StatusBadge` template |
| [static/src/fields/status_badge/status_badge.scss](static/src/fields/status_badge/status_badge.scss) | 12-slot colour palette |
