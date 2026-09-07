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
        this.listUi = useState({ expanded: false });
    }

    toggleList() {
        this.listUi.expanded = !this.listUi.expanded;
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
        // Stickers are WebP images delivered with a media_url — render like images.
        return ["image", "video", "document", "audio", "sticker"].includes(kind);
    }

    get isImageLike() {
        const kind = this.props.message.kind;
        return kind === "image" || kind === "sticker";
    }

    get mediaIcon() {
        const icons = {
            image: "fa-image", video: "fa-video-camera", document: "fa-file",
            audio: "fa-music", sticker: "fa-smile-o",
        };
        return icons[this.props.message.kind] || "fa-paperclip";
    }

    /**
     * Non-media rich inbound kinds that carry no media_url and whose body may be
     * empty (location pin, contact card).  Returns {icon, label} so the bubble
     * always shows a readable chip instead of an invisible empty bubble.
     * list_reply carries the picked option in body, so it renders as text.
     */
    get specialKind() {
        const kind = this.props.message.kind;
        const map = {
            location: { icon: "fa-map-marker", label: "Location" },
            contact:  { icon: "fa-address-card-o", label: "Contact" },
        };
        return map[kind] || null;
    }

    /**
     * Maps link for a location bubble.  Odoo stores the resolved Google Maps
     * URL (from the shared url or lat/long) in media_url; fall back to parsing
     * a bare "lat,long" body for older rows.
     */
    get locationMapsUrl() {
        if (this.props.message.kind !== "location") return null;
        if (this.props.message.media_url) return this.props.message.media_url;
        const body = (this.props.message.body || "").trim();
        const m = body.match(/^\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*$/);
        return m ? `https://www.google.com/maps?q=${m[1]},${m[2]}` : null;
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

    /** Parsed {button, sections} for an outbound interactive list, or null. */
    get listPayload() {
        const p = this.props.message.list_payload;
        return p && Array.isArray(p.sections) && p.sections.length ? p : null;
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

    // ── Template header MEDIA (image/video/document/audio header) ────────────
    // A template's header can be media instead of text; the platform forwards the
    // link + type so the bubble renders it above the body, just like inbound media.
    get headerMediaUrl()  { return this.props.message.template_header_media_url || null; }
    get headerMediaType() { return this.props.message.template_header_media_type || null; }

    get headerMediaFilename() {
        const url = this.headerMediaUrl;
        if (!url) return this.headerMediaType || "Attachment";
        // Strip query string, then take the last path segment as a filename hint.
        return url.split("?")[0].split("/").pop() || (this.headerMediaType || "Attachment");
    }

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

    onHeaderMediaClick(ev) {
        if (this.props.onOpenMedia && this.headerMediaUrl) {
            ev.preventDefault();
            ev.stopPropagation();
            this.props.onOpenMedia(
                this.headerMediaUrl, this.headerMediaType, this.headerMediaFilename);
        }
    }

    onQuotedClick() {
        const target = this.props.message.quoted_msg_id;
        if (target && this.props.onQuotedClick) {
            this.props.onQuotedClick(target);
        }
    }
}
