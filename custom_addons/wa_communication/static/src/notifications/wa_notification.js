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
};

function _cfg(type) {
    return TYPE_CONFIG[type] || { title: "WhatsApp", icon: "fa-whatsapp", mod: "default" };
}

export class WaNotification extends Component {
    static template = "wa_communication.WaNotification";
    static props = {};

    setup() {
        this.busService = useService("bus_service");
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
        const notif = {
            id,
            type:      payload.type || "wa_event",
            title:     cfg.title,
            icon:      cfg.icon,
            mod:       cfg.mod,
            leadName:  payload.lead_name || payload.phone || "",
            phone:     payload.phone || "",
            message:   payload.message || "",
            leadUrl:   payload.lead_url || "",
        };

        // Prepend and cap at MAX_VISIBLE
        this.state.notifications = [notif, ...this.state.notifications].slice(0, MAX_VISIBLE);

        // Auto-dismiss after timeout
        this._timers[id] = setTimeout(() => this.dismiss(id), DISMISS_AFTER_MS);
    }

    // ── Actions ──────────────────────────────────────────────────────────────

    dismiss(id) {
        clearTimeout(this._timers[id]);
        delete this._timers[id];
        this.state.notifications = this.state.notifications.filter((n) => n.id !== id);
    }

    openLead(notif) {
        if (notif.leadUrl) {
            window.location.hash = notif.leadUrl.replace(/^.*#/, "#");
        }
        this.dismiss(notif.id);
    }
}

registry.category("main_components").add("WaNotification", {
    Component: WaNotification,
    props: {},
});
