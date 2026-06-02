/** @odoo-module */

import { Component } from "@odoo/owl";
import { formatISTTime } from "../../utils/datetime";

/**
 * CdChatBubble — a single WhatsApp message bubble.
 *
 * Props:
 *   message {Object} wa.message row from get_thread:
 *     id, direction, initiator, kind, body, media_url, media_filename,
 *     status, occurred_at, sender_name, template_name, template_buttons,
 *     quoted_body, quoted_sender, workflow_slug
 */
export class CdChatBubble extends Component {
    static template = "cleardeals_ui.ChatBubble";

    static props = {
        message: { type: Object },
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

    get senderLabel() {
        const m = this.props.message;
        if (m.direction === "inbound") return m.sender_name || "Customer";
        if (m.initiator === "workflow") return m.sender_name || m.workflow_slug || "Workflow";
        return m.sender_name || "RM";
    }

    get isSystemEvent() {
        return this.props.message.kind === "system";
    }
}
