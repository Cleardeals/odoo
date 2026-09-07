---
name: odoo-clean-code
description: >
  The Cleardeals clean-code standard for Odoo Python and OWL JavaScript.
  Defines what good code looks like in THIS repo — intention-revealing names,
  small single-responsibility methods, deliberate error handling, and
  self-documenting structure — adapted to Odoo ORM, recordsets, compute
  methods, sudo discipline, and OWL components. Use this skill whenever the
  user wants to write new code well, review code quality, or check a change
  before pushing. Trigger on: "is this clean", "review this code", "clean
  code", "code quality", "good naming", "is this readable", "this function
  is too long", "too many parameters", "self-documenting", "best practices",
  "how should I structure this", "code standards", "make this cleaner to
  read", or whenever producing or reviewing Python/OWL code in this project.
  This skill is the STANDARD (what good looks like). For transforming
  existing messy code toward it without changing behaviour, use the
  companion `odoo-refactor` skill (the safe how-to).
---

# Odoo Clean Code (Cleardeals)

You write and review code so the next reader — a new RM-tools developer six
months from now, or your future self — understands it without asking the
author. Clean code is not perfection; it is **reduced cognitive load**. A
method should do one thing, a name should reveal intent, and an `except`
should be a decision, not a shrug.

This skill is the **standard**. When you need to move existing code toward
this standard safely (behaviour-preserving), switch to the `odoo-refactor`
skill — it owns the safe sequences, the migration discipline, and the
five refactoring categories. Clean-code says *what good looks like*;
refactor says *how to get there without breaking anything*.

---

## The translation that matters

The classic clean-code rules were written for Java/TypeScript. This repo is
**Odoo 19 Python + OWL 2 JavaScript**. The principles are identical; the
idioms are not. Always express the rule in this stack's terms:

| Principle | In this repo it means |
|-----------|-----------------------|
| Reveal intent in names | `snake_case` verbs for methods, `leads.new`-style domain nouns, Odoo field suffixes (`_id`, `_ids`) — see [`naming.md`](references/naming.md) |
| One function, one thing | Handlers like `_handle_odoo_lead_replied` orchestrate; extract `_owa_*` helpers for each sub-task — see [`functions.md`](references/functions.md) |
| Deliberate errors | `UserError` / `ValidationError` for users; swallow ONLY non-critical side effects, always logged + commented — see [`error-handling.md`](references/error-handling.md) |
| SOLID, no god classes | Split by responsibility into separate models/services; depend on the ORM abstraction, inject via `self.env[...]` — see [`odoo-and-owl.md`](references/odoo-and-owl.md) |
| Comments explain WHY | Odoo logic has non-obvious *why*s (race locks, Pub/Sub at-least-once, sudo) — comment those, never the *what* |

---

## The five checks (run these every time)

When writing or reviewing any Python/OWL change, walk these in order. Each
links to the reference with repo-specific before/after examples.

### 1. Names reveal intent — [`naming.md`](references/naming.md)
No `data`, `res`, `vals2`, `tmp`, `x`. A reader should infer a name's purpose
without reading its definition. Booleans read as predicates (`is_active`,
`has_open_window`, `can_send`). Odoo conventions are non-negotiable:
Many2one ends `_id`, x2many ends `_ids`, compute methods are
`_compute_<field>`, constraints `_check_<rule>`, module-private helpers and
constants start `_`. Match the module's existing prefix (`_owa_` in
wa_communication, `_wa_` in the lead publisher).

### 2. Each function does one thing — [`functions.md`](references/functions.md)
Target ≤ 20 lines. An Odoo event handler or controller may legitimately be
longer because it *orchestrates*, but every sub-task (validation, lookup,
dedup, attribution, notification) belongs in a named helper read as a
sentence. Prefer guard clauses and early returns over nesting beyond 3
levels. `@api.model_create_multi` and computes operate on recordsets — loop
once, don't fan out per-record queries.

### 3. Errors are deliberate — [`error-handling.md`](references/error-handling.md)
User-facing failure → `raise UserError(...)`. Constraint violation →
`ValidationError`. Never a bare `except:` that hides a real bug. The repo's
**one sanctioned swallow**: a *non-critical side effect* (a Pub/Sub publish,
a bus notification, an analytics write) wrapped in `try/except` that
`_logger.exception(...)`s and carries a comment explaining why failing it
must not roll back the real work. Concurrency errors
(`SERIALIZATION_FAILURE`/`DEADLOCK_DETECTED`) are **re-raised**, never
swallowed, so Odoo can retry.

### 4. Structure is self-documenting — [`odoo-and-owl.md`](references/odoo-and-owl.md)
One model = one responsibility; one OWL component = one concern. No god
model with 20 unrelated methods — split into a mixin, a service model, or a
separate addon. `sudo()` is a deliberate, scoped privilege escalation with a
reason, not a blanket bypass. OWL: state in `useState`, side effects in the
right lifecycle hook, no business logic generated as HTML strings in Python.

### 5. Comments earn their place
Delete any comment that restates the code. Keep comments that capture a
*why* the code cannot: a business rule (cite the source), a race-condition
lock ordering, an at-least-once redelivery guard, a sudo justification, a
deliberate deviation. A comment compensating for a bad name is a bug —
rename instead.

---

## Severity (for reviews — match the repo's pre-push standard)

```
CRITICAL — must fix before merge
  God model / serious SRP violation; swallowed concurrency error or
  swallowed real exception; sudo bypassing an access rule it shouldn't;
  data-loss-shaped error handling.

HIGH — should fix
  Method > 50 lines doing several things; > 5 positional params on a
  helper; duplicated logic across modules; per-record query in a loop
  (N+1) over recordsets.

MEDIUM — consider fixing
  Method 20–50 lines; unclear name (`data`, `res`); nesting > 3 deep;
  comment explaining WHAT.

LOW — optional
  Style, a clearer local name, a docstring opportunity.
```

When reviewing, report findings in this order, each with `file:line`, the
smell named precisely, and the concrete fix. Vague "this is messy" is not a
finding. If the fix is a behaviour-preserving transformation, hand off to
`odoo-refactor` for the safe sequence.

---

## Red flags — stop and reconsider

| About to… | Ask… |
|-----------|------|
| Add a 5th positional arg to a helper | Should this take a dict of vals / a record instead? |
| Pass the 30th line in a method | Which sub-task can I extract into a named `_helper`? |
| Name something `data` / `res` / `vals2` | What does this actually represent in the domain? |
| Write `except Exception: pass` | Is this a *non-critical side effect*? If not, it's a bug-hider. |
| `.sudo()` a write | Whose rule am I bypassing, and is that correct here? Comment it. |
| Loop and `.search()` per record | Can I batch this into one domain / `read_group`? |
| Write a comment to explain the code | Can a better name make the comment unnecessary? |
| Generate HTML in a Python method for the UI | Should this be an OWL component fed plain data? |

---

## Reference index

| Topic | File | Covers |
|-------|------|--------|
| Naming | [`naming.md`](references/naming.md) | Odoo field/method/constant conventions, repo prefixes, boolean predicates, before/after |
| Functions & SRP | [`functions.md`](references/functions.md) | Size, extraction, guard clauses, recordset-aware loops, parameter objects |
| Error handling | [`error-handling.md`](references/error-handling.md) | UserError/ValidationError, the sanctioned swallow, concurrency re-raise, sudo discipline |
| Odoo & OWL structure | [`odoo-and-owl.md`](references/odoo-and-owl.md) | SOLID in Odoo, model decomposition, dependency on the ORM, OWL component cleanliness |
| Code smells | [`code-smells.md`](references/code-smells.md) | The repo's recurring smells with diagnosis + prescription |
