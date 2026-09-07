/** @odoo-module */

/**
 * CdNotificationPopups — the global toast stack.
 *
 * Registered in `main_components`, so it is mounted on every screen of the
 * backend and shows popups regardless of which module the user is in. It is a
 * thin view over the `cd_notification` service's reactive `popups` list.
 */

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class CdNotificationPopups extends Component {
    static template = "cleardeals_ui.NotificationPopups";
    static props = {};

    setup() {
        this.center = useService("cd_notification");
        this.state = useState(this.center.state);
    }

    config(notif) {
        return this.center.getConfig(notif.type);
    }

    title(notif) {
        return notif.title || this.config(notif).title;
    }

    onCardClick(notif) {
        if (!notif.actionable) {
            this.center.open(notif);
        }
    }

    runAction(notif, act) {
        this.center.executeAction(notif, act);
    }

    dismiss(notif) {
        // Dismissing a popup also marks it read so it leaves the bell's unread set.
        this.center.markRead(notif.notification_id);
    }
}

registry.category("main_components").add("CdNotificationPopups", {
    Component: CdNotificationPopups,
    props: {},
});
