/** @odoo-module */
/**
 * Hoot unit tests for CdWindowBadge — the 24h WhatsApp free-text window pill.
 *
 * Run in a browser at /odoo/web/tests (filter: "window badge").
 * Pure, prop-driven component — no services or mock server needed.
 */
import { test, expect, describe } from "@odoo/hoot";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { CdWindowBadge } from "@cleardeals_ui/index";

describe("CdWindowBadge", () => {
    /** Server datetime string (naive UTC, "YYYY-MM-DD HH:MM:SS") N hours from now. */
    function inHours(n) {
        return new Date(Date.now() + n * 3_600_000)
            .toISOString().replace("T", " ").slice(0, 19);
    }

    test("open window shows an unlocked badge with a countdown", async () => {
        await mountWithCleanup(CdWindowBadge, {
            props: { state: "open", windowExpiresAt: inHours(5) },
        });
        expect(".cd-window-badge--open").toHaveCount(1);
        expect(".cd-window-badge .fa-unlock").toHaveCount(1);
        expect(".cd-window-badge").toHaveText(/Open/);
    });

    test("closed window shows a locked 'Window Closed' badge", async () => {
        await mountWithCleanup(CdWindowBadge, { props: { state: "closed" } });
        expect(".cd-window-badge--closed").toHaveCount(1);
        expect(".cd-window-badge .fa-lock").toHaveCount(1);
        expect(".cd-window-badge").toHaveText("Window Closed");
    });

    test("closing_soon is treated as OPEN (unlocked), with its own modifier", async () => {
        // Regression guard for the redesign: the badge must not render
        // closing_soon as "closed".
        await mountWithCleanup(CdWindowBadge, {
            props: { state: "closing_soon", windowExpiresAt: inHours(2) },
        });
        expect(".cd-window-badge--closing_soon").toHaveCount(1);
        expect(".cd-window-badge .fa-unlock").toHaveCount(1);   // open, not locked
        expect(".cd-window-badge .fa-lock").toHaveCount(0);
    });
});
