# Manifest Reference (`__manifest__.py`)

## Version field

The `version` field controls which migration scripts run on upgrade.
Odoo runs all migration scripts whose folder version is strictly greater than
the installed version and less than or equal to the manifest version.

**Rule:** `manifest version` must be ≥ the highest migration folder version.

```
Installed:  19.0.1.0.0
Migrations: 19.0.1.1.0 / 19.0.1.2.0 / 19.0.1.3.0
Manifest:   19.0.1.3.0   ← correct — all three scripts will run

Manifest:   19.0.1.0.0   ← WRONG — no scripts run, table stays empty
Manifest:   19.0.1.2.0   ← WRONG — 19.0.1.3.0 script never runs
```

## Data list load order

Odoo loads `data` entries in order. A record that references another record
must come after the record it references.

Correct order:
1. `security/property_security.xml` — defines groups
2. `security/ir.model.access.csv` — references groups defined above
3. `data/property_cron.xml` — cron jobs (may reference groups)
4. `views/*.xml` — views (may reference groups and actions)
5. `views/menus.xml` — menus reference actions, so must come last

**Common mistake:** access CSV before security XML. The CSV rows reference
group xmlids that don't exist yet — Odoo creates the rows with no group,
giving everyone access.

## Controllers key

```python
"controllers": ["controllers/controllers.py"]  # DOES NOTHING
```

This key is not processed by Odoo. Controllers are discovered through
Python imports. The correct registration is:

```python
# properties/__init__.py
from . import models, controllers

# properties/controllers/__init__.py
from . import controllers
```

Remove the `controllers` key from the manifest. It creates a false sense
of security — a developer might think removing a controller from this list
disables it, when in fact the import is what matters.

## New model checklist

When a new model is added, verify ALL of the following:
1. Model file imported in `models/__init__.py`
2. At least one row in `security/ir.model.access.csv` for the new model
3. View file (if any) listed in manifest `data`
4. Any `ir.rule` for the new model defined in `security/*.xml`

Missing any one of these causes a different class of failure:
- Missing `__init__.py` import: model does not exist, module load fails
- Missing access row: `AccessError` for all users at runtime
- Missing view in data: view not loadable, menu item leads to blank page
- Missing ir.rule: model is accessible to users who should not see it

## Description field

Keep the description accurate. Stale descriptions (referencing one-time
migrations that are complete, features that have changed, or workflows that
no longer apply) mislead developers who inherit the codebase.

Update description when:
- A new model or major feature is added
- A one-time migration is completed (mark it as done, or remove)
- Module purpose changes
