# Copilot Instructions for Odoo HRMS Project

## Python Code Standards

### Imports
- Always place imports at the top of the file
- Use this order: standard library, third-party, Odoo, local
- Example:
```pythonimport base64
from datetime import datetimefrom odoo import models, fields, api
from odoo.exceptions import ValidationErrorfrom . import other_module

### Logging
- NEVER use f-strings in logging statements
- Always use lazy formatting with %s placeholders
- ❌ BAD: `_logger.info(f"Processing {record.id}")`
- ✅ GOOD: `_logger.info("Processing %s", record.id)`

### Variable Naming
- Never use ambiguous single-letter variables like `l` (lowercase L)
- Use descriptive names: `line` not `l`, `record` not `r`
- ❌ BAD: `lambda l: l.is_required`
- ✅ GOOD: `lambda line: line.is_required`

### Trailing Commas (COM812)
- **MANDATORY**: Always include a trailing comma for the last item in multi-line data structures (dicts, lists, tuples) and function calls
- This ensures cleaner git diffs (1 line change vs 2) and correct behavior for auto-formatters
- ❌ BAD:
```python
child = self.Category.create({
    "name": "Child",
    "parent_id": parent.id
})
```
- ✅ GOOD:
```python
child = self.Category.create({
    "name": "Child",
    "parent_id": parent.id,
})
```

### Exception Handling
- Never catch blind `Exception` unless absolutely necessary
- Always catch specific exceptions: `ValidationError`, `AccessError`, etc.
- ❌ BAD: `except Exception:`
- ✅ GOOD: `except (ValidationError, AccessError):`

### Return Statements
- Avoid unnecessary variable assignment before return (RET504)
- Return directly when possible
- ❌ BAD:
```python
def get_pdf():
    pdf_content = b"%PDF-1.4..."
    return pdf_content
```
- ✅ GOOD:
```python
def get_pdf():
    return b"%PDF-1.4..."
```
- Exception: Use assignment when it improves readability for complex expressions

### Odoo-Specific Patterns
- Function calls in default arguments are okay: `fields.Date.today`
- Use camelCase for Odoo method names: `_compute_field_name`
- Use snake_case for regular Python functions

### Type Hints (Python 3.10+)
- Use modern type hints: `dict`, `list`, `tuple` (not `Dict`, `List`, `Tuple`)
- ❌ BAD: `def func() -> Dict[str, List[int]]:`
- ✅ GOOD: `def func() -> dict[str, list[int]]:`

### Encoding Declarations
- Do NOT add `# -*- coding: utf-8 -*-` (unnecessary in Python 3)

### Line Length
- Maximum 100 characters per line
- Break long lines appropriately

## Testing Standards

### Test Variables
- Always use test variables meaningfully or don't assign them
- ❌ BAD: `docs = Model.search([])  # never used`
- ✅ GOOD: `docs = Model.search([]); self.assertTrue(docs)`

### Testing Model Field Properties
- When testing model-level field properties (like `translate`, field type, etc.), access the field directly from the model class
- Do NOT create an instance if you're only inspecting field metadata
- ❌ BAD:
```python
def test_field_translatable(self):
    record = self.Model.create({"name": "Test"})  # Unnecessary
    field = self.Model._fields["name"]
    self.assertTrue(field.translate)
```
- ✅ GOOD:
```python
def test_field_translatable(self):
    field = self.Model._fields["name"]
    self.assertTrue(field.translate)
```

### Security Tests
- For access tests, always assert something or use `with self.assertRaises(AccessError):`
- Don't just call methods without verification

## File Organization

### Odoo Module Structuremodule_name/
├── init.py
├── manifest.py
├── models/
│   ├── init.py
│   └── model_name.py
├── views/
│   └── views.xml
├── security/
│   └── ir.model.access.csv
└── tests/
├── init.py
└── test_model.py

## XML Standards (Odoo Views)

### Menu Items
- Keep attributes on same line when concise
- Use 4-space indentation
- Example:
```xml  <menuitem id="menu_id" name="Menu Name" parent="parent_menu" sequence="10"/>
```
Views

Use explicit view inheritance
Always include arch attribute
Use proper xpath expressions

Common Ruff Errors to Avoid

F841: Unused variables - remove or use them
E741: Ambiguous variable names - use descriptive names
UP009: Remove UTF-8 coding declarations
I001: Keep imports sorted and organized
- G004: Use lazy logging formatting (never f-strings in logging)
- BLE001: Don't catch blind exceptions
- SIM105: Use contextlib.suppress() sparingly (our preference: stick with try-except)
- PLC0415: **Imports at top-level only - NEVER inside functions/methods**
- RET504: Avoid unnecessary assignment before return statement
- TRY401: Don't pass redundant exception object to logging.exception()- **COM812: Missing trailing comma - ALWAYS add trailing commas in multi-line structures**
When Writing New Code

Check if similar patterns exist in the codebase
Follow Odoo conventions over generic Python when they conflict
Write tests for new functionality
Use Ruff-compliant patterns from the start

