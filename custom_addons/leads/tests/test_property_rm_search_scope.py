"""`property.base._search` RM scoping must actually build a valid domain.

The override ANDed a `Domain` with a plain list.  `Domain.__and__` returns
NotImplemented for a list and `list` has no `__rand__`, so Python raised
``TypeError: unsupported operand type(s) for &: 'DomainBool' and 'list'`` —
every time the branch was reached, for every property RM.

It surfaced as a server error on "Search More" in the property dropdown of the
lead form, which is one of the few places that both carries the
``properties_module_view`` context and is used by non-manager RMs.
"""

from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install", "leads")
class TestPropertyRmSearchScope(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rm = new_test_user(
            cls.env, login="prop_rm_scope",
            groups="base.group_user,properties.group_property_rm",
            email="prop_rm_scope@example.com",
        )
        cls.other_rm = new_test_user(
            cls.env, login="prop_rm_scope_other",
            groups="base.group_user,properties.group_property_rm",
            email="prop_rm_scope_other@example.com",
        )
        Prop = cls.env["property.base"].sudo()
        cls.mine = Prop.create({
            "name": "Scope Mine", "prop_id": "SCOPE-MINE",
            "rm_user_id": cls.rm.id,
        })
        cls.theirs = Prop.create({
            "name": "Scope Theirs", "prop_id": "SCOPE-THEIRS",
            "rm_user_id": cls.other_rm.id,
        })

    def _as_rm(self):
        return self.env["property.base"].with_user(self.rm).with_context(
            properties_module_view=True)

    def test_empty_domain_does_not_raise(self):
        """The exact crash: an empty domain becomes DomainBool, then & [list]."""
        found = self._as_rm().search([])
        self.assertIn(self.mine, found)
        self.assertNotIn(self.theirs, found)

    def test_non_empty_domain_does_not_raise(self):
        found = self._as_rm().search([("name", "like", "Scope")])
        self.assertIn(self.mine, found)
        self.assertNotIn(self.theirs, found)

    def test_name_search_does_not_raise(self):
        """`Search More` goes through name_search, not search."""
        results = self._as_rm().name_search("Scope")
        ids = {r[0] for r in results}
        self.assertIn(self.mine.id, ids)
        self.assertNotIn(self.theirs.id, ids)

    def test_scoping_only_applies_inside_the_properties_context(self):
        """Without the context key the override's branch is skipped entirely.

        Asserted as "does not raise and returns rows", not as "sees every
        property": who sees what outside this branch is decided by record rules
        and ACLs that this override does not touch.
        """
        found = self.env["property.base"].sudo().search(
            [("name", "like", "Scope")])
        self.assertIn(self.mine, found)
        self.assertIn(self.theirs, found)
