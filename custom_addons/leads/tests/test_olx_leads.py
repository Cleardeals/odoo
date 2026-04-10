# -*- coding: utf-8 -*-
"""
OLX Lead Integration Tests
===========================
Tests for the OLX Business API integration introduced in leads v1.5.0.

Coverage:
    A. _parse_olx_lead
       - Phone normalization (+91 prefix, 10-digit passthrough, missing/null → None)
       - Ad enrichment: project_name from ad_by_id, fallback to None
       - portal_property_id, email, raw_data structure

    B. lead.olx.account — failure tracking and rotation ordering
       - _record_failure increments counter; auto-disables at threshold
       - _record_success resets counter, updates last_fetch_at, clears last_error
       - _get_next_account: NULL-first ordering, oldest-timestamp priority,
         inactive accounts skipped

    C. _api_fetch_olx (HTTP mocked)
       - Happy path: returns parsed lead list
       - OLX 500 (no leads) → empty list, no exception
       - 403 on auth → RuntimeError
       - Missing password → ValueError before any HTTP call
       - Auth response without access_token → RuntimeError
       - Multi-page response: leads URL called once per page

    D. _cron_rotate_olx_accounts (HTTP mocked)
       - Creates leads.new records from fetched data and processes them
       - Skips duplicate leads (same phone + portal_property_id within 30 days)
       - Records consecutive_failures on auth error
       - Resets consecutive_failures and sets last_fetch_at on success
       - Exits cleanly when no active accounts exist

    E. PropertyPortalListingLeadRelink
       - Creating a portal listing relinks unlinked leads to the property / RM
       - Correcting portal_listing_id on an existing listing triggers relink
       - Leads already linked (property_base_id set) are never overwritten
       - All unlinked leads with matching portal+ID are relinked in one shot

Fixtures:
    Inherits PortalLeadTestCase which provides test_property (with OLX listing
    cls.olx_id already attached), source_olx, rm_user, and create_portal_lead().

    TestOlxAccountState and TestOlxApiMocked create their own lead.olx.account
    records; passwords are written via the ORM inverse which stores them in
    ir.config_parameter.

    TestPortalListingRelink uses a separate 'late_prop' fixture that starts with
    NO portal listings so the relink trigger can be observed cleanly.

HTTP mocking:
    All tests in TestOlxApiMocked and the cron sub-tests use
    unittest.mock.patch('odoo.addons.leads.models.new_portal_leads.requests')
    to intercept requests.post / requests.get without touching the network.
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests import tagged

from .test_portal_common import PortalLeadTestCase

# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------

_MODULE_PATH = "odoo.addons.leads.models.new_portal_leads"

_MOCK_AUTH_RESPONSE = {"access_token": "mock_token_abc", "user_id": "888777"}

_MOCK_LEADS_RESPONSE = {
    "data": {
        "leads": [
            {
                "phoneNumber": "+919876543210",
                "name": "Test OLX Buyer",
                "adId": "12345",
                "emailId": "buyer@test.com",
            }
        ],
        "ads": [
            {"id": "12345", "title": "3BHK Bopal Heights"},
        ],
    },
    "pagination": {"totalPages": 1},
}


def _make_response(json_data=None, status_code=200):
    """
    Build a minimal mock requests.Response.

    When status_code >= 400 raise_for_status() raises HTTPError.
    Otherwise it is a no-op so the caller can proceed to .json().
    """
    from requests.exceptions import HTTPError

    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data or {}
    if status_code >= 400:
        http_err = HTTPError(f"{status_code} Error", response=mock_resp)
        mock_resp.raise_for_status.side_effect = http_err
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp


# ---------------------------------------------------------------------------
# A. _parse_olx_lead
# ---------------------------------------------------------------------------


@tagged("post_install", "-at_install")
class TestOlxLeadParsing(PortalLeadTestCase):
    """
    Unit tests for leads.new._parse_olx_lead.

    No HTTP calls, no account records — exercises phone cleaning and ad-dict
    enrichment in complete isolation.
    """

    def _parse(self, lead_dict, ad_by_id=None):
        """Thin helper so tests stay readable."""
        return self.env["leads.new"]._parse_olx_lead(lead_dict, ad_by_id or {})

    # --- Phone normalization ---

    def test_01_phone_plus91_stripped_to_10(self):
        """+91XXXXXXXXXX is stripped to the 10-digit number."""
        result = self._parse({"phoneNumber": "+919876543210", "adId": "1", "name": "X"})
        self.assertIsNotNone(result)
        self.assertEqual(result["phone"], "9876543210")

    def test_02_phone_already_10_digits_unchanged(self):
        """A 10-digit phone passes through without modification."""
        result = self._parse({"phoneNumber": "9876543210", "adId": "1", "name": "X"})
        self.assertIsNotNone(result)
        self.assertEqual(result["phone"], "9876543210")

    def test_03_empty_phone_returns_none(self):
        """Lead with empty phoneNumber is skipped — parser must return None."""
        result = self._parse({"phoneNumber": "", "adId": "1", "name": "No Phone"})
        self.assertIsNone(result, "Empty phone must cause the lead to be skipped")

    def test_04_null_phone_returns_none(self):
        """Lead with null phoneNumber is skipped."""
        result = self._parse({"phoneNumber": None, "adId": "1", "name": "Null Phone"})
        self.assertIsNone(result, "Null phone must cause the lead to be skipped")

    # --- Ad enrichment ---

    def test_05_ad_title_used_as_project_name(self):
        """adId matched in ad_by_id → project_name taken from the ad's title."""
        ad_by_id = {"99": {"id": "99", "title": "Green Valley 3BHK"}}
        result = self._parse(
            {"phoneNumber": "9876543210", "adId": "99", "name": "X"}, ad_by_id
        )
        self.assertEqual(result["project_name"], "Green Valley 3BHK")

    def test_06_unmatched_ad_id_project_name_is_none(self):
        """adId not present in ad_by_id → project_name is None."""
        result = self._parse({"phoneNumber": "9876543210", "adId": "999", "name": "X"})
        self.assertIsNone(result["project_name"])

    def test_07_portal_property_id_set_from_ad_id(self):
        """portal_property_id is always the stringified adId."""
        result = self._parse({"phoneNumber": "9876543210", "adId": "54321", "name": "X"})
        self.assertEqual(result["portal_property_id"], "54321")

    def test_08_email_extracted(self):
        """emailId is mapped to the 'email' key in the result dict."""
        result = self._parse(
            {
                "phoneNumber": "9876543210",
                "adId": "1",
                "name": "X",
                "emailId": "buyer@example.com",
            }
        )
        self.assertEqual(result["email"], "buyer@example.com")

    def test_09_raw_data_contains_lead_and_ad_keys(self):
        """raw_data is valid JSON with 'lead' and 'ad' top-level keys."""
        ad_by_id = {"7": {"id": "7", "title": "Sea View Flat"}}
        result = self._parse(
            {"phoneNumber": "9876543210", "adId": "7", "name": "X"}, ad_by_id
        )
        parsed_raw = json.loads(result["raw_data"])
        self.assertIn("lead", parsed_raw)
        self.assertIn("ad", parsed_raw)


# ---------------------------------------------------------------------------
# B. lead.olx.account — failure tracking + rotation ordering
# ---------------------------------------------------------------------------


@tagged("post_install", "-at_install")
class TestOlxAccountState(PortalLeadTestCase):
    """
    Unit tests for lead.olx.account._record_failure, _record_success,
    and _get_next_account.

    Two account fixtures are created per test class (account_a and account_b)
    with unique logins. Each test resets relevant fields via sudo().write()
    before asserting to prevent inter-test bleed.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.account_a = cls.env["lead.olx.account"].sudo().create(
            {
                "name": f"Test OLX Account A {cls.suffix}",
                "login": f"9100000001_{cls.suffix}",
                "sequence": 10,
                "password": "TestPass@123",
            }
        )
        cls.account_b = cls.env["lead.olx.account"].sudo().create(
            {
                "name": f"Test OLX Account B {cls.suffix}",
                "login": f"9100000002_{cls.suffix}",
                "sequence": 20,
                "password": "TestPass@456",
            }
        )

    def setUp(self):
        super().setUp()
        # Deactivate all accounts except account_a and account_b so that
        # _get_next_account ordering tests are not polluted by the 15 accounts
        # seeded by olx_accounts_data.xml (which also have last_fetch_at=NULL).
        # TransactionCase wraps each test in a savepoint so this is auto-rolled back.
        self._seeded = self.env["lead.olx.account"].sudo().search([
            ("id", "not in", [self.account_a.id, self.account_b.id]),
            ("active", "=", True),
        ])
        self._seeded.sudo().write({"active": False})

    # --- _record_failure ---

    def test_01_failure_increments_consecutive_failures(self):
        """Each call to _record_failure increments consecutive_failures by 1."""
        self.account_a.sudo().write({"consecutive_failures": 0})
        self.account_a._record_failure("test error")
        self.assertEqual(self.account_a.consecutive_failures, 1)

    def test_02_failure_stores_last_error_message(self):
        """_record_failure writes the error string into last_error."""
        self.account_a._record_failure("403 auth error")
        self.assertEqual(self.account_a.last_error, "403 auth error")

    def test_03_fifth_failure_auto_disables_account(self):
        """
        The account must be deactivated (active=False) upon the fifth
        consecutive failure. This prevents the cron from looping on a
        permanently broken account.
        """
        self.account_a.sudo().write({"consecutive_failures": 4, "active": True})
        self.account_a._record_failure("fifth error")
        self.assertFalse(
            self.account_a.active,
            "Account must be auto-disabled after 5 consecutive failures",
        )

    def test_04_auto_disable_appends_to_process_notes(self):
        """Auto-disable event is timestamped and recorded in process_notes."""
        self.account_a.sudo().write(
            {"consecutive_failures": 4, "active": True, "process_notes": ""}
        )
        self.account_a._record_failure("fifth error")
        self.assertIn(
            "Auto-disabled",
            self.account_a.process_notes or "",
            "Disable event must be recorded in process_notes for audit trail",
        )

    def test_05_fourth_failure_does_not_disable(self):
        """Account must remain active until the threshold is reached, not before."""
        self.account_a.sudo().write({"consecutive_failures": 3, "active": True})
        self.account_a._record_failure("fourth error")
        self.assertTrue(
            self.account_a.active,
            "Account must stay active after 4 failures (threshold is 5)",
        )

    # --- _record_success ---

    def test_06_success_resets_failure_counter(self):
        """_record_success sets consecutive_failures back to 0."""
        self.account_a.sudo().write({"consecutive_failures": 3})
        self.account_a._record_success()
        self.assertEqual(self.account_a.consecutive_failures, 0)

    def test_07_success_updates_last_fetch_at(self):
        """_record_success sets last_fetch_at to approximately the current time."""
        before = fields.Datetime.now()
        self.account_a._record_success()
        self.assertIsNotNone(self.account_a.last_fetch_at)
        self.assertGreaterEqual(self.account_a.last_fetch_at, before)

    def test_08_success_clears_last_error(self):
        """_record_success clears last_error so stale error messages are removed."""
        self.account_a.sudo().write({"last_error": "stale error from last run"})
        self.account_a._record_success()
        self.assertFalse(
            self.account_a.last_error,
            "last_error must be cleared on success",
        )

    # --- _get_next_account ---

    def test_09_null_last_fetch_takes_priority(self):
        """
        An account with last_fetch_at=NULL comes before one that has already
        fetched, regardless of sequence order.
        """
        self.account_a.sudo().write({"last_fetch_at": False, "active": True})
        self.account_b.sudo().write(
            {"last_fetch_at": fields.Datetime.now(), "active": True}
        )
        next_acc = self.env["lead.olx.account"]._get_next_account()
        self.assertEqual(
            next_acc.id,
            self.account_a.id,
            "Account with NULL last_fetch_at must be returned first (NULLS FIRST)",
        )

    def test_10_oldest_fetch_returned_next(self):
        """When both accounts have fetched, the one with the oldest timestamp wins."""
        old_ts = datetime(2026, 1, 1, 0, 0, 0)
        new_ts = datetime(2026, 6, 1, 0, 0, 0)
        self.account_a.sudo().write({"last_fetch_at": new_ts, "active": True})
        self.account_b.sudo().write(
            {"last_fetch_at": old_ts, "active": True, "sequence": 5}
        )
        next_acc = self.env["lead.olx.account"]._get_next_account()
        self.assertEqual(
            next_acc.id,
            self.account_b.id,
            "Account with older last_fetch_at must be selected next",
        )

    def test_11_inactive_accounts_are_skipped(self):
        """_get_next_account must never return an account with active=False."""
        self.account_a.sudo().write({"active": False, "last_fetch_at": False})
        self.account_b.sudo().write({"active": True, "last_fetch_at": False})
        next_acc = self.env["lead.olx.account"]._get_next_account()
        self.assertNotEqual(
            next_acc.id,
            self.account_a.id,
            "Inactive account must not be selected for rotation",
        )


# ---------------------------------------------------------------------------
# C & D. _api_fetch_olx + _cron_rotate_olx_accounts (HTTP mocked)
# ---------------------------------------------------------------------------


@tagged("post_install", "-at_install")
class TestOlxApiMocked(PortalLeadTestCase):
    """
    Integration tests for _api_fetch_olx and _cron_rotate_olx_accounts.

    All HTTP calls are intercepted with unittest.mock.patch so no network
    requests are made. Each test asserts at the model-method boundary —
    it doesn't care how the HTTP call is made, only what the method does
    with the response.

    The 'olx.socks_proxy' system parameter is intentionally left empty so
    proxies=None, reproducing the production baseline (prod IP is whitelisted;
    no proxy needed).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.olx_account = cls.env["lead.olx.account"].sudo().create(
            {
                "name": f"Mock OLX Account {cls.suffix}",
                "login": f"9200000001_{cls.suffix}",
                "sequence": 10,
                "password": "MockPass@123",
            }
        )
        # Ensure no proxy so the code paths match production
        cls.env["ir.config_parameter"].sudo().set_param("olx.socks_proxy", "")

    def setUp(self):
        super().setUp()
        # Deactivate all accounts except the test account so that
        # _cron_rotate_olx_accounts and _get_next_account always pick self.olx_account.
        # The 15 accounts seeded by olx_accounts_data.xml all have last_fetch_at=NULL
        # and take ordering priority without this guard.
        self._other_accounts = self.env["lead.olx.account"].sudo().search([
            ("id", "!=", self.olx_account.id),
            ("active", "=", True),
        ])
        self._other_accounts.sudo().write({"active": False})

    def _reset_account(self, failures=0, active=True, last_fetch_at=False):
        """Reset account state between tests."""
        self.olx_account.sudo().write(
            {
                "consecutive_failures": failures,
                "active": active,
                "last_fetch_at": last_fetch_at,
                "last_error": False,
            }
        )

    # --- _api_fetch_olx ---

    def test_01_fetch_returns_parsed_leads_on_success(self):
        """Happy path: auth + leads endpoint both succeed → list of parsed dicts."""
        self._reset_account()
        with patch(f"{_MODULE_PATH}.requests.post", return_value=_make_response(_MOCK_AUTH_RESPONSE)), \
             patch(f"{_MODULE_PATH}.requests.get", return_value=_make_response(_MOCK_LEADS_RESPONSE)):
            leads = self.env["leads.new"]._api_fetch_olx(self.olx_account)

        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["phone"], "9876543210")
        self.assertEqual(leads[0]["project_name"], "3BHK Bopal Heights")

    def test_02_fetch_returns_empty_on_500(self):
        """
        OLX returns HTTP 500 when an account has no leads in the requested
        date range. The API must treat this as an empty result, not an error —
        so the method returns [] and does not raise.
        """
        self._reset_account()
        with patch(f"{_MODULE_PATH}.requests.post", return_value=_make_response(_MOCK_AUTH_RESPONSE)), \
             patch(f"{_MODULE_PATH}.requests.get", return_value=_make_response(status_code=500)):
            leads = self.env["leads.new"]._api_fetch_olx(self.olx_account)

        self.assertEqual(leads, [], "HTTP 500 from leads endpoint must return [] not raise")

    def test_03_fetch_raises_on_403_auth(self):
        """403 on the auth endpoint → RuntimeError (wrong credentials or IP block)."""
        self._reset_account()
        with patch(f"{_MODULE_PATH}.requests.post", return_value=_make_response(status_code=403)):
            with self.assertRaises(RuntimeError):
                self.env["leads.new"]._api_fetch_olx(self.olx_account)

    def test_04_fetch_raises_on_missing_password(self):
        """
        Account with no stored password → ValueError before any HTTP call.
        Verifies that the password check happens before the network request.
        """
        no_pw_account = self.env["lead.olx.account"].sudo().create(
            {
                "name": f"No PW Account {self.suffix}",
                "login": f"9200000099_{self.suffix}",
                "sequence": 99,
                # No password written intentionally
            }
        )
        with patch(f"{_MODULE_PATH}.requests.post") as mock_post:
            with self.assertRaises(ValueError):
                self.env["leads.new"]._api_fetch_olx(no_pw_account)
            mock_post.assert_not_called()

    def test_05_fetch_raises_when_auth_response_missing_token(self):
        """
        Auth returns HTTP 200 but the JSON body has no access_token key.
        This happens when OLX changes its response schema. Must raise RuntimeError.
        """
        self._reset_account()
        with patch(f"{_MODULE_PATH}.requests.post", return_value=_make_response({"unexpected_key": "value"})):
            with self.assertRaises(RuntimeError):
                self.env["leads.new"]._api_fetch_olx(self.olx_account)

    def test_06_pagination_fetches_all_pages(self):
        """
        When the first page returns totalPages=2, the leads URL is called
        exactly twice — once for each page.
        """
        self._reset_account()
        page1 = {
            "data": {
                "leads": [{"phoneNumber": "9111111111", "name": "P1", "adId": "1"}],
                "ads": [],
            },
            "pagination": {"totalPages": 2},
        }
        page2 = {
            "data": {
                "leads": [{"phoneNumber": "9222222222", "name": "P2", "adId": "2"}],
                "ads": [],
            },
            "pagination": {"totalPages": 2},
        }
        with patch(f"{_MODULE_PATH}.requests.post", return_value=_make_response(_MOCK_AUTH_RESPONSE)), \
             patch(f"{_MODULE_PATH}.requests.get", side_effect=[_make_response(page1), _make_response(page2)]) as mock_get:
            leads = self.env["leads.new"]._api_fetch_olx(self.olx_account)

        self.assertEqual(len(leads), 2)
        self.assertEqual(mock_get.call_count, 2, "Must call leads URL once per page")

    # --- _cron_rotate_olx_accounts ---

    def test_07_cron_creates_leads_from_fetched_data(self):
        """Cron creates a leads.new record for each OLX lead returned by the API."""
        self._reset_account()
        with patch(f"{_MODULE_PATH}.requests.post", return_value=_make_response(_MOCK_AUTH_RESPONSE)), \
             patch(f"{_MODULE_PATH}.requests.get", return_value=_make_response(_MOCK_LEADS_RESPONSE)):

            before_count = self.env["leads.new"].sudo().search_count(
                [("source_id", "=", self.source_olx.id)]
            )
            self.env["leads.new"]._cron_rotate_olx_accounts()
            after_count = self.env["leads.new"].sudo().search_count(
                [("source_id", "=", self.source_olx.id)]
            )

        self.assertGreater(
            after_count,
            before_count,
            "Cron must create new leads.new records from the OLX API response",
        )

    def test_08_cron_skips_duplicate_leads(self):
        """
        Running the cron twice with the same OLX response does not create
        a second lead for the same phone + portal_property_id combination.
        """
        self._reset_account()
        with patch(f"{_MODULE_PATH}.requests.post", return_value=_make_response(_MOCK_AUTH_RESPONSE)), \
             patch(f"{_MODULE_PATH}.requests.get", return_value=_make_response(_MOCK_LEADS_RESPONSE)):
            self.env["leads.new"]._cron_rotate_olx_accounts()

        count_after_first = self.env["leads.new"].sudo().search_count(
            [("source_id", "=", self.source_olx.id)]
        )

        # Reset so this account is picked again
        self._reset_account()
        with patch(f"{_MODULE_PATH}.requests.post", return_value=_make_response(_MOCK_AUTH_RESPONSE)), \
             patch(f"{_MODULE_PATH}.requests.get", return_value=_make_response(_MOCK_LEADS_RESPONSE)):
            self.env["leads.new"]._cron_rotate_olx_accounts()

        count_after_second = self.env["leads.new"].sudo().search_count(
            [("source_id", "=", self.source_olx.id)]
        )

        self.assertEqual(
            count_after_first,
            count_after_second,
            "Duplicate lead (same phone + portal_property_id within 30 days) must be skipped",
        )

    def test_09_cron_records_failure_on_auth_error(self):
        """Auth failure increments consecutive_failures on the account record."""
        self._reset_account(failures=0)
        with patch(f"{_MODULE_PATH}.requests.post", return_value=_make_response(status_code=403)):
            self.env["leads.new"]._cron_rotate_olx_accounts()

        self.assertGreater(
            self.olx_account.consecutive_failures,
            0,
            "Auth failure must increment consecutive_failures on the account",
        )

    def test_10_cron_records_success_after_fetch(self):
        """
        After a successful cron run consecutive_failures is 0
        and last_fetch_at is populated.
        """
        self._reset_account(failures=2)
        with patch(f"{_MODULE_PATH}.requests.post", return_value=_make_response(_MOCK_AUTH_RESPONSE)), \
             patch(f"{_MODULE_PATH}.requests.get", return_value=_make_response(_MOCK_LEADS_RESPONSE)):
            self.env["leads.new"]._cron_rotate_olx_accounts()

        self.assertEqual(
            self.olx_account.consecutive_failures,
            0,
            "Successful cron run must reset consecutive_failures to 0",
        )
        self.assertIsNotNone(
            self.olx_account.last_fetch_at,
            "Successful cron run must set last_fetch_at",
        )

    def test_11_cron_exits_cleanly_with_no_active_accounts(self):
        """
        Cron must return silently (no exception) when there are no active
        OLX accounts — e.g. all accounts are auto-disabled after too many
        failures.
        """
        all_active = self.env["lead.olx.account"].sudo().search([("active", "=", True)])
        all_active.sudo().write({"active": False})
        try:
            self.env["leads.new"]._cron_rotate_olx_accounts()  # Must not raise
        finally:
            all_active.sudo().write({"active": True})


# ---------------------------------------------------------------------------
# E. PropertyPortalListingLeadRelink
# ---------------------------------------------------------------------------


@tagged("post_install", "-at_install")
class TestPortalListingRelink(PortalLeadTestCase):
    """
    Tests for PropertyPortalListingLeadRelink — the write/create hook on
    property.portal.listing that retroactively links orphaned leads to a
    property and reassigns their RM.

    Scenario tested: a lead arrives via the OLX cron before anyone has added
    the ad's ID to a property.portal.listing record. The lead lands with
    property_base_id=False and is routed to the source's fallback RM. Later,
    an operator adds the listing — at that point the lead must be updated.

    Each test uses a unique ad_id derived from cls.suffix to prevent cross-test
    interference. 'late_prop' is a fresh property with no listings so the
    "create listing" trigger is observable.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.late_prop = cls.env["property.base"].sudo().create(
            {
                "property_tag": f"LATE-PROP-{cls.suffix}",
                "name": f"Late Listing Property {cls.suffix}",
                "prop_id": f"LP{cls.suffix}",
                "bedroom_count": 2,
                "location": "Test Location",
                "city": "Test City",
                "rm_user_id": cls.rm_user.id,
                "is_active": True,
            }
        )

    def _unlinked_olx_lead(self, ad_id, phone_suffix="00"):
        """
        Create an OLX leads.new record with no property_base_id.
        Simulates a lead that arrived before its ad ID was added to any listing.
        """
        return self.env["leads.new"].with_context(automated_lead_creation=True).create(
            {
                "name": f"Unlinked OLX Lead {ad_id}",
                "phone": f"9800{phone_suffix}{self.suffix[-4:]}",
                "source_id": self.source_olx.id,
                "portal_property_id": ad_id,
                "state": "new",
            }
        )

    def test_01_creating_listing_relinks_unlinked_leads(self):
        """
        A lead that arrived before any portal listing existed is linked to the
        property and reassigned to the property's RM when the listing is created.
        """
        ad_id = f"LATE_A_{self.suffix}"
        lead = self._unlinked_olx_lead(ad_id)
        self.assertFalse(lead.property_base_id, "Pre-condition: lead must have no property")

        self.late_prop.sudo().write(
            {
                "portal_listing_ids": [
                    (0, 0, {"portal_name": "OLX", "portal_listing_id": ad_id, "active": True})
                ]
            }
        )
        lead.invalidate_recordset()

        self.assertEqual(
            lead.property_base_id.id,
            self.late_prop.id,
            "Lead must be linked to property after listing is created",
        )
        self.assertEqual(
            lead.user_id.id,
            self.rm_user.id,
            "Lead must be assigned to property's RM after relink",
        )

    def test_02_correcting_listing_id_relinks_leads(self):
        """
        When an existing listing's portal_listing_id is corrected to match a
        lead's portal_property_id, that lead gets retroactively relinked.
        """
        ad_id_wrong = f"LATE_B_WRONG_{self.suffix}"
        ad_id_correct = f"LATE_B_CORRECT_{self.suffix}"
        lead = self._unlinked_olx_lead(ad_id_correct, phone_suffix="11")

        # Create listing with an incorrect ID first
        listing = self.env["property.portal.listing"].sudo().create(
            {
                "property_base_id": self.late_prop.id,
                "portal_name": "OLX",
                "portal_listing_id": ad_id_wrong,
                "active": True,
            }
        )
        lead.invalidate_recordset()
        self.assertFalse(
            lead.property_base_id,
            "Lead must not be linked while listing ID is wrong",
        )

        # Correct the ID — relink must fire
        listing.sudo().write({"portal_listing_id": ad_id_correct})
        lead.invalidate_recordset()

        self.assertEqual(
            lead.property_base_id.id,
            self.late_prop.id,
            "Lead must be linked after listing ID is corrected",
        )

    def test_03_already_linked_leads_are_not_overwritten(self):
        """
        Leads that already have a property_base_id must NOT be touched by
        the relink trigger — the search domain includes (property_base_id=False).
        """
        ad_id = f"LATE_C_{self.suffix}"

        linked_lead = self.env["leads.new"].with_context(automated_lead_creation=True).create(
            {
                "name": "Already Linked Lead",
                "phone": "9955551234",
                "source_id": self.source_olx.id,
                "portal_property_id": ad_id,
                "property_base_id": self.test_property.id,  # already linked
                "state": "assigned",
                "user_id": self.rm_user.id,
            }
        )
        original_property_id = linked_lead.property_base_id.id

        # Adding the listing on a DIFFERENT property must not override the existing link
        self.late_prop.sudo().write(
            {
                "portal_listing_ids": [
                    (0, 0, {"portal_name": "OLX", "portal_listing_id": ad_id, "active": True})
                ]
            }
        )
        linked_lead.invalidate_recordset()

        self.assertEqual(
            linked_lead.property_base_id.id,
            original_property_id,
            "A lead with an existing property link must not be overwritten by relink",
        )

    def test_04_all_unlinked_leads_for_same_id_are_relinked(self):
        """
        When multiple unlinked leads share the same portal_property_id, all of
        them are relinked and reassigned in a single operation.
        """
        ad_id = f"LATE_D_{self.suffix}"
        lead1 = self._unlinked_olx_lead(ad_id, phone_suffix="21")
        lead2 = self._unlinked_olx_lead(ad_id, phone_suffix="22")

        self.late_prop.sudo().write(
            {
                "portal_listing_ids": [
                    (0, 0, {"portal_name": "OLX", "portal_listing_id": ad_id, "active": True})
                ]
            }
        )
        lead1.invalidate_recordset()
        lead2.invalidate_recordset()

        self.assertEqual(lead1.property_base_id.id, self.late_prop.id)
        self.assertEqual(lead2.property_base_id.id, self.late_prop.id)
        self.assertEqual(lead1.user_id.id, self.rm_user.id)
        self.assertEqual(lead2.user_id.id, self.rm_user.id)

    def test_05_relink_process_notes_records_event(self):
        """
        After relink, process_notes on the lead must contain the auto-relink
        audit message so operators can trace why an assignment changed.
        """
        ad_id = f"LATE_E_{self.suffix}"
        lead = self._unlinked_olx_lead(ad_id, phone_suffix="31")

        self.late_prop.sudo().write(
            {
                "portal_listing_ids": [
                    (0, 0, {"portal_name": "OLX", "portal_listing_id": ad_id, "active": True})
                ]
            }
        )
        lead.invalidate_recordset()

        self.assertIn(
            "Auto-relinked",
            lead.process_notes or "",
            "Relink event must be recorded in process_notes for audit trail",
        )
