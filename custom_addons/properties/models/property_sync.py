import logging
import re
from datetime import datetime

import requests

from odoo import _, api, models

try:
    from google.cloud import bigquery as _bigquery
except ImportError:  # noqa: BLE001
    _bigquery = None

_logger = logging.getLogger(__name__)


def _normalize_owner_phone(raw: str) -> str:
    """
    Strip formatting and country code from an Indian mobile number.
    Returns a clean 10-digit string, or the raw value if it cannot be resolved.
    """
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw.strip())
    if len(digits) == 10:
        return digits
    if len(digits) == 11 and digits.startswith("0"):
        return digits[1:]
    if len(digits) == 12 and digits.startswith("91"):
        return digits[2:]
    return raw  # unrecognised format — store as-is so data isn't lost


# API endpoint for the Cleardeals property listing
PROPERTY_API_URL = "https://api.cleardeals.cc/api/v1/properties"

# BigQuery — same project/table used by the lead_suggestor BQ sync
_BQ_PROJECT = "cleardeals-459513"
_BQ_CUSTOMER_TABLE = "cleardeals-459513.cleardeals_dataset.Customer_Data"
# Records per API page.  The website API uses the `limit` query param.
# Keeping at 100 halves the number of HTTP round-trips vs the default of 20.
PAGE_SIZE = 100

# Fields that the API cron is allowed to write.
# NEVER include manager-editable fields (service_expiry_date, welcome_call_date,
# property_tag) here — those are owned by the migration cron and the manager
# UI only.
API_WRITABLE_FIELDS = {
    "uuid",
    "prop_id",
    "form_no",
    "name",
    "reg_date",
    "prop_type",
    "for_sell",
    "prop_sub_type",
    "state",
    "city",
    "location",
    "rm_user_id",
    "owner_name",
    "owner_phone",
    "owner_email",
    "pricing",
    "pricing_unit",
    "gmaps_url",
    "bedroom_count",
}

# Fields that the migration cron populates from property.inventory.
# The API cron must never touch these.
MIGRATION_FIELDS = {
    "property_tag",
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


def _parse_pricing_unit(api_item: dict) -> str:
    """
    Return the unit string for the property price (e.g. 'lakh', 'crore',
    'thousand').  Mirrors the selection logic of _parse_pricing().

    For-sale properties:  sell_pricing.offer_price_unit
    For-rent properties:  rent_pricing.rent_price_unit
    Returns an empty string when the unit is absent.
    """
    for_sell = bool(api_item.get("for_sell"))
    if for_sell:
        sell = api_item.get("sell_pricing") or {}
        return str(sell.get("offer_price_unit") or "")
    rent = api_item.get("rent_pricing") or {}
    return str(rent.get("rent_price_unit") or "")


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
        "form_no": api_item.get("form_no") or "",
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
        # RM / exec — raw name; resolved to rm_user_id in the cron loop
        "_exec_name": api_item.get("exec_name") or "",
        # Owner
        "owner_name": api_item.get("owner_name") or "",
        "owner_phone": _normalize_owner_phone(api_item.get("owner_contact_no") or ""),
        "owner_email": api_item.get("owner_email") or "",
        # Financials
        "pricing": _parse_pricing(api_item),
        "pricing_unit": _parse_pricing_unit(api_item),
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
        # Normalise Many2one fields: search_read returns (id, name) tuples;
        # strip to a bare int so the change-detection diff works correctly.
        for r in existing_records:
            if isinstance(r.get("rm_user_id"), (list, tuple)):
                r["rm_user_id"] = r["rm_user_id"][0]
        # { uuid_value: {odoo_id, ...current field values...} }
        existing_map: dict[str, dict] = {
            r["uuid"]: r for r in existing_records if r.get("uuid")
        }
        # Build name→id lookup so exec_name (from API) can be resolved to
        # rm_user_id without a per-property DB hit.
        users_by_name: dict[str, int] = {
            u.name: u.id
            for u in self.env["res.users"]
            .sudo()
            .search(
                [("active", "in", [True, False])],
            )
        }
        # Alias map: normalize variant API spellings to the canonical Odoo name.
        # Key = spelling that may appear in API (AFTER basic cleaning),
        # Value = canonical name as it appears in Odoo.
        _rm_name_aliases: dict[str, str] = {
            "Bhumika Prajapati": "Bhoomika Prajapati",
            "Krusha Kadiya": "Krusha Kadiya",  # canonical spelling; catches 'krusha' after title-case
        }
        _missing_rm: set[str] = set()
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
                # Resolve exec_name → rm_user_id using the pre-built name cache.
                exec_name = vals.pop("_exec_name", "")
                # --- Normalisation pipeline ---
                # 1. Strip leading/trailing whitespace (handles '     ' and 'Name   ')
                exec_name = exec_name.strip()
                # 2. Replace hyphens with spaces (handles 'Vivek-Vaghela' style)
                exec_name = exec_name.replace("-", " ")
                # 3. Collapse multiple internal spaces into one
                exec_name = re.sub(r" {2,}", " ", exec_name)
                # 4. Apply known alias overrides
                exec_name = _rm_name_aliases.get(exec_name, exec_name)
                if exec_name:
                    uid = users_by_name.get(exec_name)
                    # 5. Case-insensitive fallback: try Title Case version
                    if uid is None:
                        uid = users_by_name.get(exec_name.title())
                    if uid:
                        vals["rm_user_id"] = uid
                    else:
                        vals["rm_user_id"] = False
                        if exec_name not in _missing_rm:
                            _logger.warning(
                                "API sync: RM '%s' not found in Odoo users.",
                                exec_name,
                            )
                            _missing_rm.add(exec_name)
                else:
                    vals["rm_user_id"] = False
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

            # Commit after every page so each page is its own short
            # transaction.  This prevents a 60+ second single transaction that
            # causes PostgreSQL SerializationFailure when concurrent requests
            # touch the same property_base rows during the sync window.
            self.env.cr.commit()

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

        Matching key: form_no  (from BigQuery Form_Number column, same value as
        the website API form_no field — stable across name / slug changes).

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

        # --- Build lookup from property.inventory indexed by form_no ---
        inventory_records = (
            self.env["property.inventory"]
            .sudo()
            .search_read(
                [],
                [
                    "id",
                    "form_no",
                    "property_tag",
                    "service_expiry_date",
                    "welcome_call_date",
                    "is_active",
                ],
            )
        )

        # { form_no: inventory_record_dict }  — form_no is the stable cross-model key
        inventory_map: dict[str, dict] = {
            r["form_no"]: r for r in inventory_records if r.get("form_no")
        }
        _logger.info(
            "Loaded %d property.inventory records into migration map (keyed by form_no).",
            len(inventory_map),
        )

        # --- Process only unmigrated property.base records that have a form_no ---
        unmigrated = self.sudo().search(
            [
                ("inventory_migrated", "=", False),
                ("form_no", "!=", False),
            ],
        )
        _logger.info(
            "%d unmigrated property.base records with form_no to process.",
            len(unmigrated),
        )

        matched = 0
        unmatched = 0

        for prop in unmigrated:
            inv = inventory_map.get(prop.form_no)
            if not inv:
                _logger.debug(
                    "No inventory match for form_no '%s' (id=%d).",
                    prop.form_no,
                    prop.id,
                )
                unmatched += 1
                continue

            # Build vals — only write fields that are actually set in the source
            migration_vals = {"inventory_migrated": True}
            field_map = {
                "property_tag": "property_tag",
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

    # =========================================================================
    # PROP-7 — Manual one-time: pull BQ Customer_Data directly into property.base
    # =========================================================================

    def action_sync_from_bigquery(self):
        """
        Manager-triggered one-time action that queries BigQuery Customer_Data
        directly and fills migration fields on existing property.base records.

        Matching key: form_no  (BQ Form_Number == website API form_no).

        Fills: property_tag, service_expiry_date, welcome_call_date, is_active.

        Only writes a field when BQ provides a non-empty value; service_expiry_date
        is only overwritten if property.base does not already have one.

        Safe to call multiple times — will refresh BQ data on every run.
        Records with no matching BQ Form_Number are left untouched.
        """
        if _bigquery is None:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("BigQuery library missing"),
                    "message": _("Install google-cloud-bigquery to use this feature."),
                    "sticky": True,
                    "type": "danger",
                },
            }

        _logger.info(
            "Manual BQ → property.base sync started by user %s.",
            self.env.user.name,
        )

        # ------------------------------------------------------------------
        # 1. Build in-memory map of property.base records keyed by form_no
        # ------------------------------------------------------------------
        base_records = self.sudo().search_read(
            [("form_no", "!=", False)],
            ["id", "form_no", "service_expiry_date"],
        )
        # { form_no_value: {id, service_expiry_date} }
        base_map: dict[str, dict] = {
            r["form_no"]: r for r in base_records if r.get("form_no")
        }
        if not base_map:
            _logger.info("No property.base records with form_no — nothing to sync.")
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Nothing to sync"),
                    "message": _(
                        "No property.base records have a Form Number yet. "
                        "Run the API sync first so form_no values are populated.",
                    ),
                    "sticky": False,
                    "type": "warning",
                },
            }

        _logger.info(
            "Loaded %d property.base records with form_no into memory.",
            len(base_map),
        )

        # ------------------------------------------------------------------
        # 2. Query BigQuery — fetch the latest row per Form_Number
        # ------------------------------------------------------------------
        try:
            client = _bigquery.Client(project=_BQ_PROJECT)
        except Exception as e:  # noqa: BLE001
            _logger.error("Failed to create BigQuery client: %s", e)
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("BigQuery connection failed"),
                    "message": str(e),
                    "sticky": True,
                    "type": "danger",
                },
            }

        # Build a parameterised IN list so we only fetch rows we actually need
        form_nos = list(base_map.keys())
        # BigQuery IN clauses have a limit of ~10 000 items — safe for our volume
        form_nos_literal = ", ".join(f"'{fn}'" for fn in form_nos)

        query = f"""
            WITH LatestRows AS (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY Form_Number
                        ORDER BY
                            SAFE.PARSE_TIMESTAMP('%d-%m-%Y %H:%M:%S', Created_Date) DESC,
                            upload_timestamp DESC
                    ) AS rn
                FROM `{_BQ_CUSTOMER_TABLE}`
                WHERE Form_Number IS NOT NULL
                  AND TRIM(Form_Number) != ''
                  AND Form_Number IN ({form_nos_literal})
            )
            SELECT
                Form_Number                                         AS form_no,
                Tag                                                 AS property_tag,
                Service_Expiry_Date                                 AS service_expiry_date_raw,
                COALESCE(
                    SAFE.PARSE_DATE('%d/%m/%Y', Service_Expiry_Date),
                    SAFE.PARSE_DATE('%d-%m-%Y', Service_Expiry_Date)
                )                                                   AS expiry_date,
                COALESCE(
                    SAFE.PARSE_DATE('%d/%m/%Y', Welcome_Call_Date),
                    SAFE.PARSE_DATE('%d-%m-%Y', Welcome_Call_Date)
                )                                                   AS welcome_call_date,
                CASE
                    WHEN Property_Status IN ('Sold-CD', 'Sold-Others', 'Rented-CD') THEN FALSE
                    WHEN COALESCE(
                        SAFE.PARSE_DATE('%d/%m/%Y', Service_Expiry_Date),
                        SAFE.PARSE_DATE('%d-%m-%Y', Service_Expiry_Date)
                    ) < CURRENT_DATE('Asia/Kolkata') THEN FALSE
                    ELSE TRUE
                END                                                 AS is_active
            FROM LatestRows
            WHERE rn = 1
        """

        try:
            _logger.info("Running BigQuery query for %d form numbers...", len(form_nos))
            rows = list(client.query(query).result())
            _logger.info("BigQuery returned %d matching rows.", len(rows))
        except Exception as e:  # noqa: BLE001
            _logger.error("BigQuery query failed: %s", e)
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("BigQuery query failed"),
                    "message": str(e),
                    "sticky": True,
                    "type": "danger",
                },
            }

        # ------------------------------------------------------------------
        # 3. Write BQ data into matched property.base records
        # ------------------------------------------------------------------
        matched = 0
        skipped = 0

        for row in rows:
            fn = row.form_no
            base_rec_meta = base_map.get(fn)
            if not base_rec_meta:
                skipped += 1
                continue

            rec = self.sudo().browse(base_rec_meta["id"])

            # Parse expiry date
            service_expiry_date = None
            if row.expiry_date:
                try:
                    service_expiry_date = (
                        datetime.strptime(str(row.expiry_date), "%Y-%m-%d").date()
                        if isinstance(row.expiry_date, str)
                        else row.expiry_date
                    )
                except Exception:  # noqa: BLE001
                    service_expiry_date = None

            # Parse welcome call date
            welcome_call_date = None
            if row.welcome_call_date:
                try:
                    welcome_call_date = (
                        datetime.strptime(str(row.welcome_call_date), "%Y-%m-%d").date()
                        if isinstance(row.welcome_call_date, str)
                        else row.welcome_call_date
                    )
                except Exception:  # noqa: BLE001
                    welcome_call_date = None

            vals = {"inventory_migrated": True}

            if row.property_tag:
                vals["property_tag"] = row.property_tag
            if welcome_call_date:
                vals["welcome_call_date"] = welcome_call_date
            # Only overwrite service_expiry_date if not already set on the record
            if service_expiry_date and not base_rec_meta.get("service_expiry_date"):
                vals["service_expiry_date"] = service_expiry_date
            vals["is_active"] = bool(row.is_active)

            rec.write(vals)
            matched += 1

            if matched % 100 == 0:
                self.env.cr.commit()
                _logger.info("Committed %d records so far...", matched)

        self.env.cr.commit()
        _logger.info(
            "BQ → property.base sync complete. Written: %d | No BQ match: %d",
            matched,
            skipped,
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("BigQuery Sync Complete"),
                "message": _(
                    "%(matched)d properties updated from BigQuery. "
                    "%(skipped)d had no matching Form Number in BQ.",
                    matched=matched,
                    skipped=skipped,
                ),
                "sticky": False,
                "type": "success",
            },
        }
