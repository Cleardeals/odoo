# Refactoring Patterns

Before/after code for every common refactoring in the Cleardeals codebase.
Every pattern shows: the smell, the before, the after, and what to verify.

---

## Pattern 1 — Extract portal name constants

**Smell:** Portal names appear as raw string literals throughout the codebase.
**Risk of before:** A typo produces silent misrouting. Changing a portal name
requires finding every occurrence.

```python
# BEFORE — in new_portal_leads.py, property_sync.py, property_inventory.py,
# lead_csv_import_wizard.py, and migration scripts
if self.source == "MagicBricks":
    target_name = "Mayuri Malivad"
elif self.source == "99acres":
    target_name = "Pratham Bhandari"

portal_field_map = {
    "MagicBricks": "magicbricks_id",
    "99acres": "ninety_nine_acres_id",
    "Housing.com": "housing_id",
    "OLX": "olx_id",
}
```

```python
# AFTER — in custom_addons/leads/constants.py (new file)
# ---------------------------------------------------------------------------
# Module : leads
# Purpose: Shared constants for portal names and lead states.
#          Import from here instead of spelling string literals inline.
# ---------------------------------------------------------------------------

# Portal name values — must match portal_listing.portal_name Selection field
PORTAL_MAGICBRICKS = "MagicBricks"
PORTAL_99ACRES = "99acres"
PORTAL_HOUSING = "Housing.com"
PORTAL_OLX = "OLX"

ALL_PORTALS = (PORTAL_MAGICBRICKS, PORTAL_99ACRES, PORTAL_HOUSING, PORTAL_OLX)

# Lead state values
STATE_NEW = "new"
STATE_ASSIGNED = "assigned"
STATE_FAILED = "failed"
```

```python
# AFTER — in new_portal_leads.py
from .constants import (
    PORTAL_MAGICBRICKS, PORTAL_99ACRES, PORTAL_HOUSING, PORTAL_OLX,
    STATE_NEW, STATE_ASSIGNED, STATE_FAILED,
)

if self.source == PORTAL_MAGICBRICKS:
    target_name = self._get_default_rm_name(PORTAL_MAGICBRICKS)
elif self.source == PORTAL_99ACRES:
    target_name = self._get_default_rm_name(PORTAL_99ACRES)
```

**Verify:** `grep -rn '"MagicBricks"\|"99acres"\|"Housing.com"\|"OLX"' custom_addons --include="*.py"`
should return zero hits after this refactoring (except for the constants file
itself and Selection field definitions).

---

## Pattern 2 — Replace hardcoded RM names with config parameters

**Smell:** RM names are hardcoded in business logic. Changing an RM
assignment requires a code deployment.

```python
# BEFORE — new_portal_leads.py _process_lead_logic()
if self.portal_name == "99acres":
    target_name = "Pratham Bhandari"
elif self.portal_name == "MagicBricks":
    target_name = "Mayuri Malivad"
else:
    target_name = "Naresh Rojiya"
rm_user = self.env["res.users"].search(
    [("name", "ilike", target_name)], limit=1
)
```

```python
# AFTER — extracted helper using ir.config_parameter
def _get_default_rm_for_portal(self):
    """
    Return the default RM for this lead's portal.

    The mapping is configurable via ir.config_parameter so that changing
    a default RM does not require a code deployment. Configure via:
        Settings → Technical → Parameters → System Parameters
        Key: leads.default_rm.{portal_key}
        Value: exact user name (case-sensitive)

    Falls back to admin if the configured user is not found.
    """
    portal_param_map = {
        PORTAL_99ACRES:     "leads.default_rm.99acres",
        PORTAL_MAGICBRICKS: "leads.default_rm.magicbricks",
        PORTAL_HOUSING:     "leads.default_rm.housing",
        PORTAL_OLX:         "leads.default_rm.olx",
    }

    config = self.env["ir.config_parameter"].sudo()
    param_key = portal_param_map.get(self.source)
    if not param_key:
        _logger.warning(
            "Lead %d: no default RM config key for portal '%s'",
            self.id, self.source,
        )
        return self.env.ref("base.user_admin")

    target_name = config.get_param(param_key)
    if not target_name:
        _logger.error(
            "Lead %d: system parameter '%s' not configured. "
            "Set it in Settings → Technical → Parameters.",
            self.id, param_key,
        )
        return self.env.ref("base.user_admin")

    rm = self.env["res.users"].search([("name", "=", target_name)], limit=1)
    if not rm:
        _logger.error(
            "Lead %d: user '%s' (from parameter '%s') not found in system.",
            self.id, target_name, param_key,
        )
        return self.env.ref("base.user_admin")

    return rm
```

**Seed the parameters in data XML:**
```xml
<!-- data/lead_config_data.xml -->
<odoo>
    <data noupdate="1">
        <!-- Default RMs for portal lead fallback assignment.
             Change these via Settings > Technical > Parameters > System Parameters
             without requiring a code deployment. -->
        <record id="param_default_rm_99acres" model="ir.config_parameter">
            <field name="key">leads.default_rm.99acres</field>
            <field name="value">Pratham Bhandari</field>
        </record>
        <record id="param_default_rm_magicbricks" model="ir.config_parameter">
            <field name="key">leads.default_rm.magicbricks</field>
            <field name="value">Mayuri Malivad</field>
        </record>
        <record id="param_default_rm_housing" model="ir.config_parameter">
            <field name="key">leads.default_rm.housing</field>
            <field name="value">Naresh Rojiya</field>
        </record>
        <record id="param_default_rm_olx" model="ir.config_parameter">
            <field name="key">leads.default_rm.olx</field>
            <field name="value">Naresh Rojiya</field>
        </record>
    </data>
</odoo>
```

---

## Pattern 3 — Extract duplicated BQ sync logic

**Smell:** `property_sync.py` and `property_inventory.py` share identical
portal listing upsert logic. Every change must be made in both files.

```python
# BEFORE — property_sync.py ~line 767 AND property_inventory.py ~line 321
# (nearly identical blocks in two files)
if row.ninety_nine_acres_id:
    vals["ninety_nine_acres_id"] = str(row.ninety_nine_acres_id)
if row.housing_id and row.housing_id not in ("None", "nan"):
    vals["housing_id"] = row.housing_id
if row.magicbricks_id and row.magicbricks_id not in ("None", "nan"):
    vals["magicbricks_id"] = row.magicbricks_id
if row.olx_id and row.olx_id not in ("None", "nan"):
    vals["olx_id"] = row.olx_id
```

```python
# AFTER — custom_addons/properties/utils/bq_sync.py (new file)
"""
Shared utilities for BigQuery → Odoo sync operations.

Used by both property_sync.py and property_inventory.py. Any change to
the BQ sync logic should be made here and will automatically apply to both.
"""
import logging
from odoo import fields

_logger = logging.getLogger(__name__)

_INVALID_BQ_VALUES = frozenset({"None", "nan", ""})

_PORTAL_ROW_ATTRS = (
    ("99acres",     "ninety_nine_acres_id"),
    ("Housing.com", "housing_id"),
    ("MagicBricks", "magicbricks_id"),
    ("OLX",         "olx_id"),
)


def _clean_bq_value(raw_value):
    """Return the cleaned string value, or None if it is empty or invalid."""
    if not raw_value:
        return None
    cleaned = str(raw_value).strip()
    return cleaned if cleaned not in _INVALID_BQ_VALUES else None


def build_portal_listing_commands(env, property_id, bq_row):
    """
    Build ORM Command list for portal_listing_ids from a BigQuery result row.

    Checks each portal's column on the BQ row, creates a new
    property.portal.listing record for any listing ID not already present.
    Skips if the listing ID already exists (even on a different property —
    logs a warning instead of overwriting).

    Args:
        env: Odoo environment (sudo not required — caller handles access)
        property_id (int): ID of the property.base record being synced
        bq_row: BigQuery result row with portal ID attributes

    Returns:
        list[Command]: ORM Command.create entries for portal_listing_ids,
                       or [] if all listings already exist.
    """
    Listing = env["property.portal.listing"]
    commands = []

    for portal_name, row_attr in _PORTAL_ROW_ATTRS:
        listing_id = _clean_bq_value(getattr(bq_row, row_attr, None))
        if not listing_id:
            continue

        existing = Listing.search([
            ("portal_name", "=", portal_name),
            ("portal_listing_id", "=", listing_id),
        ], limit=1)

        if not existing:
            commands.append(fields.Command.create({
                "portal_name": portal_name,
                "portal_listing_id": listing_id,
                "active": True,
            }))
        elif existing.property_base_id.id != property_id:
            _logger.warning(
                "BQ sync conflict: %s listing '%s' is registered to property %d, "
                "not %d. Skipping.",
                portal_name, listing_id, existing.property_base_id.id, property_id,
            )

    return commands
```

```python
# AFTER — property_sync.py (import and use the shared utility)
from ..utils.bq_sync import build_portal_listing_commands

# In the row processing loop:
portal_commands = build_portal_listing_commands(self.env, property_record.id, row)
if portal_commands:
    vals["portal_listing_ids"] = portal_commands

# AFTER — property_inventory.py (same import, same call)
from odoo.addons.properties.utils.bq_sync import build_portal_listing_commands
```

---

## Pattern 4 — Simplify write() with extracted helpers

**Smell:** `write()` override is doing multiple distinct jobs in one method
with nested logic that is hard to follow.

```python
# BEFORE
def write(self, vals):
    leads_to_stamp = self.env["leads.new"]
    first_contact_time = False
    if "current_status" in vals and vals["current_status"] != "lead":
        leads_to_stamp = self.filtered(lambda r: not r.first_contact_datetime)
        if leads_to_stamp:
            first_contact_time = fields.Datetime.now()

    res = super().write(vals)

    if leads_to_stamp and first_contact_time:
        leads_to_stamp.write({"first_contact_datetime": first_contact_time})

    channel = "leads.new"
    notification_type = "bus_notification"
    message = {"ids": self.ids, "model": "leads.new", "event": "write"}
    self.env["bus.bus"]._sendone(channel, notification_type, message)

    return res
```

```python
# AFTER — each concern has a name
def write(self, vals):
    """
    Override write to:
    1. Stamp first_contact_datetime on the first meaningful status change.
    2. Send real-time bus notification for live list updates.
    """
    # Capture before super() — we need the old value of first_contact_datetime
    leads_needing_stamp = self._get_leads_to_stamp(vals)

    res = super().write(vals)

    # Stamp after super() so the main write commits before the stamp write
    if leads_needing_stamp:
        leads_needing_stamp._stamp_first_contact()

    self._notify_bus_write()
    return res

def _get_leads_to_stamp(self, vals):
    """
    Return leads that should have first_contact_datetime stamped.

    A lead is stamped when:
      - current_status is being changed AND
      - the new status is not 'lead' (the default/initial status) AND
      - the lead has not been stamped before (first_contact_datetime is False)

    Returns empty recordset if stamping conditions are not met.
    """
    if "current_status" not in vals:
        return self.env["leads.new"]
    if vals["current_status"] == "lead":
        return self.env["leads.new"]
    return self.filtered(lambda r: not r.first_contact_datetime)

def _stamp_first_contact(self):
    """Set first_contact_datetime to now on these leads."""
    self.write({"first_contact_datetime": fields.Datetime.now()})
    # NOTE: This recursive write() call is safe because first_contact_datetime
    # is not in _get_leads_to_stamp's condition — it will never trigger
    # another stamp cycle.

def _notify_bus_write(self):
    """Send bus notification so live list views refresh."""
    self.env["bus.bus"]._sendone(
        "leads.new",
        "bus_notification",
        {"ids": self.ids, "model": "leads.new", "event": "write"},
    )
```

**Verify:** The stamp still fires exactly once. Write a test:
```python
def test_first_contact_stamped_exactly_once(self):
    lead = self.env["leads.new"].create({...})
    lead.write({"current_status": "busy"})     # first change — stamp
    first_stamp = lead.first_contact_datetime
    lead.write({"current_status": "ringing"})  # second change — no re-stamp
    self.assertEqual(lead.first_contact_datetime, first_stamp)
```

---

## Pattern 5 — Replace inline Selection values with Selection class

**Smell:** Selection values for `current_status` are long strings defined
once but referenced everywhere as literals.

```python
# BEFORE — long strings scattered through the code
if self.current_status == "site_visit_done":
    ...
if self.current_status in ("busy", "ringing", "switched_off"):
    ...
```

```python
# AFTER — in constants.py
class LeadStatus:
    """
    Constants for leads.new.current_status Selection values.

    Use these instead of raw string literals to prevent typos and to
    enable IDE autocompletion and refactoring support.

    Example:
        from .constants import LeadStatus
        if self.current_status == LeadStatus.SITE_VISIT_DONE:
            ...
    """
    LEAD = "lead"
    BUSY = "busy"
    RINGING = "ringing"
    CALL_BACK_LATER = "call_back_later"
    SITE_VISIT_SCHEDULED = "site_visit_scheduled"
    OPTION_NOT_MATCHING = "option_not_matching_requirements"
    DETAILS_SHARED = "details_shared_of_property"
    NO_REQUIREMENTS = "no_requirements"
    DETAIL_SHARED_INTERESTED = "detail_shared_and_interested_for_site_visit"
    SWITCHED_OFF = "switched_off"
    REQUIREMENT_CLOSED = "requirement_closed"
    PROPERTY_SOLD_OUT = "property_sold_out"
    RESCHEDULED = "rescheduled"
    BUDGET_NOT_SUFFICIENT = "budget_not_sufficient"
    SITE_VISIT_DONE = "site_visit_done"
    WRONG_NUMBER = "number_not_in_use_wrong_number"
    OTHER = "other"

    # Groupings for common domain queries
    ACTIVE_STATUSES = frozenset({LEAD, RINGING, CALL_BACK_LATER,
                                  SITE_VISIT_SCHEDULED, DETAILS_SHARED,
                                  DETAIL_SHARED_INTERESTED})
    CLOSED_STATUSES = frozenset({REQUIREMENT_CLOSED, PROPERTY_SOLD_OUT,
                                  SITE_VISIT_DONE, BUDGET_NOT_SUFFICIENT})
    UNREACHABLE_STATUSES = frozenset({BUSY, SWITCHED_OFF, WRONG_NUMBER})
```

This makes domain queries readable:
```python
# BEFORE
domain = [("current_status", "in", ["requirement_closed", "property_sold_out",
           "site_visit_done", "budget_not_sufficient"])]

# AFTER
domain = [("current_status", "in", list(LeadStatus.CLOSED_STATUSES))]
```