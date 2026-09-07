"""Gate the shared OWL component library's Hoot suites in CI.

``cleardeals_ui`` has no Python models, so nothing used to run for it at all.
Its components are consumed by every other custom addon, which makes an unrun
test suite here the most expensive one in the repo.
"""

import odoo.tests

from .common import HootSuiteCase


@odoo.tests.tagged("post_install", "-at_install")
class TestCleardealsUiJs(HootSuiteCase):
    MODULE = "cleardeals_ui"
