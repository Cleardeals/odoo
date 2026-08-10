"""Shared harness for driving a module's OWL/Hoot suites in CI.

``static/tests/*.test.js`` files only ever ran when a developer opened
``/web/tests`` by hand, so a drifted assertion could sit broken indefinitely.
:class:`HootSuiteCase` runs the same page headlessly, the way
``addons/web/tests/test_js.py`` does for core.

Every custom addon that ships ``*.test.js`` should subclass it::

    @odoo.tests.tagged("post_install", "-at_install")
    class TestMyModuleJs(HootSuiteCase):
        MODULE = "my_module"

This module carries no tests of its own and is deliberately not imported by
``tests/__init__.py``.
"""

import unittest
from pathlib import Path

import odoo.tests
from odoo.modules import Manifest
from odoo.tests import common as test_common
from odoo.tools.misc import file_path


def hoot_error_checker(message):
    """Only stop the browser on errors Hoot did not already account for.

    Hoot reports its own test failures by *withholding* the success signal, so
    its ``[HOOT]``-prefixed console errors must not abort the run early — we
    want the full failure report in the log first. Anything else (a missing
    dependency, a template compile error) is fatal immediately.
    """
    return "[HOOT]" not in message


class HootSuiteCase(odoo.tests.HttpCase):
    """Runs ``/web/tests`` filtered to :attr:`MODULE` in headless Chrome."""

    MODULE = None

    # Subclasses add no test methods of their own, and Odoo's loader only
    # collects methods found in a test class's own __dict__ (see
    # odoo/tests/loader.py::get_module_test_cases) — without this the whole
    # case is collected as zero tests and silently does nothing.
    allow_inherited_tests_method = True

    #: Hoot kills the run itself at `timeout` ms per test; this is the outer
    #: bound on the whole browser session.
    BROWSER_TIMEOUT = 600

    def test_browser_harness_is_available(self):
        """Turn ``browser_js``'s two silent skips into hard failures.

        A missing ``websocket-client`` or Chrome makes ``browser_js`` raise
        ``SkipTest``, and a skipped test does not fail the build — which is
        exactly how a browser suite goes quiet without anyone noticing.
        """
        self.assertIsNotNone(
            test_common.websocket,
            "websocket-client is not installed, so browser_js would silently "
            "skip. It is pinned in requirements.txt — rebuild the Docker image.",
        )
        try:
            test_common._find_executable()
        except unittest.SkipTest:
            self.fail(
                "No chrome/chromium on PATH, so browser_js would silently skip. "
                "The Dockerfile installs `chromium` — rebuild the Docker image."
            )

    def test_unit_tests_are_registered(self):
        """Guard the guard.

        Hoot reports success when its filter matches *nothing*, so a missing or
        unbundled test directory would make :meth:`test_hoot_suite` pass while
        checking nothing at all.
        """
        test_dir = Path(file_path(self.MODULE)) / "static" / "tests"
        self.assertTrue(
            sorted(test_dir.glob("**/*.test.js")),
            f"No *.test.js under {test_dir} — the Hoot suite would pass vacuously.",
        )

        bundle = Manifest.for_addon(self.MODULE).get("assets", {})
        entries = bundle.get("web.assets_unit_tests", [])
        self.assertTrue(
            any(entry.startswith(f"{self.MODULE}/static/tests") for entry in entries),
            f"{self.MODULE} ships *.test.js files but does not add them to "
            "'web.assets_unit_tests', so /web/tests would never load them.",
        )

    @odoo.tests.no_retry
    def test_hoot_suite(self):
        try:
            self.browser_js(
                "/web/tests?headless&loglevel=2&preset=desktop&timeout=15000"
                f"&filter={self.MODULE}",
                "",
                "",
                login="admin",
                timeout=self.BROWSER_TIMEOUT,
                success_signal="[HOOT] Test suite succeeded",
                error_checker=hoot_error_checker,
            )
        except unittest.SkipTest as exc:
            # browser_js skips whenever the harness itself is broken — no
            # devtools port, a dead Chrome, a missing dependency. A skip is
            # green, so an unusable browser would quietly ungate every suite
            # here. Only a real test result is allowed to be green.
            self.fail(f"Browser harness unusable, refusing to skip the JS suite: {exc}")
