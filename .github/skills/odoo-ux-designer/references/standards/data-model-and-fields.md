# Data Model and Field Design Standards

---

## Data model design

### The single-vs-multiple model decision

This is the most consequential early decision. Use this test:

```
Ask: "Does a [Type A] and a [Type B] ever appear in the same list,
      share the same security rules, and share 80%+ of their fields?"

Yes to all → single model with a type Selection field
No to any  → separate models
```

Real decision from this codebase:
```
"Should 99acres listings and MagicBricks listings be separate models?"

Same list? Yes — Portal Listings tab shows all four together
Same security? Yes — managers manage all portals identically
80% shared fields? Yes — portal_name, portal_listing_id, listing_label,
                         active, listed_on are the same for all portals

Decision: single model with portal_name Selection field ✓
```

Counter-example:
```
"Should properties and leads be the same model?"

Same list? No — never shown together
Same security? No — very different access rules
80% shared? No — completely different fields

Decision: separate models ✓
```

### Model naming

```
Convention: {domain}.{entity} in lowercase with dots
Good:   property.portal.listing
        lead.property.interest
        property.base
Bad:    PortalListing
        portal_listing
        PropertyPortalListing
```

The `_name` attribute is permanent. It determines the DB table name,
the XML ID prefix, and every reference from other models. Choose it
carefully — renaming requires a migration that touches every reference.

### Table naming (automatic from _name)

```python
property.portal.listing → property_portal_listing
leads.new               → leads_new
lead.property.interest  → lead_property_interest
```

Rule: dots become underscores. Never name models with underscores
in the domain part — it creates ambiguous table names.

### Lifecycle and state design

Define the complete lifecycle before writing any field.
Every state must have:
- A name (what the system calls it)
- A trigger (what moves a record into this state)
- An owner (who is responsible for records in this state)
- An exit (what moves the record out, and to where)

```
leads.new lifecycle:

new (trigger: portal lead created or manual create by cron path)
  owner: nobody — this is the problem state
  exit: _process_lead_logic() succeeds → assigned
        _process_lead_logic() fails → failed
        manager manually assigns → assigned

assigned (trigger: _process_lead_logic() sets user_id + state)
  owner: the assigned RM
  exit: [no formal exit state currently]

failed (trigger: _process_lead_logic() throws exception)
  owner: nobody — admin must investigate
  exit: manual admin correction
```

States not in this diagram have no place in the model.

### ondelete — define before writing

Every `Many2one` field must have an explicit `ondelete`:

```python
# Child is meaningless without parent → cascade
property_base_id = fields.Many2one(
    "property.base",
    ondelete="cascade",   # delete portal listing if property deleted
)

# Child can exist without parent → set null
property_base_id = fields.Many2one(
    "property.base",
    ondelete="set null",  # lead remains if property deleted
)

# Parent must not be deleted while children exist → restrict
# Use sparingly — it surprises users who try to delete a parent record
user_id = fields.Many2one(
    "res.users",
    ondelete="restrict",
)
```

Not setting `ondelete` defaults to `set null`. This is correct for
optional relationships but wrong for required ones. Be explicit.

---

## Field design standards

### The naming hierarchy

Fields must be named for what they store, not how they are implemented:

```python
# BAD — describes the implementation
portal_name_field = fields.Char()
active_boolean_flag = fields.Boolean()
listing_id_string = fields.Char()

# GOOD — describes the domain concept
source = fields.Char()           # what is the origin of this lead?
is_active = fields.Boolean()     # is this listing currently live?
portal_listing_id = fields.Char() # what ID did the portal assign?
```

When naming a field, write the question it answers. The field name
should be the shortest accurate answer to that question.

### The type hierarchy — most constrained first

```
Boolean      → use when: only two states, no ambiguity
               example: is_active, is_webhook_sent, is_ops_sale_lead

Selection    → use when: fixed set of values known at design time
               example: state, current_status, portal_name, listing_type

Integer      → use when: counting or ranking (no decimals)
               example: lead_count, portal_listing_count

Float        → use when: continuous values with decimals
               example: price, commission_rate

Date         → use when: time of day is irrelevant
               example: service_expiry_date, listed_on, create_date_only

Datetime     → use when: time of day matters
               example: site_visit_date, first_contact_datetime

Many2one     → use when: referencing another record
               example: property_base_id, user_id, rm_user_id

Char         → use when: free-form text under ~100 characters
               example: name, phone, portal_listing_id, label

Text         → use when: long free-form content (remarks, notes)
               example: remarks, process_notes, raw_data

Html         → use when: rich text is needed and user creates it
               never use for system-generated content — use Text
```

Every `Char` field should be questioned at design time:
"Is this actually a Selection, Many2one, or constrained type?"

### The help string — inline documentation for users

Every non-obvious field must have a `help=` string. This is not optional.
The help string appears as a tooltip in the Odoo UI and serves as
the field's user-facing documentation.

```python
# BAD — no help, user cannot understand the field's purpose
portal_listing_id = fields.Char(string="Listing ID", index=True)

# GOOD — help explains what to put here and why
portal_listing_id = fields.Char(
    string="Listing ID",
    index=True,
    help=(
        "The unique ID assigned by the portal for this specific listing. "
        "For MagicBricks: a numeric string like '9871234'. "
        "For OLX: alphanumeric like 'OLX44556'. "
        "For 99acres: the property code from the URL. "
        "Do not include the portal domain — just the ID itself."
    ),
)

# GOOD — help explains non-obvious behaviour
is_active = fields.Boolean(
    string="Active",
    default=True,
    index=True,
    help=(
        "Uncheck when this listing is removed from the portal. "
        "Inactive listings are hidden from the Portal Listings tab by "
        "default but remain searchable. "
        "Leads arriving with an inactive listing ID still resolve correctly "
        "to this property — the resolution falls back to inactive listings."
    ),
)
```

Fields that are genuinely self-evident do not need help strings:
`name` on a model named "Lead" is obvious. `is_active` on a simple
toggle is obvious. The bar is: "Would an RM reading this tooltip
understand what to put here?"

### Computed and related fields

```python
# computed — system derives the value, user never sets it
display_name = fields.Char(
    compute="_compute_display_name",
    store=True,        # store=True when filtered/sorted/grouped on frequently
    readonly=True,     # ALWAYS readonly when store=True
)

# related — shortcut to a field on a linked record
base_property_city = fields.Char(
    related="property_base_id.city",
    string="Property City",
    store=True,        # store=True for list view performance
    readonly=True,     # ALWAYS readonly on related fields
)
```

Critical rule: `store=True` on a computed or related field must always
be accompanied by `readonly=True`. A stored computed field that is also
writable creates an ambiguous field that Odoo handles inconsistently.

### Index discipline

Add `index=True` to every field that will be used in:
- A `domain=` argument in any search
- A `filter_domain=` in a search view
- A `group_by` in any view context
- An `order=` on the model or any ORM call
- A `WHERE` clause in any migration SQL

```python
# These must be indexed — they appear in domains or ordering constantly
state = fields.Selection(..., index=True)
user_id = fields.Many2one(..., index=True)
is_webhook_sent = fields.Boolean(..., index=True)
portal_name = fields.Char(..., index=True)
portal_listing_id = fields.Char(..., index=True)
create_date_only = fields.Date(..., store=True)  # indexed implicitly when stored
```

An un-indexed field used in a WHERE clause on a 6000-row table adds
50-200ms per query. Multiply by every list view load.

### Selection field design

Define selection values as module-level constants, not inline strings:

```python
# BAD — magic strings scattered through the code
state = fields.Selection([
    ('new', 'New'),
    ('assigned', 'Assigned'),
    ('failed', 'Failed Assignment'),
])

# GOOD — constants enable refactoring and documentation
STATE_NEW = 'new'
STATE_ASSIGNED = 'assigned'
STATE_FAILED = 'failed'

LEAD_STATE_SELECTION = [
    (STATE_NEW, 'New'),
    (STATE_ASSIGNED, 'Assigned'),
    (STATE_FAILED, 'Failed Assignment'),
]

state = fields.Selection(
    selection=LEAD_STATE_SELECTION,
    default=STATE_NEW,
    ...
)
```

Then in code: `if self.state == STATE_NEW:` not `if self.state == 'new':`

---

## The naming anti-patterns to avoid

These are the most common naming mistakes in Odoo development:

```python
# Too generic — what kind of ID?
id_field = fields.Char()            → portal_listing_id
record_id = fields.Many2one(...)    → property_base_id

# Hungarian notation — type is in the field definition, not the name
is_active_bool = fields.Boolean()   → is_active
name_char = fields.Char()           → name
date_field = fields.Date()          → listed_on

# Redundant model name
lead_state = fields.Selection()     → state (it's already on leads.new)
property_city = fields.Char()       → city (it's on property.base)

# Misleading abbreviations
prop_id = fields.Char()             → this one is fine (established convention)
pb_id = fields.Many2one(...)        → property_base_id (spell it out)
lpi = fields.Char()                 → portal_listing_id (never acronyms)

# Tense inconsistency
is_sent / was_sent / has_sent       → is_webhook_sent (consistent is_ prefix)
created_date / creation_date        → create_date_only (follow Odoo convention)
```