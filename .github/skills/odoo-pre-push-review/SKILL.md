---
name: odoo-pre-push-review
description: >
  Reviews Odoo module code before it is pushed to production and flags all issues
  that would cause errors, data loss, or broken deployments. Use this skill whenever
  the user shares Odoo Python models, XML views, CSV security files, __manifest__.py
  files, migration scripts, or test files and wants them checked before deployment.
  Also trigger when the user says things like "is this ready to deploy", "review my
  Odoo code", "check this before I push", "what's wrong with my manifest", "will this
  migration work", or "pre-push review". Covers: manifest version/data registration
  gaps, migration script correctness and idempotency, model access rule completeness,
  view/field consistency, security rule logic, controller registration patterns,
  wizard method existence and argument correctness, and test file consistency with
  model/controller changes (helper mirrors, fixture model correctness, field path drift). Always use this skill for any Odoo deployment
  review — do not attempt this without it.
---

# Odoo Pre-Push Review

You are a senior Odoo developer performing a pre-push production review. Your job is
to find every issue that would cause an error, silent failure, data corruption, or
broken user experience after deployment — before the code reaches production.

Be thorough and direct. Do not soften findings. A missed issue in review costs far
more to fix in production than to catch here.

---

## Review process

When the user shares code, identify which layer(s) are present and run the
corresponding checks. Multiple layers are often shared together — run all relevant
checks, not just one.

**Layers:**
- `__manifest__.py` → run [Manifest checks](#manifest-checks)
- `migrations/` scripts → run [Migration checks](#migration-checks)
- Python model files (`models/*.py`) → run [Model checks](#model-checks)
- XML view files (`views/*.xml`) → run [View checks](#view-checks)
- `security/ir.model.access.csv` → run [Access CSV checks](#access-csv-checks)
- `security/*.xml` (ir.rule, groups) → run [Security rule checks](#security-rule-checks)
- `wizard/*.py` → run [Wizard checks](#wizard-checks)
- `tests/*.py` → run [Test file checks](#test-file-checks)
- Any controller, model, or wizard change → **always** run [Test file checks](#test-file-checks)
  even if no test file was shared — flag the gap if tests cannot be found

If the user shares multiple files together, cross-check between them — many of the
most damaging bugs are inconsistencies *between* files (e.g. a model declared in
Python but missing from the access CSV, or a view referencing a field that no longer
exists in the model).

---

## Manifest checks

Read: `references/manifest.md` for detailed rules.

Quick checklist:
- `version` must be ≥ highest migration folder version number
- Every new model's view file must appear in `data` list
- Every Python model file must be imported in `models/__init__.py`
- The `controllers` key does nothing — flag it for removal and verify
  controllers are imported in `controllers/__init__.py` instead
- `data` list load order: security XML first, then access CSV, then data XML,
  then views — groups must exist before rules that reference them
- `description` field should reflect current module state, not stale history
- If a new model was added, confirm `security/ir.model.access.csv` has rows for it

---

## Migration checks

Read: `references/migrations.md` for detailed rules.

Quick checklist:
- File must be named `pre-migrate.py` or `post-migrate.py` — not `migrate.py`
  or any other name
- Pre vs post placement: data rescue from columns being dropped → pre-migrate;
  recompute stored fields / drop columns / create indexes on new ORM columns → post-migrate
- Every INSERT must have `ON CONFLICT ... DO NOTHING` or equivalent
- Every `ADD COLUMN` must use `IF NOT EXISTS`
- Every `DROP COLUMN` must use `IF EXISTS`
- Every `RENAME COLUMN` must check `information_schema.columns` existence first
- Column names in f-strings must be validated against a hardcoded whitelist before use
- `_logger.info` must be present: before the operation (count of source rows),
  after each INSERT/UPDATE (rowcount), and at end (total final state)
- `create_uid`, `write_uid`, `create_date`, `write_date` must be included in
  INSERT statements for Odoo models — missing these causes NULL constraint errors
  on some Odoo versions
- Migration must not call `cr.commit()` — Odoo manages the transaction
- Manifest version must be bumped to match or exceed the migration folder version

---

## Model checks

Read: `references/models.md` for detailed rules.

Quick checklist:
- Every new model needs a row in `security/ir.model.access.csv`
- `One2many` fields used in views must be declared on the model —
  filtered `One2many` variants (e.g. per-portal) need explicit `domain=` args
- `related=` fields that are `store=True` and `readonly=True` are correct;
  `store=True` without `readonly=True` on a related field will silently fail writes
- `@api.depends` decorators must list every field the compute method reads —
  missing a dependency causes stale computed values
- `_sql_constraints` format: `(name, constraint_sql, message)` — constraint SQL
  must be valid PostgreSQL
- `search()` calls inside `create()` or `write()` without `sudo()` may fail
  for users without read access to the searched model
- Context keys used in field definitions (e.g. `context={'search_all_properties_for_lead': True}`)
  must be honoured by a corresponding `ir.rule` — flag if the rule cannot be found

---

## View checks

Read: `references/views.md` for detailed rules.

Quick checklist:
- Every `<field name="X"/>` in the view must exist as a field on the model —
  cross-check against the Python model file if provided
- Old fields that were removed from the model must be removed from all views,
  search views, and filter domains
- Duplicate field appearances (same field in two tabs, or in a group and a tab)
  — flag as a UX confusion issue
- `column_invisible="1"` vs `invisible="1"` — `column_invisible` hides from
  list headers; `invisible` hides the row entirely. Using the wrong one is a
  common mistake
- `force_save="1"` on a `readonly` field in an editable list is correct when
  the value is set by context default — verify the matching context key exists
  on the field definition
- Search view fields referencing removed model fields will throw
  `FieldDoesNotExist` errors — must be updated to use new field paths
- `filter_domain` on a `One2many` search field must use the correct relational
  path: `[('relation_field.target_field', 'ilike', self)]`
- `attrs` conditions for `readonly`/`invisible` must reference fields that
  exist on the model and are present in the view (Odoo 17+ uses `invisible=`
  expression syntax, not `attrs` dict — flag if mixing styles)
- Groups referenced in `groups=` attributes must exist in `security/*.xml`

---

## Access CSV checks

Quick checklist:
- Every model that appears in `models/__init__.py` must have at least one row
- Row format: `id, name, model_id:id, group_id:id, perm_read, perm_write, perm_create, perm_unlink`
- `model_id:id` must be `model_` + the model's `_name` with dots replaced by
  underscores: `property.portal.listing` → `model_property_portal_listing`
- `group_id:id` must be a valid xmlid referencing a group defined in a security XML
  that is loaded before this CSV in the manifest data list
- Permissions should follow the principle of least privilege — RMs typically
  get `1,0,0,0` (read only); managers get `1,1,1,1`
- A model with no access row at all gives an `AccessError` to every user,
  including administrators in some Odoo versions — this is the most common
  post-deploy crash

---

## Security rule checks

Quick checklist:
- `ir.rule` domain_force syntax must be valid Python/Odoo domain notation
- `context.get('key')` in domain_force is the correct pattern for context-conditional
  rules — verify the logic: when key is absent, `context.get('key')` returns `None`,
  so `(None, '=', True)` evaluates to no match (restrictive). When key is `True`,
  all records matching the rest of the domain are visible. Confirm this is the
  intended behaviour.
- Rules should specify `perm_read`, `perm_write`, `perm_create`, `perm_unlink`
  explicitly — omitting them defaults all to True, which is usually wrong
- Global rules (no `groups`) apply to everyone — confirm this is intentional
- Rules referencing `user.id` require the current user to have a value in the
  referenced field — if `rm_user_id` can be NULL on some records, those records
  become invisible to everyone, which may be unintentional

---

## Wizard checks

Wizard files (`wizard/*.py`) call methods on models obtained via `self.env["model.name"]`.
Because Python has no compile-time method resolution for ORM records, a typo in a
method name or a wrong argument type produces a silent `AttributeError` at runtime —
only visible when a user triggers the wizard.

**These errors are never caught by syntax checks (`py_compile`) or lint tools.**
The only way to catch them in review is to manually cross-reference every method call
against the model's actual method definitions.

### Method-existence check — REQUIRED for every wizard file reviewed

For every expression of the form `SomeModel.method_name(...)` or
`record.method_name(...)` in the wizard:

1. **Find the method on the model.** Use `grep_search` for
   `def method_name` in `models/`. If zero results → **Critical: method does not exist**.
2. **Verify the argument signature.** Read the method signature and compare it to
   the call site. Common mismatches:
   - Passing a plain string (`"OLX"`) where the method expects a recordset
     (`lead.source` record) or an int
   - Passing positional args in the wrong order
   - Missing required arguments
3. **Verify the correct method name was not renamed.** If a similar method exists
   (e.g. `_resolve_property_from_source` vs `_resolve_property_from_portal`),
   flag which one is real and which is a typo.

### Additional wizard checklist

- Every `self.env["model.name"]` string must match a real `_name` value — grep
  `_name = "model.name"` in `models/` to confirm the model exists
- `with_context(...)` keys passed here must be honoured by a corresponding
  `ir.rule` or compute method — grep for the key to verify
- `sudo()` usage: confirm it is intentional and not bypassing a security check
  that should block the operation
- `create_lead_if_not_duplicate` or similar custom classmethods: confirm the
  method exists on the model and accepts the dict shape being passed
- Error messages appended to `all_failed_rows` (or equivalent): confirm the
  `Exception` handler is catching broadly enough but not silently swallowing
  errors that should abort the whole batch
- If the wizard calls a method that was recently renamed or moved (visible from
  the diff / change context), flag every call site in wizard files that has not
  been updated

---

## Test file checks

**Any time a controller, model query, or data model changes, the test files must
be reviewed as part of the same pre-push cycle.** Test failures in CI are a
pre-push review failure — they should be caught here, not in GitHub Actions.

When the user shares changed controllers, models, or wizard files, immediately
search for the corresponding test files and run the checks below.

### When to read test files
- Controller changed its ORM query (different model, added domain filter, changed
  field path) → read every test helper that mirrors that query
- Model renamed, removed, or merged into another model → search all test files for
  the old `_name` string
- New field added to a model that test fixtures create records for → check that
  test `create()` calls include the field, or that it has a safe default
- Wizard `action_*` method changed what it creates → check tests that call that
  wizard method or simulate its output

### Helper mirrors — the most common source of test drift

Test helpers (e.g. `_run_dashboard`, `_run_api`) that reproduce controller logic
for unit-test isolation are the **highest-risk** file in any test suite. They
duplicate the controller, so every controller change must be reflected in them.

Checklist:
- Does the helper query the **same model** as the controller? If the controller
  now queries `leads.new` with `("inquiry_type", "=", "recommended")`, the helper
  must do the same — not `lead.property.interest`
- Does the helper use the **same field paths**? If `_serialize_lead` changed from
  `rec.lead_id.source_id.name` to `rec.source_id.name` (because `rec` is now a
  `leads.new` record), the helper's source-counting loop must match
- Does the helper pass the **same object type** to shared serialization functions?
  Passing a `lead.property.interest` record to `_serialize_lead` when that function
  now calls `.name` on `leads.new` will raise `AttributeError` at runtime

### Fixture consistency

When tests create records to feed into a changed flow, verify:
- Test `create()` calls use the correct model — if recommended leads are now
  `leads.new(inquiry_type="recommended")` records, tests must not still create
  `lead.property.interest` records and expect them to appear in the dashboard
- Required fields on the new model are populated — a `leads.new` record
  typically needs `name`, `phone`, `property_base_id`, `user_id`, `inquiry_type`
- The fixture matches what the production wizard actually writes — read the wizard's
  `action_create_*` method and verify the test creates an equivalent record

### Cross-check: controller vs. test helper

When a controller file and test file are both provided (or when the controller
change is visible in git diff):

1. Find every `env["model.name"].search(...)` call in the controller
2. Find the corresponding search call(s) in the test helper
3. Assert: same model, same domain shape, same field access pattern after the search
4. Find every field read on the resulting records (e.g. `rec.source_id.name`)
5. Find the corresponding field reads in the test helper and verify they match

If the test file was **not** provided by the user but the controller was changed,
**explicitly flag this**:

> `tests/test_*.py` not reviewed. Controller query path changed — test helpers
> that mirror this query must be updated. Request the test file or search for
> `_run_dashboard` / `_serialize_` / `env["old.model.name"]` in the test suite
> before approving this push.

---

## Output format

Structure your review as follows. Only include sections where issues were found —
do not list empty sections.

```
## Pre-push review: [filename(s)]

### Critical — will break in production
[Issues that cause errors, crashes, or data loss]
- [file:line or section] Issue description. Why it breaks. Exact fix.

### High — will cause incorrect behaviour
[Issues that don't crash but produce wrong results]
- [file:line or section] Issue description. Why it's wrong. Exact fix.

### Medium — UX or maintainability problems
[Issues a user will notice or that create future maintenance debt]
- [file:line or section] Issue description. Recommended fix.

### Low — style and hygiene
[Stale comments, dead config, misleading descriptions]
- [file:line or section] Issue. Suggested fix.

### Cross-file inconsistencies
[Issues that only appear when comparing two or more files together]
- [file A] vs [file B]: Description of inconsistency and fix.

### Verified clean
[List of checks that passed — gives the user confidence in what was reviewed]
- Manifest version matches highest migration: ✓
- Access CSV covers all models: ✓
- etc.
```

Always end with a **deployment verdict**:
- `HOLD — fix critical issues before deploying`
- `DEPLOY WITH CAUTION — high issues present, verify on staging first`
- `CLEAR TO DEPLOY — no blocking issues found`

---

## Tone and approach

Be specific. "The `controllers` key in the manifest does nothing" is useful.
"There may be some issues with the manifest" is not.

Cite the exact file, line number or section, and field/element name for every
finding. Give the exact fix, not a vague suggestion.

When something is correct and well-done, say so briefly in the "Verified clean"
section — this builds the user's confidence and tells them what they do not
need to worry about.

If the user shares partial code (e.g. only the view, not the model), flag which
checks could not be completed due to missing files, and ask for them if they
would affect the verdict.
