"""
property_resolver.py
--------------------
Core lookup helpers shared by every seller endpoint.

The seller flow always starts the same way:
  1. Normalise the owner's phone number.
  2. Find all property.base records whose owner_phone matches.
  3. Return the property tags (and optionally the full records) so the
     individual endpoint controllers can do their specific queries.

Keeping this here prevents the same ORM calls from being duplicated
across summary, funnel, activity, site_visits, etc.
"""

import logging
import re

from .phone_utils import normalize_phone_to_10_digit

_logger = logging.getLogger(__name__)


def get_properties_for_phone(env, phone_10: str):
    """
    Return all property.base records whose owner_phone contains `phone_10`.

    owner_phone may be stored in several real-world formats:
      - Single number, clean:       "9028233802"
      - Single number, with prefix: "919028233802" | "+919028233802"
      - Multiple numbers, space-separated: "9316108956 8780576009"

    Strategy:
      1. SQL LIKE to cheaply narrow candidates to rows that contain the
         10-digit string as a substring.
      2. Python token filter: split on whitespace/commas, normalise each
         token, accept the record only if any token normalises to phone_10.
         This avoids false positives where the 10-digit string appears
         embedded inside a longer number.

    Parameters
    ----------
    env       : Odoo environment (request.env)
    phone_10  : normalised 10-digit phone string

    Returns
    -------
    property.base recordset  (may be empty)
    """
    PropertyInventory = env["property.base"].sudo()

    # Step 1: broad SQL match — finds rows where phone_10 appears anywhere
    # in the stored string (handles all prefix/multi-number variants).
    candidates = PropertyInventory.search(
        [("owner_phone", "like", phone_10)],
    )

    # Step 2: exact token match in Python — each space/comma-separated token
    # is normalised; accept the record if any token resolves to phone_10.
    def _any_token_matches(stored: str) -> bool:
        for token in re.split(r"[\s,;]+", stored or ""):
            if normalize_phone_to_10_digit(token.strip()) == phone_10:
                return True
        return False

    props = candidates.filtered(lambda p: _any_token_matches(p.owner_phone))

    _logger.debug(
        "property_resolver: phone=%s -> %d candidates, %d matched",
        phone_10,
        len(candidates),
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
    Return all leads.new records whose property_base_id.property_tag is in the
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
        env["property.base"]
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
                ("property_base_id", "in", props.ids),
                ("inquiry_type", "=", "primary"),
            ],
        )
    )


def get_recommended_leads_for_tags(env, property_tags: list[str]):
    """
    Return all leads.new records with inquiry_type='recommended' where the
    recommended property belongs to the seller's portfolio.

    Parameters
    ----------
    env            : Odoo environment
    property_tags  : list of property tag strings

    Returns
    -------
    leads.new recordset  (inquiry_type='recommended')
    """
    if not property_tags:
        return env["leads.new"].sudo().browse([])

    props = (
        env["property.base"]
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
                ("property_base_id", "in", props.ids),
                ("inquiry_type", "=", "recommended"),
            ],
        )
    )
