/** @odoo-module */

/**
 * WaMessageRow — a single expandable row in the Message Log table.
 *
 * Receives the row data dict from the server.  On click, the parent toggles
 * expandedRowId which re-renders this row with the expanded detail panel.
 * When expanded, it lazy-loads the full detail via get_message_detail().
 */

import { Component, useState, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class WaMessageRow extends Component {
    static template = "wa_communication.WaMessageRow";
    static props = {
        row:          Object,
        isExpanded:   Boolean,
        onToggle:     Function,
    };

    setup() {
        this.orm   = useService("orm");
        this.state = useState({
            detail:        null,
            detailLoading: false,
            detailError:   null,
        });

        // Load detail when the row becomes expanded
        onWillUpdateProps((nextProps) => {
            if (nextProps.isExpanded && !this.state.detail && !this.state.detailLoading) {
                this._loadDetail(nextProps.row.id);
            }
        });
    }

    async _loadDetail(id) {
        this.state.detailLoading = true;
        this.state.detailError   = null;
        try {
            const detail = await this.orm.call(
                "wa.message.log",
                "get_message_detail",
                [],
                { message_id: id }
            );
            this.state.detail = detail;
        } catch (e) {
            this.state.detailError = e.message || "Failed to load detail";
        } finally {
            this.state.detailLoading = false;
        }
    }

    onClick() {
        this.props.onToggle(this.props.row.id);
    }

    // Helpers used in the template

    get dirBadgeClass() {
        return this.props.row.direction === "inbound"
            ? "cd-msg-log__badge cd-msg-log__badge--inbound"
            : "cd-msg-log__badge cd-msg-log__badge--outbound";
    }

    get kindBadgeClass() {
        const k = this.props.row.kind;
        if (k === "template")     return "cd-msg-log__badge cd-msg-log__badge--template";
        if (k === "button_reply") return "cd-msg-log__badge cd-msg-log__badge--cta";
        return "cd-msg-log__badge cd-msg-log__badge--text";
    }

    get statusBadgeClass() {
        const c = this.props.row.status_color;
        return `cd-msg-log__status cd-msg-log__status--${c}`;
    }

    get hasFailure() {
        return !!this.props.row.failure_label;
    }

    get failureLines() {
        return (this.props.row.failure_label || "").split("\n");
    }

    get costDisplay() {
        const c = this.props.row.cost_inr;
        if (!c) return "—";
        return `₹${c.toFixed(2)}`;
    }
}
