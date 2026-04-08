---
name: odoo-doc-writer
description: >
  Writes, audits, and updates all forms of documentation for the Cleardeals Odoo
  codebase following FAANG-grade documentation standards. Use this skill whenever
  the user wants to document code, APIs, migrations, tests, or modules — whether
  writing fresh documentation for new code, retrofitting documentation onto existing
  undocumented code, updating documentation after a change, or generating module-level
  READMEs and changelogs. Trigger on: "document this", "add docstrings", "write the
  docs for", "document this API", "this needs documentation", "write a README for",
  "update the docs", "generate a changelog", "add comments to this", "document this
  migration", "write an ADR for", or any request to explain, describe, or record
  what code does or why a decision was made. Also trigger when the user shares
  undocumented code and asks what it does — documenting it is the correct response.
  Always use this skill for any documentation task — it contains the standards,
  templates, and Cleardeals-specific conventions needed to produce documentation
  that is consistent, complete, and genuinely useful.
---

# Odoo Documentation Writer

You write documentation that engineers actually read. The standard is Google,
Stripe, and Shopify engineering — not academic thoroughness, but precise
usefulness. Every piece of documentation you write must answer one question
for its reader: *what do I need to know to work confidently with this?*

Documentation that does not serve a reader is noise. You never document for
the sake of coverage metrics. You document to transfer understanding.

---

## Step 1 — Identify what is being documented and who reads it

Before writing a word, establish:

| What | Primary reader | Documentation type |
|---|---|---|
| A model or method | Future developer (including future you) | Inline docstring |
| A module | New developer onboarding | Module README |
| A REST API endpoint | External integrator | API reference |
| A migration script | Developer debugging a production issue | Migration docstring + inline comments |
| A test file | Developer writing new tests | Test file header + test method docstrings |
| A security rule or architectural decision | Tech lead / future architect | ADR (Architecture Decision Record) |
| A change to existing code | Any developer reading git blame | Inline comment on the change |
| A version release | Whole team | CHANGELOG entry |

Read the relevant standard before writing:
- Inline code (docstrings, comments) → `references/standards/inline.md`
- Module README → `references/templates/readme.md`
- API documentation → `references/standards/api.md`
- Migration documentation → `references/standards/migrations.md`
- Test documentation → `references/standards/tests.md`
- ADR → `references/templates/adr.md`
- CHANGELOG → `references/templates/changelog.md`

---

## Step 2 — The documentation hierarchy

Every codebase has five layers of documentation. Understand which layer
you are writing for and apply the right standard.

```
Layer 1 — WHY (Architecture Decision Records)
  Lives in: docs/decisions/
  Written when: a non-obvious architectural choice is made
  Reader: future tech lead asking "why did they do it this way?"
  Frequency: once per major decision, never updated (append ADR-NNN instead)

Layer 2 — WHAT (Module READMEs)
  Lives in: each module's root directory as README.md
  Written when: a module is created or substantially changed
  Reader: developer new to the module
  Frequency: updated when module purpose, dependencies, or setup changes

Layer 3 — HOW (Docstrings on classes and public methods)
  Lives in: the source file itself
  Written when: the method is written
  Reader: developer calling or modifying the method
  Frequency: updated whenever the method's contract changes

Layer 4 — WHY HERE (Inline comments on non-obvious logic)
  Lives in: the source file, on the specific line
  Written when: the logic is not self-evident from reading it
  Reader: developer reading this specific line 6 months from now
  Frequency: updated when the logic changes

Layer 5 — WHAT CHANGED (CHANGELOG)
  Lives in: module root as CHANGELOG.md
  Written when: a version is deployed
  Reader: anyone asking "what changed in version X"
  Frequency: every deployment
```

The most common mistake is writing Layer 4 comments (explaining what
the code does) instead of Layer 4 comments (explaining why it does it
this way). Code already shows what it does. Comments exist for the why.

---

## Step 3 — The rules that apply to everything

These apply regardless of which layer you are writing.

**Rule 1: Write for the reader who is lost at 11pm**
The person reading your documentation is usually debugging something
that broke in production. They are stressed and in a hurry. Every piece
of documentation should answer the questions a stressed developer would
ask. Not the questions a calm developer would ask when everything is fine.

**Rule 2: The first sentence is the whole story**
Every docstring, README, and ADR must have a first sentence that stands
alone as a complete summary. Someone scanning with Ctrl+F should be able
to read only the first sentence and know whether this is what they are
looking for.

**Rule 3: Document the contract, not the implementation**
A docstring explains what a function promises to do, what it requires
to be true before calling it (preconditions), and what will be true
after it runs (postconditions). It does not describe the implementation.
If someone needs to read the implementation to understand the docstring,
the docstring failed.

**Rule 4: Document the surprising things**
Obvious code needs no comment. The lines that need documentation are
the ones where a competent developer would stop and ask "why?". If you
read a line and think "I know exactly why this is here", skip it.
If you read a line and think "that's odd", document it.

**Rule 5: Examples are worth 10 paragraphs**
For any API, method, or module that accepts inputs, provide at least
one example of a real call with real values. Not `method(param1, param2)`
but `resolve_property("MagicBricks", "MB9871234")`.

**Rule 6: Document failure modes as prominently as success modes**
The happy path is obvious from the code. What every reader needs to know
is: what can go wrong, what does the code do when it does, and how do
you recover? This applies to docstrings, API docs, and migration docs.

**Rule 7: Version and date every document that can go stale**
READMEs, ADRs, and API docs should have a "Last updated" date and the
version they describe. A document with no date is a document you cannot
trust.

---

## Step 4 — Cleardeals-specific documentation conventions

These are the conventions specific to this codebase. Apply them in
addition to the general standards.

**Module ownership header**
Every Python file in `custom_addons/` must have this at the top,
after the imports:

```python
# ---------------------------------------------------------------------------
# Module : {module_name}
# Model  : {model._name or 'N/A for utilities'}
# Purpose: {one sentence — what this file does in the system}
# Owner  : Cleardeals Tech
# ---------------------------------------------------------------------------
```

**Method category grouping**
Methods in a model class must be grouped in this order, with a comment
separator between each group:

```python
class MyModel(models.Model):
    _name = "my.model"

    # --- Fields -----------------------------------------------------------

    name = fields.Char(...)

    # --- Computed fields --------------------------------------------------

    @api.depends(...)
    def _compute_something(self): ...

    # --- Constraints ------------------------------------------------------

    @api.constrains(...)
    def _check_something(self): ...

    # --- ORM overrides ----------------------------------------------------

    def create(self, vals_list): ...
    def write(self, vals): ...

    # --- Business logic ---------------------------------------------------

    def _process_lead_logic(self): ...

    # --- Cron jobs --------------------------------------------------------

    @api.model
    def _cron_something(self): ...

    # --- Helper methods ---------------------------------------------------

    def _find_property(self): ...
```

**Portal and source field documentation**
Any method that reads `self.source` (formerly `portal_name`) must document
the possible values and the manual vs portal distinction:

```python
"""
Parameters:
    source (str or False): Origin of this lead.
        Portal values: "MagicBricks", "99acres", "Housing.com", "OLX"
        Manual value: False or empty string (lead created by RM directly)
        Use bool(self.source) to distinguish portal from manual leads.
"""
```

**Migration docstring format**
Every `migrate(cr, version)` function must follow this exact docstring
structure (from the migration writer skill — repeated here for completeness):

```python
def migrate(cr, version):
    """
    [One sentence: what this script does.]

    Context:
        [Why this migration exists — what changed in the code that
        requires this DB change.]

    Idempotency:
        [Exactly what makes this safe to re-run.]

    Assumptions:
        [What must be true for this to run correctly.]

    Verification:
        Run after upgrade:
            SELECT portal_name, COUNT(*) FROM property_portal_listing
            GROUP BY portal_name;
    """
```

**Security rule documentation**
Every `ir.rule` XML record must have a comment above it explaining
the access intent in plain English:

```xml
<!-- RMs can read their own properties normally.
     When search_all_properties_for_lead context key is True (set on the
     property_base_id Many2one field in leads.new and lead.property.interest),
     all active properties are visible for the purpose of selecting a property
     on a lead form. Write/create/unlink are never affected by this context. -->
<record id="property_base_rule_rm" model="ir.rule">
```

---

## Output format rules

**For inline documentation (docstrings + comments):**
Return the complete file with documentation added. Never return just
the docstrings in isolation — show them in context. Use diff-style
output only when the change is a small addition to a large file.

**For READMEs and ADRs:**
Return the complete markdown file, ready to be saved. Include the
file path as the first line: `# custom_addons/properties/README.md`

**For API documentation:**
Return structured markdown with one section per endpoint.
Include: method, path, authentication, request body, response shape,
error codes, and a complete curl example.

**For CHANGELOG entries:**
Return the entry in the exact format defined in the CHANGELOG template.
Do not return the whole CHANGELOG — only the new entry to prepend.

**For test documentation:**
Return the complete test file with documentation added. Include a
file-level docstring explaining what the test suite covers and what
fixtures it depends on.