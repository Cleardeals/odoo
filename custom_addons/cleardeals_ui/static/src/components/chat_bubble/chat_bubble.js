/** @odoo-module */

import { Component, useState } from "@odoo/owl";
import { markup } from "@odoo/owl";
import { formatISTTime, formatISTDateTime } from "../../utils/datetime";
import { formatWhatsAppHtml, highlightHtml } from "../../utils/whatsapp_format";

/**
 * CdChatBubble — a single WhatsApp message bubble.
 *
 * Props:
 *   message {Object} wa.message row from get_thread:
 *     id, direction, initiator, kind, body, media_url, media_filename,
 *     status, occurred_at, sender_name, template_name, template_header,
 *     template_footer, template_buttons, quoted_body, quoted_sender,
 *     quoted_msg_id, workflow_slug, delivered_at, seen_at
 *   searchQuery   {String}   optional — current in-chat search term
 *   onOpenMedia   {Function} optional (url, kind, filename) => void
 *   onQuotedClick {Function} optional (msgId) => void
 */
export class CdChatBubble extends Component {
    static template = "cleardeals_ui.ChatBubble";

    static props = {
        message:       { type: Object },
        searchQuery:   { type: String, optional: true },
        onOpenMedia:   { type: Function, optional: true },
        onQuotedClick: { type: Function, optional: true },
    };

    setup() {
        this.info = useState({ open: false });
    }

    get isInbound() {
        return this.props.message.direction === "inbound";
    }

    get bubbleClass() {
        return this.isInbound
            ? "cd-chat-bubble cd-chat-bubble--inbound"
            : "cd-chat-bubble cd-chat-bubble--outbound";
    }

    get isMedia() {
        const kind = this.props.message.kind;
        return ["image", "video", "document", "audio"].includes(kind);
    }

    get mediaIcon() {
        const icons = { image: "fa-image", video: "fa-video-camera", document: "fa-file", audio: "fa-music" };
        return icons[this.props.message.kind] || "fa-paperclip";
    }

    get timeLabel() {
        return formatISTTime(this.props.message.occurred_at);
    }

    get isSystemEvent() {
        return this.props.message.kind === "system";
    }

    get templateButtons() {
        const b = this.props.message.template_buttons;
        return Array.isArray(b) ? b : [];
    }

    // ── WhatsApp formatted HTML (OWL-safe via markup()) ──────────────────────

    _renderHtml(raw) {
        const q = this.props.searchQuery && this.props.searchQuery.trim();
        const html = formatWhatsAppHtml(raw);
        return markup(q ? highlightHtml(html, q) : html);
    }

    get bodyHtml()   { return this._renderHtml(this.props.message.body); }
    get headerHtml() { return this._renderHtml(this.props.message.template_header); }
    get footerHtml() { return this._renderHtml(this.props.message.template_footer); }

    get senderLabel() {
        const m = this.props.message;
        if (m.direction === "inbound") return m.sender_name || "Customer";
        if (m.initiator === "workflow") return m.sender_name || m.workflow_slug || "Workflow";
        return m.sender_name || "RM";
    }

    // ── Message info (ⓘ) ────────────────────────────────────────────────────

    get sentLabel() {
        return formatISTDateTime(this.props.message.occurred_at);
    }

    get deliveredLabel() {
        return this.props.message.delivered_at
            ? formatISTDateTime(this.props.message.delivered_at)
            : null;
    }

    get seenLabel() {
        return this.props.message.seen_at
            ? formatISTDateTime(this.props.message.seen_at)
            : null;
    }

    toggleInfo(ev) {
        ev.stopPropagation();
        this.info.open = !this.info.open;
    }

    // ── Interaction ───────────────────────────────────────────────────────────

    onMediaClick(ev) {
        const m = this.props.message;
        if (this.props.onOpenMedia && m.media_url) {
            ev.preventDefault();
            this.props.onOpenMedia(m.media_url, m.kind, m.media_filename || m.kind);
        }
    }

    onQuotedClick() {
        const target = this.props.message.quoted_msg_id;
        if (target && this.props.onQuotedClick) {
            this.props.onQuotedClick(target);
        }
    }
}
