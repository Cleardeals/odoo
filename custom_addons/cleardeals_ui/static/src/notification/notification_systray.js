/** @odoo-module */

/**
 * CdNotificationBell — systray bell with unread count + history dropdown.
 *
 * Persistent home for the central notification system: a click opens a list of
 * the user's notifications (recovered from the backend on load), each with its
 * inline actions and click-through navigation. Mounted via the `systray`
 * registry so it sits in the top bar on every screen.
 *
 * Uses a self-managed open/close panel (not the core Dropdown) to stay robust
 * across web-client versions.
 */

import { Component, useState, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useExternalListener } from "@odoo/owl";

export class CdNotificationBell extends Component {
    static template = "cleardeals_ui.NotificationBell";
    static props = {};

    setup() {
        this.center = useService("cd_notification");
        this.state = useState(this.center.state);
        this.ui = useState({ open: false });
        this.root = useRef("root");
        // Close the panel on any outside click.
        useExternalListener(window, "click", (ev) => {
            if (this.ui.open && this.root.el && !this.root.el.contains(ev.target)) {
                this.ui.open = false;
            }
        });
    }

    toggle() {
        this.ui.open = !this.ui.open;
    }

    config(notif) {
        return this.center.getConfig(notif.type);
    }

    title(notif) {
        return notif.title || this.config(notif).title;
    }

    onItemClick(notif) {
        if (!notif.actionable) {
            this.center.open(notif);
            this.ui.open = false;
        }
    }

    runAction(notif, act) {
        this.center.executeAction(notif, act);
    }

    markRead(notif) {
        this.center.markRead(notif.notification_id);
    }

    markAllRead() {
        this.center.markAllRead();
    }
}

registry.category("systray").add(
    "cd_notification_bell",
    { Component: CdNotificationBell },
    { sequence: 25 }
);
