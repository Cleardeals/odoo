/** @odoo-module */

/**
 * WhatsApp notification type configs.
 *
 * Registers how each WA notification type is displayed and acted upon in the
 * central notification system (popups + systray bell, in cleardeals_ui). Adding
 * a WA notification kind is purely declarative here — no change to the generic
 * notification center is needed.
 *
 * `actions` are declarative: the center runs `orm.call(model, method, args(n))`.
 * `open` drives click-through navigation for passive notifications.
 */

import { registry } from "@web/core/registry";

const types = registry.category("cd_notification_types");

const openLead = { model: "leads.new", resId: (n) => n.lead_id };

// Actionable handover request → Approve / Decline on wa.reassignment.request.
types.add("reassignment_request", {
    title: "Chat handover requested",
    icon: "fa-user-plus",
    mod: "review",
    actions: [
        {
            key: "approve",
            label: "Approve",
            btnClass: "btn-success",
            icon: "fa-check",
            model: "wa.reassignment.request",
            method: "approve",
            args: (n) => [[n.request_id]],
            okMessage: "Chat handed over.",
        },
        {
            key: "decline",
            label: "Decline",
            btnClass: "btn-outline-secondary",
            icon: "fa-times",
            model: "wa.reassignment.request",
            method: "decline",
            args: (n) => [[n.request_id]],
            okMessage: "Request declined.",
            okType: "warning",
        },
    ],
});

types.add("assignment_changed", {
    title: "Chat assigned to you",
    icon: "fa-check-circle",
    mod: "replied",
    open: openLead,
});

types.add("reassignment_approved", {
    title: "Request approved",
    icon: "fa-check-circle",
    mod: "replied",
    open: openLead,
});

types.add("reassignment_declined", {
    title: "Request declined",
    icon: "fa-times-circle",
    mod: "failure",
});

types.add("reassignment_failed", {
    title: "Reassignment failed",
    icon: "fa-exclamation-triangle",
    mod: "failure",
});

types.add("lead_replied", {
    title: "WhatsApp reply",
    icon: "fa-comment",
    mod: "replied",
    open: openLead,
});

types.add("ambiguous_reply", {
    title: "WhatsApp: review needed",
    icon: "fa-exclamation-triangle",
    mod: "review",
    open: openLead,
});

types.add("permanent_failure", {
    title: "WhatsApp delivery failed",
    icon: "fa-times-circle",
    mod: "failure",
    open: openLead,
});

// Inbound message nobody owns (unknown number, or lead with no RM) → managers
// triage it from the WhatsApp Inbox. No lead to open, so click-through opens the
// Inbox client action instead.
types.add("unrouted_inbound", {
    title: "Unassigned WhatsApp message",
    icon: "fa-question-circle",
    mod: "review",
    open: { action: "wa_communication.action_wa_inbox" },
});
