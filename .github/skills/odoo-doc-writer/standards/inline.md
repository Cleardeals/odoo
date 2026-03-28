# Inline Documentation Standards

## The Google Python docstring format (used by Google, Stripe, Shopify)

This is the standard for all Python code in this codebase. It is the
most readable format for IDEs, grep, and human eyes simultaneously.

### Class docstring

```python
class PropertyPortalListing(models.Model):
    """Represents a single portal listing ID for a property.

    A property can have multiple listings per portal — for example,
    the same property listed at two different price points on OLX,
    or re-listed after expiry with a new ID. Each listing maps back
    to exactly one property.base record. The unique constraint on
    (portal_name, portal_listing_id) ensures a listing ID is never
    shared between two properties.

    Attributes:
        property_base_id: The canonical property this listing belongs to.
        portal_name: The portal this listing lives on. One of:
            "99acres", "Housing.com", "MagicBricks", "OLX".
        portal_listing_id: The ID string assigned by the portal.
        listing_label: Human-readable label for this listing, in the
            format "{prop_id} | {portal_name} | {portal_listing_id}".
            Example: "CD-4521 | MagicBricks | MB9871234"
        active: False when the listing is expired or removed from the
            portal. Leads referencing this ID still resolve correctly.

    Example:
        # Create a new listing for a property
        listing = env["property.portal.listing"].create({
            "property_base_id": prop.id,
            "portal_name": "MagicBricks",
            "portal_listing_id": "MB9871234",
            "listing_label": "CD-4521 | MagicBricks | MB9871234",
            "active": True,
        })
    """
```

### Method docstring — full format (for public methods)

```python
def resolve_property(self, portal, portal_listing_id):
    """Find the property associated with a portal listing ID.

    Used by the lead webhook handler and the Housing.com cron to map
    an incoming portal lead to its canonical property.base record.
    Prefers active listings; falls back to inactive so leads arriving
    on recently-expired listings still resolve correctly.

    Args:
        portal (str): The portal name. Must be one of:
            "99acres", "Housing.com", "MagicBricks", "OLX".
            Case-sensitive — matches the portal_name column exactly.
        portal_listing_id (str): The listing ID as received from the
            portal webhook or API response. Leading/trailing whitespace
            is not stripped — callers must normalise before passing.

    Returns:
        property.base: The matched property record, or an empty
            property.base recordset if no match is found.
            Never returns False or None.

    Raises:
        Nothing. Resolution failure returns an empty recordset, not
        an exception. Callers must check if the result is falsy.

    Example:
        prop = env["property.portal.listing"].resolve_property(
            portal="MagicBricks",
            portal_listing_id="MB9871234",
        )
        if not prop:
            # No match — route to default RM
            ...

    Note:
        The unique constraint on (portal_name, portal_listing_id)
        guarantees at most one match. The order="is_active desc" in
        the search is defensive only — in practice there is always
        exactly 0 or 1 result.
    """
```

### Method docstring — short format (for simple private helpers)

Short format is appropriate when the method is short, private (prefixed
with `_`), and its purpose is immediately clear from its name.

```python
def _table_exists(cr, table_name):
    """Return True if table_name exists in the public schema."""
```

```python
def _standardize_phone(self, phone_number):
    """Strip non-numeric characters and return a 10-digit phone number.

    Returns the numeric string as-is if it does not match expected
    formats (10 digits, or 12 digits starting with 91).
    Returns empty string if phone_number is falsy.
    """
```

### When to use full vs short format

Use full format when ANY of these are true:
- The method is called from outside the class
- The method has parameters that are not self-evident
- The method can fail or return empty/falsy
- The method has non-obvious behaviour (fallbacks, side effects)
- The method is part of a migration or cron (always full format)

Use short format when ALL of these are true:
- The method is private (`_` prefix)
- It has 0-1 parameters beyond self/cr
- Its name fully describes what it does
- It cannot fail

---

## Inline comment standards

### The golden rule

Comments explain WHY. Code explains WHAT.

```python
# BAD — restates the code in English
# Search for the property by portal name and listing ID
listing = self.search([
    ("portal_name", "=", portal),
    ("portal_listing_id", "=", portal_listing_id),
], order="is_active desc", limit=1)

# GOOD — explains the non-obvious decision
# order="is_active desc" prefers active listings but the limit=1 means
# we get the single best match. The unique constraint guarantees at most
# one row per (portal, listing_id) anyway — this ordering is defensive.
listing = self.search([
    ("portal_name", "=", portal),
    ("portal_listing_id", "=", portal_listing_id),
], order="is_active desc", limit=1)
```

### When to write an inline comment

Write a comment when a reasonable developer would stop and ask "why?":

```python
# Suppress automatic chatter log on creation. Context must be set on
# `self` before super() — calling super().with_context().create()
# returns the same overridden method and causes infinite recursion.
new_leads = super(
    NewPortalLead,
    self.with_context(mail_create_nolog=True),
).create(vals_list)
```

```python
# ON CONFLICT DO NOTHING makes this idempotent — safe to re-run if
# the upgrade fails halfway and is restarted. The unique constraint on
# (portal_name, portal_listing_id) is the dedup key.
cr.execute("""
    INSERT INTO property_portal_listing ...
    ON CONFLICT (portal_name, portal_listing_id) DO NOTHING
""")
```

```python
# sudo() is safe here: this is a read-only lookup to find the RM
# for a property, not an operation that grants write access.
rm_user = property_rec.sudo().rm_user_id
```

### When NOT to write an inline comment

Do not comment obvious code. These comments are noise:

```python
# BAD
# Check if the property exists
if property_rec:

# BAD
# Loop through each portal
for portal_name, source_col in _PORTAL_COLUMN_MAP:

# BAD
# Return the result
return listing.property_id if listing else self.env["property.base"]
```

### Section separator comments in model files

Use these to group methods visually. They are the only comments that
describe what (rather than why) because they are structural, not logical:

```python
# --- Fields ---------------------------------------------------------------
# --- Computed fields ------------------------------------------------------
# --- Constraints ----------------------------------------------------------
# --- ORM overrides --------------------------------------------------------
# --- Business logic -------------------------------------------------------
# --- Cron jobs ------------------------------------------------------------
# --- Helper methods -------------------------------------------------------
```

### TODO and FIXME conventions

```python
# TODO(CDLS-XXX): Remove this once portal_name column is dropped in 19.0.1.4.0
# FIXME: This falls back to admin if the default RM is not found — needs
#        a proper error state instead of silently assigning to admin
# NOTE: This behaviour is intentionally permissive — see ADR-003
```

Always attach a ticket number to TODO and FIXME. A TODO without a ticket
is a TODO that will never be done.

---

## Field documentation in Odoo models

Every non-obvious field must have a `help=` string. Help strings appear
as tooltips in the Odoo UI and serve as inline field-level documentation.

```python
# BAD — no help, meaning unclear from name alone
portal_listing_id = fields.Char(string="Listing ID", index=True)

# GOOD
portal_listing_id = fields.Char(
    string="Listing ID",
    index=True,
    help=(
        "The unique ID assigned by the portal for this listing. "
        "For MagicBricks this is an integer string (e.g. '9871234'). "
        "For OLX this is an alphanumeric string. "
        "Do not include the portal domain — just the ID."
    ),
)
```

```python
# Good use of help= to document non-obvious behaviour
is_active = fields.Boolean(
    string="Active",
    default=True,
    index=True,
    help=(
        "Uncheck when this listing is expired or removed from the portal. "
        "Inactive listings are hidden from the Portal Listings tab by default "
        "but can be found by removing the 'Active' filter. "
        "Leads arriving on an inactive listing ID still resolve to this "
        "property — the resolution uses an inactive fallback."
    ),
)
```

Fields that are always self-evident (name, active on simple models,
create_date) do not need help strings. The bar is: would a manager
reading the Odoo form understand this field without the tooltip?

---

## XML view documentation

Comments in XML views explain why a choice was made, not what element
is present. The XML already shows what is present.

```xml
<!-- BAD — describes what is already visible in the XML -->
<!-- Portal Listings tab showing all portal IDs for this property -->
<page string="Portal Listings" groups="properties.group_property_manager">

<!-- GOOD — explains why this exists and what replaces what -->
<!-- Replaces the old "Portal IDs" tab (flat ninety_nine_acres_id etc. fields).
     Those fields are kept in the DB for now (see CDLS-112 for planned removal)
     but are no longer editable here. Managers use this tab to add/edit all
     portal listings in one place, grouped by portal. -->
<page string="Portal Listings" groups="properties.group_property_manager">
```

```xml
<!-- force_save="1" is required here: portal_name is set by the parent
     One2many's default_portal_name context, must be readonly so managers
     cannot change it accidentally, but must still be persisted on save. -->
<field name="portal_name" column_invisible="1" force_save="1"/>
```