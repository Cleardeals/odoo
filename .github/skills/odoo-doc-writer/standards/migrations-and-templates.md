# Migration and Test Documentation Standards

---

## Migration documentation

Migrations are read by developers debugging a production problem at the
worst possible moment. Documentation must be precise enough to answer
"what did this script do and how do I verify it ran correctly?" without
running the script again.

### File-level header comment

Every migration file gets this header before the imports:

```python
"""
Migration: {module} {version} — {one-line description}

What this does:
    {2–3 sentences describing the data change}

Why this was needed:
    {The code change that made this migration necessary.
     Reference the model or field that changed.}

When this runs:
    Phase: pre / post
    Trigger: upgrade of {module} from {from_version} to {version}

Idempotency guarantee:
    {Exactly what prevents this from doing harm if run twice.
     e.g. "ON CONFLICT DO NOTHING on the unique (portal_name, portal_listing_id) key"}

Pre-conditions:
    - {What must exist in the DB before this runs}
    - {e.g. "property_portal_listing table created by ORM in a prior version"}

Post-conditions:
    After this runs successfully:
    - {What will be true in the DB}
    - {e.g. "All properties with a non-NULL ninety_nine_acres_id have a
       corresponding row in property_portal_listing with portal_name='99acres'"}

Verification:
    Run immediately after upgrade to confirm success:

        SELECT portal_name, COUNT(*)
        FROM property_portal_listing
        GROUP BY portal_name
        ORDER BY portal_name;

        -- Expected: rows for each of the four portals
        -- 99acres: {N} rows
        -- Housing.com: {N} rows
        -- MagicBricks: {N} rows
        -- OLX: {N} rows

Related:
    - Jira: CDLS-{ticket}
    - Companion migration: {post/pre}-{descriptor}.py in same version
"""
```

### The `migrate()` function docstring

In addition to the file-level header, every `migrate()` function gets a
short docstring that reads like a commit message — a single sentence summary
followed by any runtime-specific notes:

```python
def migrate(cr, version):
    """Seed property_portal_listing from legacy flat portal ID columns.

    Reads ninety_nine_acres_id, housing_id, magicbricks_id, olx_id
    from property_base and inserts one property_portal_listing row per
    non-NULL value. Label format: {prop_id} | {portal_name} | {listing_id}.

    See module docstring for full context, idempotency guarantee, and
    verification queries.
    """
```

### Inline comments in migrations

Migration scripts have a higher bar for inline comments than application
code. Every non-trivial SQL operation must have a comment:

```python
# WHITELIST GUARD — column names cannot be parameterised in psycopg2.
# Validate source_col against this set before using it in an f-string.
# If source_col is not whitelisted, the migration aborts with ValueError.
if source_col not in _PORTAL_COLUMN_WHITELIST:
    raise ValueError(...)

# Count source rows BEFORE inserting so the log shows both what was
# available and what was actually inserted. Discrepancies indicate
# pre-existing duplicates that were skipped by ON CONFLICT.
cr.execute(f"SELECT COUNT(*) FROM property_base WHERE {source_col} IS NOT NULL ...")

# ON CONFLICT DO NOTHING — idempotency guarantee.
# The unique constraint on (portal_name, portal_listing_id) ensures
# that re-running this script on a DB where it already ran produces
# zero new rows without errors.
cr.execute(f"INSERT INTO property_portal_listing ... ON CONFLICT ... DO NOTHING")

# create_uid=1, write_uid=1 — system user (OdooBot).
# Required because property_portal_listing.create_uid is NOT NULL.
# Omitting these fields causes a NULL constraint violation on some
# Odoo versions.
```

---

## Test documentation

Tests are read by developers writing new tests and by developers trying
to understand what a feature is supposed to do. Well-documented tests
serve as living specifications.

### File-level docstring

Every test file must start with a module docstring:

```python
"""
Tests for portal lead property resolution (leads module).

What this covers:
    - Property resolution via property.portal.listing.resolve_property()
    - One test per portal: MagicBricks, Housing.com, 99acres, OLX
    - Resolution of inactive listings (fallback behaviour)
    - Resolution failure (unknown portal, unknown listing ID)

What this does NOT cover:
    - Lead state transitions (_process_lead_logic is tested separately)
    - Duplicate detection (tested in test_lead_dedup.py)
    - Manual lead creation (tested in test_manual_lead_creation.py)

Fixtures:
    Inherits from TestPortalCommon (test_portal_common.py) which creates:
    - self.property: one property.base record
    - self.mb_id, self.hsg_id, self.acres_id, self.olx_id: listing ID strings
    - Four property.portal.listing records, one per portal

Setup:
    No external dependencies. All records created in setUpClass.
    Safe to run in isolation or as part of the full test suite.
"""
```

### Test class docstring

```python
class TestPortalLeadProcessing(TestPortalCommon):
    """Verify that resolve_property() correctly maps portal IDs to properties.

    Each test method corresponds to one portal. The pattern is identical
    across all portals — resolve a known listing ID and assert the correct
    property is returned. This structure makes it easy to add a new portal
    by copying any existing test method and updating the portal/ID values.
    """
```

### Test method docstring

The test method name alone is not enough. Every test method needs a
one-line docstring that reads like a requirement:

```python
def test_01_resolve_property_by_magicbricks_listing(self):
    """A MagicBricks listing ID resolves to the correct property."""
    resolved = self.env["property.portal.listing"].resolve_property(
        portal="MagicBricks",
        portal_listing_id=self.mb_id,
    )
    self.assertEqual(resolved, self.property)
```

```python
def test_05_resolve_inactive_listing_falls_back_to_property(self):
    """An inactive listing ID still resolves to the property, not an empty set.

    When a listing is deactivated (e.g. listing expired on the portal),
    leads that arrive referencing the old ID should still be routed to
    the correct property. This prevents orphaned leads.
    """
    self.listing_mb.write({"active": False})
    resolved = self.env["property.portal.listing"].resolve_property(
        portal="MagicBricks",
        portal_listing_id=self.mb_id,
    )
    self.assertEqual(resolved, self.property)
```

```python
def test_06_resolve_unknown_listing_returns_empty_recordset(self):
    """An unknown listing ID returns an empty property.base recordset, not False.

    Callers must check truthiness (if not prop:) not identity (if prop is False:).
    This test enforces the documented return type contract of resolve_property().
    """
    resolved = self.env["property.portal.listing"].resolve_property(
        portal="MagicBricks",
        portal_listing_id="NONEXISTENT",
    )
    self.assertFalse(resolved)
    self.assertEqual(resolved._name, "property.base")  # correct type, empty
```

### Test fixture documentation

The shared fixture class is the most important thing to document in the
test layer. New developers look here first:

```python
class TestPortalCommon(TransactionCase):
    """Shared fixtures for all portal lead processing tests.

    Creates one property and four portal listings (one per portal) in
    setUpClass so the DB setup runs once per test class, not per test.

    Class attributes available to all inheriting test classes:

        self.property (property.base):
            A single test property with prop_id "TEST-001".
            All four portal listing IDs are linked to this property.

        self.mb_id (str): MagicBricks listing ID, e.g. "MB_abc123"
        self.hsg_id (str): Housing.com listing ID, e.g. "HSG_abc123"
        self.acres_id (str): 99acres listing ID, e.g. "99A_abc123"
        self.olx_id (str): OLX listing ID, e.g. "OLX_abc123"

        self.listing_mb (property.portal.listing): MagicBricks listing record
        self.listing_hsg (property.portal.listing): Housing.com listing record
        self.listing_acres (property.portal.listing): 99acres listing record
        self.listing_olx (property.portal.listing): OLX listing record

    The suffix `self.suffix` is a unique string per test run to prevent
    ID collisions when tests run in parallel or against a non-empty DB.

    Usage:
        class TestSomething(TestPortalCommon):
            def test_something(self):
                # self.property, self.mb_id etc. are available here
                pass
    """
```

### Assert message convention

Every assertion must have a message that explains what went wrong
and what was expected:

```python
# BAD — fails with: AssertionError: False is not true
self.assertTrue(resolved)

# GOOD — fails with: "resolve_property('MagicBricks', 'MB_abc123')
#         returned empty. Expected property CD-TEST-001."
self.assertTrue(
    resolved,
    f"resolve_property('MagicBricks', '{self.mb_id}') returned empty. "
    f"Expected property {self.property.prop_id}."
)

# BAD
self.assertEqual(lead.state, "assigned")

# GOOD
self.assertEqual(
    lead.state,
    "assigned",
    f"Manual lead {lead.id} should start as 'assigned', got '{lead.state}'. "
    "Check default_get() override in NewPortalLead."
)
```