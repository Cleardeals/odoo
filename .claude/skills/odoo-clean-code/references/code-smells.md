# Code Smells — diagnosis & prescription (Cleardeals)

Name the smell precisely before prescribing. A vague "messy" leads to change
without improvement. Each smell below maps to a concrete fix; for the *safe
transformation sequence*, hand off to the `odoo-refactor` skill.

| Smell | How it shows up here | Prescription |
|-------|----------------------|--------------|
| **Long method** | A handler with validation + lookup + create + notify inlined | Extract each sub-task into a named `_owa_*` helper; orchestrator becomes a summary |
| **Long parameter list** | A helper taking 5+ positional args | Pass the record or a `vals` dict; OWL → an options object |
| **Magic values** | Hardcoded RM names, status strings, topic names inline | Module constants (`_STATUS_RANK`), `ir.config_parameter`, or a Selection |
| **Duplication** | Same BQ sync in `property_sync.py` & `property_inventory.py`; repeated phone-normalize | Extract one canonical helper; reuse `_standardize_phone` / `_owa_canonical_wa_phone` |
| **Deep nesting** | 3+ `if` levels in a send/handler path | Guard clauses, early returns |
| **God model / component** | One model with many unrelated methods | Split by responsibility into `_inherit` files or a service model |
| **Primitive obsession** | Passing raw phone strings everywhere | Normalize at the boundary via the canonical helper; keep one representation |
| **Dead code** | Commented-out blocks, unused fields/methods | Delete — git remembers |
| **Comment explains WHAT** | `# loop items and sum` | Rename / restructure so the code says it |
| **Feature envy** | A helper reaching deep into another model's fields | Move the logic onto the model that owns the data |
| **Swallowed error** | `except Exception: pass` on a core operation | Re-raise or handle; only non-critical side effects may swallow (logged + commented) |

---

## Repo-specific recurring smells (fix on sight)

These are known hotspots — when you touch code near them, apply the fix.

**Magic phone handling.** Phone strings get re-normalized ad hoc. There are
two canonical helpers — use them, don't reinvent:
`leads.new._standardize_phone()` (10-digit lead format) and
`wa.conversation._owa_canonical_wa_phone()` (12-digit WA key).

**Hardcoded RM / config in code.** Fallback RM names and thresholds belong in
`ir.config_parameter`, not inline literals that need a deploy to change.

**Status / Selection string literals.** Long Selection values referenced as
bare strings across files want module-level constants so they're referenced
symbolically and typo-proof (see `_STATUS_RANK`, `_FAILURE_CODE_TO_STATUS`
in `wa_conversation.py` for the pattern).

**HTML generated in Python for the UI.** Any method building markup strings
for the frontend is a smell — it belongs in an OWL component fed plain data
(see the `cleardeals-owl-components` skill).

**Emoji-only logging.** `_logger.info("🔄 Processing...")` says *what*; add a
structural reason (*why* the branch is taken) or replace with a clearer name
+ a meaningful log line.

---

## Diagnosis output (when reviewing)

For each finding, produce:

```
[SEVERITY] file:line — <smell named precisely>
  Why it matters: <the cognitive-load / maintenance cost, one line>
  Fix: <the concrete change>
  Safe how-to: <hand to odoo-refactor if it's a behaviour-preserving transform>
```

Severity follows the SKILL.md scale (CRITICAL / HIGH / MEDIUM / LOW). Group
by severity, highest first. Never report a smell without a concrete fix.
