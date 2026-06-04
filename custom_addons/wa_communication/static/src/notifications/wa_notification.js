/** @odoo-module */

/**
 * WaNotification — global toast popup for real-time WA events.
 *
 * Registered in main_components so it is always mounted in the Odoo backend.
 * Subscribes to the bus channel ``wa_notification_{uid}`` on mount and
 * displays a stacked, auto-dismissing notification card for each incoming
 * ``wa_event`` message.
 *
 * Replaces the mail.activity-based RM alerts removed from wa_conversation.py.
 *
 * Supported event types:
 *   lead_replied      — buyer sent a WA reply (purple)
 *   ambiguous_reply   — unroutable reply, needs RM review (amber)
 *   permanent_failure — delivery failed permanently (red)
 */

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";

const DISMISS_AFTER_MS = 8000;
const MAX_VISIBLE = 5;

// ── Icon/colour config per event type ─────────────────────────────────────────
const TYPE_CONFIG = {
    lead_replied: {
        title: "WA Reply",
        icon:  "fa-comment",
        mod:   "replied",
    },
    ambiguous_reply: {
        title: "WA: Review Required",
        icon:  "fa-exclamation-triangle",
        mod:   "review",
    },
    permanent_failure: {
        title: "WA Delivery Failed",
        icon:  "fa-times-circle",
        mod:   "failure",
    },
    reassignment_request: {
        title: "Chat handover requested",
        icon:  "fa-user-plus",
        mod:   "review",
    },
    assignment_changed: {
        title: "Chat assigned to you",
        icon:  "fa-check-circle",
        mod:   "replied",
    },
    reassignment_approved: {
        title: "Request approved",
        icon:  "fa-check-circle",
        mod:   "replied",
    },
    reassignment_declined: {
        title: "Request declined",
        icon:  "fa-times-circle",
        mod:   "failure",
    },
    reassignment_failed: {
        title: "Reassignment failed",
        icon:  "fa-times-circle",
        mod:   "failure",
    },
};

function _cfg(type) {
    return TYPE_CONFIG[type] || { title: "WhatsApp", icon: "fa-whatsapp", mod: "default" };
}

export class WaNotification extends Component {
    static template = "wa_communication.WaNotification";
    static props = {};

    setup() {
        this.busService = useService("bus_service");
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({ notifications: [] });
        this._nextId = 1;
        this._timers = {};

        onMounted(() => this._subscribe());
        onWillUnmount(() => {
            Object.values(this._timers).forEach(clearTimeout);
        });
    }

    // ── Subscription ────────────────────────────────────────────────────────

    _subscribe() {
        const uid = session.uid;
        if (!uid) return;

        const channel = `wa_notification_${uid}`;
        this.busService.subscribe("wa_event", (payload) => this._onEvent(payload));
        this.busService.addChannel(channel);
    }

    // ── Event handler ────────────────────────────────────────────────────────

    _onEvent(payload) {
        const id  = this._nextId++;
        const cfg = _cfg(payload.type);
        const actionable = payload.type === "reassignment_request";
        const notif = {
            id,
            type:      payload.type || "wa_event",
            title:     cfg.title,
            icon:      cfg.icon,
            mod:       cfg.mod,
            leadName:  payload.lead_name || payload.phone || "",
            phone:     payload.phone || "",
            message:   actionable
                ? `${payload.requester_name || "An RM"} wants to take over this chat.`
                : (payload.message || ""),
            leadUrl:   payload.lead_url || "",
            leadId:    payload.lead_id || null,
            actionable,
            requestId: payload.request_id || null,
            busy:      false,
        };

        // Prepend and cap at MAX_VISIBLE
        this.state.notifications = [notif, ...this.state.notifications].slice(0, MAX_VISIBLE);

        // Actionable cards persist until the user acts; others auto-dismiss.
        if (!actionable) {
            this._timers[id] = setTimeout(() => this.dismiss(id), DISMISS_AFTER_MS);
        }
    }

    // ── Actions ──────────────────────────────────────────────────────────────

    dismiss(id) {
        clearTimeout(this._timers[id]);
        delete this._timers[id];
        this.state.notifications = this.state.notifications.filter((n) => n.id !== id);
    }

    async approve(notif) {
        await this._resolve(notif, "approve", "Chat handed over.");
    }

    async decline(notif) {
        await this._resolve(notif, "decline", "Request declined.");
    }

    async _resolve(notif, method, okMsg) {
        if (!notif.requestId || notif.busy) return;
        notif.busy = true;
        try {
            await this.orm.call("wa.reassignment.request", method, [[notif.requestId]]);
            this.notification.add(okMsg, { type: "success" });
            this.dismiss(notif.id);
        } catch (e) {
            this.notification.add(e.data?.message || "Action failed", { type: "danger" });
            notif.busy = false;
        }
    }

    /** Whether clicking the card should jump to the lead's WhatsApp inbox. */
    isClickable(notif) {
        return !notif.actionable && !!(notif.leadId || notif.leadUrl);
    }

    openLead(notif) {
        // Open the lead form (which hosts the WhatsApp Activity inbox tab).
        if (notif.leadId) {
            this.action.doAction({
                type:      "ir.actions.act_window",
                res_model: "leads.new",
                res_id:    notif.leadId,
                views:     [[false, "form"]],
                target:    "current",
            });
        } else if (notif.leadUrl) {
            window.location.hash = notif.leadUrl.replace(/^.*#/, "#");
        }
        this.dismiss(notif.id);
    }
}

registry.category("main_components").add("WaNotification", {
    Component: WaNotification,
    props: {},
});
