"""Gate this module's OWL/Hoot browser suites in CI.

See ``cleardeals_ui/tests/common.py`` for what the base case actually checks.
"""

import odoo.tests
from odoo.addons.cleardeals_ui.tests.common import HootSuiteCase


@odoo.tests.tagged("post_install", "-at_install")
class TestWaCommunicationJs(HootSuiteCase):
    MODULE = "wa_communication"
