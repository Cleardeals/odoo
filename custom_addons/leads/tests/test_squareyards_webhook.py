# -*- coding: utf-8 -*-
"""
HTTP integration tests for the Square Yards inbound lead webhook
(`POST /api/v1/squareyards_webhook`).

The endpoint's whole job lives at the HTTP boundary — auth headers, status
codes, JSON parsing, method handling — so these run through a real request via
HttpCase.url_open rather than calling the controller method directly.

Covered:
  * Auth matrix       — valid apikey / X-API-KEY fallback / missing / wrong / unset param.
  * Payload validation — missing mobile, missing propertyId, missing name (allowed),
                          malformed JSON, wrong HTTP method, extra fields ignored.
  * Field mapping      — mobile->phone (+ normalisation), email, projectName,
                          propertyId->portal_property_id, full body in raw_data,
                          numeric mobile/propertyId coerced safely.
  * Property matching  — listing match -> property RM; no match -> fallback RM;
                          same id on another portal does NOT cross-match.
  * Duplicate handling — same phone+propertyId is de-duped (still 200); a different
                          phone creates a new lead.
"""

import json
from time import time

from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user

_URL = "/api/v1/squareyards_webhook"


@tagged("post_install", "-at_install")
class TestSquareYardsWebhook(HttpCase):
    """Inbound Square Yards webhook — end-to-end over HTTP."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.suffix = str(int(time()))
        cls.api_key = f"sy-test-key-{cls.suffix}"

        cls.env["ir.config_parameter"].sudo().set_param(
            "squareyards.webhook.api.key", cls.api_key,
        )

        # RM that owns the matched property, and the fallback RM for the source.
        cls.prop_rm = new_test_user(
            cls.env,
            login=f"sy_prop_rm_{cls.suffix}",
            name="SY Property RM",
            groups="base.group_user",
        )
        cls.fallback_rm = new_test_user(
            cls.env,
            login=f"sy_fallback_rm_{cls.suffix}",
            name="SY Fallback RM",
            groups="base.group_user",
        )

        # Seeded SquareYards source + a deterministic fallback RM for unmatched leads.
        cls.source = cls.env.ref("leads.lead_source_squareyards")
        cls.source.sudo().write({"default_rm_user_id": cls.fallback_rm.id})

        # A property registered with a SquareYards listing id (the join key).
        cls.listing_id = f"SY-{cls.suffix}"
        cls.property = cls.env["property.base"].sudo().create(
            {
                "name": f"SY Webhook Property {cls.suffix}",
                "property_tag": f"SY-WH-{cls.suffix}",
                "rm_user_id": cls.prop_rm.id,
                "portal_listing_ids": [
                    (0, 0, {
                        "portal_name": "SquareYards",
                        "portal_listing_id": cls.listing_id,
                        "active": True,
                    }),
                ],
            }
        )

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    @classmethod
    def _phone(cls, n):
        """A unique, valid 10-digit number per test (starts with 9)."""
        return str(9000000000 + (int(cls.suffix) + n) % 1000000000)

    def _post(self, payload, key=None, header="apikey", raw=None):
        """POST to the webhook. `raw` overrides JSON encoding (for malformed-body tests)."""
        headers = {"Content-Type": "application/json"}
        if key is not None:
            headers[header] = key
        body = raw if raw is not None else json.dumps(payload)
        return self.url_open(_URL, data=body, headers=headers)

    def _lead_for(self, phone):
        return self.env["leads.new"].sudo().search([("phone", "=", phone)], limit=1)

    # ------------------------------------------------------------------ #
    # Auth matrix                                                         #
    # ------------------------------------------------------------------ #

    def test_01_valid_apikey_creates_lead(self):
        phone = self._phone(1)
        resp = self._post(
            {"mobile": phone, "propertyId": self.listing_id, "name": "Valid"},
            key=self.api_key,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self._lead_for(phone))

    def test_02_x_api_key_fallback_header(self):
        phone = self._phone(2)
        resp = self._post(
            {"mobile": phone, "propertyId": self.listing_id},
            key=self.api_key,
            header="X-API-KEY",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self._lead_for(phone))

    def test_03_missing_key_rejected(self):
        phone = self._phone(3)
        resp = self._post({"mobile": phone, "propertyId": self.listing_id}, key=None)
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(self._lead_for(phone))

    def test_04_wrong_key_rejected(self):
        phone = self._phone(4)
        resp = self._post(
            {"mobile": phone, "propertyId": self.listing_id}, key="totally-wrong",
        )
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(self._lead_for(phone))

    def test_05_unset_server_param_returns_503(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "squareyards.webhook.api.key", "",
        )
        phone = self._phone(5)
        resp = self._post(
            {"mobile": phone, "propertyId": self.listing_id}, key=self.api_key,
        )
        self.assertEqual(resp.status_code, 503)
        self.assertFalse(self._lead_for(phone))

    # ------------------------------------------------------------------ #
    # Payload validation                                                  #
    # ------------------------------------------------------------------ #

    def test_06_missing_mobile_rejected(self):
        resp = self._post({"propertyId": self.listing_id, "name": "No Phone"}, key=self.api_key)
        self.assertEqual(resp.status_code, 400)

    def test_07_missing_property_id_rejected(self):
        phone = self._phone(7)
        resp = self._post({"mobile": phone, "name": "No Prop"}, key=self.api_key)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(self._lead_for(phone))

    def test_08_missing_name_is_allowed_whatsapp_flow(self):
        """WhatsApp-button leads carry no name; lead is created with a fallback name."""
        phone = self._phone(8)
        resp = self._post({"mobile": phone, "propertyId": self.listing_id}, key=self.api_key)
        self.assertEqual(resp.status_code, 200)
        lead = self._lead_for(phone)
        self.assertTrue(lead)
        self.assertEqual(lead.name, "SquareYards Lead")

    def test_09_malformed_json_returns_400(self):
        resp = self._post(None, key=self.api_key, raw="{not valid json")
        self.assertEqual(resp.status_code, 400)

    def test_10_get_method_not_allowed(self):
        resp = self.url_open(_URL, headers={"apikey": self.api_key})
        self.assertEqual(resp.status_code, 405)

    def test_11_extra_fields_ignored_and_stored_in_raw_data(self):
        phone = self._phone(11)
        payload = {
            "mobile": phone,
            "propertyId": self.listing_id,
            "name": "Extra Fields",
            "availArea": 100,
            "totalPrice": 50000,
            "listingType": "rent",
            "cityName": "Gurgaon",
            "unitType": "3bhk",
        }
        resp = self._post(payload, key=self.api_key)
        self.assertEqual(resp.status_code, 200)
        lead = self._lead_for(phone)
        self.assertTrue(lead)
        raw = json.loads(lead.raw_data)
        self.assertEqual(raw["cityName"], "Gurgaon")
        self.assertEqual(raw["totalPrice"], 50000)

    # ------------------------------------------------------------------ #
    # Field mapping & phone normalisation                                 #
    # ------------------------------------------------------------------ #

    def test_12_happy_path_field_mapping(self):
        phone = self._phone(12)
        resp = self._post(
            {
                "mobile": phone,
                "propertyId": self.listing_id,
                "name": "Full Map",
                "email": "buyer@example.com",
                "projectName": "Green Heights",
            },
            key=self.api_key,
        )
        self.assertEqual(resp.status_code, 200)
        lead = self._lead_for(phone)
        self.assertEqual(lead.name, "Full Map")
        self.assertEqual(lead.email, "buyer@example.com")
        self.assertEqual(lead.project_name, "Green Heights")
        self.assertEqual(lead.portal_property_id, self.listing_id)
        self.assertEqual(lead.source_id, self.source)
        self.assertEqual(lead.source_id.portal_code, "SquareYards")

    def test_13_phone_normalisation_strips_country_code(self):
        local = self._phone(13)
        resp = self._post(
            {"mobile": f"+91 {local}", "propertyId": self.listing_id}, key=self.api_key,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self._lead_for(local), "12-digit +91 number should store as 10 digits")

    def test_14_numeric_mobile_and_property_id_coerced(self):
        local = self._phone(14)
        # Send mobile and propertyId as JSON numbers, not strings.
        payload = {"mobile": int(local), "propertyId": 987654}
        resp = self._post(payload, key=self.api_key)
        self.assertEqual(resp.status_code, 200)
        lead = self._lead_for(local)
        self.assertTrue(lead)
        self.assertEqual(lead.portal_property_id, "987654")

    # ------------------------------------------------------------------ #
    # Property matching & RM assignment                                   #
    # ------------------------------------------------------------------ #

    def test_15_matched_listing_assigns_property_rm(self):
        phone = self._phone(15)
        self._post({"mobile": phone, "propertyId": self.listing_id}, key=self.api_key)
        lead = self._lead_for(phone)
        self.assertEqual(lead.property_base_id, self.property)
        self.assertEqual(lead.user_id, self.prop_rm)
        self.assertEqual(lead.state, "assigned")

    def test_16_unmatched_listing_uses_fallback_rm(self):
        phone = self._phone(16)
        self._post(
            {"mobile": phone, "propertyId": f"NOPE-{self.suffix}"}, key=self.api_key,
        )
        lead = self._lead_for(phone)
        self.assertFalse(lead.property_base_id)
        self.assertEqual(lead.user_id, self.fallback_rm)

    def test_17_same_id_on_other_portal_does_not_cross_match(self):
        """A propertyId that only exists under OLX must not match a SquareYards lead."""
        olx_only_id = f"OLXONLY-{self.suffix}"
        self.env["property.base"].sudo().create(
            {
                "name": f"OLX Only {self.suffix}",
                "property_tag": f"OLX-ONLY-{self.suffix}",
                "rm_user_id": self.prop_rm.id,
                "portal_listing_ids": [
                    (0, 0, {
                        "portal_name": "OLX",
                        "portal_listing_id": olx_only_id,
                        "active": True,
                    }),
                ],
            }
        )
        phone = self._phone(17)
        self._post({"mobile": phone, "propertyId": olx_only_id}, key=self.api_key)
        lead = self._lead_for(phone)
        self.assertFalse(lead.property_base_id, "SquareYards lead must not match an OLX listing")
        self.assertEqual(lead.user_id, self.fallback_rm)

    # ------------------------------------------------------------------ #
    # Duplicate handling                                                  #
    # ------------------------------------------------------------------ #

    def test_18_duplicate_same_phone_and_property_is_deduped(self):
        phone = self._phone(18)
        first = self._post({"mobile": phone, "propertyId": self.listing_id}, key=self.api_key)
        second = self._post({"mobile": phone, "propertyId": self.listing_id}, key=self.api_key)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200, "Duplicate is acknowledged, not an error")
        self.assertEqual(
            self.env["leads.new"].sudo().search_count([("phone", "=", phone)]),
            1,
            "Second identical push must not create a second lead",
        )

    def test_19_different_phone_creates_new_lead(self):
        phone_a = self._phone(190)
        phone_b = self._phone(191)
        self._post({"mobile": phone_a, "propertyId": self.listing_id}, key=self.api_key)
        self._post({"mobile": phone_b, "propertyId": self.listing_id}, key=self.api_key)
        self.assertTrue(self._lead_for(phone_a))
        self.assertTrue(self._lead_for(phone_b))
