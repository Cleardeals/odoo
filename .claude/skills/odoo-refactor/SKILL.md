---
name: odoo-refactor
description: >
  Refactors Odoo module code to be cleaner, more maintainable, and easier
  to extend — without changing behaviour. Use this skill whenever the user
  wants to improve existing code quality, reduce duplication, simplify
  complex logic, rename things for clarity, extract shared utilities,
  or prepare code for a new feature. Trigger on: "refactor this",
  "clean up this code", "this is getting messy", "too much duplication",
  "hard to understand", "how do I simplify this", "this method is too long",
  "extract this into a helper", "rename this field", "consolidate these",
  "this is hard to maintain", "technical debt", "code smell", "this is
  getting hard to change", "improve this before adding features", or any
  request to make existing code better without adding new functionality.
  Also trigger proactively when reviewing code for pre-push and noticing
  structural problems beyond just correctness — refactoring opportunities
  should be called out separately from bugs. Always use this skill for
  any refactoring task — it contains safe refactoring sequences, the
  Cleardeals-specific patterns, and the discipline to never break
  behaviour while improving structure.
---

# Odoo Refactor

You make existing code better without changing what it does. Every refactoring
you produce must be behaviourally equivalent — the tests that passed before
must still pass after, and the system must do exactly the same thing for
every user.

Refactoring is not rewriting. Rewriting changes the design. Refactoring
improves the expression of the existing design. The distinction matters
because refactoring can be done incrementally and safely, while rewriting
is a high-risk replacement.

The goal is code that a developer who joins the team six months from now
can understand, modify, and extend with confidence — without needing the
original author to explain it.

**Companion skill — the standard you refactor toward.** This skill owns the
*safe how-to* of changing code without changing behaviour. What "good" looks
like — naming, function size, deliberate error handling, SOLID in Odoo, the
sanctioned-swallow rule — lives in the **`odoo-clean-code`** skill. When you
diagnose a smell here, the target shape is defined there. Use them together:
clean-code says *what good looks like*, refactor says *how to get there safely*.

---

## The refactoring contract

Before touching any code:

**1. Understand what the code does, not just what it says.**
Read the code fully. Understand every branch, every side effect, every
implicit dependency. A refactoring that misunderstands the code will
change behaviour silently. This is the most dangerous kind of bug.

**2. Verify tests exist before refactoring.**
If the code has no tests, write tests first. Tests are the safety net
that makes refactoring safe. Without them, you cannot know whether you
broke something. If writing tests reveals unexpected behaviour, stop —
that is a bug to understand and fix separately, not something to refactor
around.

**3. Refactor in small steps, each independently deployable.**
Never do a massive refactor in one commit. Each step must be a working
state of the codebase. If a step breaks something, you can revert just
that step without losing all the work.

**4. Never mix refactoring with feature work.**
If you are refactoring `_find_property()` and notice it needs to call
`resolve_property()` as part of the CDLS-131 feature — do the refactor
commit first, then the feature change. Mixing them makes the git history
impossible to understand and code review impossible to do.

---

## The five refactoring categories

Every refactoring falls into one of these. Identify the category first —
it determines the safe sequence and the risk level.

```
Category 1 — RENAME (lowest risk)
  Renaming a variable, method, field, or model to better express intent.
  Risk: breaking references in other files.
  Safe sequence: rename in Python → update all XML references →
                 update tests → update migration scripts if it's a DB column.

Category 2 — EXTRACT (low risk)
  Moving duplicated or complex logic into a named helper method or module.
  Risk: introducing a regression if the extraction changes behaviour subtly.
  Safe sequence: write the helper → verify it produces identical output
                 in all cases → replace callsites one by one → delete original.

Category 3 — SIMPLIFY (medium risk)
  Replacing complex conditional logic with clearer equivalents.
  Risk: edge cases hidden in the original complexity.
  Safe sequence: add tests covering all branches FIRST → simplify →
                 verify tests still pass.

Category 4 — RESTRUCTURE (medium-high risk)
  Moving logic between files, reorganising model method groups,
  splitting large models, merging duplicated models.
  Risk: circular imports, broken module dependencies, missing __init__ imports.
  Safe sequence: plan the full file structure → move one unit at a time →
                 verify the module loads after each move.

Category 5 — SCHEMA CHANGE (highest risk)
  Renaming a model field, changing a field type, removing a field.
  Risk: data loss, broken views, broken API consumers, broken tests.
  Safe sequence: requires a migration script + manifest bump + full callsite
                 audit before any code change. Use the odoo-migration-writer
                 skill in parallel.
```

Read: `references/standards/safe-sequences.md` for the step-by-step
safe sequence for every category.

---

## Stage 1 — Diagnose before prescribing

Read the code fully before suggesting any refactoring. Identify the
specific problem. Name it precisely. A vague "this is messy" diagnosis
leads to vague refactoring that makes the code different but not better.

**The seven code smells worth acting on:**

```
1. LONG METHOD — a method over 20 lines doing more than one thing
   Prescription: extract sub-tasks into named helper methods

2. MAGIC VALUES — literal strings or numbers with unexplained meaning
   Prescription: extract to named constants at module level

3. DUPLICATION — the same logic in two or more places
   Prescription: extract to a shared helper; identify the canonical home

4. DEEP NESTING — more than 3 levels of indentation
   Prescription: early returns, extracted conditions, guard clauses

5. COMMENT THAT EXPLAINS WHAT — comment restating the code in English
   Prescription: rename the variable or method so the code is self-explanatory

6. INCONSISTENT ABSTRACTION — method mixes high-level intent with
   low-level implementation details
   Prescription: extract the low-level details into named helpers with
   descriptive names, leaving the high-level method readable as a summary

7. LARGE CLASS — model with 15+ methods doing multiple unrelated things
   Prescription: identify the distinct responsibilities; consider whether
   some methods belong on a different model or in a utility module
```

Read: `references/standards/code-smells.md` for detailed diagnosis
patterns with examples from this codebase.

---

## Stage 2 — Plan the refactoring

For every refactoring, produce a plan before writing code:

```
WHAT: [One sentence — what structural problem is being fixed]
WHY: [Why this makes the code more maintainable — what becomes easier]
RISK: [What could break if done incorrectly]
SEQUENCE: [The ordered steps, each independently deployable]
TESTS NEEDED FIRST: [What tests must exist before starting]
FILES TOUCHED: [Every file that changes — helps estimate scope]
MIGRATION NEEDED: [Yes/No — if Yes, link to migration-writer skill]
```

If the plan touches more than 10 files or requires a schema change,
it is large enough to be a Jira task (CDLS-XXX) tracked separately,
not an inline fix.

---

## Stage 3 — Execute the refactoring

Read: `references/patterns/refactoring-patterns.md` for specific
before/after patterns for every common refactoring in this codebase.

Read: `references/playbooks/` for step-by-step playbooks for the
most common large-scale refactorings:
- `playbooks/rename-field.md` — safely rename any model field
- `playbooks/extract-helper.md` — extract shared logic across modules
- `playbooks/simplify-conditionals.md` — replace complex if/else trees
- `playbooks/split-large-model.md` — decompose a model doing too much

---

## Stage 4 — Verify nothing broke

After every refactoring step:

```
□ The module loads without errors (odoo-bin -u module --stop-after-init)
□ All existing tests pass
□ No new warnings in the server log
□ A manual smoke test of the primary user workflow confirms no regression
□ git diff shows only structural changes — no logical differences
```

If any of these fail, the refactoring changed behaviour. Stop, understand
why, and fix the regression before continuing.

---

## Output format

For every refactoring task, produce in this order:

### 1. Diagnosis
The specific smell, where it is, and why it matters for maintainability.
One paragraph. Cite specific line numbers or method names.

### 2. Refactoring plan
The WHAT / WHY / RISK / SEQUENCE / TESTS / FILES / MIGRATION summary.

### 3. Before and after
Complete before/after code for every file that changes.
Never produce just the "after" — showing both makes the change reviewable
and helps the developer understand exactly what changed and why.

### 4. Tests to add or update
Any new tests required to cover the refactored code.
Any existing tests that need updating because names or interfaces changed.

### 5. Verification steps
Specific things to check after applying the refactoring.
Not "run the tests" — specific assertions or manual checks.

---

## Cleardeals-specific refactoring priorities

These are the areas of the codebase most in need of ongoing refactoring
attention. When given code from any of these areas, apply the relevant
standard automatically.

**`_find_property()` and `resolve_property()`**
The portal field map dict is the historical approach. Any code still
using `portal_field_map` should be refactored to use `resolve_property()`
on `property.portal.listing`. This is a Category 1 (rename/replace)
refactoring with a clear extraction target.

**`property_sync.py` and `property_inventory.py`**
These two files share almost identical BQ sync logic. The duplication
is Category 3 — the shared parts belong in a utility function or base
class. Every time the sync logic is changed, it must be changed in both
files, which is a maintenance trap.

**`_process_lead_logic()` fallback RM assignment**
The hardcoded RM names (`Pratham Bhandari`, `Mayuri Malivad`,
`Naresh Rojiya`) are magic values. They belong in `ir.config_parameter`
or a separate configuration model, not in the code. Any change to RM
assignments currently requires a code deployment.

**Status selection field strings**
The `current_status` Selection values are long strings defined inline
and referenced as string literals throughout the codebase. They belong
as module-level constants so they can be referenced symbolically.

**Comment-to-code ratio**
Many methods in `new_portal_leads.py` have `_logger.info(f"🔄 Processing...")`.
The emoji logging, while visually distinctive, should be supplemented with
structural comments explaining the WHY of the logic, not just the WHAT.