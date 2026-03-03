import logging
import re

import requests

from odoo import api, models

_logger = logging.getLogger(__name__)

# API endpoint for the Cleardeals property listing
PROPERTY_API_URL = "https://api.cleardeals.cc/api/v1/properties"
# Records per API page.  The website API uses the `limit` query param.
# Keeping at 100 halves the number of HTTP round-trips vs the default of 20.
PAGE_SIZE = 100

# Fields that the API cron is allowed to write.
# NEVER include manager-editable fields (service_expiry_date, welcome_call_date,
# property_tag, portal IDs) here — those are owned by the migration cron and
# the manager UI only.
API_WRITABLE_FIELDS = {
    "uuid",
    "prop_id",
    "name",
    "reg_date",
    "prop_type",
    "for_sell",
    "prop_sub_type",
    "state",
    "city",
    "location",
    "rm_name",
    "owner_name",
    "owner_phone",
    "owner_email",
    "pricing",
    "gmaps_url",
    "bedroom_count",
}

# Fields that the migration cron populates from property.inventory.
# The API cron must never touch these.
MIGRATION_FIELDS = {
    "property_tag",
    "ninety_nine_acres_id",
    "housing_id",
    "magicbricks_id",
    "olx_id",
    "service_expiry_date",
    "welcome_call_date",
}


def _parse_bedroom_count(bedroom_str) -> int:
    """
    Extract an integer bedroom count from the API's details.bedroom_count field.

    The API returns a string such as "3 BHK", "2 BHK", or None (for commercial
    properties that have no bedrooms).  We take the first run of digits found
    in the string and return that as an integer, defaulting to 0.

    Examples:
        "3 BHK"  -> 3
        "2BHK"   -> 2
        None     -> 0
        ""       -> 0
    """
    if not bedroom_str:
        return 0
    match = re.search(r"(\d+)", str(bedroom_str))
    return int(match.group(1)) if match else 0


def _parse_reg_date(reg_date_str) -> str:
    """
    Normalise the API's reg_date ISO datetime string to a plain YYYY-MM-DD
    date string that Odoo's Date field accepts.

    Input examples:
        "2026-03-02T00:00:00.000Z"  -> "2026-03-02"
        "2026-03-02"                -> "2026-03-02"  (already clean)
        None / ""                   -> False         (field left empty)
    """
    if not reg_date_str:
        return False
    # ISO datetime: take everything before the first 'T'
    return str(reg_date_str).split("T")[0]


def _parse_pricing(api_item: dict) -> float:
    """
    Return the relevant price value depending on whether the property is for
    sale or for rent.

    For-sale properties:
        sell_pricing.offer_price  (unit: lakh / crore / etc. — stored as-is)
    For-rent properties:
        rent_pricing.rent_price   (unit: thousand / etc. — stored as-is)

    The numeric value from the API is stored directly; unit conversion can be
    added later if needed.  Returns 0.0 when no pricing block is present.
    """
    for_sell = bool(api_item.get("for_sell"))
    if for_sell:
        sell = api_item.get("sell_pricing") or {}
        return float(sell.get("offer_price") or 0.0)
    rent = api_item.get("rent_pricing") or {}
    return float(rent.get("rent_price") or 0.0)


def _map_api_record(api_item: dict) -> dict:
    """
    Map a single property JSON object returned by the Cleardeals website API
    to a property.base vals dict.

    API response structure (confirmed against live endpoint):
    {
        "id":               str  (UUID),
        "property_name":    str,
        "prop_id":          str  (8-char short code),
        "reg_date":         str  (ISO datetime e.g. "2026-03-02T00:00:00.000Z"),
        "prop_type":        str  ("residential" | "commercial"),
        "for_sell":         bool,
        "prop_sub_type":    str,
        "exec_name":        str,
        "owner_name":       str,
        "owner_contact_no": str,
        "owner_email":      str,
        "gmaps_url":        str | null,
        "state":            { "name": str, ... },
        "city":             { "name": str, ... },
        "location_area":    { "name": str, ... },
        "details":          { "bedroom_count": "3 BHK" | null, ... },
        "sell_pricing":     { "offer_price": float, ... } | null,
        "rent_pricing":     { "rent_price": float, ... }  | null,
        ...
    }

    Only fields in API_WRITABLE_FIELDS are returned; manager-editable fields
    are never included.
    """
    details = api_item.get("details") or {}

    return {
        # Identifiers
        "uuid": api_item.get("id"),
        "prop_id": api_item.get("prop_id"),
        # Core info
        "name": api_item.get("property_name"),
        "reg_date": _parse_reg_date(api_item.get("reg_date")),
        "prop_type": api_item.get("prop_type"),
        "for_sell": bool(api_item.get("for_sell")),
        "prop_sub_type": api_item.get("prop_sub_type"),
        # Location — nested objects; fall back to empty string if absent
        "state": (api_item.get("state") or {}).get("name", ""),
        "city": (api_item.get("city") or {}).get("name", ""),
        "location": (api_item.get("location_area") or {}).get("name", ""),
        # RM / exec
        "rm_name": api_item.get("exec_name") or "",
        # Owner
        "owner_name": api_item.get("owner_name") or "",
        "owner_phone": api_item.get("owner_contact_no") or "",
        "owner_email": api_item.get("owner_email") or "",
        # Financials
        "pricing": _parse_pricing(api_item),
        # Map
        "gmaps_url": api_item.get("gmaps_url") or "",
        # Details — nested object
        "bedroom_count": _parse_bedroom_count(details.get("bedroom_count")),
    }


class PropertyBaseSync(models.Model):
    """
    Sync logic for property.base — kept separate from the field definitions so
    property_base.py stays readable.

    Methods here are added to property.base via _inherit.
    """

    _inherit = "property.base"

    # =========================================================================
    # PROP-5 — API → Odoo sync cron  (every 3 hours)
    # =========================================================================

    @api.model
    def _cron_sync_from_api(self):
        """
        Fetches all properties from api.cleardeals.cc page by page and
        upserts them into property.base.

        Strategy:
        - Load all existing records into a uuid-keyed Python dict (one DB call).
        - For each API page, split items into "new" and "existing" buckets.
        - New → bulk create(vals_list).
        - Existing → compare only API_WRITABLE_FIELDS; write() only if changed.
        - MIGRATION_FIELDS are never touched.
        """
        _logger.info("Starting API sync for property.base...")

        try:
            response_test = requests.get(
                PROPERTY_API_URL,
                params={"page": 1, "limit": 1},
                timeout=10,
            )
            response_test.raise_for_status()
        except requests.RequestException as e:
            _logger.error("API sync aborted — endpoint unreachable: %s", e)
            return

        # --- Build in-memory lookup of existing records ---
        # search_read returns only the fields we need; avoids loading ORM objects
        # for 1200+ records unnecessarily.
        existing_records = self.sudo().search_read(
            [],
            list(API_WRITABLE_FIELDS) + ["id", "uuid"],
        )
        # { uuid_value: {odoo_id, ...current field values...} }
        existing_map: dict[str, dict] = {
            r["uuid"]: r for r in existing_records if r.get("uuid")
        }
        _logger.info(
            "Loaded %d existing property.base records into memory.",
            len(existing_map),
        )

        page = 1
        total_pages = None  # resolved after the first response
        total_created = 0
        total_updated = 0
        total_unchanged = 0

        while True:
            try:
                response = requests.get(
                    PROPERTY_API_URL,
                    # No auth header — endpoint is open
                    params={"page": page, "limit": PAGE_SIZE},
                    timeout=30,
                )
                response.raise_for_status()
                payload = response.json()
            except requests.RequestException as e:
                _logger.error(
                    "API sync failed on page %d: %s",
                    page,
                    e,
                )
                break

            # --- Parse response envelope ---
            # Shape: { "success": bool, "properties": [...], "pagination": {...} }
            if not payload.get("success", True):
                _logger.error("API returned success=false on page %d.", page)
                break

            items = payload.get("properties") or []

            # Resolve total pages from the pagination block on first call
            pagination = payload.get("pagination") or {}
            if total_pages is None:
                total_pages = pagination.get("totalPages") or 1
                _logger.info(
                    "API sync: %d total properties across %d pages (limit=%d).",
                    pagination.get("total", "?"),
                    total_pages,
                    PAGE_SIZE,
                )

            has_next = page < total_pages

            if not items:
                _logger.info("Page %d returned 0 items — stopping early.", page)
                break

            vals_to_create = []

            for api_item in items:
                vals = _map_api_record(api_item)
                uuid_val = vals.get("uuid")

                if not uuid_val:
                    _logger.warning(
                        "Skipping API item with no uuid: %s",
                        api_item,
                    )
                    continue

                if uuid_val in existing_map:
                    # --- UPDATE PATH: only write changed API-writable fields ---
                    current = existing_map[uuid_val]
                    diff = {
                        k: v
                        for k, v in vals.items()
                        if k in API_WRITABLE_FIELDS and current.get(k) != v
                    }
                    if diff:
                        self.sudo().browse(current["id"]).write(diff)
                        total_updated += 1
                    else:
                        total_unchanged += 1
                else:
                    # --- CREATE PATH ---
                    vals_to_create.append(vals)
                    # Mark in map so a duplicate uuid within the same API run
                    # doesn't trigger a second create
                    existing_map[uuid_val] = vals

            if vals_to_create:
                created = self.sudo().create(vals_to_create)
                total_created += len(created)
                _logger.info(
                    "Page %d: created %d new records.",
                    page,
                    len(created),
                )

            _logger.info(
                "Page %d processed. Running totals — created: %d, "
                "updated: %d, unchanged: %d.",
                page,
                total_created,
                total_updated,
                total_unchanged,
            )

            if not has_next:
                break
            page += 1

        _logger.info(
            "API sync complete. Created: %d | Updated: %d | Unchanged: %d",
            total_created,
            total_updated,
            total_unchanged,
        )

    # =========================================================================
    # PROP-6 — One-time migration: property.inventory → property.base
    # =========================================================================

    @api.model
    def _cron_sync_from_inventory(self):
        """
        One-time migration cron that reads the legacy property.inventory records
        already present in Odoo (synced from BigQuery) and copies the
        manager-editable fields into the matching property.base record.

        Matching key: property_link (computed identically in both models).

        After a successful match the record's inventory_migrated flag is set
        True so this cron skips it on every subsequent run.

        Also relinks all property.lead.suggestion records so their property_id
        FK points to the new property.base record instead of property.inventory.

        Safe to run repeatedly — only processes records where
        inventory_migrated = False.
        """
        _logger.info("Starting property.inventory → property.base migration cron...")

        # Guard: if property.inventory no longer exists (post-deletion), exit cleanly
        if "property.inventory" not in self.env:
            _logger.info(
                "property.inventory model not found — migration already complete.",
            )
            return

        # --- Build lookup from property.inventory indexed by property_link ---
        inventory_records = (
            self.env["property.inventory"]
            .sudo()
            .search_read(
                [],
                [
                    "id",
                    "property_link",
                    "property_tag",
                    "ninety_nine_acres_id",
                    "housing_id",
                    "magicbricks_id",
                    "olx_id",
                    "service_expiry_date",
                    "welcome_call_date",
                    "is_active",
                ],
            )
        )

        # { property_link: inventory_record_dict }
        inventory_map: dict[str, dict] = {
            r["property_link"]: r for r in inventory_records if r.get("property_link")
        }
        _logger.info(
            "Loaded %d property.inventory records into migration map.",
            len(inventory_map),
        )

        # --- Process only unmigrated property.base records ---
        unmigrated = self.sudo().search(
            [
                ("inventory_migrated", "=", False),
                ("property_link", "!=", False),
            ],
        )
        _logger.info(
            "%d unmigrated property.base records to process.",
            len(unmigrated),
        )

        matched = 0
        unmatched = 0

        for prop in unmigrated:
            inv = inventory_map.get(prop.property_link)
            if not inv:
                _logger.debug(
                    "No inventory match for property_link '%s' (id=%d).",
                    prop.property_link,
                    prop.id,
                )
                unmatched += 1
                continue

            # Build vals — only write fields that are actually set in the source
            migration_vals = {"inventory_migrated": True}
            field_map = {
                "property_tag": "property_tag",
                "ninety_nine_acres_id": "ninety_nine_acres_id",
                "housing_id": "housing_id",
                "magicbricks_id": "magicbricks_id",
                "olx_id": "olx_id",
                "service_expiry_date": "service_expiry_date",
                "welcome_call_date": "welcome_call_date",
                "is_active": "is_active",
            }
            for src_field, dst_field in field_map.items():
                src_val = inv.get(src_field)
                # search_read returns Many2one as (id, name) tuple; handle dates
                # returned as date objects transparently
                if src_val not in (None, False, ""):
                    # Only set service_expiry_date if not already populated by API
                    if dst_field == "service_expiry_date" and prop.service_expiry_date:
                        continue
                    migration_vals[dst_field] = src_val

            prop.write(migration_vals)
            matched += 1

            # NOTE: Relinking property.lead.suggestion records to property.base
            # is deferred to the lead_suggestor refactor (PROP-9).
            # property_lead_suggestion.property_inventory_id is still a FK to
            # property.inventory — writing a property.base id into it would
            # violate the FK constraint.  Once lead_suggestor adds a
            # property_base_id Many2one field pointing to property.base, a
            # separate migration pass can set that field here.

        _logger.info(
            "Migration cron complete. Matched: %d | Unmatched (will retry): %d",
            matched,
            unmatched,
        )
