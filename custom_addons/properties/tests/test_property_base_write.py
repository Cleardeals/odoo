"""
Tests for the ``write()`` override on ``property.base``.

The override automatically synchronises ``is_active`` when
``service_expiry_date`` is changed:
  - Future expiry  → is_active becomes True
  - Past expiry    → is_active becomes False
  - Today expiry   → is_active becomes True (boundary: >= today)
  - Explicit is_active in the same write() call overrides the auto-logic
  - Clearing the date leaves is_active unchanged
  - Writing other fields with no expiry change does not touch is_active
"""

from datetime import date, timedelta

from odoo.tests import tagged

from .test_property_common import PropertyBaseTestCase


@tagged("post_install", "-at_install")
class TestPropertyBaseWrite(PropertyBaseTestCase):
    """write() override: is_active auto-sync with service_expiry_date."""

    # ------------------------------------------------------------------ #
    # Auto-sync: future expiry → active                                   #
    # ------------------------------------------------------------------ #

    def test_01_future_expiry_activates_record(self):
        """Writing a future service_expiry_date should set is_active=True."""
        prop = self.make_property(is_active=False, service_expiry_date=False)
        prop.write({"service_expiry_date": date.today() + timedelta(days=30)})
        self.assertTrue(prop.is_active)

    def test_02_far_future_expiry_activates_record(self):
        """A very distant future date should still activate the record."""
        prop = self.make_property(is_active=False, service_expiry_date=False)
        prop.write({"service_expiry_date": date(2099, 12, 31)})
        self.assertTrue(prop.is_active)

    # ------------------------------------------------------------------ #
    # Auto-sync: past expiry → inactive                                   #
    # ------------------------------------------------------------------ #

    def test_03_past_expiry_deactivates_record(self):
        """Writing a past service_expiry_date should set is_active=False."""
        prop = self.make_property(is_active=True)
        prop.write({"service_expiry_date": date.today() - timedelta(days=1)})
        self.assertFalse(prop.is_active)

    def test_04_older_past_expiry_deactivates_record(self):
        """Even a long-past expiry should deactivate."""
        prop = self.make_property(is_active=True)
        prop.write({"service_expiry_date": date(2020, 1, 1)})
        self.assertFalse(prop.is_active)

    # ------------------------------------------------------------------ #
    # Boundary: today == active                                            #
    # ------------------------------------------------------------------ #

    def test_05_today_expiry_keeps_active(self):
        """Expiry date of today is on the boundary and should remain active."""
        prop = self.make_property(is_active=False, service_expiry_date=False)
        prop.write({"service_expiry_date": date.today()})
        self.assertTrue(prop.is_active, "Expiry == today should be active (>= today)")

    # ------------------------------------------------------------------ #
    # Explicit is_active wins over auto-logic                             #
    # ------------------------------------------------------------------ #

    def test_06_explicit_is_active_true_overrides_past_expiry(self):
        """If caller provides is_active=True with a past expiry, that value wins."""
        prop = self.make_property(is_active=True)
        prop.write(
            {
                "service_expiry_date": date.today() - timedelta(days=10),
                "is_active": True,
            },
        )
        self.assertTrue(
            prop.is_active,
            "Explicit is_active=True should not be overridden by auto-logic",
        )

    def test_07_explicit_is_active_false_overrides_future_expiry(self):
        """If caller provides is_active=False with a future expiry, that value wins."""
        prop = self.make_property(is_active=True)
        prop.write(
            {
                "service_expiry_date": date.today() + timedelta(days=30),
                "is_active": False,
            },
        )
        self.assertFalse(
            prop.is_active,
            "Explicit is_active=False should not be overridden by auto-logic",
        )

    # ------------------------------------------------------------------ #
    # No expiry change → is_active untouched                              #
    # ------------------------------------------------------------------ #

    def test_08_write_other_field_does_not_change_is_active(self):
        """Writing a non-expiry field must not change is_active."""
        prop = self.make_property(is_active=True)
        prop.write({"city": "New City"})
        self.assertTrue(prop.is_active, "is_active should be unchanged")

    def test_09_write_pricing_does_not_change_is_active(self):
        prop = self.make_property(is_active=False, service_expiry_date=False)
        prop.write({"pricing": 99.0})
        self.assertFalse(prop.is_active)

    # ------------------------------------------------------------------ #
    # Clearing expiry date                                                 #
    # ------------------------------------------------------------------ #

    def test_10_clearing_expiry_date_leaves_is_active_unchanged(self):
        """Setting service_expiry_date=False should not trigger auto-sync."""
        prop = self.make_property(
            is_active=True,
            service_expiry_date=date.today() + timedelta(days=10),
        )
        prop.write({"service_expiry_date": False})
        # is_active untouched because expiry_val is falsy
        self.assertTrue(prop.is_active)

    # ------------------------------------------------------------------ #
    # Batch write across multiple records                                  #
    # ------------------------------------------------------------------ #

    def test_11_batch_write_with_future_expiry_activates_all(self):
        """write() on a recordset should activate every record in the set."""
        p1 = self.make_property(is_active=False, service_expiry_date=False)
        p2 = self.make_property(is_active=False, service_expiry_date=False)
        recordset = p1 | p2

        recordset.write({"service_expiry_date": date.today() + timedelta(days=60)})

        for rec in [p1, p2]:
            rec.invalidate_recordset()
            self.assertTrue(rec.is_active)

    def test_12_batch_write_with_past_expiry_deactivates_all(self):
        """write() on a recordset should deactivate every record in the set."""
        p1 = self.make_property(is_active=True)
        p2 = self.make_property(is_active=True)
        recordset = p1 | p2

        recordset.write({"service_expiry_date": date.today() - timedelta(days=5)})

        for rec in [p1, p2]:
            rec.invalidate_recordset()
            self.assertFalse(rec.is_active)
