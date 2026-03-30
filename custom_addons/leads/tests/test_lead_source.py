# -*- coding: utf-8 -*-
from time import time

import psycopg2

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestLeadSource(TransactionCase):
    """Tests for lead.source and lead.source.category behavior."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.suffix = str(int(time()))

        cls.category_model = cls.env["lead.source.category"]
        cls.source_model = cls.env["lead.source"]
        cls.lead_model = cls.env["leads.new"]

        cls.portal_category = cls.env.ref("leads.lead_source_category_portal")

        cls.manual_category = cls.category_model.create(
            {
                "name": f"Manual Category {cls.suffix}",
                "code": f"manual_category_{cls.suffix}",
                "source_type": "manual",
            },
        )

    def test_01_create_manual_source(self):
        source = self.source_model.create(
            {
                "name": f"Manual Source {self.suffix}",
                "category_id": self.manual_category.id,
            },
        )

        self.assertEqual(source.source_type, "manual")
        self.assertFalse(source.portal_code)

    def test_02_portal_source_requires_portal_code(self):
        with self.assertRaises(ValidationError):
            self.source_model.create(
                {
                    "name": f"Portal Missing Code {self.suffix}",
                    "category_id": self.portal_category.id,
                },
            )

    def test_03_manual_source_rejects_portal_code(self):
        with self.assertRaises(ValidationError):
            self.source_model.create(
                {
                    "name": f"Manual Has Portal Code {self.suffix}",
                    "category_id": self.manual_category.id,
                    "portal_code": "OLX",
                },
            )

    def test_04_unique_category_code(self):
        category_vals = {
            "name": f"Unique Category {self.suffix}",
            "code": f"unique_category_{self.suffix}",
            "source_type": "manual",
        }
        self.category_model.create(category_vals)

        with mute_logger("odoo.sql_db"), self.assertRaises(psycopg2.IntegrityError):
            self.category_model.create(
                {
                    "name": f"Duplicate Unique Category {self.suffix}",
                    "code": f"unique_category_{self.suffix}",
                    "source_type": "manual",
                },
            )

    def test_05_unique_source_name(self):
        source_vals = {
            "name": f"Unique Source {self.suffix}",
            "category_id": self.manual_category.id,
        }
        self.source_model.create(source_vals)

        with mute_logger("odoo.sql_db"), self.assertRaises(psycopg2.IntegrityError):
            self.source_model.create(
                {
                    "name": f"Unique Source {self.suffix}",
                    "category_id": self.manual_category.id,
                },
            )

    def test_06_get_or_create_source_reuses_existing(self):
        existing = self.source_model.create(
            {
                "name": f"Existing Source {self.suffix}",
                "category_id": self.manual_category.id,
            },
        )

        reused = self.lead_model._get_or_create_source(
            f"Existing Source {self.suffix}",
            source_type="manual",
        )

        self.assertEqual(reused.id, existing.id)
        self.assertEqual(
            self.source_model.search_count([("name", "=", existing.name)]),
            1,
        )

    def test_07_get_or_create_source_creates_portal_with_canonical_code(self):
        source = self.lead_model._get_or_create_source(
            f"magicbricks.com {self.suffix}",
            source_type="portal",
        )

        # Canonical lookup uses exact source_name; append suffix means this is not canonical
        # and should fallback to manual source.
        self.assertEqual(source.source_type, "manual")
        self.assertFalse(source.portal_code)

        canonical_source = self.lead_model._get_or_create_source(
            "magicbricks.com",
            source_type="portal",
        )
        self.assertEqual(canonical_source.source_type, "portal")
        self.assertEqual(canonical_source.portal_code, "MagicBricks")

    def test_08_get_or_create_source_unknown_portal_becomes_manual(self):
        source = self.lead_model._get_or_create_source(
            f"Flyer Campaign {self.suffix}",
            source_type="portal",
        )

        self.assertEqual(source.source_type, "manual")
        self.assertFalse(source.portal_code)

    def test_09_canonical_portal_code_mapping(self):
        self.assertEqual(self.lead_model._canonical_portal_code("housing"), "Housing.com")
        self.assertEqual(
            self.lead_model._canonical_portal_code("MagicBricks.com"),
            "MagicBricks",
        )
        self.assertIsNone(self.lead_model._canonical_portal_code("Pamphlet"))

    def test_10_lead_create_requires_source(self):
        with self.assertRaises(ValidationError):
            self.lead_model.with_context(automated_lead_creation=True).create(
                {
                    "name": f"Lead Without Source {self.suffix}",
                    "phone": "9876543210",
                },
            )

    def test_11_lead_create_autofills_source_from_portal_name(self):
        lead = self.lead_model.with_context(automated_lead_creation=True).create(
            {
                "name": f"Lead Portal Name {self.suffix}",
                "phone": "9876543211",
                "portal_name": "MagicBricks",
            },
        )

        self.assertTrue(lead.source_id)
        self.assertEqual(lead.source_id.name, "MagicBricks")
        self.assertEqual(lead.source_type, "portal")

    def test_12_manual_source_lead_assigns_creator(self):
        source = self.lead_model._get_or_create_source(
            f"Reference Source {self.suffix}",
            source_type="manual",
        )

        lead = self.lead_model.create(
            {
                "name": f"Manual Source Lead {self.suffix}",
                "phone": "9876543212",
                "source_id": source.id,
            },
        )

        self.assertEqual(lead.source_type, "manual")
        self.assertEqual(lead.state, "assigned")
        self.assertEqual(lead.user_id, self.env.user)
        self.assertTrue(lead.message_ids)
        self.assertIn("Manual Lead Created", lead.message_ids[0].body or "")

    def test_13_is_portal_source_handles_stale_lead_source_type(self):
        source = self.lead_model._get_or_create_source(
            "MagicBricks",
            source_type="portal",
        )
        lead = self.lead_model.with_context(automated_lead_creation=True).create(
            {
                "name": f"Portal Visibility Lead {self.suffix}",
                "phone": "9876543213",
                "source_id": source.id,
                "portal_property_id": f"MB-{self.suffix}",
            },
        )

        self.assertTrue(lead.is_portal_source)

        # Simulate migrated rows where stored related source_type is stale/null.
        self.env.cr.execute(
            "UPDATE leads_new SET source_type = 'manual' WHERE id = %s",
            (lead.id,),
        )
        self.env.cr.execute(
            "SELECT source_type FROM leads_new WHERE id = %s",
            (lead.id,),
        )
        self.assertEqual(self.env.cr.fetchone()[0], "manual")

        lead.invalidate_recordset(["is_portal_source"])
        self.assertTrue(lead.is_portal_source)

    def test_14_is_portal_source_false_for_manual(self):
        source = self.lead_model._get_or_create_source(
            f"Manual Visibility Source {self.suffix}",
            source_type="manual",
        )
        lead = self.lead_model.with_context(automated_lead_creation=True).create(
            {
                "name": f"Manual Visibility Lead {self.suffix}",
                "phone": "9876543214",
                "source_id": source.id,
            },
        )

        self.assertFalse(lead.is_portal_source)

    def test_15_sync_portal_default_rm_does_not_override_manual(self):
        users = self.env["res.users"].with_context(no_reset_password=True)
        group_user = self.env.ref("base.group_user")

        mapped_user = users.create(
            {
                "name": "Purvi Desai",
                "login": f"purvi_desai_{self.suffix}",
                "email": f"purvi_desai_{self.suffix}@example.com",
                "groups_id": [(6, 0, [group_user.id])],
            }
        )
        manual_user = users.create(
            {
                "name": f"Manual RM {self.suffix}",
                "login": f"manual_rm_{self.suffix}",
                "email": f"manual_rm_{self.suffix}@example.com",
                "groups_id": [(6, 0, [group_user.id])],
            }
        )

        source = self.env.ref("leads.lead_source_99acres")
        source.write({"default_rm_user_id": manual_user.id})

        self.source_model._sync_portal_default_rms()
        source.invalidate_recordset(["default_rm_user_id"])

        self.assertEqual(source.default_rm_user_id, manual_user)
        self.assertNotEqual(source.default_rm_user_id, mapped_user)
