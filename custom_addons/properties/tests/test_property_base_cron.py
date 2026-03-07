"""
Tests for the expiry-cleanup scheduled action on ``property.base``.

The cron ``_cron_cleanup_expired_properties()`` runs nightly and marks
properties inactive when their ``service_expiry_date`` is in the past
relative to the current date.

Covers:
  - Expired records (past date) → marked inactive
  - Active records (future date) → untouched
  - Boundary: expiry == today → remains active
  - Batch handling: multiple expired records in a single run
  - Already-inactive records are not modified (idempotency)
  - Records without a service_expiry_date are not affected
  - Cron is resilient to unexpected exceptions (does not propagate)
"""

from datetime import date, timedelta
from unittest.mock import patch

from odoo.tests import tagged

from .test_property_common import PropertyBaseTestCase


@tagged("post_install", "-at_install")
class TestPropertyBaseCron(PropertyBaseTestCase):
    """Scheduled-action tests for _cron_cleanup_expired_properties."""

    def _run_cron(self):
        """Invoke the cron and invalidate caches so reads see fresh DB state."""
        self.env["property.base"]._cron_cleanup_expired_properties()

    # ------------------------------------------------------------------ #
    # Core deactivation logic                                              #
    # ------------------------------------------------------------------ #

    def test_01_expired_yesterday_becomes_inactive(self):
        """A property whose service expires yesterday must be deactivated."""
        prop = self.make_property(
            is_active=True,
            service_expiry_date=date.today() - timedelta(days=1),
        )
        self._run_cron()
        prop.invalidate_recordset()
        self.assertFalse(prop.is_active)

    def test_02_expired_long_ago_becomes_inactive(self):
        """A property expired months ago must also be deactivated."""
        prop = self.make_property(
            is_active=True,
            service_expiry_date=date(2020, 1, 1),
        )
        self._run_cron()
        prop.invalidate_recordset()
        self.assertFalse(prop.is_active)

    # ------------------------------------------------------------------ #
    # Active records remain untouched                                      #
    # ------------------------------------------------------------------ #

    def test_03_future_expiry_stays_active(self):
        """A property with a future expiry date must not be touched by cron."""
        prop = self.make_property(
            is_active=True,
            service_expiry_date=date.today() + timedelta(days=30),
        )
        self._run_cron()
        prop.invalidate_recordset()
        self.assertTrue(prop.is_active)

    def test_04_far_future_expiry_stays_active(self):
        prop = self.make_property(
            is_active=True,
            service_expiry_date=date(2099, 12, 31),
        )
        self._run_cron()
        prop.invalidate_recordset()
        self.assertTrue(prop.is_active)

    # ------------------------------------------------------------------ #
    # Boundary condition: expiry == today                                  #
    # ------------------------------------------------------------------ #

    def test_05_expiry_today_remains_active(self):
        """The cron uses a strict less-than comparison: expiry < today.
        A property expiring today must remain active."""
        prop = self.make_property(
            is_active=True,
            service_expiry_date=date.today(),
        )
        self._run_cron()
        prop.invalidate_recordset()
        self.assertTrue(
            prop.is_active, "Expiry on today's date should not be deactivated"
        )

    # ------------------------------------------------------------------ #
    # Batch handling                                                       #
    # ------------------------------------------------------------------ #

    def test_06_batch_multiple_expired_all_deactivated(self):
        """Cron should handle deactivating multiple expired records at once."""
        props = [
            self.make_property(
                is_active=True, service_expiry_date=date.today() - timedelta(days=d)
            )
            for d in (1, 5, 10, 30, 365)
        ]
        self._run_cron()
        for prop in props:
            prop.invalidate_recordset()
            self.assertFalse(
                prop.is_active,
                f"Property expiring {prop.service_expiry_date} should be inactive",
            )

    def test_07_mixed_expiry_only_expired_deactivated(self):
        """Only expired records should be deactivated; active ones stay active."""
        expired = self.make_property(
            is_active=True,
            service_expiry_date=date.today() - timedelta(days=1),
        )
        active = self.make_property(
            is_active=True,
            service_expiry_date=date.today() + timedelta(days=1),
        )
        self._run_cron()

        expired.invalidate_recordset()
        active.invalidate_recordset()

        self.assertFalse(expired.is_active)
        self.assertTrue(active.is_active)

    # ------------------------------------------------------------------ #
    # Idempotency                                                          #
    # ------------------------------------------------------------------ #

    def test_08_already_inactive_not_modified(self):
        """Running cron on an already-inactive property should be a no-op."""
        prop = self.make_property(
            is_active=False,
            service_expiry_date=date.today() - timedelta(days=10),
        )
        self._run_cron()
        prop.invalidate_recordset()
        self.assertFalse(prop.is_active, "Should still be inactive — no change")

    def test_09_cron_idempotent_second_run(self):
        """Running the cron twice should not raise or change values further."""
        prop = self.make_property(
            is_active=True,
            service_expiry_date=date.today() - timedelta(days=1),
        )
        self._run_cron()
        prop.invalidate_recordset()
        self.assertFalse(prop.is_active)

        # Second run — should be a no-op and not raise
        self._run_cron()
        prop.invalidate_recordset()
        self.assertFalse(prop.is_active)

    # ------------------------------------------------------------------ #
    # Records without a service_expiry_date                               #
    # ------------------------------------------------------------------ #

    def test_10_no_expiry_date_record_not_deactivated(self):
        """A property with no service_expiry_date should be ignored by cron."""
        prop = self.make_property(is_active=True, service_expiry_date=False)
        self._run_cron()
        prop.invalidate_recordset()
        self.assertTrue(
            prop.is_active, "Properties without expiry date should not be deactivated"
        )

    # ------------------------------------------------------------------ #
    # resilience                                                           #
    # ------------------------------------------------------------------ #

    def test_11_cron_does_not_propagate_internal_errors(self):
        """The cron catches exceptions internally and must not let them bubble up."""
        with patch.object(
            type(self.env["property.base"]),
            "search",
            side_effect=Exception("Simulated DB failure"),
        ):
            try:
                self.env["property.base"]._cron_cleanup_expired_properties()
            except Exception as exc:  # noqa: BLE001
                self.fail(f"Cron should not propagate exceptions, got: {exc}")
