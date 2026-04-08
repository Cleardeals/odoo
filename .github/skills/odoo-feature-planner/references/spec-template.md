# Feature Specification Template

Use this exact structure. Fill every section. Mark "N/A — [reason]" only
when something genuinely does not apply. Never omit a section because it
is hard to answer — that difficulty is the signal that it needs answering.

---

```markdown
# Feature Spec: [Feature Name]

**Epic:** CDLS-XXX (assign or mark TBD)
**Requested by:** [name / role]
**Date:** [today's date]
**Status:** Draft → In Review → Approved

---

## What this builds

[2–4 sentences in plain English. Zero jargon. A manager who does not
read code should confirm this matches what they asked for. If they
need to read anything below this section to understand the feature,
rewrite this section.]

---

## Why it matters

[The specific business problem this solves. What the team cannot do
today. Be concrete — not "improves efficiency" but "RMs currently
cannot create leads manually, meaning any walk-in or referral lead
must be entered directly in the database by a developer."]

---

## Who uses it and how

### RM workflow
Step by step — what the RM sees, what they click, what they fill in,
what confirmation they receive, what happens when something goes wrong.
No assumptions. No "they click the button to do X" — describe the button,
the form, the fields, the save action.

### Manager workflow
What a manager sees differently after this feature. New tabs, new list
columns, new actions they can take that RMs cannot. What they now can
report on or act on that they could not before.

### Automated / system behaviour
What the system does without human input after this feature is deployed.
Which crons change behaviour. What new automations are introduced.
What triggers what.

---

## Modules and files affected

| Module | File | Change type | Summary |
|---|---|---|---|
| `properties` | `property_base.py` | Field added | New `portal_listing_ids` One2many |
| `leads` | `new_portal_leads.py` | Logic change | `_find_property()` uses resolve_property() |
| `leads` | `new_portal_lead_views.xml` | View change | Source field conditional readonly |
| ... | ... | ... | ... |

---

## Data model changes

### New model: `[model._name]`
- **Table:** `[table_name]`
- **Fields:**
  | Field | Type | Index | Constraint | Notes |
  |---|---|---|---|---|
  | `property_base_id` | Many2one('property.base') | Yes | cascade | Required |
  | `portal_name` | Char | Yes | — | e.g. "MagicBricks" |
  | ... | | | | |
- **_sql_constraints:** `[name, SQL, user message]`
- **Access:** Managers full CRUD / RMs read-only / [other]
- **Chatter:** Yes / No

### Modified model: `[model._name]`
- **Added fields:** [field name, type, migration implications]
- **Renamed fields:** [old → new] — requires `pre-rename_*.py` migration
- **Removed fields:** [field name] — requires `post-drop_*.py` migration
- **Changed field behaviour:** [e.g. `portal_name` was Char, now replaced
  by relational path through `property_portal_listing`]

---

## Security model

Write this as sentences, not just a table. State who can do what and
explicitly state who cannot.

Example:
- RMs can read all active properties when selecting `property_base_id`
  on a lead form. This is enabled by the `search_all_properties_for_lead`
  context key on the `property_base_id` field, honoured by the RM's
  `ir.rule` on `property.base`.
- RMs cannot write to properties owned by other RMs under any circumstances.
  The context key grants read access in the Many2one dropdown only.
- Managers have full CRUD on all new models introduced by this feature.

**ir.rule changes:**
| Rule xmlid | Current domain | New domain | Reason |
|---|---|---|---|
| `property_base_rule_rm` | `[('rm_user_id', '=', user.id)]` | See below | Cross-RM read needed |

New domain:
```python
['|',
    ('rm_user_id', '=', user.id),
    '&', ('active', '=', True),
         (context.get('search_all_properties_for_lead'), '=', True)
]
```

**ir.model.access.csv changes:**
| id | model | group | perm_read | perm_write | perm_create | perm_unlink |
|---|---|---|---|---|---|---|
| access_property_portal_listing_manager | model_property_portal_listing | group_property_manager | 1 | 1 | 1 | 1 |
| access_property_portal_listing_rm | model_property_portal_listing | group_property_rm | 1 | 0 | 0 | 0 |

---

## Logic and business rules

Numbered. Precise enough that a developer can write a test for each rule
without asking questions.

1. A manually created lead must start with `state='assigned'` and
   `user_id` equal to the creating user's id. It must never enter
   `state='new'`.

2. A portal lead (identified by `source` being set to a portal name)
   must continue to start with `state='new'` and be processed by
   `_process_lead_logic()`.

3. The `_process_lead_logic()` method must skip records where
   `state != 'new'`. It must not modify manually created leads.

4. When a manual lead is saved without a `property_base_id`, this is
   valid. The RM may not know the property at creation time.

5. [Continue until all rules are enumerated]

---

## Edge cases

| Edge case | What happens | How it is handled |
|---|---|---|
| RM creates manual lead with no property | `property_base_id` is NULL | Allowed — RM fills in later |
| Portal lead arrives for listing ID not in property_portal_listing | `resolve_property()` returns empty | Assigned to default RM per portal, process_notes logged |
| RM is deactivated while they have open leads | `user_id` remains set | Leads remain — manager must reassign via list view |
| Two manual leads created for same phone number | No dedup check (manual leads skip create_lead_if_not_duplicate) | Intentional — manual leads are not portal leads |
| BQ sync runs after manager manually edits a portal listing | sync rewrites portal listing data | Portal listing fields are NOT in SYNC_FIELDS — BQ cannot overwrite |
| [Add more] | | |

---

## Existing automations — impact analysis

| Automation | Affected? | Impact | Resolution |
|---|---|---|---|
| `_cron_reprocess_unassigned_leads` | Yes | Would process manual leads if they were state='new' | Manual leads start as state='assigned' — naturally excluded |
| `_cron_send_new_lead_webhooks` | Yes | Payload key portal_name → source; new is_manual_lead key | Update payload dict + coordinate n8n workflow update |
| `_cron_pull_external_leads` | Yes | Creates leads with portal_lead_creation context | Add with_context(portal_lead_creation=True) to create call |
| Property sync cron | No | Does not touch leads | N/A |
| Expiry cleanup cron | No | Does not touch leads | N/A |

---

## Migration requirements

| Module | Version folder | File | Phase | What it does |
|---|---|---|---|---|
| `leads` | `19.0.1.2.0` | `pre-rename_portal_name_to_source.py` | pre | Renames portal_name column to source on leads_new |
| `properties` | `19.0.1.4.0` | `post-drop_legacy_portal_columns.py` | post | Drops ninety_nine_acres_id etc. after ORM update |

**Manifest bumps:**
- `leads/__manifest__.py`: `19.0.1.1.0` → `19.0.1.2.0`
- `properties/__manifest__.py`: `19.0.1.3.0` → `19.0.1.4.0`

**Existing data impact:**
- 6,000+ leads_new records: portal_name column renamed to source —
  data preserved, no NULLs introduced
- property_base records with non-NULL portal ID columns: backfilled
  into property_portal_listing in 19.0.1.1.0–19.0.1.3.0

---

## API and integration changes

**Properties REST API (`/api/v1/properties`):**

Before:
```json
{
  "ninety_nine_acres_id": "99A-12345",
  "housing_id": null,
  "magicbricks_id": "MB9871234",
  "olx_id": null
}
```

After:
```json
{
  "portal_listings": [
    {"portal": "99acres", "listing_id": "99A-12345", "is_active": true},
    {"portal": "magicbricks", "listing_id": "MB9871234", "is_active": true}
  ]
}
```

**n8n webhook payload (`_cron_send_new_lead_webhooks`):**
- `portal_name` key renamed to `source`
- New key `is_manual_lead` (boolean) added
- n8n workflow must be updated to read `source` instead of `portal_name`
  and to branch on `is_manual_lead`

**Housing.com cron:** No change to payload parsing.

**OLX CSV import:** `COLUMN_MAPPING` key `olx_id` → `olx_listing_id`

---

## View changes

**`property_base_views.xml`:**
- REMOVE: Portal IDs tab (ninety_nine_acres_id, housing_id, magicbricks_id, olx_id)
- ADD: Portal Listings notebook page with four per-portal One2many sections
- MODIFY: Search view — replace 4 flat field entries with single
  `portal_listing_ids` field with `filter_domain`

**`new_portal_lead_views.xml`:**
- MODIFY: `source` field — `readonly="portal_property_id != False"`
- MODIFY: `portal_property_id` field — `readonly="source != False"`
- ADD: Manual lead indicator banner — `invisible="source != False"`
- Verify: group-by options for portal_name → source in any ir.filters records

---

## Deployment checklist

Execute in this exact order on production day:

- [ ] Staging verified: migration ran on production data clone, row counts match
- [ ] Staging verified: all affected views load without errors
- [ ] Staging verified: portal lead arrives and resolves correctly
- [ ] Staging verified: manual lead created by RM starts as state=assigned
- [ ] n8n workflow updated to read `source` instead of `portal_name`
- [ ] n8n workflow updated to handle `is_manual_lead=True` routing
- [ ] Run: `odoo-bin -u properties,leads -d [db] --stop-after-init 2>&1 | tee migration_$(date +%Y%m%d).log`
- [ ] Read migration log — verify expected row counts for each portal
- [ ] Run post-deployment SQL verification queries
- [ ] Open property form in UI — verify Portal Listings tab shows migrated data
- [ ] Open lead form in UI — verify source field and conditional readonly works
- [ ] Create one test manual lead as an RM — verify state=assigned, user_id set
- [ ] Trigger one test portal webhook — verify state goes new → assigned correctly
- [ ] Monitor `_cron_reprocess_unassigned_leads` next scheduled run
- [ ] Monitor `_cron_send_new_lead_webhooks` — verify n8n receives payload correctly
- [ ] Keep production data snapshot for 30 days

---

## Explicitly out of scope

[Everything this feature does NOT do. This section prevents scope creep
during implementation. Be specific.]

- Does not add bulk manual lead import capability
- Does not change how portal leads are deduplicated
- Does not give RMs write access to other RMs' properties
- Does not change the Housing.com API authentication or fetch frequency
- Does not modify the lead scoring or property matching ML models

---

## Open questions

[Unresolved decisions that must be answered before or during implementation.]

| Question | Who answers | By when | Impact if not answered |
|---|---|---|---|
| Should n8n treat manual leads differently in the WhatsApp automation? | [name] | Before deploy | n8n routing logic |
| What should happen to leads with NULL source in Metabase reporting? | Manager | Sprint planning | Report filter logic |

---

## Jira task breakdown

[Generated from this spec. One story per logical group of work.
CDLS- prefix. Stories contain subtasks per file or component.]

**Epic: CDLS-XXX — [Feature name]**

**CDLS-XXX — [Story: Security layer]**
  CDLS-XXX — Locate and audit existing ir.rule for property.base RM group
  CDLS-XXX — Update ir.rule domain to honour search_all_properties_for_lead
  CDLS-XXX — Verify context key present on both property_base_id fields
  CDLS-XXX — Write security tests: cross-RM read allowed, cross-RM write blocked

**CDLS-XXX — [Story: Field rename migration]**
  CDLS-XXX — Write pre-rename_portal_name_to_source.py with idempotency guard
  CDLS-XXX — Global find-replace portal_name → source across all consumers
  CDLS-XXX — Bump leads manifest to new version
  CDLS-XXX — Verify PORTAL_NAME_MAP keys still match source values

**[Continue for each story...]**
```