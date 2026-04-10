# Safe Refactoring Sequences

Every category of refactoring has a sequence that keeps the codebase
in a working state at every step. Never skip steps. Never combine steps
from different sequences.

---

## Category 1 — Rename (variable, method, constant)

Risk: references in other files not updated.

```
Step 1: Add tests covering all code paths that call the old name
        (if tests do not already exist)

Step 2: Search every file for the old name
        grep -rn "old_name" custom_addons --include="*.py" --include="*.xml"

Step 3: Rename in the Python model/method file

Step 4: Update every Python reference (other models, wizards, controllers)

Step 5: Update every XML reference (views, data files, security)
        grep -rn "old_name" custom_addons --include="*.xml"

Step 6: Update every test reference (fixtures, assertions, method names)

Step 7: Update docstrings and comments that mention the old name

Step 8: Load the module — odoo-bin -u module --stop-after-init
        (a missing reference shows as a load error, not a runtime error)

Step 9: Run the tests

Step 10: git commit — "refactor: rename X to Y"
         Never mix with other changes in the same commit
```

### Special case: renaming a DB column (model field)

If the field stores data in the database, renaming it requires a migration.
The Python rename alone does NOT rename the DB column — Odoo will create
a new empty column with the new name while the old column retains its data.

```
Step 1: (above steps 1–2)

Step 3: Write the migration script BEFORE changing any Python
        File: {module}/migrations/{new_version}/pre-rename_{old}_to_{new}.py
        Use the odoo-migration-writer skill for this step.

Step 4: Rename the field in property_base.py / new_portal_leads.py etc.

Step 5: Bump the manifest version to match the migration folder

Step 6: (continue with above steps 4–10)

Step 7: Verify on staging that the column was renamed, not duplicated
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'leads_new'
        ORDER BY column_name;
```

---

## Category 2 — Extract (pull logic into a helper)

Risk: extraction changes behaviour if the helper does not handle all
the same cases as the original inline code.

```
Step 1: Add tests for the code being extracted
        Write tests that describe every branch, edge case, and side effect.
        Run them — they must all pass before you extract anything.

Step 2: Write the new helper method with the extracted logic
        Do NOT delete the original inline code yet.
        The helper is an addition, not a replacement.

Step 3: Write tests specifically for the new helper
        They should be identical in intent to the tests from Step 1.

Step 4: In the original method, replace ONE callsite with the helper.
        The inline code still exists elsewhere.

Step 5: Run all tests. If anything fails, the helper has a bug.
        Fix the helper, not the tests.

Step 6: Replace remaining callsites one by one, running tests after each.

Step 7: Delete the original inline code.

Step 8: Run all tests.

Step 9: git commit — "refactor: extract _helper_name() from method_name()"
```

### Special case: extracting to a shared utility (used by multiple modules)

```
Step 1-3: (as above)

Step 4: Decide the canonical home for the shared code
        Option A: utils.py in the module that owns the concept
        Option B: a new shared module that both depend on

Step 5: Create the utility file with __init__.py import

Step 6: Add the dependency in the consuming module's __manifest__.py

Step 7: Replace callsites in Module A, test

Step 8: Replace callsites in Module B, test

Step 9: git commit — "refactor: extract shared BQ sync utility"
```

---

## Category 3 — Simplify (complex conditionals)

Risk: edge cases are hidden in the original complexity. Simplification
that changes an edge case is a behaviour change, not a refactoring.

```
Step 1: Map every branch of the original logic
        Draw a decision tree. Every leaf is a test case.

Step 2: Write a test for every leaf in the decision tree
        If any branch has no test, add one before continuing.
        Run all tests — every branch must be covered.

Step 3: Write the simplified version ALONGSIDE the original
        Name it _new_method_name() temporarily.

Step 4: Write tests for the simplified version using the same cases.

Step 5: Verify both versions produce identical output for all inputs
        Write a comparison test if the logic is complex:
        for test_input in test_cases:
            self.assertEqual(
                original_method(test_input),
                simplified_method(test_input),
                f"Mismatch for input: {test_input}"
            )

Step 6: Replace the original with the simplified version.

Step 7: Run all tests.

Step 8: git commit — "refactor: simplify _method_name conditional logic"
```

### Guard clause pattern (most common simplification)

Replace nested if-else with early returns:

```python
# BEFORE — nested, hard to follow the happy path
def _process_lead_logic(self):
    if self.state == 'new':
        property_rec = self._find_property()
        if property_rec:
            rm = self._find_rm(property_rec)
            if rm:
                self.write({...})
            else:
                self.write({"state": "failed"})
        else:
            self.write({"state": "failed"})

# AFTER — guard clauses, happy path is the last thing
def _process_lead_logic(self):
    if self.state != STATE_NEW:
        return

    property_rec = self._find_property()
    if not property_rec:
        return self._mark_failed("Property not found")

    rm = self._find_rm(property_rec)
    if not rm:
        return self._mark_failed("RM not found")

    self.write({...})
```

---

## Category 4 — Restructure (move code between files)

Risk: circular imports, broken module dependencies, missing __init__.py entries.

```
Step 1: Plan the target file structure completely before moving anything.
        Draw the import graph. Verify no cycles.

Step 2: Create the new files with empty content and correct __init__.py imports.
        Load the module — verify it still loads (no import errors yet).

Step 3: Move ONE class or function.
        Copy-paste — do NOT delete from the original yet.
        Add an import alias in the original location pointing to the new one:
            from .new_location import MovedClass  # temporary alias

Step 4: Load the module. Run tests. Fix any import errors.

Step 5: If tests pass, delete the original definition (keep the alias).
        Load the module. Run tests.

Step 6: Repeat steps 3-5 for each class/function being moved.

Step 7: Update all callsites to import from the new location.
        Remove the temporary aliases.

Step 8: Load the module. Run tests.

Step 9: git commit — "refactor: move X to new_module.py"
```

---

## Category 5 — Schema change (field rename, type change, removal)

Risk: data loss, broken views, broken API consumers.
This is the highest risk category. It requires the migration-writer skill.

```
Step 1: Use the odoo-migration-writer skill to plan and write the migration.
        Do NOT touch any Python code until the migration is written and reviewed.

Step 2: Use the odoo-pre-push-review skill on the migration script.

Step 3: Write a migration test that verifies the DB state after migration.
        Use the odoo-test-writer skill for this.

Step 4: Run the migration on a staging DB with production data.
        Verify row counts and data integrity.

Step 5: NOW make the Python model changes.

Step 6: Update all XML views, search views, filter domains.
        grep -rn "old_field_name" custom_addons --include="*.xml"

Step 7: Update all API serialisers, controller field lists.

Step 8: Update all tests.

Step 9: Bump the manifest version.

Step 10: Run the full test suite on the staging DB.

Step 11: git commit per logical group:
         "migration: rename portal_name to source (19.0.1.X.0)"
         "refactor: update model — portal_name renamed to source"
         "refactor: update views — portal_name renamed to source"
         "refactor: update tests — portal_name renamed to source"
         Never in one commit.
```

---

## The incremental refactoring principle

Large refactors done in one step are dangerous. The codebase spends
hours or days in a broken state. Reviews are hard because the diff is massive.
If something goes wrong, rollback loses all progress.

Instead, ask: "What is the smallest independently deployable improvement?"

For the `property_sync.py` / `property_inventory.py` duplication:
```
Week 1: Extract build_portal_listing_commands() into property_sync.py
        (no new file, just a local helper)

Week 2: Move the helper to utils/bq_sync.py

Week 3: Update property_inventory.py to import from utils/bq_sync.py
        Delete the duplicated code from property_inventory.py

Week 4: (optional) Write a test that imports from both files and verifies
        they produce identical output for the same input
```

Each week's change is a single commit that leaves the codebase in a
better state than it found it. No "big refactor branch" that diverges
from main for three weeks and becomes impossible to merge.