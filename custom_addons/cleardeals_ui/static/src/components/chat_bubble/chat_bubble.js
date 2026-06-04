/** @odoo-module */

import { Component } from "@odoo/owl";
import { formatISTTime } from "../../utils/datetime";
import { formatWhatsApp } from "../../utils/whatsapp_format";

/**
 * CdChatBubble — a single WhatsApp message bubble.
 *
 * Props:
 *   message {Object} wa.message row from get_thread:
 *     id, direction, initiator, kind, body, media_url, media_filename,
 *     status, occurred_at, sender_name, template_name, template_header,
 *     template_footer, template_buttons, quoted_body, quoted_sender,
 *     quoted_msg_id, workflow_slug
 *   onOpenMedia   {Function} optional (url, kind, filename) => void — open in-tab preview
 *   onQuotedClick {Function} optional (msgId) => void — scroll to quoted original
 */
export class CdChatBubble extends Component {
    static template = "cleardeals_ui.ChatBubble";

    static props = {
        message:       { type: Object },
        onOpenMedia:   { type: Function, optional: true },
        onQuotedClick: { type: Function, optional: true },
    };

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

    /** Body rendered with WhatsApp inline formatting (bold/italic/strike/mono). */
    get bodyHtml() {
        return formatWhatsApp(this.props.message.body);
    }

    get headerHtml() {
        return formatWhatsApp(this.props.message.template_header);
    }

    get footerHtml() {
        return formatWhatsApp(this.props.message.template_footer);
    }

    get senderLabel() {
        const m = this.props.message;
        if (m.direction === "inbound") return m.sender_name || "Customer";
        if (m.initiator === "workflow") return m.sender_name || m.workflow_slug || "Workflow";
        return m.sender_name || "RM";
    }

    get isSystemEvent() {
        return this.props.message.kind === "system";
    }

    get templateButtons() {
        const b = this.props.message.template_buttons;
        return Array.isArray(b) ? b : [];
    }

    // ── Interaction ───────────────────────────────────────────────────────────

    onMediaClick(ev) {
        // Preview inside the chat (lightbox) rather than navigating to a new tab.
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
