/** @odoo-module */

/**
 * Notification type registry — the "configurable per event" part of the
 * central notification system.
 *
 * Any module registers a display/behaviour config for its notification types::
 *
 *   import { registry } from "@web/core/registry";
 *   registry.category("cd_notification_types").add("reassignment_request", {
 *       title: "Chat handover requested",
 *       icon: "fa-user-plus",
 *       mod: "review",                 // colour variant: default|replied|review|failure
 *       actions: [                     // optional inline actions (actionable cards)
 *           { key: "approve", label: "Approve", btnClass: "btn-success",
 *             icon: "fa-check", model: "wa.reassignment.request",
 *             method: "approve", args: (n) => [[n.request_id]],
 *             okMessage: "Chat handed over." },
 *           ...
 *       ],
 *       // optional click-through navigation for non-actionable cards:
 *       open: { model: "leads.new", resId: (n) => n.lead_id },
 *   });
 *
 * The component reads the config purely as data, so no module needs to touch the
 * generic center to add a new kind of notification.
 */

import { registry } from "@web/core/registry";

const DEFAULT_CONFIG = {
    title: "Notification",
    icon: "fa-bell",
    mod: "default",
    actions: [],
    open: null,
};

/** Resolve the display/behaviour config for a notification type (never throws). */
export function getNotifConfig(type) {
    const cfg = registry.category("cd_notification_types").get(type, null);
    return { ...DEFAULT_CONFIG, ...(cfg || {}) };
}
