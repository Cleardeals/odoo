/** @odoo-module */
/**
 * Hoot unit tests for the WaInbox client action.
 *
 * Run in a browser at /odoo/web/tests (filter: "WaInbox").
 *
 * WaInbox is a heavy client action: it RPCs `get_inbox` / `get_for_composer`
 * on mount and injects orm + bus_service + cd_notification + notification +
 * action. We mock the RPCs (`onRpc`) and stub the two custom/bus services
 * (`mockService`) so the component mounts in isolation, then assert the
 * role-aware structure and the quick-filter wiring.
 */
import { test, expect, describe, beforeEach } from "@odoo/hoot";
import { click, queryAll } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    defineModels, models, onRpc, mockService,
    mountWithCleanup, patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { user } from "@web/core/user";
import { WaInbox } from "@wa_communication/inbox/wa_inbox";

// Mounting the full client action pulls services (bus/mail) that touch
// discuss.channel, so register the mail models too. Then add our own minimal
// models so call_kw resolves; the methods themselves are mocked via onRpc.
class WaConversation extends models.Model { _name = "wa.conversation"; }
class WaQuickReply extends models.Model { _name = "wa.quick.reply"; }
defineMailModels();
defineModels([WaConversation, WaQuickReply]);

const EMPTY_COUNTS = {
    ownership: { mine: 0, unassigned: 0, others: 0, all: 0 },
    needs_reply: 0, closing_soon: 0, rms: [],
};

function inboxPayload(over = {}) {
    return { rows: [], total: 0, counts: EMPTY_COUNTS, is_manager: false, ...over };
}

/** Flush the async onMounted chain (user.hasGroup → _loadInbox RPC). */
async function ready() {
    await animationFrame();
    await animationFrame();
}

describe("WaInbox", () => {
    beforeEach(() => {
        // The composer's quick replies and read-marking are irrelevant here.
        onRpc("get_for_composer", () => []);
        onRpc("mark_as_read", () => true);
        // Stub the services that would otherwise do bus/RPC work on start.
        mockService("cd_notification", {
            setActiveSuppressKey() {},
            clearActiveSuppressKey() {},
        });
        mockService("bus_service", {
            addChannel() {},
            deleteChannel() {},
            subscribe() {},
            unsubscribe() {},
            start() {},
        });
    });

    test("RM sees no ownership tabs, three quick chips, and the plain empty state", async () => {
        patchWithCleanup(user, { hasGroup: () => false });
        onRpc("get_inbox", () => inboxPayload({ is_manager: false }));

        await mountWithCleanup(WaInbox);
        await ready();

        expect(".wa-inbox__segments").toHaveCount(0);          // ownership tabs hidden
        expect(".wa-inbox__chip").toHaveCount(3);              // Needs reply / Closing soon / Filters
        // The inbox defaults to the WhatsApp-like "all chats" view, not a
        // needs-reply queue, so an empty list is just an empty inbox.
        expect(".wa-inbox__empty-title").toHaveText("No conversations here yet");
    });

    test("the caught-up state appears only once 'Needs reply' is on", async () => {
        patchWithCleanup(user, { hasGroup: () => false });
        const filterCalls = [];
        onRpc("get_inbox", ({ kwargs }) => {
            filterCalls.push(kwargs.filters);
            return inboxPayload({ is_manager: false });
        });

        await mountWithCleanup(WaInbox);
        await ready();

        await click(queryAll(".wa-inbox__chip")[0]);           // the "Needs reply" chip
        await animationFrame();

        // needs_reply is a queue, not a refinement — an empty result means the
        // queue is drained, not that the filters matched nothing.
        expect(filterCalls.at(-1).needs_reply).toBe(true);
        expect(".wa-inbox__empty-title").toHaveText("You're all caught up");
    });

    test("Manager sees the ownership tabs with live counts", async () => {
        patchWithCleanup(user, { hasGroup: () => true });
        onRpc("get_inbox", () => inboxPayload({
            total: 5, is_manager: true,
            counts: {
                ownership: { mine: 2, unassigned: 1, others: 2, all: 5 },
                needs_reply: 3, closing_soon: 1, rms: [],
            },
        }));

        await mountWithCleanup(WaInbox);
        await ready();

        expect(".wa-inbox__segments").toHaveCount(1);
        expect(".wa-inbox__segment").toHaveCount(3);            // Mine / Unassigned / All
        // Quick-chip counts come straight from the payload.
        expect(queryAll(".wa-inbox__chip-count")[0]).toHaveText("3");   // Needs reply
        expect(queryAll(".wa-inbox__chip-count")[1]).toHaveText("1");   // Closing soon
    });

    test("clicking 'Closing soon' reloads with window=closing_soon", async () => {
        patchWithCleanup(user, { hasGroup: () => true });
        const filterCalls = [];
        onRpc("get_inbox", ({ kwargs }) => {
            filterCalls.push(kwargs.filters);
            return inboxPayload({ is_manager: true, counts: { ...EMPTY_COUNTS, closing_soon: 2 } });
        });

        await mountWithCleanup(WaInbox);
        await ready();

        await click(queryAll(".wa-inbox__chip")[1]);           // the "Closing soon" chip
        await animationFrame();

        expect(filterCalls.at(-1).window).toBe("closing_soon");
    });

    test("the Filters chip opens the popover with a Reset control", async () => {
        patchWithCleanup(user, { hasGroup: () => true });
        onRpc("get_inbox", () => inboxPayload({ is_manager: true }));

        await mountWithCleanup(WaInbox);
        await ready();

        expect(".wa-inbox__filters-pop").toHaveCount(0);       // closed by default
        await click(queryAll(".wa-inbox__chip")[2]);           // "Filters"
        await animationFrame();
        expect(".wa-inbox__filters-pop").toHaveCount(1);
        expect(".wa-inbox__filters-reset").toHaveCount(1);
    });
});
