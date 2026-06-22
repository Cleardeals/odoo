/** @odoo-module */
/**
 * Hoot unit tests for CdConversationListItem — one row in the inbox list.
 *
 * Run in a browser at /odoo/web/tests (filter: "conversation list item").
 * Prop-driven; the only child is CdWindowBadge, so no services/mock server.
 */
import { test, expect, describe } from "@odoo/hoot";
import { click } from "@odoo/hoot-dom";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { CdConversationListItem } from "@cleardeals_ui/index";

describe("CdConversationListItem", () => {
    function makeRow(overrides = {}) {
        return {
            id: 1,
            lead_id: 10,
            lead_name: "Asha Buyer",
            phone: "919812345678",
            last_message: "Is the flat still available?",
            last_message_at: new Date().toISOString(),
            unread_count: 0,
            window_state: "open",
            window_expires_at: null,
            assigned_user_name: "RM One",
            ...overrides,
        };
    }

    async function mountRow(props = {}) {
        await mountWithCleanup(CdConversationListItem, {
            props: { conversation: makeRow(props.conversation), selected: false,
                     onSelect: () => {}, ...props },
        });
    }

    test("renders lead name and message preview", async () => {
        await mountRow();
        expect(".cd-conv-item__name").toHaveText("Asha Buyer");
        expect(".cd-conv-item__preview").toHaveText("Is the flat still available?");
    });

    test("falls back to phone when there is no lead name", async () => {
        await mountRow({ conversation: { lead_name: null } });
        expect(".cd-conv-item__name").toHaveText("919812345678");
    });

    test("shows the unread badge and unread styling only when unread", async () => {
        await mountRow({ conversation: { unread_count: 3 } });
        expect(".cd-conv-item__badge").toHaveText("3");
        expect(".cd-conv-item--unread").toHaveCount(1);
    });

    test("renders the SLA waiting chip with its tone", async () => {
        await mountRow({
            conversation: { unread_count: 1 },
            waiting: { label: "4h 10m", tone: "bad" },
        });
        expect(".cd-conv-item__waiting--bad").toHaveCount(1);
        expect(".cd-conv-item__waiting").toHaveText(/4h 10m/);
    });

    test("an unassigned row offers Claim; an owned row offers Reassign", async () => {
        // Unassigned → Claim
        await mountRow({
            conversation: { assigned_user_name: null },
            onClaim: () => {}, onAssign: () => {},
        });
        expect(".cd-conv-item__action-btn--claim").toHaveCount(1);

        // Owned → no Claim, the reassign action instead
        await mountRow({ onClaim: () => {}, onAssign: () => {} });
        expect(".cd-conv-item__action-btn--claim").toHaveCount(0);
        expect(".fa-exchange").toHaveCount(1);
    });

    test("clicking the row fires onSelect", async () => {
        let selected = false;
        await mountWithCleanup(CdConversationListItem, {
            props: { conversation: makeRow(), selected: false,
                     onSelect: () => { selected = true; } },
        });
        await click(".cd-conv-item");
        expect(selected).toBe(true);
    });

    test("selected row carries the selected modifier", async () => {
        await mountWithCleanup(CdConversationListItem, {
            props: { conversation: makeRow(), selected: true, onSelect: () => {} },
        });
        expect(".cd-conv-item--selected").toHaveCount(1);
    });
});
