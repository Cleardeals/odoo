/** @odoo-module */
/**
 * Hoot unit tests for the CdChatComposer phone layout.
 *
 * Two behaviours are pinned here because both were reachability bugs, not
 * cosmetic ones:
 *
 *   1. Four 30px attach buttons crowd the input off a 390px screen, so they
 *      collapse into one sheet trigger. The four kinds must still be reachable.
 *   2. When the 24h window is closed, a template is the only way to reach the
 *      buyer — so the notice that says so now offers the template picker
 *      inline. On the lead form the phone had no other route to it at all.
 */
import { test, expect, describe } from "@odoo/hoot";
import { click, queryAll, queryAllTexts } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { EventBus } from "@odoo/owl";
import { mockService, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { CdChatComposer } from "@cleardeals_ui/components/chat_composer/chat_composer";

/** Force the small-screen branch — `env.isSmall` reads the ui service. */
function mockSmallScreen() {
    mockService("ui", (env) => {
        Object.defineProperty(env, "isSmall", { value: true });
        return { bus: new EventBus(), size: 0, isSmall: true,
                 activateElement() {}, deactivateElement() {} };
    });
}

async function mountComposer(props = {}) {
    await mountWithCleanup(CdChatComposer, {
        props: { windowState: "open", onSend: () => {}, ...props },
    });
}

describe("CdChatComposer on a phone", () => {
    test("the four attach buttons collapse into one sheet trigger", async () => {
        mockSmallScreen();
        await mountComposer();

        // Quick replies + one paperclip, rather than quick replies + four.
        expect(".cd-chat-composer__attach-btn").toHaveCount(2);

        await click(queryAll(".cd-chat-composer__attach-btn")[1]);
        await animationFrame();

        const rows = queryAllTexts(".cd-sheet__action").join(" | ");
        expect(rows.includes("Photo")).toBe(true);
        expect(rows.includes("Video")).toBe(true);
        expect(rows.includes("Document")).toBe(true);
        expect(rows.includes("Interactive list")).toBe(true);
    });

    test("the desktop row is untouched", async () => {
        await mountComposer();
        // Quick replies + image + video + document + list.
        expect(".cd-chat-composer__attach-btn").toHaveCount(5);
        expect(".cd-sheet").toHaveCount(0);
    });

    test("a closed window offers the template picker inline", async () => {
        let opened = 0;
        await mountComposer({
            windowState: "closed",
            onOpenTemplates: () => { opened++; },
        });

        expect(".cd-chat-composer__closed-notice").toHaveCount(1);
        await click(".cd-chat-composer__closed-cta");
        expect(opened).toBe(1);
    });

    test("without a template callback the notice stays a plain warning", async () => {
        // The inline button is opt-in: a caller with no picker must not render
        // a button that leads nowhere.
        await mountComposer({ windowState: "closed" });
        expect(".cd-chat-composer__closed-notice").toHaveCount(1);
        expect(".cd-chat-composer__closed-cta").toHaveCount(0);
    });
});
