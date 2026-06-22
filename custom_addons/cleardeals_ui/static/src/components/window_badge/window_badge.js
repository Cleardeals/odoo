/** @odoo-module */

import { Component } from "@odoo/owl";
import { parseServerDateTime } from "../../utils/datetime";

/**
 * CdWindowBadge — shows the 24h WhatsApp free-text window state.
 *
 * Props:
 *   state          {String}  "open" | "closing_soon" | "closed"
 *   windowExpiresAt {String} ISO-8601 UTC timestamp (optional — shows countdown when open)
 */
export class CdWindowBadge extends Component {
    static template = "cleardeals_ui.WindowBadge";

    static props = {
        state:           { type: String },
        windowExpiresAt: { type: String, optional: true },
    };

    /** "closing_soon" is still an open window — only "closed" is locked. */
    get isOpen() {
        return this.props.state !== "closed";
    }

    get label() {
        if (!this.isOpen) return "Window Closed";
        if (!this.props.windowExpiresAt) return "Window Open";
        const expires = parseServerDateTime(this.props.windowExpiresAt);
        const diffMs = expires - Date.now();
        if (diffMs <= 0) return "Window Closed";
        const diffH = Math.floor(diffMs / 3_600_000);
        const diffM = Math.floor((diffMs % 3_600_000) / 60_000);
        return diffH > 0 ? `Open · ${diffH}h ${diffM}m left` : `Open · ${diffM}m left`;
    }
}
