# ORM Overrides: `leads` Module

- Module: leads
- Version documented: 1.5.0
- Last updated: 2026-04-13
- Status: Current
- Scope: All `create`, `write`, `web_save`, and `_search` overrides in `custom_addons/leads/`

---

## Overview

This document records every ORM method override in the `leads` module: what was changed,
why the standard Odoo behaviour was insufficient, and what failure the override prevents.

Each section covers one override. The sections are ordered by model, then by method.

---

## 1. `leads.new` — `create()`

**File:** `models/new_portal_leads.py`

### What it does

Intercepts every new `leads.new` record before it is written to the database and performs
four operations in sequence:

1. **Phone normalisation.** Calls `_standardize_phone()` to strip non-numeric characters,
   remove the leading `91` country code if present, and keep a 10-digit number.
   Applied to every lead regardless of source.

2. **Source resolution.** If `source_id` is not supplied but a `portal_name` string is
   present (legacy field from Housing.com/MagicBricks imports), the override calls
   `_get_or_create_source()` to find or create the matching `lead.source` record and
   fills `source_id`. A lead without a source is rejected with a `ValidationError`.

3. **Duplicate detection (automated leads only).** For leads created by cron (context key
   `automated_lead_creation=True`), the override calls `_compute_duplicate_domain()` to
   build a domain matching same phone + same resolved property within 180 days.
   If a match exists the lead is silently dropped (returns without creating). This guard
   runs only for automated leads; manually created leads raise a `ValidationError` so the
   RM sees the conflict explicitly.

4. **Bus notification.** After successfully creating the record, emits a `bus.bus`
   notification on channel `"leads.new"` so connected list-view clients reload instantly
   without a full browser refresh.

### Why the override is needed

- Odoo's standard `create()` does not normalise phone numbers. Without normalisation, the
  same phone number arrives in at least four forms (`9198765 43210`, `+919876543210`,
  `9876543210`, `98765 43210`), all treated as distinct, and duplicates are never caught.

- The duplicate guard cannot be a `@api.constrains` because constraints fire after the
  write and the cron wants a silent no-op drop, not a rollback and error.

- Bus notification in `create()` matches the notification in `write()` so the list view
  stays live for both new arrivals and status changes without polling.

### Key implementation detail — `mail_create_nolog`

The `super().create()` call is invoked on `self.with_context(mail_create_nolog=True)` to
suppress the automatic "Record created" chatter entry. The context must be set on `self`
before `super()` is called. Calling `super().with_context().create()` would resolve back
to this override and recurse infinitely.

```python
new_leads = super(
    NewPortalLead,
    self.with_context(mail_create_nolog=True),
).create(normalized_vals_list)
```

---

## 2. `leads.new` — `write()`

**File:** `models/new_portal_leads.py`

### What it does

Intercepts every field update on an existing `leads.new` record and performs two
operations after the standard write:

1. **First-contact timestamp.** When `current_status` changes to any value other than
   `"lead"` and `first_contact_datetime` is still empty, the override stamps the current
   time. This records the exact moment an RM first meaningfully interacted with the lead
   (moved it out of the "just arrived" state).

2. **Bus notification with silent-field guard.** Emits a `bus.bus` notification so
   connected list-view clients reload. Writes that touch only the set
   `{"first_contact_datetime", "is_webhook_sent", "process_notes"}` are skipped —
   these are internal bookkeeping fields with no visible effect on the list view, and
   emitting a notification for them would trigger an unnecessary full reload on every
   connected client.

### Why the override is needed

- `first_contact_datetime` cannot be a `related` or `compute` field because it must
  record a point in time, not reflect the current value of another field.

- Without the silent-field guard, the webhook cron (`_cron_send_new_lead_webhooks`)
  sets `is_webhook_sent = True` on hundreds of leads per batch, firing hundreds of
  bus notifications and causing every connected RM to reload their list view mid-work.

### Critical: avoiding recursive bus notifications

The timestamp stamp calls `super(NewPortalLead, leads_to_stamp).write(...)` rather than
`leads_to_stamp.write(...)`. This bypasses the override so the inner write does not fire
a second bus notification. If `leads_to_stamp.write()` were called instead:

1. Inner write enters this override → `super().write()` → fires bus notification #1.
2. Outer write resumes → fires bus notification #2.

Two notifications trigger two simultaneous `_webReadGroup` reloads. The first reload
destroys the OWL component while the second is still resolving, producing an
`UncaughtPromiseError: Component is destroyed` in the browser console. This was a
confirmed production bug affecting RMs that changed `current_status` on fresh leads.

---

## 3. `leads.new` — `web_save()`

**File:** `models/new_portal_leads.py`

### What it does

Intercepts the save-and-read-back cycle that the Odoo web client performs when a user
saves a form. When the save is a **lead reassignment** (i.e. `user_id` is in `vals` and
it is changing to a different user), the override performs the write normally but reads
the record back using `sudo()` to bypass the record rule.

For all other saves it delegates to the standard `super().web_save()` unchanged.

### Why the override is needed

The `ir.rule` "New Leads: RM See Own" restricts reads to `[('user_id', '=', user.id)]`.

The sequence of operations in a standard `web_save` is:

1. `self.write(vals)` — succeeds, because at write-time `user_id` still equals
   the current RM (record rules are evaluated against the pre-write values).
2. `self.web_read(specification)` — fails with an access error, because `user_id`
   now points to the new RM.

The result in the browser is a 200 response containing an access-denied error message,
which the web client displays as a pop-up notification. The lead was successfully
reassigned (the write did go through) but the UI shows an error, confusing the RM.

**Why `sudo()` here is safe and not a security hole:** `sudo()` applies only to the
confirmation read of the exact record that was just written (identified by `self` before
the write). `next_id` is explicitly **not** honoured in the reassigning branch — doing so
would allow the caller to supply an arbitrary client-controlled ID and read any record in
the database with `sudo()`, bypassing the "RM See Own" rule entirely. The strict read rule
continues to apply on every subsequent request — the reassigning RM loses access to the
lead the moment they navigate away, because the rule checks `user_id` at read time and
`user_id` no longer matches.

### Alternative approaches considered

| Approach | Problem |
|---|---|
| Widen the record rule using `write_uid = user.id` | `write_uid` persists indefinitely on the record. Every lead an RM ever touched would remain visible to them forever, making the "RM See Own" rule meaningless. |
| Split into separate read/write rules with `write_uid` on the read rule | Same leakage problem — `write_uid` does not reset after the RM loses ownership. |
| Catch the access error client-side and dismiss it | The error is real from Odoo's perspective; dismissing it hides a symptom rather than fixing the cause. |

---

## 4. `lead.olx.account` — `write()`

**File:** `models/lead_olx_account.py`

### What it does

Before delegating to the standard write, checks whether `login` is being changed.
If it is, migrates the stored password from the old `ir.config_parameter` key
(`olx.account.<old_login>.password`) to the new key (`olx.account.<new_login>.password`)
and clears the old key.

### Why the override is needed

OLX account passwords are never stored in the database column. The `password` field is
a non-stored compute field — all writes go to `ir.config_parameter` via the
`_inverse_password()` method, keyed by the account's `login` value.

If an admin corrects a login (e.g. fixes a typo in the phone number), the key in
`ir.config_parameter` no longer matches the new login. The next OLX poll would fail
silently with "No password configured for account X", with no visible indication that
the password was simply stored under the old key.

This override ensures login edits are always safe — the password follows the login
automatically.

### What happens when the new key already has a value

The override only migrates if the old key has a value. It does not overwrite an existing
password stored under the new key; this is intentional to avoid clobbering a deliberately
set password if an admin re-types a login that already existed.

---

## 5. `property.base` — `_search()`

**File:** `models/property_base_extend.py`

### What it does

Injects an additional domain filter `[('rm_user_id', '=', user.id)]` into every
`_search()` call when both of the following are true:

- The context key `properties_module_view` is present (set by every action in the
  Properties module).
- The current user is in `properties.group_property_rm` but not in
  `properties.group_property_manager`.

For all other contexts (lead forms, domain searches, scheduled jobs) the override passes
through to `super()` with no additional filter.

### Why the override is needed

Two conflicting requirements exist for `property.base` reads:

| Context | Required behaviour |
|---|---|
| Properties module list view | RM sees only their own properties |
| Lead form `property_base_id` field | RM sees all properties (to select a recommended property owned by a different RM) |

The `ir.rule` in the leads module (`rule_property_base_leads_rm_read_all`) grants
`[(1,'=',1)]` (read all) to `leads.group_lead_score_rm`. Odoo ORs rules across groups,
so any RM who is in both the properties RM group and the leads RM group can read all
property records — which is correct for lead forms but wrong for the Properties list view.

Adding `properties_module_view` as a context key on module actions, then detecting it
here, restores the list-view restriction without breaking cross-RM reads anywhere else.

**Why `_search()` instead of a domain on the field or an additional rule:**
A domain on the Many2one field only affects the dropdown picker, not `search()` calls.
An additional `ir.rule` with context detection is not possible in standard Odoo — rules
cannot inspect `self.env.context`. `_search()` can.

---

## 6. `property.base` — `write()`

**File:** `models/property_base_extend.py`

### What it does

After the standard write, checks whether any of the four portal ID fields
(`magicbricks_id`, `ninety_nine_acres_id`, `housing_id`, `olx_id`) were updated.
For each that was, searches for `leads.new` records that arrived with a matching
`portal_name` + `portal_property_id` but have `property_base_id = False`
(unlinked leads). For each match, sets `property_base_id` and reassigns `user_id`
to the property's RM (falls back to admin if none is set).

### Why the override is needed

Portal leads arrive before the property record is set up, or before the correct portal
ID is entered. In this scenario:

1. Lead arrives with `portal_name = "MagicBricks"`, `portal_property_id = "MB9871234"`.
2. No `property.base` record has `magicbricks_id = "MB9871234"` yet.
3. Lead is created with `property_base_id = False`, assigned to the default RM.
4. Later, someone enters `MB9871234` in the MagicBricks ID field on the property.
5. This override fires, finds the lead, sets `property_base_id`, and reassigns the RM.

Without this retroactive relinking, leads permanently stay with the wrong RM and
lose their property association unless someone manually corrects them.

---

## 7. `property.portal.listing` — `create()` and `write()`

**File:** `models/property_base_extend.py` — class `PropertyPortalListingLeadRelink`

### What it does

After every `create()` of a `property.portal.listing` record, and after every `write()`
that changes `portal_listing_id`, `portal_name`, or `property_base_id`, calls the shared
helper `_relink_leads_for_listing()` which performs the same unlinked-lead search and
reassignment described in Override 6.

### Why this is separate from Override 6

`property.base` directly holds field-level portal IDs (`magicbricks_id`, etc.).
`property.portal.listing` is the join table that maps a portal listing ID to a
`property.base` record — it is a separate model with its own create/write lifecycle.
Both paths need to trigger relinking because either can be the one that establishes
the match:

- A lead arrives and the portal ID already exists on `property.base` directly → Override 6.
- A lead arrives and the portal ID is added via a new `property.portal.listing` row → Override 7.

### `write()` pre-capture pattern

The `write()` override captures the old values of the three relevant fields before calling
`super()`:

```python
old_state = {
    rec.id: (rec.portal_name, rec.portal_listing_id, rec.property_base_id)
    for rec in self
}
result = super().write(vals)
```

This is necessary because after `super().write()`, `self` reflects the new values and the
comparison `rec.portal_name != old_name` would always be `False` if compared post-write.

---

## Quick Reference Table

| Model | Method | Primary purpose | Production bug it prevents |
|---|---|---|---|
| `leads.new` | `create()` | Phone normalisation, duplicate guard, bus notification | Duplicate leads, non-standardised phone numbers breaking dedup |
| `leads.new` | `write()` | First-contact timestamp, silent-field bus guard | Double bus notification → OWL "Component is destroyed" crash |
| `leads.new` | `web_save()` | Post-reassignment read-back via `sudo()` | "Access Denied" error after RM reassigns a lead |
| `lead.olx.account` | `write()` | Config param key migration on login change | Silent "No password" failure after admin edits login |
| `property.base` | `_search()` | List-view restriction via context key | RMs seeing all properties in Properties module list |
| `property.base` | `write()` | Retroactive lead relink when portal ID fields change | Leads permanently stuck with wrong RM/no property |
| `property.portal.listing` | `create()` + `write()` | Retroactive lead relink when listing is created/updated | Leads permanently stuck with wrong RM/no property |
