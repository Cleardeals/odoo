"""
property_resolver.py
--------------------
Core lookup helpers shared by every seller endpoint.

The seller flow always starts the same way:
  1. Normalise the owner's phone number.
  2. Find all property.inventory records whose owner_phone matches.
  3. Return the property tags (and optionally the full records) so the
     individual endpoint controllers can do their specific queries.

Keeping this here prevents the same ORM calls from being duplicated
across summary, funnel, activity, site_visits, etc.
"""

import logging

_logger = logging.getLogger(__name__)


def get_properties_for_phone(env, phone_10: str):
    """
    Return all active property.inventory records whose owner_phone
    normalises to `phone_10` (a clean 10-digit string).

    Odoo stores owner_phone in various formats (with/without 91, spaces, etc.),
    so we search by the raw stored value first, then fall back to the 91-prefix
    format.

    Parameters
    ----------
    env       : Odoo environment (request.env)
    phone_10  : normalised 10-digit phone string

    Returns
    -------
    property.inventory recordset  (may be empty)
    """
    PropertyInventory = env["property.inventory"].sudo()

    # Primary match: stored as exact 10-digit
    props = PropertyInventory.search(
        [
            ("owner_phone", "=", phone_10),
        ],
    )

    if not props:
        # Fallback: stored with country code "91XXXXXXXXXX"
        props = PropertyInventory.search(
            [
                ("owner_phone", "=", f"91{phone_10}"),
            ],
        )

    _logger.debug(
        "property_resolver: phone=%s -> %d properties found",
        phone_10,
        len(props),
    )
    return props


def get_property_tags(env, phone_10: str) -> list[str]:
    """
    Convenience wrapper - returns just the list of property tags.
    """
    return get_properties_for_phone(env, phone_10).mapped("property_tag")


def get_primary_leads_for_tags(env, property_tags: list[str]):
    """
    Return all leads.new records whose property_id.property_tag is in the
    given list. These are the *primary* inquiries on the seller's properties.

    Parameters
    ----------
    env            : Odoo environment
    property_tags  : list of property tag strings

    Returns
    -------
    leads.new recordset
    """
    if not property_tags:
        return env["leads.new"].sudo().browse([])

    props = (
        env["property.inventory"]
        .sudo()
        .search(
            [
                ("property_tag", "in", property_tags),
            ],
        )
    )

    return (
        env["leads.new"]
        .sudo()
        .search(
            [
                ("property_id", "in", props.ids),
            ],
        )
    )


def get_recommended_leads_for_tags(env, property_tags: list[str]):
    """
    Return all lead.property.interest records where the recommended
    property belongs to the seller's portfolio.

    Parameters
    ----------
    env            : Odoo environment
    property_tags  : list of property tag strings

    Returns
    -------
    lead.property.interest recordset
    """
    if not property_tags:
        return env["lead.property.interest"].sudo().browse([])

    props = (
        env["property.inventory"]
        .sudo()
        .search(
            [
                ("property_tag", "in", property_tags),
            ],
        )
    )

    return (
        env["lead.property.interest"]
        .sudo()
        .search(
            [
                ("property_id", "in", props.ids),
            ],
        )
    )
