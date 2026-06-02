/** @odoo-module */

import { Component, useRef, useState, onMounted, onPatched } from "@odoo/owl";
import { CdChatBubble } from "../chat_bubble/chat_bubble";

/**
 * CdChatThread — scrollable message list with an in-thread media lightbox.
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
        this.lightbox = useState({ open: false, url: "", kind: "", filename: "" });
        this._lastCount = 0;
        onMounted(() => this._scrollToBottom());
        onPatched(() => {
            // Only auto-scroll when new messages arrived, so opening the lightbox
            // (a state change) doesn't yank the thread to the bottom.
            if (this.props.messages.length !== this._lastCount) {
                this._lastCount = this.props.messages.length;
                this._scrollToBottom();
            }
        });
    }

    _scrollToBottom() {
        const el = this.scrollRef.el;
        if (el) el.scrollTop = el.scrollHeight;
    }

    // ── Media lightbox (issue: previews stay in-tab) ───────────────────────────

    openMedia(url, kind, filename) {
        this.lightbox.open = true;
        this.lightbox.url = url;
        this.lightbox.kind = kind;
        this.lightbox.filename = filename || "";
    }

    closeMedia() {
        this.lightbox.open = false;
        this.lightbox.url = "";
    }

    get isPdf() {
        const f = (this.lightbox.filename || this.lightbox.url || "").toLowerCase();
        return this.lightbox.kind === "document" && f.endsWith(".pdf");
    }

    // ── Quoted-message highlight (scroll to original + flash) ──────────────────

    scrollToMessage(msgId) {
        const el = this.scrollRef.el;
        if (!el) return;
        const target = el.querySelector(`#cd-msg-${msgId}`);
        if (!target) return;
        target.scrollIntoView({ behavior: "smooth", block: "center" });
        target.classList.remove("cd-chat-bubble--flash");
        // force reflow so the animation can re-trigger on repeated taps
        void target.offsetWidth;
        target.classList.add("cd-chat-bubble--flash");
        setTimeout(() => target.classList.remove("cd-chat-bubble--flash"), 1500);
    }
}
