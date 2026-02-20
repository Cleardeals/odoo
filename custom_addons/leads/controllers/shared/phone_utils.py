"""
Docstring for custom_addons.leads.controllers.shared.phone_utils

Centralized phone normalization helpers.
All API endpoints accept a phone number with or without the Indian Country Code. This module strips formattiong, resolves the country code, and
returns the canonical 10 digit local number used inside odoo.
"""

import re


def normalize_phone_to_10_digit(phone: str) -> str | None:
    """
    Accepts any common Indian phone format and returns a clean 10-digit string.

    Accepted inputs
    ---------------
    - "9876543210"          → "9876543210"
    - "919876543210"        → "9876543210"
    - "+919876543210"       → "9876543210"
    - "09876543210"         → "9876543210"
    - "  98765 43210 "      → "9876543210"

    Returns None if the number cannot be resolved to a 10-digit format.
    """
    if not phone:
        return None

    digits_only = re.sub(r"\D", "", str(phone).strip())

    if len(digits_only) == 10:
        return digits_only

    if len(digits_only) == 11 and digits_only.startswith("0"):
        return digits_only[1:]

    if len(digits_only) == 12 and digits_only.startswith("91"):
        return digits_only[2:]

    # Format Doesn't match, either too short, or too long.
    return None


def extract_phone_from_request(request) -> str | None:
    """
    Pulls the `phone` query-parameter from an Odoo HTTP request
    and returns the normalised 10-digit string, or None if missing / invalid.

    Usage
    -----
        phone = extract_phone_from_request(request)
        if not phone:
            return error_response(400, "phone parameter is required or invalid")
    """
    raw_phone = request.params.get("phone", "").strip()
    return normalize_phone_to_10_digit(raw_phone)
