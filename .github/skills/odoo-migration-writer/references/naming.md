# Migration File Naming Convention (Odoo 19)

## The full path structure

```
{module}/migrations/{full_version}/{phase}-{descriptor}.py
```

Or using the preferred alias:

```
{module}/upgrades/{full_version}/{phase}-{descriptor}.py
```

Both `migrations/` and `upgrades/` are valid from Odoo 13+. `upgrades/` is
the preferred name because "migrate" implies moving away from Odoo, while
"upgrade" correctly describes what is happening. Either works — pick one
and be consistent within a project.

## Full version format

```
{odoo_major_version}.{module_minor_version}
```

For Cleardeals on Odoo 19:
```
19.0.1.4.0
│  │ │ │ └─ patch (increment for each new migration batch)
│  │ │ └─── minor (increment for new features)
│  │ └───── major (increment for breaking changes)
│  └──────── always 0 for the second segment in Odoo versioning
└──────────── Odoo series
```

The version in the folder name must be:
- **Higher** than the currently installed module version
- **Equal to or lower** than the version set in `__manifest__.py`

If neither condition is true, the script does not run.

## Phase prefix

| Prefix | Phase | When it runs |
|---|---|---|
| `pre-` | Pre-phase | Before the module is loaded and updated |
| `post-` | Post-phase | After the module and its dependencies are loaded and updated |
| `end-` | End-phase | After ALL modules have been loaded and updated |

## Descriptor

The part after the phase prefix is free-form snake_case. Make it descriptive:

```
pre-seed_portal_listings.py         ✓ clear
pre-migrate.py                      ✗ vague — what is being migrated?
pre-rename_portal_name_to_source.py ✓ exact
pre-fix.py                          ✗ useless
post-drop_legacy_portal_columns.py  ✓ clear
post-update.py                      ✗ vague
```

## Ordering within a phase

Files within a phase execute in **lexical order**. When multiple scripts
run in the same phase and order matters, prefix with a two-digit number:

```
pre-01-validate_source_data.py     runs first
pre-02-seed_portal_listings.py     runs second
pre-03-normalise_labels.py         runs third
```

Without numbers, lexical order applies:
```
pre-drop_columns.py     'd' comes before 's'
pre-seed_new_table.py   runs after drop — which may be wrong!
```

When in doubt, use numbers. They make intent explicit.

## Real examples from this codebase

```
# Backfilling portal listings from flat fields
properties/migrations/19.0.1.1.0/pre-seed_portal_listings.py

# Improving the label format on already-seeded rows
properties/migrations/19.0.1.2.0/pre-normalise_listing_labels.py

# Final label format with prop_id | portal | listing_id
properties/migrations/19.0.1.3.0/pre-finalise_listing_labels.py

# Renaming portal_name to source on leads_new
leads/migrations/19.0.1.2.0/pre-rename_portal_name_to_source.py

# Dropping the legacy flat columns after verification
properties/migrations/19.0.1.4.0/post-drop_legacy_portal_columns.py
```

## What NOT to name your files

These are all wrong and the migration will not run or will cause confusion:

```
pre_migrate.py          ✗ underscore not hyphen — wrong naming scheme
migrate.py              ✗ no phase prefix — never executed automatically
post_migrate.py         ✗ underscore not hyphen
pre-migrate.py          ✗ 'migrate' alone is vague but technically works —
                          avoid because it tells you nothing about the change
19.0.1.4.0.py           ✗ file in wrong location, not in version subfolder
```

## Verifying scripts will run

Before deploying, confirm the version arithmetic:

```sql
-- Check installed version
SELECT latest_version FROM ir_module_module WHERE name = 'properties';
-- e.g. returns: 19.0.1.3.0

-- Your migration folder: 19.0.1.4.0
-- Your manifest version: 19.0.1.4.0
-- 19.0.1.3.0 < 19.0.1.4.0 ≤ 19.0.1.4.0 → WILL RUN ✓

-- If manifest were still 19.0.1.3.0:
-- 19.0.1.3.0 < 19.0.1.4.0 but 19.0.1.4.0 > 19.0.1.3.0 → WILL NOT RUN ✗
```
