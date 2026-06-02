/** @odoo-module */

import { Component } from "@odoo/owl";
import { CdWindowBadge } from "../window_badge/window_badge";
import { relativeTime } from "../../utils/datetime";

/**
 * CdConversationListItem — one row in the inbox conversation list.
 *
 * Props:
 *   conversation {Object}   inbox row dict from wa.conversation.get_inbox
 *   selected     {Boolean}  whether this row is currently active
 *   onSelect     {Function} () => void
 *   onViewLead   {Function} (leadId) => void
 *   onAssign     {Function} (convId) => void
 */
export class CdConversationListItem extends Component {
    static template = "cleardeals_ui.ConversationListItem";
    static components = { CdWindowBadge };

    static props = {
        conversation: { type: Object },
        selected:     { type: Boolean },
        onSelect:     { type: Function },
        onViewLead:   { type: Function },
        onAssign:     { type: Function },
    };

    get rowClass() {
        return [
            "cd-conv-item",
            this.props.selected ? "cd-conv-item--selected" : "",
            this.props.conversation.unread_count > 0 ? "cd-conv-item--unread" : "",
        ].filter(Boolean).join(" ");
    }

    get timeLabel() {
        return relativeTime(this.props.conversation.last_message_at);
    }

    onClickRow() { this.props.onSelect(); }
    onClickLead(ev) {
        ev.stopPropagation();
        if (this.props.conversation.lead_id) this.props.onViewLead(this.props.conversation.lead_id);
    }
    onClickAssign(ev) {
        ev.stopPropagation();
        this.props.onAssign(this.props.conversation.id);
    }
}
