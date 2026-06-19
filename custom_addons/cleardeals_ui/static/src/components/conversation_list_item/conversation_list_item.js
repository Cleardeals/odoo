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
 *   onViewLead   {Function} optional — (leadId) => void
 *   onAssign     {Function} optional — (convId) => void   (reassign an owned chat)
 *   onClaim      {Function} optional — (convId) => void   (claim an unassigned chat)
 *   waiting      {Object}   optional — {label, tone} urgency chip for needs-reply chats
 */
export class CdConversationListItem extends Component {
    static template = "cleardeals_ui.ConversationListItem";
    static components = { CdWindowBadge };

    static props = {
        conversation: { type: Object },
        selected:     { type: Boolean },
        onSelect:     { type: Function },
        onViewLead:   { type: Function, optional: true },
        onAssign:     { type: Function, optional: true },
        onClaim:      { type: Function, optional: true },
        waiting:      { type: Object, optional: true },
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

    /** An unclaimed chat offers "Claim"; an owned one offers "Reassign". */
    get isUnassigned() {
        return !this.props.conversation.assigned_user_name;
    }

    onClickRow() { this.props.onSelect(); }

    onClickLead(ev) {
        ev.stopPropagation();
        if (this.props.onViewLead && this.props.conversation.lead_id) {
            this.props.onViewLead(this.props.conversation.lead_id);
        }
    }

    onClickAssign(ev) {
        ev.stopPropagation();
        this.props.onAssign?.(this.props.conversation.id);
    }

    onClickClaim(ev) {
        ev.stopPropagation();
        this.props.onClaim?.(this.props.conversation.id);
    }
}
