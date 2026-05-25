/** @odoo-module */

import { Component } from "@odoo/owl";

/**
 * CdRecentFailuresTable — failure log table for the WA Dashboard bottom panel.
 *
 * Props:
 *   rows       {Array}    Each row: {id, lead_id, lead_name, phone,
 *                          workflow_name, failure_reason, failure_status,
 *                          occurred_at}
 *   onOpenLead {Function} Called with lead_id when the "Open" button is clicked.
 *
 * Not a field widget — imported directly by WaDashboard.
 */
export class CdRecentFailuresTable extends Component {
    static template = "cleardeals_ui.RecentFailuresTable";

    static props = {
        rows:       { type: Array },
        onOpenLead: { type: Function },
    };

    /** Map failure status to a CSS colour variant class. */
    badgeClass(status) {
        const map = {
            failed:          "cd-status-badge--color-1",
            meta_blocked:    "cd-status-badge--color-2",
            invalid_number:  "cd-status-badge--color-3",
            opted_out:       "cd-status-badge--color-4",
            rate_limited:    "cd-status-badge--color-5",
            template_error:  "cd-status-badge--color-6",
            expired:         "cd-status-badge--color-7",
        };
        return map[status] || "cd-status-badge--color-1";
    }

    /**
     * Convert an ISO UTC datetime string to a locale time string with timezone.
     * Returns an empty string for falsy values.
     */
    formatTime(iso) {
        if (!iso) return "";
        try {
            const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
            return d.toLocaleTimeString([], {
                hour:   "2-digit",
                minute: "2-digit",
                timeZoneName: "short",
            });
        } catch {
            return iso;
        }
    }

    handleOpenLead(row) {
        if (row.lead_id) {
            this.props.onOpenLead(row.lead_id);
        }
    }
}
