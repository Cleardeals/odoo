---
name: odoo-pre-push-review
description: >
  Reviews Odoo module code before it is pushed to production and flags all issues
  that would cause errors, data loss, or broken deployments. Use this skill whenever
  the user shares Odoo Python models, XML views, CSV security files, __manifest__.py
  files, or migration scripts and wants them checked before deployment. Also trigger
  when the user says things like "is this ready to deploy", "review my Odoo code",
  "check this before I push", "what's wrong with my manifest", "will this migration
  work", or "pre-push review". Covers: manifest version/data registration gaps,
  migration script correctness and idempotency, model access rule completeness,
  view/field consistency, security rule logic, and controller registration patterns.
  Always use this skill for any Odoo deployment review — do not attempt this without it.
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
