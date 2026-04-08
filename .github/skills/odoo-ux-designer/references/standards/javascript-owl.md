# Custom JavaScript and OWL Component Reference

## When to use JavaScript vs XML

This is the most important decision in Odoo frontend work. JavaScript adds
real complexity — testing burden, upgrade risk, and a steeper learning curve.
Never reach for JavaScript when XML achieves the same result.

```
Use pure XML when:
  ✓ Displaying and editing standard model fields
  ✓ Conditional visibility with invisible= or groups=
  ✓ Standard form / list / kanban / search views
  ✓ Button actions calling Python methods via type="object"
  ✓ Status bars, toggles, many2one dropdowns, date pickers
  ✓ Chatter, activity tracking, smart buttons

Use JavaScript (OWL) when:
  ✓ The interaction cannot be expressed declaratively in XML at all
  ✓ A custom field widget needs to render differently from all built-ins
  ✓ Real-time UI updates from bus notifications (live lead counter)
  ✓ Multi-step in-form wizard with complex local state
  ✓ Clipboard + external URL in one user action (WhatsApp button)
  ✓ A dashboard with charts, live counters, maps, or D3 visualisations
  ✓ Drag-and-drop between columns or within a list
  ✓ A custom many2one widget with preview cards, not just a dropdown
  ✓ Inline editing that bypasses the standard form save flow

Ask yourself: "Is there an Odoo widget or XML attribute that does this?"
If yes — use it. JavaScript is the last resort, not the first tool.
```

---

## Odoo 17/19 JavaScript architecture

Understanding the architecture prevents the most common mistakes.

```
Odoo Web Client (browser)
├── OWL framework (Odoo's own React-like component system)
│   ├── Component — base class for all UI components
│   ├── useState, useRef, onMounted, onWillUnmount — hooks
│   └── xml`...` — tagged template literal for inline templates
│
├── Services (global singletons, injected via useService)
│   ├── orm — RPC calls to Python models
│   ├── notification — toast messages
│   ├── dialog — modal dialogs
│   ├── action — navigate / open actions
│   ├── bus_service — real-time pub/sub
│   └── rpc — low-level HTTP calls
│
├── Field Widgets (registered in the "fields" registry)
│   ├── Extend AbstractField for custom field rendering
│   └── Register with registry.category("fields").add(name, Component)
│
├── Client Actions (registered in the "actions" registry)
│   ├── Full-screen or dialog components triggered by ir.actions.client
│   └── Register with registry.category("actions").add(tag, Component)
│
└── View Extensions (patches to existing views)
    ├── patch() from @web/core/utils/patch
    └── Use sparingly — patches break on Odoo upgrades
```

---

## Module structure for custom JavaScript

Every piece of custom JavaScript belongs in a static folder with this structure:

```
custom_addons/{module}/
├── static/
│   ├── src/
│   │   ├── js/
│   │   │   ├── components/          ← reusable OWL components
│   │   │   │   └── lead_status_badge.js
│   │   │   ├── fields/              ← custom field widgets
│   │   │   │   └── portal_listing_badge.js
│   │   │   ├── actions/             ← client actions
│   │   │   │   └── whatsapp_action.js
│   │   │   └── views/               ← view extensions (use sparingly)
│   │   │       └── lead_list_patch.js
│   │   ├── xml/                     ← OWL templates
│   │   │   ├── lead_status_badge.xml
│   │   │   └── whatsapp_action.xml
│   │   └── scss/                    ← styles
│   │       └── leads.scss
│   └── tests/
│       └── js/
│           └── test_lead_status_badge.js
└── __manifest__.py
```

Register everything in `__manifest__.py`:

```python
"assets": {
    "web.assets_backend": [
        # Order matters — JS before XML that references it
        "leads/static/src/js/actions/whatsapp_action.js",
        "leads/static/src/xml/whatsapp_action.xml",
        "leads/static/src/js/fields/portal_listing_badge.js",
        "leads/static/src/xml/portal_listing_badge.xml",
        "leads/static/src/js/components/lead_status_badge.js",
        "leads/static/src/xml/lead_status_badge.xml",
        "leads/static/src/scss/leads.scss",
    ],
    "web.assets_tests": [
        "leads/static/tests/js/**/*.js",
    ],
},
```

---

## Pattern 1 — Client action (the WhatsApp button pattern)

This is the established Cleardeals pattern. Use it as the template for
any action that needs to do something JavaScript must handle — clipboard,
external URLs, device APIs, multi-step flows with local state.

**How it works:**
1. Python method returns `{"type": "ir.actions.client", "tag": "my_tag", "context": {...}}`
2. Odoo router looks up the tag in the "actions" registry
3. The registered OWL component mounts and receives `props.action`

```javascript
// static/src/js/actions/whatsapp_action.js
/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted } from "@odoo/owl";

/**
 * WhatsApp client action: copy pre-filled message to clipboard,
 * then open the WhatsApp deep link to launch the desktop app.
 *
 * Triggered by: leads.new.action_whatsapp_with_copy()
 * Context shape: { whatsapp_url: str, message_text: str }
 *
 * Why a client action instead of a button onclick?
 * Because we need two browser APIs (clipboard + window.location)
 * that cannot be called from Python. The Python method builds the
 * message and URL; the client action executes the browser side.
 */
export class WhatsappWithCopyAction extends Component {
    static template = "leads.WhatsappWithCopyAction";
    static props = ["action", "onClose?"];

    setup() {
        this.notification = useService("notification");
        this.whatsappUrl = this.props.action.context.whatsapp_url;
        this.messageText = this.props.action.context.message_text;

        onMounted(async () => {
            await this._execute();
        });
    }

    async _execute() {
        try {
            // Step 1: copy message to clipboard
            await navigator.clipboard.writeText(this.messageText);

            // Step 2: open WhatsApp deep link
            window.location.href = this.whatsappUrl;

            // Step 3: show confirmation toast
            this.notification.add("Message copied. Opening WhatsApp...", {
                type: "success",
                sticky: false,
            });

            // Step 4: close the action dialog if one was opened
            this.props.onClose?.();

        } catch (error) {
            // Clipboard API requires HTTPS and user gesture
            // Fall back to showing the message for manual copy
            this.notification.add(
                "Could not copy automatically. Please copy the message manually.",
                { type: "warning", sticky: true }
            );
            console.error("WhatsApp action failed:", error);
        }
    }
}

// Register with the tag used in the Python ir.actions.client return value
registry.category("actions").add("whatsapp_with_copy", WhatsappWithCopyAction);
```

```xml
<!-- static/src/xml/whatsapp_action.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    <!--
        Template for WhatsappWithCopyAction.
        This renders nothing visible — the action executes in onMounted
        and closes itself. The empty div is required for OWL to mount.
    -->
    <t t-name="leads.WhatsappWithCopyAction">
        <div/>
    </t>
</templates>
```

---

## Pattern 2 — Custom field widget

Use when a field needs to render differently from all available built-in
widgets. The most common cases: coloured badges, custom formatters,
inline action buttons next to a field value, interactive sparklines.

```javascript
// static/src/js/fields/portal_listing_badge.js
/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * PortalListingBadgeWidget — renders portal_listing_count as a coloured badge.
 *
 * Usage in XML view:
 *   <field name="portal_listing_count" widget="portal_listing_badge"/>
 *
 * Renders:
 *   Green badge when count > 0: "3 listings"
 *   Grey badge when count = 0: "No listings"
 *
 * Why not use a computed Char field and a regular text display?
 * Because the colour coding requires DOM manipulation that cannot be
 * expressed through field formatting alone in Odoo's standard widgets.
 */
export class PortalListingBadgeWidget extends Component {
    static template = "properties.PortalListingBadgeWidget";
    static props = { ...standardFieldProps };

    get count() {
        return this.props.record.data[this.props.name] || 0;
    }

    get badgeClass() {
        return this.count > 0 ? "badge bg-success" : "badge bg-secondary";
    }

    get label() {
        if (this.count === 0) return "No listings";
        return `${this.count} listing${this.count !== 1 ? "s" : ""}`;
    }
}

// "fields" registry maps widget name → component
registry.category("fields").add("portal_listing_badge", {
    component: PortalListingBadgeWidget,
    supportedTypes: ["integer"],         // which field types this widget supports
    extractProps: ({ attrs }) => ({}),   // additional props from XML attributes
});
```

```xml
<!-- static/src/xml/portal_listing_badge.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    <t t-name="properties.PortalListingBadgeWidget">
        <span t-attf-class="{{ component.badgeClass }}"
              t-esc="component.label"/>
    </t>
</templates>
```

**Using the widget in a view:**

```xml
<!-- In property_base_views.xml list view -->
<field name="portal_listing_count"
       widget="portal_listing_badge"
       string="Listings"
       optional="show"/>
```

---

## Pattern 3 — Reusable OWL component

Use for UI elements that appear in multiple places and have their own
internal state or logic. Not a field widget — a standalone component
embedded in a template or mounted in a view.

```javascript
// static/src/js/components/lead_status_badge.js
/** @odoo-module **/

import { Component } from "@odoo/owl";

/**
 * LeadStatusBadge — displays a lead's state with colour coding.
 *
 * Props:
 *   state (string): "new" | "assigned" | "failed"
 *   label (string, optional): override the display label
 *
 * Usage in OWL template:
 *   <LeadStatusBadge state="record.data.state"/>
 *
 * This is NOT a field widget — it is a display component for use
 * inside other OWL templates, not directly in XML form views.
 */
export class LeadStatusBadge extends Component {
    static template = "leads.LeadStatusBadge";
    static props = {
        state: { type: String },
        label: { type: String, optional: true },
    };

    // Map state values to Bootstrap badge classes
    static STATE_CLASSES = {
        new: "badge bg-danger",
        assigned: "badge bg-success",
        failed: "badge bg-secondary",
    };

    // Map state values to human labels
    static STATE_LABELS = {
        new: "Unassigned",
        assigned: "Assigned",
        failed: "Failed",
    };

    get badgeClass() {
        return LeadStatusBadge.STATE_CLASSES[this.props.state] || "badge bg-light";
    }

    get displayLabel() {
        return this.props.label || LeadStatusBadge.STATE_LABELS[this.props.state] || this.props.state;
    }
}
```

```xml
<!-- static/src/xml/lead_status_badge.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    <t t-name="leads.LeadStatusBadge">
        <span t-attf-class="{{ component.badgeClass }}"
              t-esc="component.displayLabel"/>
    </t>
</templates>
```

---

## Pattern 4 — Bus notification listener (live updates)

Use when a list view should refresh automatically when records change —
for example, the RM's lead list showing new incoming leads in real time
without a page refresh.

```javascript
// static/src/js/views/lead_list_live.js
/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onWillUnmount } from "@odoo/owl";

/**
 * Patch the ListController for leads.new to auto-refresh on bus events.
 *
 * When a new portal lead is created (via webhook/cron), the backend
 * sends a bus notification on the "leads.new" channel. This patch
 * subscribes to that channel and triggers a reload when a "create"
 * event arrives, so the RM's list updates without manual refresh.
 *
 * Why patch ListController instead of creating a new view?
 * Because we want to augment the existing list view behaviour, not
 * replace it. Patching is appropriate here — we are adding a side
 * effect (subscription) not changing the view's core logic.
 *
 * Upgrade risk: this patch will break if Odoo renames or restructures
 * ListController. Re-verify after each Odoo major version upgrade.
 */
patch(ListController.prototype, {
    setup() {
        super.setup();

        // Only activate on the leads.new model
        if (this.props.resModel !== "leads.new") return;

        const busService = useService("bus_service");

        onMounted(() => {
            busService.subscribe("leads.new", (notification) => {
                // Reload the list on new lead creation
                if (notification.event === "create") {
                    this.model.load();
                }
            });
        });

        onWillUnmount(() => {
            busService.unsubscribe("leads.new");
        });
    },
});
```

**Important:** patches must be included in assets unconditionally.
They cannot be conditionally applied per-view in XML.
The `if (this.props.resModel !== "leads.new") return;` guard inside
the patch limits its effect to only the intended model.

---

## Pattern 5 — ORM calls from JavaScript

Use `useService("orm")` for any data fetch or write from a component.
Never use `fetch()` directly for Odoo model operations.

```javascript
/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

/**
 * LeadQuickStats — shows a manager's pipeline summary without loading
 * the full list view. Used in a dashboard or manager home screen.
 *
 * Fetches aggregated data directly from leads.new via search_read,
 * rendering counts by state. Updates every 5 minutes automatically.
 */
export class LeadQuickStats extends Component {
    static template = "leads.LeadQuickStats";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            stats: { new: 0, assigned: 0, failed: 0 },
            error: null,
        });

        onMounted(async () => {
            await this._loadStats();
            // Refresh every 5 minutes
            this._refreshInterval = setInterval(() => this._loadStats(), 5 * 60 * 1000);
        });
    }

    async _loadStats() {
        try {
            // Use orm.readGroup for aggregated data — much more efficient
            // than fetching all records and counting in JavaScript
            const groups = await this.orm.readGroup(
                "leads.new",
                [],                  // domain: all records
                ["state"],           // group by state
                ["state"],           // fields to fetch
            );

            const stats = { new: 0, assigned: 0, failed: 0 };
            for (const group of groups) {
                if (group.state in stats) {
                    stats[group.state] = group.state_count;
                }
            }

            Object.assign(this.state, { loading: false, stats, error: null });

        } catch (error) {
            Object.assign(this.state, {
                loading: false,
                error: "Failed to load stats. Please refresh.",
            });
            console.error("LeadQuickStats load failed:", error);
        }
    }

    onWillUnmount() {
        clearInterval(this._refreshInterval);
    }
}
```

**ORM service methods:**

```javascript
// Read records
const records = await this.orm.searchRead(
    "leads.new",                    // model
    [["state", "=", "new"]],        // domain
    ["name", "phone", "user_id"],   // fields
    { limit: 50, order: "create_date desc" }
);

// Aggregate
const groups = await this.orm.readGroup(
    "leads.new",
    [],
    ["current_status"],
    ["current_status"],
);

// Write
await this.orm.write("leads.new", [recordId], { current_status: "lead" });

// Create
const newId = await this.orm.create("leads.new", { name: "Test", phone: "9876543210" });

// Call a Python method
const result = await this.orm.call(
    "leads.new",         // model
    "_process_lead_logic",  // method name
    [[recordId]],        // args: list of IDs as first argument
    {},                  // kwargs
);

// Read many2one display names efficiently
const names = await this.orm.call(
    "leads.new",
    "name_get",
    [[1, 2, 3]],
);
```

---

## Pattern 6 — Custom dashboard / home action

Use when a manager needs a summary view that is not a standard Odoo
list or kanban — live counters, charts, a property map, or a pipeline
overview that mixes data from multiple models.

```javascript
// static/src/js/actions/manager_dashboard.js
/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

/**
 * ManagerDashboard — pipeline overview for managers.
 *
 * Registered as client action tag "leads.manager_dashboard".
 * Triggered by: a menu item with action type ir.actions.client.
 *
 * Shows:
 *   - Total leads by state (counts, not individual records)
 *   - Site visits scheduled today
 *   - Uncontacted assigned leads (assigned but first_contact_datetime = False)
 *   - Per-RM breakdown of lead counts
 *
 * Data is loaded once on mount and can be refreshed manually.
 * Auto-refresh is NOT implemented here to avoid RPC load — managers
 * refresh the page when they need current data.
 */
export class ManagerDashboard extends Component {
    static template = "leads.ManagerDashboard";
    static props = ["action", "onClose?"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading: true,
            pipelineStats: [],
            siteVisitsToday: 0,
            uncontacted: 0,
            rmBreakdown: [],
        });

        onMounted(async () => {
            await this._loadAll();
        });
    }

    async _loadAll() {
        const today = new Date().toISOString().split("T")[0];

        const [pipeline, siteVisits, uncontacted, byRm] = await Promise.all([
            // Pipeline by state
            this.orm.readGroup("leads.new", [], ["state"], ["state"]),

            // Site visits today
            this.orm.searchCount("leads.new", [
                ["site_visit_date_only", "=", today],
            ]),

            // Assigned but never contacted
            this.orm.searchCount("leads.new", [
                ["state", "=", "assigned"],
                ["first_contact_datetime", "=", false],
            ]),

            // Per-RM breakdown
            this.orm.readGroup(
                "leads.new",
                [["state", "=", "assigned"]],
                ["user_id"],
                ["user_id"],
                { orderby: "user_id_count desc", limit: 10 }
            ),
        ]);

        Object.assign(this.state, {
            loading: false,
            pipelineStats: pipeline,
            siteVisitsToday: siteVisits,
            uncontacted: uncontacted,
            rmBreakdown: byRm,
        });
    }

    // Navigate to a filtered list view on card click
    openLeadList(domain, context = {}) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Leads",
            res_model: "leads.new",
            view_mode: "list,form",
            domain: domain,
            context: context,
        });
    }

    onRefresh() {
        Object.assign(this.state, { loading: true });
        this._loadAll();
    }
}

registry.category("actions").add("leads.manager_dashboard", ManagerDashboard);
```

```xml
<!-- static/src/xml/manager_dashboard.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    <t t-name="leads.ManagerDashboard">
        <div class="o_action o_leads_dashboard">

            <!-- Loading state -->
            <div t-if="component.state.loading" class="text-center py-5">
                <i class="fa fa-spinner fa-spin fa-2x text-muted"/>
                <p class="text-muted mt-2">Loading pipeline...</p>
            </div>

            <!-- Dashboard content -->
            <div t-else="" class="container-fluid py-3">

                <!-- Header row -->
                <div class="d-flex justify-content-between align-items-center mb-4">
                    <h4 class="mb-0">Pipeline Overview</h4>
                    <button class="btn btn-sm btn-outline-secondary"
                            t-on-click="onRefresh">
                        <i class="fa fa-refresh me-1"/> Refresh
                    </button>
                </div>

                <!-- Stat cards row -->
                <div class="row g-3 mb-4">

                    <!-- Unassigned leads — clickable to filtered list -->
                    <div class="col-md-3">
                        <div class="card border-danger h-100 cursor-pointer"
                             t-on-click="() => openLeadList([['state', '=', 'new']])">
                            <div class="card-body text-center">
                                <h2 class="text-danger mb-1">
                                    <t t-foreach="component.state.pipelineStats"
                                       t-as="group"
                                       t-key="group.state">
                                        <t t-if="group.state === 'new'"
                                           t-esc="group.state_count"/>
                                    </t>
                                </h2>
                                <p class="text-muted mb-0 small">Unassigned</p>
                            </div>
                        </div>
                    </div>

                    <!-- Site visits today -->
                    <div class="col-md-3">
                        <div class="card border-info h-100 cursor-pointer"
                             t-on-click="() => openLeadList(
                                 [['site_visit_date_only', '=', new Date().toISOString().split('T')[0]]]
                             )">
                            <div class="card-body text-center">
                                <h2 class="text-info mb-1">
                                    <t t-esc="component.state.siteVisitsToday"/>
                                </h2>
                                <p class="text-muted mb-0 small">Site Visits Today</p>
                            </div>
                        </div>
                    </div>

                    <!-- Uncontacted leads -->
                    <div class="col-md-3">
                        <div class="card border-warning h-100 cursor-pointer"
                             t-on-click="() => openLeadList([
                                 ['state', '=', 'assigned'],
                                 ['first_contact_datetime', '=', false]
                             ])">
                            <div class="card-body text-center">
                                <h2 class="text-warning mb-1">
                                    <t t-esc="component.state.uncontacted"/>
                                </h2>
                                <p class="text-muted mb-0 small">Never Contacted</p>
                            </div>
                        </div>
                    </div>

                </div>

                <!-- Per-RM breakdown table -->
                <div class="card">
                    <div class="card-header">
                        <strong>Assigned leads by RM</strong>
                    </div>
                    <div class="card-body p-0">
                        <table class="table table-sm table-hover mb-0">
                            <thead>
                                <tr>
                                    <th>RM</th>
                                    <th class="text-end">Assigned leads</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr t-foreach="component.state.rmBreakdown"
                                    t-as="row"
                                    t-key="row.user_id[0]"
                                    class="cursor-pointer"
                                    t-on-click="() => openLeadList(
                                        [['user_id', '=', row.user_id[0]], ['state', '=', 'assigned']]
                                    )">
                                    <td t-esc="row.user_id[1]"/>
                                    <td class="text-end">
                                        <span class="badge bg-primary">
                                            <t t-esc="row.user_id_count"/>
                                        </span>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

            </div>
        </div>
    </t>
</templates>
```

**Triggering the dashboard from a menu item:**

```xml
<!-- In the module's data XML -->
<record id="action_manager_dashboard" model="ir.actions.client">
    <field name="name">Pipeline Dashboard</field>
    <field name="tag">leads.manager_dashboard</field>
</record>

<menuitem id="menu_manager_dashboard"
          name="Dashboard"
          parent="menu_leads_root"
          action="action_manager_dashboard"
          groups="properties.group_property_manager"
          sequence="1"/>
```

---

## Pattern 7 — Notification service (toasts)

```javascript
const notification = useService("notification");

// Success toast (auto-dismisses after 4 seconds)
notification.add("Lead assigned successfully.", {
    type: "success",
    sticky: false,
});

// Warning toast (stays until dismissed)
notification.add("Portal ID not found. Lead assigned to default RM.", {
    type: "warning",
    sticky: true,
});

// Error toast
notification.add("Failed to sync. Please try again.", {
    type: "danger",
    sticky: true,
});

// Toast with action button
notification.add("Duplicate lead detected.", {
    type: "warning",
    sticky: true,
    buttons: [{
        name: "View existing lead",
        primary: true,
        onClick: () => {
            this.action.doAction({
                type: "ir.actions.act_window",
                res_model: "leads.new",
                res_id: existingLeadId,
                views: [[false, "form"]],
            });
        },
    }],
});
```

---

## Pattern 8 — Dialog service (confirmation + custom dialogs)

```javascript
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

// In component setup()
this.dialog = useService("dialog");

// Simple confirmation
async onDeleteListing() {
    await new Promise((resolve, reject) => {
        this.dialog.add(ConfirmationDialog, {
            title: "Remove Portal Listing",
            body: "This listing will be marked inactive. Leads on this ID will still resolve to the property.",
            confirm: resolve,
            cancel: reject,
        });
    });
    // User confirmed — proceed with the delete
    await this.orm.write("property.portal.listing", [this.listingId], { active: false });
}
```

---

## SCSS patterns for custom Odoo styling

```scss
// static/src/scss/leads.scss

// Always scope to your module's root element to avoid polluting global styles
.o_leads_dashboard {

    // Dashboard stat cards with hover effect
    .card {
        transition: transform 0.15s ease, box-shadow 0.15s ease;

        &.cursor-pointer:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
        }
    }

    // RM breakdown table rows
    .table tbody tr.cursor-pointer:hover {
        background-color: var(--bs-table-hover-bg);
        cursor: pointer;
    }
}

// WhatsApp button — consistent green across all lead forms
// Scoped to the form view wrapper
.o_form_view .btn-whatsapp {
    background-color: #25D366;
    border-color: #25D366;
    color: white;

    &:hover, &:focus {
        background-color: #1ebe5d;
        border-color: #1ebe5d;
        color: white;
    }

    i.fa-whatsapp {
        font-size: 1em;
    }
}

// New lead highlight in list view
// Odoo applies .o_data_row_selected on decoration classes
// Use CSS variables so it respects dark mode
.o_list_view .o_data_row.o_leads_is_new td {
    background-color: var(--bs-success-bg-subtle);
    color: var(--bs-success-text-emphasis);
}
```

---

## Common mistakes and how to avoid them

**Mistake 1: Calling Python methods via fetch() instead of orm service**
```javascript
// WRONG — bypasses Odoo's CSRF protection and session handling
const response = await fetch("/web/dataset/call_kw", { ... });

// RIGHT — use the orm service
const result = await this.orm.call("leads.new", "my_method", [[id]], {});
```

**Mistake 2: Mutating props directly**
```javascript
// WRONG — OWL props are immutable
this.props.record.data.state = "assigned";

// RIGHT — use orm.write() and let the view reload
await this.orm.write("leads.new", [this.props.record.resId], { state: "assigned" });
await this.props.record.load();
```

**Mistake 3: Not cleaning up subscriptions**
```javascript
// WRONG — memory leak, multiple subscriptions accumulate
onMounted(() => {
    busService.subscribe("leads.new", handler);
    // no cleanup
});

// RIGHT
onMounted(() => { busService.subscribe("leads.new", handler); });
onWillUnmount(() => { busService.unsubscribe("leads.new"); });
```

**Mistake 4: Using patch() for something achievable in XML**
```javascript
// WRONG — patching to add a custom column that XML handles fine
patch(ListRenderer.prototype, { /* ... */ });

// RIGHT — add the column in the XML view definition
<field name="my_field" optional="show"/>
```

**Mistake 5: Hardcoding model names as strings in multiple places**
```javascript
// WRONG — if model is renamed, must find all occurrences
await this.orm.searchRead("leads.new", ...);
busService.subscribe("leads.new", handler);

// RIGHT — define once as a constant
const LEAD_MODEL = "leads.new";
await this.orm.searchRead(LEAD_MODEL, ...);
busService.subscribe(LEAD_MODEL, handler);
```