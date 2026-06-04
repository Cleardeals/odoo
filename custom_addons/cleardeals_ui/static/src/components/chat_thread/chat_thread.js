/** @odoo-module */

import { Component, useRef, useState, onMounted, onPatched } from "@odoo/owl";
import { CdChatBubble } from "../chat_bubble/chat_bubble";
import { istDayKey, formatDayLabel } from "../../utils/datetime";

/**
 * CdChatThread — scrollable message list with date separators, an in-thread
 * media lightbox, and WhatsApp-style in-chat search.
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
        this.search = useState({ open: false, query: "", matches: [], idx: 0 });
        this._lastCount = 0;
        onMounted(() => this._scrollToBottom());
        onPatched(() => {
            // Only auto-scroll when new messages arrived, so opening the lightbox
            // (a state change) doesn't yank the thread to the bottom.
            if (this.props.messages.length !== this._lastCount) {
                this._lastCount = this.props.messages.length;
                this._scrollToBottom();
                if (this.search.open && this.search.query) this._recomputeMatches();
            }
        });
    }

    // ── Date separators ────────────────────────────────────────────────────────

    /**
     * Flatten messages into a render list interleaved with day separators:
     *   [{type:'date', key, label}, {type:'msg', msg}, …]
     */
    get items() {
        const out = [];
        let lastKey = null;
        for (const msg of this.props.messages) {
            const key = istDayKey(msg.occurred_at);
            if (key && key !== lastKey) {
                out.push({ type: "date", key, label: formatDayLabel(msg.occurred_at) });
                lastKey = key;
            }
            out.push({ type: "msg", msg });
        }
        return out;
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

    // ── In-chat search (WhatsApp-style) ────────────────────────────────────────

    toggleSearch() {
        this.search.open = !this.search.open;
        if (!this.search.open) {
            this._clearHighlights();
            this.search.query = "";
            this.search.matches = [];
            this.search.idx = 0;
        }
    }

    closeSearch() {
        this.search.open = false;
        this._clearHighlights();
        this.search.query = "";
        this.search.matches = [];
        this.search.idx = 0;
    }

    onSearchInput(ev) {
        this.search.query = ev.target.value;
        this._recomputeMatches();
    }

    _recomputeMatches() {
        const q = (this.search.query || "").trim().toLowerCase();
        this._clearHighlights();
        if (!q) {
            this.search.matches = [];
            this.search.idx = 0;
            return;
        }
        const matches = [];
        for (const msg of this.props.messages) {
            const hay = `${msg.body || ""} ${msg.sender_name || ""} ${msg.media_filename || ""}`.toLowerCase();
            if (hay.includes(q)) matches.push(msg.id);
        }
        this.search.matches = matches;
        // Jump to the most recent match by default.
        this.search.idx = matches.length ? matches.length - 1 : 0;
        this._applyHighlights();
    }

    _applyHighlights() {
        const el = this.scrollRef.el;
        if (!el) return;
        // The phrase highlight is handled by the searchQuery prop passed to each
        // CdChatBubble — OWL re-renders the body HTML with <mark> tags via the
        // formatWhatsAppHtml + highlightHtml path.  Here we only apply the glow
        // class on the bubble wrapper so it remains OWL-safe (no innerHTML mutation).
        this.search.matches.forEach((id) => {
            const node = el.querySelector(`#cd-msg-${id}`);
            if (node) node.classList.add("cd-chat-bubble--search-hit");
        });
        this._focusCurrent();
    }

    _focusCurrent() {
        const el = this.scrollRef.el;
        if (!el || !this.search.matches.length) return;
        el.querySelectorAll(".cd-chat-bubble--search-current")
            .forEach((n) => n.classList.remove("cd-chat-bubble--search-current"));
        const id = this.search.matches[this.search.idx];
        const node = el.querySelector(`#cd-msg-${id}`);
        if (node) {
            node.classList.add("cd-chat-bubble--search-current");
            node.scrollIntoView({ behavior: "smooth", block: "center" });
        }
    }

    _clearHighlights() {
        const el = this.scrollRef.el;
        if (!el) return;
        el.querySelectorAll(".cd-chat-bubble--search-hit, .cd-chat-bubble--search-current")
            .forEach((n) => n.classList.remove("cd-chat-bubble--search-hit", "cd-chat-bubble--search-current"));
        // Phrase de-highlighting is automatic: when search.query becomes "" the
        // searchQuery prop is "" and OWL re-renders without any <mark> tags.
    }

    nextMatch() {
        if (!this.search.matches.length) return;
        this.search.idx = (this.search.idx + 1) % this.search.matches.length;
        this._focusCurrent();
    }

    prevMatch() {
        if (!this.search.matches.length) return;
        this.search.idx = (this.search.idx - 1 + this.search.matches.length) % this.search.matches.length;
        this._focusCurrent();
    }

    onSearchKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            if (ev.shiftKey) this.prevMatch();
            else this.nextMatch();
        } else if (ev.key === "Escape") {
            this.closeSearch();
        }
    }

    get matchLabel() {
        if (!this.search.query.trim()) return "";
        if (!this.search.matches.length) return "No results";
        return `${this.search.idx + 1} of ${this.search.matches.length}`;
    }
}
