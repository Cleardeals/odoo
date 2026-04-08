# Migration Phases — Decision Tree and Examples

## What happens in each phase

```
INSTALLED MODULE STATE (e.g. 19.0.1.3.0)
            │
            ▼
┌───────────────────────────────────────┐
│            PRE PHASE                  │
│  pre-*.py files run here              │
│                                       │
│  • Old columns STILL EXIST            │
│  • New model tables MAY exist         │
│    (if added in a prior version)      │
│  • New model tables MAY NOT exist     │
│    (if new in THIS version)           │
│  • ORM has NOT applied changes yet    │
│                                       │
│  Use for: rescuing data, renaming     │
│  columns, seeding new tables from     │
│  data that is about to be removed     │
└───────────────────────────────────────┘
            │
            ▼
┌───────────────────────────────────────┐
│         ORM APPLIES CHANGES           │
│                                       │
│  Adds new columns, removes deleted    │
│  fields, creates new model tables,    │
│  applies _sql_constraints.            │
│                                       │
│  You cannot intervene here.           │
└───────────────────────────────────────┘
            │
            ▼
┌───────────────────────────────────────┐
│           POST PHASE                  │
│  post-*.py files run here             │
│                                       │
│  • New columns EXIST                  │
│  • Old columns that were REMOVED      │
│    from Python model are NOW GONE     │
│  • New model tables EXIST             │
│                                       │
│  Use for: dropping legacy columns,    │
│  recomputing stored fields, creating  │
│  indexes, sending notifications       │
└───────────────────────────────────────┘
            │
            ▼
┌───────────────────────────────────────┐
│            END PHASE                  │
│  end-*.py files run here              │
│                                       │
│  • ALL modules have been upgraded     │
│  • Cross-module data dependencies     │
│    are fully resolved                 │
│                                       │
│  Use for: cross-module fixes,         │
│  data that depends on multiple        │
│  modules being in their final state   │
└───────────────────────────────────────┘
            │
            ▼
UPGRADED MODULE STATE (e.g. 19.0.1.4.0)
```

---

## Decision table

| Situation | Phase | Reasoning |
|---|---|---|
| Seeding `property_portal_listing` from `ninety_nine_acres_id` etc. | `pre` | Source columns exist in pre; ORM may remove them after |
| Renaming `leads_new.portal_name` → `leads_new.source` | `pre` | Must rename before ORM tries to create `source` as a new column |
| Copying data before a `fields.Char` is deleted from Python | `pre` | ORM deletes the column; rescue in pre |
| Normalising labels in `property_portal_listing` (table already exists from prior version) | `pre` | Table exists, safe to update; do before ORM applies any new constraints |
| Dropping `ninety_nine_acres_id` after removing field from Python | `post` | ORM must finish first — it may still reference the column during its own processing |
| Recomputing `base_property_tag` (a stored related field) after restructure | `post` | Needs new column structure to be in place |
| Adding an index on `portal_listing_id` (ORM-managed column) | `post` | Column created by ORM; index after |
| Fixing data that depends on both `properties` and `leads` being upgraded | `end` | Both modules must be fully updated first |

---

## The critical mistake — DROP in pre

```
# WRONG:
properties/migrations/19.0.1.4.0/pre-drop_legacy_columns.py

def migrate(cr, version):
    cr.execute("ALTER TABLE property_base DROP COLUMN ninety_nine_acres_id")
    # ↑ You drop the column here

    # Then the ORM runs and tries to manage ninety_nine_acres_id
    # — it's gone — CRASH during upgrade
```

```
# CORRECT:
properties/migrations/19.0.1.4.0/post-drop_legacy_columns.py

def migrate(cr, version):
    # ORM has already finished. The Python field declaration is gone.
    # The ORM no longer references ninety_nine_acres_id.
    # Now safe to drop.
    cr.execute("ALTER TABLE property_base DROP COLUMN IF EXISTS ninety_nine_acres_id")
```

---

## The other critical mistake — reading a dropped column in post

```
# WRONG:
properties/migrations/19.0.1.4.0/post-seed_from_old_columns.py

def migrate(cr, version):
    # The field ninety_nine_acres_id was removed from property_base.py
    # The ORM dropped it. It no longer exists.
    cr.execute("SELECT ninety_nine_acres_id FROM property_base")
    # ↑ ERROR: column "ninety_nine_acres_id" does not exist
```

```
# CORRECT:
properties/migrations/19.0.1.4.0/pre-seed_from_old_columns.py

def migrate(cr, version):
    # In pre-phase, ninety_nine_acres_id still exists.
    # Seed the new table before ORM removes the source column.
    cr.execute("""
        INSERT INTO property_portal_listing (property_base_id, portal_name, ...)
        SELECT id, '99acres', ninety_nine_acres_id FROM property_base
        WHERE ninety_nine_acres_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
```

---

## When a new model table may not exist in pre-phase

If `property_portal_listing` is a brand new model added in this same upgrade:

```
Scenario A: Model existed in a previous version
  → Table was created when that version was installed
  → Table EXISTS in pre-phase
  → Safe to INSERT in pre-phase ✓

Scenario B: Model is new in THIS upgrade
  → ORM creates the table during this upgrade
  → Table does NOT EXIST yet in pre-phase
  → INSERT in pre-phase will fail with "table does not exist"
  → Must use post-phase instead, or add _table_exists() guard
```

Always use the `_table_exists()` guard when there is any doubt:

```python
def migrate(cr, version):
    if not _table_exists(cr, "property_portal_listing"):
        _logger.warning(
            "%s %s: property_portal_listing not found — "
            "skipping (table will be seeded post-ORM if needed).",
            __name__, version,
        )
        return
    # ... proceed with insert
```

---

## Multi-script example: the full portal listing migration

This is how the Cleardeals portal listing work was structured:

```
properties/migrations/19.0.1.1.0/pre-seed_portal_listings.py
  → INSERT from flat columns with property_tag as label
  → ON CONFLICT DO NOTHING

properties/migrations/19.0.1.2.0/pre-normalise_listing_labels.py
  → UPDATE labels to prop_id | property_tag | listing_id format
  → WHERE listing_label IS NULL OR stale format

properties/migrations/19.0.1.3.0/pre-finalise_listing_labels.py
  → Final format: prop_id | portal_name | listing_id
  → UPDATE all rows matching old formats

# Future — when ready to drop the legacy columns:
properties/migrations/19.0.1.4.0/post-drop_legacy_portal_columns.py
  → ALTER TABLE property_base DROP COLUMN IF EXISTS ninety_nine_acres_id
  → ... repeat for all four
```

Each version is a discrete, independently deployable change. If `19.0.1.2.0`
had a bug, you fix it in `19.0.1.3.0` — you never edit `19.0.1.2.0` after
it has run on any environment.
