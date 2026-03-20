"""
Serializer for ``property.base`` records.

``serialize_property(record)`` converts a single Odoo recordset (a
``property.base`` browse record) into a plain Python ``dict`` that is safe
to pass directly to ``json.dumps`` (via :func:`response_utils.success_response`).

Design decisions
----------------
* Only *stored* or *simply-computed* fields are included.  Heavy computed
  fields (``gmaps_embed_html``) are excluded to keep the payload lean.
* Relational many2one fields are expanded to ``{"id": …, "name": …}`` dicts.
* Falsy Odoo values (``False``) are normalised to ``None`` / ``null``.
* Date objects are converted to ISO-8601 strings (``YYYY-MM-DD``).

Usage::

    from .serializers import serialize_property

    data = serialize_property(prop_record)          # single record → dict
    data = [serialize_property(r) for r in recs]   # recordset  → list[dict]
"""


def serialize_property(record) -> dict:
    """
    Convert a ``property.base`` browse record into a JSON-safe dict.

    Parameters
    ----------
    record:
        A single-record ``property.base`` browse object
        (``env["property.base"].browse(id)``).

    Returns
    -------
    dict
        Flat dictionary suitable for JSON serialisation.
    """

    def _char(val):
        """Return string or None."""
        return val if val else None

    def _bool(val):
        return bool(val)

    def _int(val):
        return int(val) if val else None

    def _float(val):
        return float(val) if val else None

    def _date(val):
        """Return ISO-8601 date string or None."""
        return val.isoformat() if val else None

    def _m2o(rel):
        """Expand a Many2one field to {id, name} or None."""
        if rel and rel.id:
            return {"id": rel.id, "name": rel.display_name or rel.name}
        return None

    def _portal_listings(lines):
        """Serialize property.portal.listing lines."""
        result = []
        for line in lines:
            result.append(
                {
                    "id": line.id,
                    "portal_name": _char(line.portal_name),
                    "portal_listing_id": _char(line.portal_listing_id),
                    "listing_label": _char(line.listing_label),
                    "active": _bool(line.active),
                },
            )
        return result

    return {
        # ------------------------------------------------------------------
        # Identifiers
        # ------------------------------------------------------------------
        "id": record.id,
        "uuid": _char(record.uuid),
        "prop_id": _char(record.prop_id),
        "form_no": _char(record.form_no),
        # ------------------------------------------------------------------
        # Core descriptors (API-sourced — PROP-2.1)
        # ------------------------------------------------------------------
        "name": _char(record.name),
        "reg_date": _date(record.reg_date),
        "prop_type": _char(record.prop_type),
        "prop_sub_type": _char(record.prop_sub_type),
        "for_sell": _bool(record.for_sell),
        "state": _char(record.state),
        "city": _char(record.city),
        "location": _char(record.location),
        # ------------------------------------------------------------------
        # Pricing
        # ------------------------------------------------------------------
        "pricing": _float(record.pricing),
        "pricing_unit": _char(record.pricing_unit),
        "pricing_display": _char(record.pricing_display),
        # ------------------------------------------------------------------
        # Owner info
        # ------------------------------------------------------------------
        "owner_name": _char(record.owner_name),
        "owner_phone": _char(record.owner_phone),
        "owner_email": _char(record.owner_email),
        # ------------------------------------------------------------------
        # Assignment
        # ------------------------------------------------------------------
        "rm_user": _m2o(record.rm_user_id),
        # ------------------------------------------------------------------
        # Physical attributes
        # ------------------------------------------------------------------
        "bedroom_count": _int(record.bedroom_count),
        "bhk": _char(record.bhk),
        # ------------------------------------------------------------------
        # Links / media
        # ------------------------------------------------------------------
        "property_link": _char(record.property_link),
        "gmaps_url": _char(record.gmaps_url),
        # ------------------------------------------------------------------
        # Portal / listing IDs (new relation model)
        # ------------------------------------------------------------------
        "property_tag": _char(record.property_tag),
        "portal_listings": _portal_listings(
            record.portal_listing_ids.sorted(
                key=lambda r: (
                    r.portal_name or "",
                    r.portal_listing_id or "",
                    r.id,
                ),
            ),
        ),
        "legacy_portal_ids": {
            "ninety_nine_acres_id": _char(record.ninety_nine_acres_id),
            "housing_id": _char(record.housing_id),
            "magicbricks_id": _char(record.magicbricks_id),
            "olx_id": _char(record.olx_id),
        },
        # ------------------------------------------------------------------
        # Dates (Manager-editable)
        # ------------------------------------------------------------------
        "service_expiry_date": _date(record.service_expiry_date),
        "welcome_call_date": _date(record.welcome_call_date),
        # ------------------------------------------------------------------
        # Status / system fields (PROP-2.5)
        # ------------------------------------------------------------------
        "is_active": _bool(record.is_active),
        "inventory_migrated": _bool(record.inventory_migrated),
        # ------------------------------------------------------------------
        # Computed display helpers (read-only, not stored)
        # ------------------------------------------------------------------
        "listing_type": _char(record.listing_type),
        "prop_type_display": _char(record.prop_type_display),
        "is_new": _bool(record.is_new),
    }
