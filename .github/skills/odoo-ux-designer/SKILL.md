---
name: odoo-ux-designer
description: >
  Designs every dimension of an Odoo feature end-to-end — the data model,
  field names, automation logic, and user interface — so that the result is
  both technically correct and genuinely pleasant for RMs and managers to use.
  Use this skill whenever a feature needs to be designed or reviewed at any
  level: what models to create, what to name fields, what to automate, how to
  structure the form view, what columns belong in the list view, what filters
  managers need, and what an RM should never have to do manually. Trigger on:
  "design this feature", "how should I build this", "what's the best way to
  implement", "design the UI for", "improve this view", "too many clicks",
  "what fields do I need", "how should this work", "make this easier", "what
  should be automatic", "review my model design", or any request about how
  something should be built, shown, or experienced in Odoo. Also trigger
  proactively on every new feature — implementation without UX design produces
  technically correct but practically unusable results. Always use this skill
  before writing any model, view, or feature code.
---

# Odoo Feature Design Intelligence

You design Odoo features end-to-end — from the first decision about what model
to create, through what to name every field, through what the system should do
automatically, to exactly what the RM sees when they open the form.

The measure of a good design is not whether it is technically elegant. It is
whether an RM can do their job faster, a manager can see problems immediately,
and a developer joining the team six months from now can understand every
decision without asking anyone.

Every decision you make — model name, field name, automation, view layout —
must be justified by one of these three outcomes.

---

## The five design dimensions

Every feature touches all five. Design them in order — each one constrains
the next.

```
Dimension 1 — DATA MODEL
What entities exist? What are their relationships?
This is the foundation. Wrong here = wrong everywhere.

Dimension 2 — FIELD DESIGN
What is each field named, typed, and constrained?
Names and types are permanent. Get them right before writing code.

Dimension 3 — AUTOMATION
What should the system do without the user having to think about it?
Every manual step that can be automated is a mistake waiting to happen.

Dimension 4 — INFORMATION ARCHITECTURE
What does each user see, when, and in what order?
The right data in the wrong order is still a bad UX.

Dimension 5 — INTERACTION DESIGN
How does the user actually operate the interface?
Clicks, forms, buttons, filters, bulk actions.

Dimension 6 — CUSTOM JAVASCRIPT (when XML is not enough)
What interactions require browser APIs, real-time updates, or custom
rendering that Odoo's XML views cannot express?
Always the last tool — only after exhausting XML options.
```

Read the relevant reference before designing each dimension:
- Data model → `references/standards/data-model-and-fields.md`
- Field design → `references/standards/data-model-and-fields.md`
- Automation → `references/standards/automation.md`
- Information architecture → `references/patterns/interaction-patterns.md`
- Interaction design → `references/patterns/interaction-patterns.md`
- Custom JavaScript → `references/standards/javascript-owl.md`

---

## Stage 1 — Understand the work before designing anything

Before any design decision, answer these:

**What is the user's actual job?**
Not what the feature does — what does the human being do all day?
An RM handles calls, qualifies leads, schedules visits, follows up.
A manager monitors pipeline health, spots problems, reassigns work.
Design for the job, not the feature.

**What is the most repetitive thing they do?**
The most repetitive task is the highest-value automation target.
If an RM manually writes the same type of remark 50 times a day,
that should be a selection field. If a manager re-assigns the same
unmatched leads every morning, that should be an automated rule.

**What mistake do they make most often?**
Good design prevents the most common mistake structurally, not through
training. If RMs forget to add remarks, the system should make remarks
contextually required. If duplicate leads are a problem, dedup belongs
in the create path, not in a manual review process.

**What do they not know they need?**
Users describe their current problems, not their optimal workflow.
Ask what happens after the task is done. What do they wish they could
see at a glance? What do they have to look up in two different places?

---

## Stage 2 — Data model design

Read: `references/standards/data-model.md`

The decisions that matter most:

**One model or two?**
A single model with a type field vs two separate models is the most
consequential early decision. Use a single model when:
- The records share 80%+ of their fields
- They appear in the same list views and reports
- Security rules apply identically to both

Use separate models when:
- Each type has significantly different fields
- They have fundamentally different lifecycles
- Users never think of them as the same thing

The `property.portal.listing` decision is the reference example:
one model with a `portal_name` Selection field, because all four portals
share the same structure and resolve through the same code path.

**What is the lifecycle?**
Every model has a lifecycle — the states a record moves through.
Define it completely before writing any field. Draw it explicitly:

```
leads.new:    new → assigned → [working with various statuses] → closed
property.base: active ← BQ sync → inactive (when service expires)
portal.listing: active → inactive (when listing removed from portal)
```

States that are not in the diagram do not belong in the model.

**What cascades on delete?**
Define `ondelete` for every `Many2one` before writing the model.
- `cascade` — child is meaningless without parent (portal listing without property)
- `set null` — child can exist without parent (lead without property)
- `restrict` — parent cannot be deleted while children exist (use sparingly)

Getting this wrong after deploy requires a migration.

---

## Stage 3 — Field design

Read: `references/standards/field-design.md`

**Naming — the rule that matters most**
A field name must describe what it stores, not how it is implemented.
`source` not `portal_name_field`. `is_active` not `active_flag`.
`listed_on` not `listing_creation_date_portal`.

A new developer should be able to read the model definition and understand
the domain without reading the implementation. Field names are the vocabulary
of your domain. Choose them like you are writing a dictionary.

**The field type hierarchy**
Choose the most constrained type that correctly represents the data:
- `Boolean` before `Selection` before `Char`
- `Integer` or `Float` before `Char` for numbers
- `Date` before `Datetime` when time of day is irrelevant
- `Many2one` before `Char` for references to other records
- `Selection` before `Char` for a fixed set of values

`Char` is always the lazy choice. It accepts anything and enforces nothing.
Every `Char` field should be questioned: is there a more constrained type?

**What is readonly and why**
Make a field readonly only when it is wrong for a user to change it:
- Computed fields (system calculates, user cannot override)
- Auto-filled portal data (portal sets it, RM should not change it)
- State fields managed by the system

Never make a field readonly because "it might be edited by accident".
That is the system failing to communicate, not the user failing to understand.

**What is required and when**
Hard-required (`required=True`) means the record cannot be saved without it.
Use for fields that make the record meaningless without a value.

Contextually-required means: required when a condition is true.
Use `@api.constrains` or form-level validation for these.

Never make a field required when the user might legitimately not know
the value at creation time. An RM creating a manual lead may not know
the property yet — `property_base_id` should not be required.

**Indexed fields**
Every field that appears in a search domain, a filter, a group-by, or
an `order` clause must have `index=True`. Check:
- `state`, `user_id`, `create_date` on `leads.new`
- `portal_name`, `portal_listing_id` on `property.portal.listing`
- `is_active`, `rm_user_id` on `property.base`

Un-indexed search fields on tables with 5000+ rows cause slow views.

---

## Stage 4 — Automation design

Read: `references/standards/automation.md`

**The automation hierarchy**
Order of preference — use the highest-level mechanism that works:

```
1. Field defaults (default= on the field)
   Requires no code, no override, no cron.
   Use for: state, user_id, is_active, dates

2. Computed fields (compute=)
   Automatic, reactive, no user action required.
   Use for: display names, derived values, aggregates, related fields

3. ORM overrides (create(), write())
   Runs on every create/write, synchronous, part of the transaction.
   Use for: business rules, stamping first_contact_datetime,
   state transitions, dedup checks

4. Automated actions (ir.actions.server / base_automation)
   Triggered by events (record creation, field change, time-based).
   Use for: notifications, scheduled follow-ups, cross-model updates

5. Scheduled actions / crons
   Asynchronous, runs on a schedule.
   Use for: BQ sync, batch processing, periodic cleanup,
   webhook dispatch

6. Manual user action
   The user explicitly clicks a button.
   Use for: actions that require human confirmation or judgment
   Use as a last resort — every manual step is an error opportunity
```

**The automation question**
For every step in a user's workflow, ask:
"Why does a human need to do this?"

If the answer is "because the system doesn't know X yet" → fix the system.
If the answer is "because judgment is required" → keep it manual.
If the answer is "that's just how it works" → automate it.

**Automation in the Cleardeals lead pipeline**
The reference implementation of well-designed automation:

```
Portal lead arrives via webhook
  ↓ [system] create() called with state='new', source='MagicBricks'
  ↓ [system] create_lead_if_not_duplicate() deduplicates automatically
  ↓ [system] _process_lead_logic() finds property + RM, sets state='assigned'
  ↓ [system] _cron_reprocess_unassigned_leads() catches failures every 4 hours
  ↓ [system] _cron_send_new_lead_webhooks() dispatches to n8n every minute
  ↓ [RM] Opens lead, sees it already assigned to them with property populated
  ↓ [RM] Calls client, updates current_status and remarks (2 actions)
  ↓ [system] first_contact_datetime stamped automatically on first status change
```

The RM's job is calling clients and understanding their needs. Everything
else is automated. This is the bar for every new feature.

**What to automate in new features**
When designing a new feature, list every step the user would have to take
manually. Then eliminate as many as possible:

- Defaults that can be inferred → use `default=` or `default_get()`
- Values that derive from other values → use `compute=`
- Assignments that follow a rule → use `write()` override or automated action
- Notifications → use `message_post()` or n8n webhook
- State transitions that follow from an action → trigger in `write()`
- Time-based cleanup → use a cron

---

## Stage 5 — Information architecture

Read: `references/standards/information-architecture.md`

**The fold line principle**
Everything a user needs for their primary task must be visible without
scrolling or clicking a tab. On a standard laptop in Odoo, the fold line
is approximately: header + one two-column group of 6–8 fields.

Above the fold: identity fields + primary action fields
Below the fold: secondary information, context, history
In tabs: sub-tasks, manager-only data, technical fields

**The three-second rule**
A user opening a record must be able to answer "what is this and what
do I need to do?" in three seconds. Test this literally: open the view,
start a timer, see if the answer is obvious.

If the record's name, state, and primary action are not all visible in
three seconds, the information hierarchy is wrong.

**Tab design — tasks not overflow**
A tab's name must describe a user task, not a category:
- "Recommended Properties" ✓ — a task the RM does
- "Site Visit" ✓ — a sub-task with its own fields
- "Portal Listings" ✓ — a management task
- "More Information" ✗ — not a task, just overflow
- "Details" ✗ — not a task, just a generic label

If you cannot name the tab as a task the user performs, the fields in
it probably belong in the main form.

**Progressive disclosure**
Show context-dependent fields only when they are relevant:

```xml
<!-- Show site visit date only when status makes it relevant -->
<field name="site_visit_date"
       invisible="current_status not in
                  ('site_visit_scheduled', 'site_visit_done',
                   'rescheduled')"/>

<!-- Show feedback only after the visit is done -->
<field name="feedback_site_visit_done"
       invisible="current_status != 'site_visit_done'"/>
```

Every field visible when it is not relevant is noise that slows the user.

---

## Stage 6 — Interaction design

Read: `references/patterns/interaction-patterns.md`

**The 3-click rule**
Any action an RM performs more than once per day must complete in
3 clicks from the list view. Count them:
1. Click a record to open it
2. Click a field or button to act
3. Save

If the primary task requires more than 3 clicks, the design is wrong.

**The right view type for the right task**

| User task | Right view | Wrong view |
|---|---|---|
| RM processes their lead queue | List view (scan) + Form (act) | Kanban (too visual) |
| Manager monitors pipeline | List with group-by RM | Form (one at a time) |
| Manager reassigns bulk leads | List with bulk action | Form (one at a time) |
| RM sees lead status distribution | Kanban by current_status | Pivot (too abstract) |
| Manager checks weekly numbers | Pivot / Graph | List (too granular) |

**Defaults are UX design**
The default state of every view when a user first opens it is a design
decision. Get it wrong and the user spends their first 10 seconds
correcting the view before they can do any work.

For every `ir.actions.act_window`, set a context that reflects what the
user actually wants to see when they arrive:

```python
# RM arrives and sees their own unresolved leads — not 6000 total
'context': {
    'search_default_my_leads': 1,
    'search_default_assigned': 1,
}

# Manager arrives and sees all leads grouped by RM
'context': {
    'search_default_group_rm': 1,
}
```

**What should never require a click**
- Knowing who a lead is assigned to (visible in the list)
- Knowing a lead's current status (decoration-* colours + column)
- Knowing if a property is expired (decoration-muted)
- Knowing if a lead has been contacted (first_contact_datetime in list)

If a manager has to open a record to find any of these, add a column.

---

## Stage 7 — Custom JavaScript design

Read: `references/standards/javascript-owl.md`

Only reach this stage if Dimensions 1–5 have been completed and a specific
interaction has been identified that XML views cannot handle. JavaScript
is never the starting point — it is the answer to a specific limitation.

**The JavaScript decision gate**

Before writing any JavaScript, answer:
1. Is there an Odoo built-in widget that handles this? (`widget="statusbar"`,
   `widget="boolean_toggle"`, `widget="many2one_avatar_user"`, etc.)
2. Is there an XML attribute that expresses this? (`invisible=`, `readonly=`,
   `decoration-*`, `optional=`, `groups=`)
3. Is there a Python computed field that would make this unnecessary?

If the answer to all three is "no" — then JavaScript is justified.

**The four legitimate JavaScript use cases in this codebase**

```
1. Client actions — one-click multi-step browser operations
   Example: WhatsApp button (clipboard + deep link in one click)
   Pattern: ir.actions.client + registry "actions" + OWL component

2. Custom field widgets — rendering a field differently from all built-ins
   Example: portal_listing_count as a coloured badge
   Pattern: registry "fields" + OWL component + XML template

3. Live updates — real-time list refresh from bus notifications
   Example: RM's lead list showing new leads without page refresh
   Pattern: bus_service subscription + patch(ListController)

4. Dashboards — manager summaries mixing data from multiple models
   Example: pipeline overview with clickable stat cards
   Pattern: ir.actions.client + OWL component + orm.readGroup()
```

Everything else is achievable in XML. If a use case does not fit one
of these four patterns, question whether JavaScript is actually needed.

---

## Output format for every design task

Produce all seven in order. Never skip one.

### 1. Design rationale (the non-obvious decisions)
What you decided and why. Focus on decisions that could have gone
differently. If JavaScript was chosen over XML, explain specifically
which XML limitation made JavaScript necessary.

### 2. Data model definition
Complete Python model with every field, its type, constraints, help text,
and index. Group with separator comments. Include `_sql_constraints` and
`ondelete` on every `Many2one`.

### 3. Automation specification
Every automated behaviour — defaults, computed fields, ORM overrides,
automated actions, crons — with the exact trigger and the exact outcome.
Express as: "When [event], the system automatically [action], so the
user never has to [manual step]."

### 4. View XML
Complete, deployable XML for every view the feature needs.
Form + list + search as a minimum. Kanban if the task warrants it.
Every view must be a complete file, not a snippet.

### 5. JavaScript files (only when Stage 7 determined they are needed)
Complete `.js`, `.xml` template, and `.scss` files.
Include the manifest `assets` entry.
Every file must be complete and deployable — no snippets.
Every component must have a JSDoc comment explaining:
  - What it does and why JavaScript was needed
  - What Python method or context it receives data from
  - The exact props it accepts
  - Any services it uses and why

### 6. Performance notes
Every field with a performance implication. Every One2many in a list
that should be replaced with a count. Every missing index. Every
default filter that prevents a full-table load. Every JavaScript ORM
call that should use `readGroup` instead of `searchRead` + JS counting.

### 7. What to verify
Specific, testable things to confirm after implementation.
Written as: "[User role] should be able to [action] and see [result]."
For JavaScript: include browser-level verification — "Opening the
WhatsApp button in a browser without HTTPS should show a warning toast,
not a silent failure."

---

## Cleardeals design conventions

These are the established patterns. Follow them for consistency — a user
who learned the system in one module should not have to re-learn it elsewhere.

**Naming conventions**
```
State fields:    state (not status, not lead_state)
Active toggle:   is_active (property.base uses active for Odoo archiving)
Source field:    source (not portal_name, not origin)
RM field:        rm_user_id (properties) / user_id (leads)
Portal ID:       portal_listing_id (not portal_id, not listing_id)
Label field:     listing_label (not name, not description)
Tag field:       property_tag (the internal short code)
```

**The source field distinction**
`bool(record.source)` distinguishes portal leads from manual leads.
Any new feature that needs to behave differently for manual vs portal
leads uses this check. Document it wherever `source` is referenced.

**Lead status colours in list views**
```
state='new'      → decoration-danger   (red — needs attention)
state='assigned' → decoration-success  (green — being handled)
state='failed'   → decoration-muted    (grey — not actionable)
```

**The manager-only gate**
Always `groups="properties.group_property_manager"` on:
- Portal listing tabs and fields
- Internal notes and process logs
- Migration and sync status fields
- Raw data dumps and technical fields
- Financial or commission-related data

Never mix manager-only fields with RM-facing fields in the same group.
The `groups=` attribute must be on the `<page>` or `<group>` element,
not on individual `<field>` elements within it — otherwise the label
is hidden but the field space is still reserved.

**Phone and WhatsApp pattern**
Phone number display always uses `phone_whatsapp_html` (computed HTML field
with embedded WhatsApp link). The raw `phone` field is below it for copying.
The `action_whatsapp_with_copy` button fires the client action that copies
the message and opens WhatsApp in one click.

**New record banners**
Time-sensitive status uses `alert-success` (new), `alert-warning` (expiring),
`alert-danger` (expired). Always with `invisible=` condition. Always `mb-0`.