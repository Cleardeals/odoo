/** @odoo-module */

import { Component, useRef, onPatched } from "@odoo/owl";
import { CdChatBubble } from "../chat_bubble/chat_bubble";

/**
 * CdChatThread — scrollable message list.
 *
 * Props:
 *   messages {Array}  Array of wa.message row dicts from get_thread.
 */
export class CdChatThread extends Component {
    static template = "cleardeals_ui.ChatThread";
    static components = { CdChatBubble };

    static props = {
        messages: { type: Array },
    };

    scrollRef = useRef("scrollContainer");

    setup() {
        onPatched(() => this._scrollToBottom());
    }

    _scrollToBottom() {
        const el = this.scrollRef.el;
        if (el) el.scrollTop = el.scrollHeight;
    }
}
