/** @odoo-module */
/**
 * Hoot unit tests for CdBottomSheet — the mobile replacement for an anchored
 * popover. See bottom_sheet.js for why phones get a sheet instead.
 */
import { test, expect, describe } from "@odoo/hoot";
import { click, queryAll } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, xml, useState } from "@odoo/owl";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { CdBottomSheet } from "@cleardeals_ui/components/bottom_sheet/bottom_sheet";

/** Host that owns the open/closed state, as every real caller does. */
class Host extends Component {
    static components = { CdBottomSheet };
    static props = {};
    static template = xml`
        <div>
            <t t-if="state.open">
                <CdBottomSheet title="'Filters'" onClose.bind="close">
                    <button class="cd-sheet__action test-row">A row</button>
                </CdBottomSheet>
            </t>
        </div>`;
    setup() { this.state = useState({ open: true }); }
    close() { this.state.open = false; }
}

describe("CdBottomSheet", () => {
    test("renders its title and slotted rows", async () => {
        await mountWithCleanup(Host);
        expect(".cd-sheet").toHaveCount(1);
        expect(".cd-sheet__title").toHaveText("Filters");
        expect(".test-row").toHaveCount(1);
    });

    test("the backdrop closes it", async () => {
        await mountWithCleanup(Host);
        await click(".cd-sheet__backdrop");
        await animationFrame();
        expect(".cd-sheet").toHaveCount(0);
    });

    test("a tap inside the sheet does not close it", async () => {
        // The whole point of the backdrop handler is that it must not fire for
        // clicks that bubble up from the sheet's own controls.
        await mountWithCleanup(Host);
        await click(queryAll(".test-row")[0]);
        await animationFrame();
        expect(".cd-sheet").toHaveCount(1);
    });

    test("the close button closes it", async () => {
        await mountWithCleanup(Host);
        await click(".cd-sheet__close");
        await animationFrame();
        expect(".cd-sheet").toHaveCount(0);
    });
});
