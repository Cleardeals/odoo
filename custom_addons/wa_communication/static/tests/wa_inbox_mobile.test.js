/** @odoo-module */
/**
 * Hoot unit tests for the WaInbox phone layout.
 *
 * The desktop inbox puts up to five buttons in the thread header — Template,
 * View Lead, Create lead, Assign, Interakt — which overflows a 390px screen.
 * On a phone they collapse into Template plus one overflow, and the rest move
 * into a bottom sheet.
 *
 * What these tests pin is REACHABILITY, not looks: every action that exists on
 * a desktop must still be one or two taps away on a phone. A CSS-only fix can
 * hide a control and still pass a screenshot review; it cannot pass this.
 */
import { test, expect, describe, beforeEach } from "@odoo/hoot";
import { click, queryAll, queryAllTexts } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { EventBus } from "@odoo/owl";
import {
    defineModels, models, onRpc, mockService,
    mountWithCleanup, patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { user } from "@web/core/user";
import { WaInbox } from "@wa_communication/inbox/wa_inbox";

class WaConversation extends models.Model { _name = "wa.conversation"; }
class WaQuickReply extends models.Model { _name = "wa.quick.reply"; }
defineMailModels();
defineModels([WaConversation, WaQuickReply]);

const EMPTY_COUNTS = {
    ownership: { mine: 0, unassigned: 0, others: 0, all: 0 },
    needs_reply: 0, closing_soon: 0, rms: [],
};

const CONV = {
    id: 7,
    phone: "919023283799",
    lead_name: "Test Lead",
    lead_id: 42,
    assigned_user_name: "RM One",
    interakt_url: "https://app.interakt.ai/inbox/7",
    // Required: the list row renders a CdWindowBadge, whose `state` prop is a
    // non-optional String.
    window_state: "open",
};

/** The inbox payload shape, with one conversation in the list. */
function inboxPayload(over = {}) {
    return {
        rows: [{ ...CONV, unread_count: 0, last_message_at: false }],
        total: 1, counts: EMPTY_COUNTS, is_manager: false, ...over,
    };
}

/** get_thread's shape — enough for the header to render its actions. */
function threadPayload(over = {}) {
    return {
        conversation: { ...CONV, window_state: "open" },
        messages: [],
        can_send: true,
        ...over,
    };
}

/**
 * Force the small-screen branch.
 *
 * `env.isSmall` is a getter onto the ui service, so the size has to be faked at
 * the service rather than by resizing anything — mirrors Odoo's own
 * statusbar_field tests.
 */
function mockSmallScreen() {
    mockService("ui", (env) => {
        Object.defineProperty(env, "isSmall", { value: true });
        return { bus: new EventBus(), size: 0, isSmall: true,
                 activateElement() {}, deactivateElement() {} };
    });
}

async function ready() {
    await animationFrame();
    await animationFrame();
}

describe("WaInbox on a phone", () => {
    beforeEach(() => {
        onRpc("get_for_composer", () => []);
        onRpc("mark_as_read", () => true);
        mockService("cd_notification", {
            setActiveSuppressKey() {}, clearActiveSuppressKey() {},
        });
        mockService("bus_service", {
            addChannel() {}, deleteChannel() {}, subscribe() {},
            unsubscribe() {}, start() {},
        });
    });

    test("the thread header collapses to Template plus one overflow", async () => {
        mockSmallScreen();
        patchWithCleanup(user, { hasGroup: () => true });
        onRpc("get_inbox", () => inboxPayload({ is_manager: true }));
        onRpc("get_thread", () => threadPayload());

        await mountWithCleanup(WaInbox);
        await ready();
        await click(queryAll(".cd-conv-item")[0]);
        await animationFrame();

        // Exactly one actions row renders, and it holds two buttons — not the
        // five that overflow a phone header.
        expect(".wa-inbox__thread-actions").toHaveCount(1);
        expect(".wa-inbox__thread-actions .btn").toHaveCount(2);
        // Template stays out of the overflow: with the 24h window closed it is
        // the only way to reach the buyer, so it must never cost two taps.
        expect(queryAllTexts(".wa-inbox__thread-actions .btn")[0].includes("Template")).toBe(true);
    });

    test("every desktop action is still reachable through the sheet", async () => {
        mockSmallScreen();
        patchWithCleanup(user, { hasGroup: () => true });
        onRpc("get_inbox", () => inboxPayload({ is_manager: true }));
        onRpc("get_thread", () => threadPayload());

        await mountWithCleanup(WaInbox);
        await ready();
        await click(queryAll(".cd-conv-item")[0]);
        await animationFrame();

        expect(".cd-sheet").toHaveCount(0);

        // The overflow button is the second one in the row.
        await click(queryAll(".wa-inbox__thread-actions .btn")[1]);
        await animationFrame();

        expect(".cd-sheet").toHaveCount(1);
        const actions = queryAllTexts(".cd-sheet__action").join(" | ");
        expect(actions.includes("View lead")).toBe(true);
        expect(actions.includes("Assign to RM")).toBe(true);
        expect(actions.includes("Open in Interakt")).toBe(true);
    });

    test("the assign picker is a searchable sheet, not a dropdown", async () => {
        mockSmallScreen();
        patchWithCleanup(user, { hasGroup: () => true });
        onRpc("get_inbox", () => inboxPayload({ is_manager: true }));
        onRpc("get_thread", () => threadPayload());
        // openAssignPicker reads res.users directly, so intercept the read
        // rather than a named method.
        onRpc("search_read", () => [
            { id: 1, name: "Asha Patel" },
            { id: 2, name: "Vivek Vaghela" },
        ]);

        await mountWithCleanup(WaInbox);
        await ready();
        await click(queryAll(".cd-conv-item")[0]);
        await animationFrame();
        await click(queryAll(".wa-inbox__thread-actions .btn")[1]);
        await animationFrame();

        const assignRow = queryAll(".cd-sheet__action")
            .find(el => el.textContent.includes("Assign to RM"));
        await click(assignRow);
        await animationFrame();
        await animationFrame();

        // A search box, because scrolling a long RM list on a phone is worse
        // than typing three letters.
        expect(".cd-sheet__search input").toHaveCount(1);
        expect(queryAllTexts(".cd-sheet__action").join(" | ").includes("Asha Patel")).toBe(true);
    });

    test("the desktop layout is untouched", async () => {
        // No small-screen mock: the five-button row must survive this change.
        patchWithCleanup(user, { hasGroup: () => true });
        onRpc("get_inbox", () => inboxPayload({ is_manager: true }));
        onRpc("get_thread", () => threadPayload());

        await mountWithCleanup(WaInbox);
        await ready();
        await click(queryAll(".cd-conv-item")[0]);
        await animationFrame();

        expect(".wa-inbox__thread-actions").toHaveCount(1);
        // Template + View Lead + Assign + Interakt, all inline, no overflow.
        expect(".wa-inbox__thread-actions .btn").toHaveCount(4);
        expect(".cd-sheet").toHaveCount(0);
    });
});
