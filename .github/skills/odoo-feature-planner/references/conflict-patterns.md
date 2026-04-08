# Conflict Patterns

Ten patterns that cause production problems in the Cleardeals codebase.
Check every new feature against all ten. Document your finding for each
one — a conscious "not affected" is different from "I didn't check".

---

## Pattern 1 — Cron state assumptions

**The trap:** A cron queries records by `state` and processes them.
A new feature changes how records enter or exit that state.
The cron picks up records it should not, or misses records it should handle.

**Real example from this codebase:**
`_cron_reprocess_unassigned_leads` queries `state='new'`.
Manual leads were designed to start as `state='assigned'` to be invisible
to this cron. If manual leads had accidentally started as `state='new'`,
the cron would have run `_process_lead_logic()` on them, overwriting the
manually set `property_base_id` and `user_id` with portal-lookup results
— finding nothing and falling back to a default RM.

**Check:** For any feature touching `leads.new.state`, ask:
does `_cron_reprocess_unassigned_leads` still behave correctly?

---

## Pattern 2 — Security rule blocking a necessary cross-user read

**The trap:** A new feature requires User A to read records owned by User B.
The existing `ir.rule` blocks this. The feature fails with `AccessError`
or silently returns an empty recordset.

**Real example from this codebase:**
Manual lead creation required an RM to select any active property as
`property_base_id`. The existing rule `[('rm_user_id', '=', user.id)]`
blocked cross-RM property reads. The context key
`search_all_properties_for_lead` was already planted on the `property_base_id`
field definition, but the `ir.rule` had never been updated to honour it.
The key did nothing until the rule was changed.

**Check:** When a feature requires cross-user reads, always grep for
`context=` on the relevant `Many2one` field. If a context key exists,
find the `ir.rule` and verify it reads `context.get('that_key')`.
If the rule does not reference the key, the key is decorative.

---

## Pattern 3 — Field rename cascading silently to 16 files

**The trap:** A field is renamed in Python and the column migration is
written. Runtime errors appear from files that still reference the old
field name — but only when that code path is triggered.

**Real example from this codebase:**
`portal_name` → `source` affected 16 files across 5 modules:
`new_portal_leads.py` (6 references across 4 methods),
`property_base_extend.py` (deleted entirely),
`lead_csv_import_wizard.py` (4 references including COLUMN_MAPPING key),
`lead_migration_wizard_views.xml` (help text),
`serializers.py` (payload key),
`_cron_send_new_lead_webhooks` (payload dict key),
`action_whatsapp_with_copy` (message builder),
5 test fixture files (setUpClass creates + assertEqual assertions).

**Check:** Before planning any field rename, run the grep mentally
or literally across: all Python model files, dependent module Python
files, all XML views, ir.filters data records, test fixtures, API
serialisers, webhook payload builders, and external integration code.

---

## Pattern 4 — Create path bypass

**The trap:** New logic is added to `create()` or `default_get()`.
Some records are created via a path that bypasses these methods.
Those records are silently created without the new logic applied.

**Real example from this codebase:**
Manual lead creation added `default_get()` to pre-fill `state='assigned'`
and `user_id=current_user`. But `create_lead_if_not_duplicate()` calls
`self.create()` directly in the cron context — bypassing `default_get()`
entirely. Without `with_context(portal_lead_creation=True)`, the cron's
create calls would have been mis-classified as manual leads.

**Cleardeals create paths for `leads.new`:**
- `create_lead_if_not_duplicate()` — used by Housing.com cron
- Webhook controller POST endpoint (if one exists)
- `lead_csv_import_wizard.py` action_import
- Any `cr.execute()` in migration scripts (bypasses ORM entirely)

Each path must be audited when `create()` logic changes.

---

## Pattern 5 — Duplicate data display

**The trap:** A UI change adds a new way to view or edit data without
removing the old way. Users see the same data in two places, edit one,
and the other appears stale or shows conflicting values.

**Real example from this codebase:**
The Portal IDs tab (flat fields: `ninety_nine_acres_id` etc.) and the
Portal Listings tab (new `One2many`) were simultaneously present in
`property_base_views.xml`. A manager editing `ninety_nine_acres_id`
directly in the old tab bypassed `property_portal_listing` entirely.

**Check:** Whenever a field is replaced by a new model or moved to a
new location in the form, search every XML file for the old field name.
Remove it from every view when the new one is added. Check form views,
list views, search views, filter domains, and group-by contexts.

---

## Pattern 6 — Search view referencing removed fields

**The trap:** A field is removed from the Python model. Its entry in
the search view is not updated. The next time any user opens the search
bar, Odoo validates the view and throws `FieldDoesNotExist`.

**Real example from this codebase:**
`ninety_nine_acres_id`, `housing_id`, `magicbricks_id`, `olx_id` were
removed from `property.base` but their `<field>` entries remained in
`view_property_base_search`. This would have thrown an error on any
search bar interaction after the column drop migration ran.

**Check:** For every field removal, grep all XML files for that field
name. Check: form view `<field>` elements, list view columns, search
view fields, `filter_domain` attributes, `context=` group-by attributes,
and `ir.filters` records in data XML.

---

## Pattern 7 — Accidentally correct behaviour

**The trap:** The new feature works "for free" because of an existing
edge condition in the current logic. This behaviour is correct now but
becomes wrong if the surrounding logic is ever refactored — and the
correctness is invisible to future developers.

**Real example from this codebase:**
`create_lead_if_not_duplicate()` skips duplicate checking when
`portal_property_id` is empty: "Cannot check for duplicate (missing
phone/prop_id), creating lead." For manually created leads with no
`portal_property_id`, this accidentally produced the correct behaviour
— manual leads should not be deduplicated against portal leads.
But this was not intentional and was not documented. A refactor of the
dedup logic could "fix" this and break manual lead creation.

**Check:** For any case where the new feature works without explicit
code to support it, add a code comment explaining the intentional
reliance on this behaviour. Document it in the spec under edge cases.

---

## Pattern 8 — BigQuery sync overwriting manual changes

**The trap:** A manager manually sets a field on a property or lead
record. The BQ sync cron runs and overwrites it with the BigQuery value,
erasing the manual change silently.

**Real example from this codebase:**
`property_sync.py` overwrites all fields in `SYNC_FIELDS` on every sync
cycle. Any field in this list is subject to being overwritten. The portal
ID fields (`ninety_nine_acres_id` etc.) were in SYNC_FIELDS, meaning any
manually corrected portal ID would be reverted on the next 3-hour sync.

**Check:** For every new feature field, make a deliberate decision:
- BQ-sourced (add to SYNC_FIELDS, managers cannot manually override)
- Odoo-managed (do NOT add to SYNC_FIELDS, BQ cannot overwrite)
- Both (implement a manual override flag or a "last_modified_by" guard)

Also: if the same change needs to go into both `property_sync.py` and
`property_inventory.py` in `lead_suggestor`, both files must be updated.

---

## Pattern 9 — Missing ir.model.access row

**The trap:** A new model is added. The access CSV row is missing or
has an incorrect `model_id:id`. Every user gets `AccessError` when any
code touches the model — including administrators in some Odoo versions.

**Real example from this codebase:**
`property.portal.listing` was added. The access CSV needed explicit rows
for `model_property_portal_listing`. Without them, the Portal Listings
tab would throw `AccessError` for all users when loading.

**`model_id:id` derivation (never guess this):**
```
model._name              → model_id:id in CSV
property.base            → model_property_base
property.portal.listing  → model_property_portal_listing
leads.new                → model_leads_new
lead.property.interest   → model_lead_property_interest
```
Rule: replace dots with underscores, prefix with `model_`.

**Check:** For every new `models.Model` subclass, verify the access
CSV has at least one row. Also check: if a new model in module A is
queried from module B, module B's access CSV may also need a row.

---

## Pattern 10 — n8n webhook payload mismatch

**The trap:** A field is renamed or a new field is added to the n8n
webhook payload in `_cron_send_new_lead_webhooks`. The n8n workflow
is not updated simultaneously. The workflow either silently reads a
null value or fails with a key error.

**Real example from this codebase:**
The `portal_name` → `source` rename changed the payload key. The n8n
workflow needed to switch from reading `data.portal_name` to `data.source`.
Additionally, a new `is_manual_lead` boolean was added so n8n could route
manual vs portal leads through different workflow branches.

**Current payload shape (as of CDLS-200 planning):**
```python
{
    "lead_id": lead.id,
    "name": lead.name,
    "phone": lead.phone,
    "source": lead.source,           # was portal_name
    "portal_property_id": lead.portal_property_id,
    "is_manual_lead": not bool(lead.source),  # new field
    "rm_name": lead.user_id.name,
    "property_id": prop.id,
    "property_tag": prop.property_tag,
    "property_bhk": prop.bhk,
    "property_location": prop.location,
    "property_city": prop.city,
    "property_link": prop.property_link,
}
```

**Check:** For any feature that touches `leads.new` fields, grep
`_cron_send_new_lead_webhooks` for the field name. If it is in the
payload dict, the n8n workflow update must be coordinated and deployed
at the same time as the Odoo change.