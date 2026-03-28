# Question Bank

Questions calibrated to each feature type. Never ask all of them.
Select the 4–6 whose answers most change the architecture.
Ground every question in something specific found during the audit.

---

## New model questions

```
1. What is the complete lifecycle of a record?
   [created by what trigger] → [intermediate states] → [terminal state]
   Draw this as a state machine before asking anything else.

2. Who owns a record after creation?
   If a user creates it, they own it. If a cron creates it, who owns it?
   Who can reassign ownership?

3. What happens to records in this model when a linked property/lead
   is deleted or archived?
   (determines ondelete= behaviour — cascade, set null, or restrict)

4. Will this model need a dedicated menu item, or is it only accessible
   embedded in another form?

5. Will records ever need to be bulk-created or bulk-edited by managers?
   (determines whether a wizard or list view edit is needed)

6. Does this model need to be queryable from BigQuery?
   (determines whether a BQ sync or export is needed)
```

---

## New field questions

```
1. What value should existing records have after the upgrade?
   NULL is a valid answer — but it must be intentional, not accidental.

2. Is this field set automatically by code, manually by a user, or both?
   If both: what happens when the code tries to set a value the user
   has already changed?

3. Should this field appear in the search bar / group-by options?
   (if yes: needs filter_domain in search view, and possibly an index)

4. Will the BigQuery sync need to write to this field?
   (if yes: add to SYNC_FIELDS; if no: explicitly confirm it should not
   be overwritten by BQ)

5. What is the readonly policy?
   RMs see it but cannot edit? Managers can edit? Nobody can edit
   (always computed)?
```

---

## Workflow / state change questions

```
1. Draw the complete state machine including the new state.
   What are all valid transitions? What transitions are now invalid?

2. Which existing crons query the state field this feature changes?
   Will they pick up records they should not after the change?
   (Always check _cron_reprocess_unassigned_leads for leads.new)

3. When a state transition happens, who is notified and how?
   (chatter message, n8n webhook, WhatsApp, email — specify each)

4. What must be true for a transition to be valid?
   (validation that should raise UserError if conditions not met)

5. Can the transition be reversed? By whom?
   If yes: is there an audit trail of who reversed it and when?
```

---

## UI / view change questions

```
1. Walk me through the exact user journey step by step.
   What does the user see first? What do they click? What do they fill in?
   What confirmation do they get? What happens if they make a mistake?

2. Is any currently read-only field becoming editable?
   If yes: what happens to the existing auto-populated value when a user
   manually overrides it?

3. Are any currently visible fields being removed or hidden?
   If yes: do managers ever filter or group by those fields?
   (filters and group-by options in search view must also be removed)

4. Is this change visible to RMs, managers, or both?
   If manager-only: is the groups= attribute on the right element
   (page, group, field) to fully hide it from RMs?
```

---

## Integration / webhook questions

```
1. Does this feature change any field in the n8n webhook payload?
   (rename, remove, or add a key in _cron_send_new_lead_webhooks)
   If yes: who manages the n8n workflow and when can they update it?
   Deployment of the Odoo change and the n8n update must be coordinated.

2. Does this feature add fields that the Housing.com cron needs to populate?
   If yes: _parse_housing_response() must be updated.

3. Does this feature add fields that the OLX CSV import needs to populate?
   If yes: COLUMN_MAPPING in lead_csv_import_wizard.py must be updated.

4. Does this feature add fields that BigQuery should sync?
   If yes: property_sync.py AND property_inventory.py must both be updated.
   If no: confirm explicitly that BQ should not overwrite the new field.
```

---

## Security questions

```
1. State the access requirement in one sentence:
   "[Role X] should be able to [read/write/create/delete] [Model Y]
   when [Condition Z] and should NOT be able to when [Condition NOT-Z]."

2. Is there an existing context key on the relevant field definition?
   (grep for context= on the Many2one field — e.g. search_all_properties_for_lead)
   If yes: the ir.rule needs to honour it. If no: one may need to be added.

3. After this change, can an RM ever read a record belonging to another RM
   that they could not read before?
   If yes: confirm this is intentional and document the exact scope.

4. After this change, can an RM ever write to a record belonging to another RM?
   If yes: this needs explicit manager sign-off — it is a fundamental
   security model change for Cleardeals.
```

---

## Questions that surface the most reliably hidden problems

Always ask at least one of these regardless of feature type:

```
THE CRON QUESTION
"Which automated processes currently query the models this feature
 changes? Will any of them behave differently — picking up records
 they should skip, or skipping records they should process?"

THE EXISTING DATA QUESTION  
"How many records currently exist in the affected tables?
 What do the messiest 5% look like — what values are NULL,
 unexpected, or created by old code paths that no longer run?"

THE ROLLBACK QUESTION
"If this feature causes a critical bug 2 hours after deploy on a
 Friday evening, what is the fastest path back to a working state?
 Is there a data change that cannot be undone?"

THE REAL USER QUESTION
"Show me exactly what an RM sees when they use this feature on a
 real lead. What do they click? How long does it take? What could
 confuse them or cause them to make a mistake?"

THE SIMPLER VERSION QUESTION
"What is the minimum version of this feature that still solves the
 core problem? What would we cut if we had half the time?"

THE OWNERSHIP QUESTION
"If a record created by this feature sits unactioned for 3 days,
 who sees it, who gets notified, and who is responsible for it?"
```