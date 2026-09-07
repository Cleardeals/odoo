# Refactoring Playbooks

Step-by-step guides for the most common large-scale refactorings
in the Cleardeals codebase. Each playbook is independently executable.

---

## Playbook 1 — Rename a model field safely

**When to use:** A field's name no longer accurately describes what it stores.
Example: `portal_name` → `source` (generalising from portal-only to any lead origin).

**Time estimate:** 2–4 hours depending on number of references.

**Before starting:** Run `grep -rn "portal_name" custom_addons --include="*.py" --include="*.xml"`
and count the hits. If > 20, allocate more time.

```
PHASE 1 — Preparation (do not touch model code yet)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1.1 Write tests for every code path that reads or writes the field.
    If tests exist, verify they cover all branches.

1.2 Write the pre-migrate.py script using the odoo-migration-writer skill.
    The script renames the DB column before the ORM runs.
    File: {module}/migrations/{new_version}/pre-rename_{old}_to_{new}.py

1.3 Write a migration test using the odoo-test-writer skill.

1.4 Run the migration on a staging DB with production data.
    Verify the column was renamed, not duplicated.

PHASE 2 — Python model changes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

2.1 Rename the field declaration in the primary model file.
    Update: string=, help=, any tracking= or related= references.

2.2 Update all references in the same file (method bodies, compute methods).

2.3 Update references in other Python files (search in order):
    - Same module: models/, wizard/, controllers/
    - Dependent modules: leads/, lead_suggestor/

2.4 Bump the manifest version.

2.5 Load the module: odoo-bin -u module --stop-after-init
    Fix any load errors before continuing.

PHASE 3 — XML and data files
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

3.1 Update view files: form views, list views, search views.
    Special attention: filter_domain attributes, decoration conditions,
    attrs/invisible expressions.

3.2 Update ir.filters records in data XML files.

3.3 Update any report templates or QWeb that reference the field.

3.4 Load the module again. Run tests.

PHASE 4 — External integrations
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

4.1 Update the n8n webhook payload key in _cron_send_new_lead_webhooks.
    Coordinate with whoever manages the n8n workflow — they must update
    the workflow to read the new key before the Odoo change is deployed.

4.2 Update the WhatsApp message builder if it references the field.

4.3 Update the API serialiser if the field appears in the response shape.
    Update the API documentation (docs/api.md).

PHASE 5 — Tests
━━━━━━━━━━━━━━━

5.1 Update all test fixtures (setUpClass create() calls).
5.2 Update all test assertions (field name in assertEqual etc.).
5.3 Rename test methods that include the old field name.
5.4 Run the full test suite.

PHASE 6 — Commit
━━━━━━━━━━━━━━━━

6.1 git add migrations/ → commit "migration: rename portal_name to source (19.0.X.X)"
6.2 git add models/ → commit "refactor: rename field portal_name to source"
6.3 git add views/ data/ → commit "refactor: update views for portal_name rename"
6.4 git add tests/ → commit "refactor: update tests for portal_name rename"

Never in one commit. Four commits allows reverting any phase independently.
```

---

## Playbook 2 — Extract shared logic from two sync files

**When to use:** `property_sync.py` and `property_inventory.py` have
diverged or you are about to change logic that exists in both.

**Time estimate:** 3–5 hours.

```
PHASE 1 — Identify the exact duplication
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1.1 Diff the relevant sections of both files.
    diff <(grep -A 20 "portal_listing" property_sync.py) \
         <(grep -A 20 "portal_listing" property_inventory.py)

1.2 List every place the duplicated code diverges.
    Each divergence is either: a legitimate difference (keep it),
    or a drift (the files should be identical — note for step 3.2).

1.3 Write a test that verifies both files produce identical output
    for the same BigQuery row input. This test catches future divergence.

PHASE 2 — Create the shared utility
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

2.1 Create custom_addons/properties/utils/__init__.py (empty)
2.2 Create custom_addons/properties/utils/bq_sync.py
    with the shared function. See refactoring-patterns.md Pattern 3.

2.3 Add the import to properties/models/__init__.py:
    from . import utils  # or import directly in the files that need it

2.4 Load the module: odoo-bin -u properties --stop-after-init
    Verify utils/ loads without errors.

PHASE 3 — Replace in property_sync.py first
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

3.1 Import the shared function in property_sync.py.
3.2 Replace the inline block with the shared function call.
3.3 Run tests. Fix any divergence found.
3.4 Commit: "refactor: use shared bq_sync utility in property_sync"

PHASE 4 — Replace in property_inventory.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

4.1 Import the shared function in property_inventory.py.
4.2 Replace the inline block.
4.3 Run tests.
4.4 Commit: "refactor: use shared bq_sync utility in property_inventory"
```

---

## Playbook 3 — Break up a large method

**When to use:** A method exceeds 20 lines, does multiple distinct things,
or requires a comment to explain each section.

**Time estimate:** 1–2 hours.

```
PHASE 1 — Map the method's responsibilities
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1.1 Read the method and annotate each section with a sentence describing
    what it does. Each sentence is a potential helper method name.

1.2 Identify the dependencies between sections.
    A section that produces data used by the next section is a good
    extraction candidate — it has a clear input/output contract.

1.3 Write tests for the whole method before changing anything.

PHASE 2 — Extract one helper at a time
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

2.1 Identify the LAST distinct section of the method.
    Extract it first — it has no downstream dependencies within the method.

2.2 Create the helper method with a descriptive name.
    The name should read as the section's one-sentence description from 1.1.

2.3 Replace the section with a call to the helper.

2.4 Run tests. If anything fails, the extraction changed behaviour.
    Fix the helper.

2.5 Repeat 2.1–2.4 for each remaining section, working backwards.

PHASE 3 — Name the orchestrating method
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

3.1 The remaining method body should now read as a clear sequence
    of helper calls. Update its docstring to reflect the orchestration.

3.2 If the method is still longer than 10 lines, repeat Phase 2.

3.3 Commit: "refactor: extract helpers from _process_lead_logic()"
```

---

## Playbook 4 — Add constants for magic values

**When to use:** String literals or numbers appear in logic without
explanation, or the same string appears in multiple files.

**Time estimate:** 30–60 minutes.

```
PHASE 1 — Find all magic values
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1.1 Search for repeated string literals:
    grep -rn '"99acres"\|"MagicBricks"\|"Housing.com"\|"OLX"' \
    custom_addons --include="*.py" | grep -v "constants.py"

1.2 Search for state string literals:
    grep -rn '"new"\|"assigned"\|"failed"' \
    custom_addons --include="*.py" | grep "leads"

1.3 List every magic number (timeouts, limits, grace periods):
    grep -rn "timedelta(hours=" custom_addons --include="*.py"
    grep -rn "limit=[0-9]" custom_addons --include="*.py"

PHASE 2 — Create the constants file
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

2.1 Create custom_addons/{module}/constants.py
    See refactoring-patterns.md for the template.

2.2 Define constants for every value found in Phase 1.
    Group by domain: portal names, lead states, timing values.

PHASE 3 — Replace occurrences
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

3.1 Import constants at the top of each file that references them.
3.2 Replace each occurrence — one file at a time.
3.3 Run tests after each file.
3.4 Re-run the grep from Phase 1. It should return zero hits.

3.5 Commit: "refactor: extract magic strings to constants"
```

---

## The maintainability scorecard

Use this to measure whether a refactoring made the code more maintainable.
Score before and after. A good refactoring improves every applicable dimension.

```
READABILITY
□ Can a developer new to the file understand each method without reading
  other methods? (each method is self-contained)
□ Do method names express intent, not mechanics?
□ Are magic values replaced with named constants?
□ Do comments explain WHY, not WHAT?

CHANGEABILITY
□ To change the default RM assignment, how many files must be edited?
  (should be 1 — the config parameter data file)
□ To add a fifth portal (NoBroker), how many files must be edited?
  (should be 2 — constants.py for the new constant, and the Selection field)
□ To change the unassigned lead grace period, how many files must be edited?
  (should be 1 — the constants file)

TESTABILITY
□ Can each method be tested independently without testing the whole feature?
□ Are there any methods that are impossible to test without side effects?

DUPLICATION
□ Does the same logic exist in more than one place?
□ When you change X in property_sync.py, must you also change it
  in property_inventory.py?

COHESION
□ Does each method do exactly one thing?
□ Does each file have a single, clear purpose?
□ Are there methods that feel out of place in their current model?
```

A healthy codebase scores positively on all dimensions. Start with
the lowest-scoring dimension — it is always the highest-value refactoring target.