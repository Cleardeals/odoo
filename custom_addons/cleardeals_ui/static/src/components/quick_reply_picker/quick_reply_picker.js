/** @odoo-module */

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";

/**
 * CdQuickReplyPicker — a small searchable popover of saved quick replies.
 *
 * Pure / props-driven (no ORM): the host fetches the list and handles insert.
 *
 * Props:
 *   replies   {Array}    [{id, title, shortcut, body, is_shared}]
 *   onSelect  {Function} (body) => void — insert the chosen reply
 *   onClose   {Function} () => void — dismiss the popover
 *   initialQuery {String} optional — preseed the search (e.g. the "/foo" typed)
 */
export class CdQuickReplyPicker extends Component {
    static template = "cleardeals_ui.QuickReplyPicker";

    static props = {
        replies:      { type: Array },
        onSelect:     { type: Function },
        onClose:      { type: Function, optional: true },
        initialQuery: { type: String, optional: true },
    };

    setup() {
        this.state = useState({ query: this.props.initialQuery || "" });
        this.rootRef = useRef("root");
        this._onDocClick = (ev) => {
            if (this.rootRef.el && !this.rootRef.el.contains(ev.target)) {
                this.props.onClose?.();
            }
        };
        onMounted(() => {
            // Defer so the opening click doesn't immediately close it.
            setTimeout(() => document.addEventListener("click", this._onDocClick), 0);
        });
        onWillUnmount(() => document.removeEventListener("click", this._onDocClick));
    }

    get filtered() {
        let q = (this.state.query || "").trim().toLowerCase();
        if (q.startsWith("/")) q = q.slice(1);
        if (!q) return this.props.replies;
        return this.props.replies.filter((r) =>
            (r.title || "").toLowerCase().includes(q) ||
            (r.shortcut || "").toLowerCase().includes(q) ||
            (r.body || "").toLowerCase().includes(q)
        );
    }

    onPick(reply) {
        this.props.onSelect(reply.body);
        this.props.onClose?.();
    }

    onSearchInput(ev) {
        this.state.query = ev.target.value;
    }
}
