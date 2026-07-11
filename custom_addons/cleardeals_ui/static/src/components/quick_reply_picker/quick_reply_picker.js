/** @odoo-module */

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";

/**
 * CdQuickReplyPicker — a small searchable popover of saved quick replies.
 *
 * Pure / props-driven (no ORM): the host fetches the list and handles insert.
 *
 * Props:
 *   replies   {Array}    [{id, title, shortcut, body, kind, list_payload, is_shared}]
 *   onSelect  {Function} (reply) => void — the host inserts (text) or sends (list)
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
        // Typeahead mode: filter live from `query` (the host's input) and hide
        // the picker's own search box. Used by the "/" slash-command flow.
        query:        { type: String, optional: true },
        typeahead:    { type: Boolean, optional: true },
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
            // In typeahead mode the host's input governs visibility, so skip the
            // outside-click close (clicking the textarea must not dismiss it).
            if (this.props.typeahead) return;
            // Defer so the opening click doesn't immediately close it.
            setTimeout(() => document.addEventListener("click", this._onDocClick), 0);
        });
        onWillUnmount(() => document.removeEventListener("click", this._onDocClick));
    }

    get isTypeahead() { return !!this.props.typeahead; }

    get filtered() {
        const raw = this.isTypeahead ? (this.props.query || "") : (this.state.query || "");
        let q = raw.trim().toLowerCase();
        if (q.startsWith("/")) q = q.slice(1);
        if (!q) return this.props.replies;
        return this.props.replies.filter((r) =>
            (r.title || "").toLowerCase().includes(q) ||
            (r.shortcut || "").toLowerCase().includes(q) ||
            (r.body || "").toLowerCase().includes(q)
        );
    }

    onPick(reply) {
        this.props.onSelect(reply);
        this.props.onClose?.();
    }

    onSearchInput(ev) {
        this.state.query = ev.target.value;
    }
}
