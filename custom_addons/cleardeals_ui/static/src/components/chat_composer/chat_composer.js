/** @odoo-module */

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { CdQuickReplyPicker } from "../quick_reply_picker/quick_reply_picker";
import { wrapSelection } from "../../utils/whatsapp_format";

/**
 * CdChatComposer — message compose box with multi-file attach and send.
 *
 * Props:
 *   windowState  {String}   "open" | "closed"
 *   onSend       {Function} (body, kind, opts) => void
 *   disabled     {Boolean}  optional hard-disable
 *   disabledReason {String} optional — shown when disabled (e.g. assignee gate)
 *   quickReplies {Array}    optional — [{id,title,shortcut,body,is_shared}]
 */
export class CdChatComposer extends Component {
    static template = "cleardeals_ui.ChatComposer";
    static components = { CdQuickReplyPicker };

    static props = {
        windowState:    { type: String },
        onSend:         { type: Function },
        disabled:       { type: Boolean, optional: true },
        disabledReason: { type: String, optional: true },
        quickReplies:   { type: Array, optional: true },
    };

    static defaultProps = { disabled: false, disabledReason: "", quickReplies: [] };

    setup() {
        this.state = useState({
            body:          "",
            pendingFiles:  [],  // [{id, kind, name, localPreviewUrl, uploadUrl, uploading, error}]
            sharedCaption: "",
            uploadError:   null,
            showQuickReplies: false,
        });
        this.fmtPopup = useState({ visible: false, x: 0, y: 0 });
        this._nextFileId = 0;
        this._selectingKind = null;
        this.fileRef = useRef("fileInput");
        this.inputRef = useRef("input");

        // Show/hide the floating format popup whenever the document selection changes.
        this._onSelChange = () => this._updateFmtPopup();
        onMounted(() => document.addEventListener("selectionchange", this._onSelChange));
        onWillUnmount(() => document.removeEventListener("selectionchange", this._onSelChange));
    }

    get isClosed()        { return this.props.windowState === "closed"; }
    get canSendFreeText() { return !this.isClosed && !this.props.disabled; }
    get hasPending()      { return this.state.pendingFiles.length > 0; }
    get allUploaded() {
        return this.hasPending &&
               this.state.pendingFiles.every(f => f.uploadUrl && !f.uploading && !f.error);
    }
    get readyCount() {
        return this.state.pendingFiles.filter(f => f.uploadUrl && !f.uploading).length;
    }
    get placeholderText() {
        return this.isClosed
            ? "Window closed — use Send Template to reach this contact"
            : "Type a message…";
    }

    onInput(ev) {
        this.state.body = ev.target.value;
        // Slash-command typeahead: open the quick-reply picker as soon as the
        // message begins with "/", filtering live as the RM keeps typing.
        const trimmed = (this.state.body || "").trimStart();
        if (this.hasQuickReplies && trimmed.startsWith("/")) {
            this.state.showQuickReplies = true;
        } else if (this.state.showQuickReplies && !trimmed.startsWith("/")) {
            this.state.showQuickReplies = false;
        }
    }
    onKeydown(ev) {
        if (ev.key === "Escape" && this.state.showQuickReplies) {
            this.state.showQuickReplies = false;
            return;
        }
        // Ctrl/Cmd + B → bold,  Ctrl/Cmd + I → italic,  Ctrl/Cmd + Shift + S → strike
        if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && this.canSendFreeText) {
            const k = ev.key.toLowerCase();
            if (k === "b") { ev.preventDefault(); this.applyFormat("*"); return; }
            if (k === "i") { ev.preventDefault(); this.applyFormat("_"); return; }
            if (ev.shiftKey && k === "s") { ev.preventDefault(); this.applyFormat("~"); return; }
        }
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendText();
        }
    }

    // ── Format popup (appears above the text selection) ─────────────────────────

    _updateFmtPopup() {
        const el = this.inputRef.el;
        if (!el || document.activeElement !== el) {
            if (this.fmtPopup.visible) this.fmtPopup.visible = false;
            return;
        }
        if (el.selectionStart === el.selectionEnd) {
            if (this.fmtPopup.visible) this.fmtPopup.visible = false;
            return;
        }
        const pos = this._getCursorPixelPos();
        if (pos) {
            this.fmtPopup.x = pos.x;
            this.fmtPopup.y = pos.y;
            this.fmtPopup.visible = true;
        }
    }

    /**
     * Use a mirror-div to compute the viewport coordinates of the current
     * textarea selection so the format popup can be positioned precisely
     * above the selected text.
     */
    _getCursorPixelPos() {
        const el = this.inputRef.el;
        if (!el) return null;
        const s = window.getComputedStyle(el);
        const elRect = el.getBoundingClientRect();

        const mirror = document.createElement("div");
        Object.assign(mirror.style, {
            position:   "fixed",
            top:        elRect.top  + "px",
            left:       elRect.left + "px",
            width:      elRect.width + "px",
            overflow:   "hidden",
            visibility: "hidden",
            pointerEvents: "none",
            whiteSpace: "pre-wrap",
            wordBreak:  "break-word",
        });
        const copyProps = [
            "fontFamily", "fontSize", "fontWeight", "fontStyle", "letterSpacing",
            "lineHeight", "textTransform", "paddingTop", "paddingRight",
            "paddingBottom", "paddingLeft", "borderTopWidth", "borderRightWidth",
            "borderBottomWidth", "borderLeftWidth", "boxSizing",
        ];
        for (const p of copyProps) mirror.style[p] = s[p];

        // Text up to the start of selection
        mirror.appendChild(document.createTextNode(el.value.slice(0, el.selectionStart)));

        // Span that covers the selected text
        const span = document.createElement("span");
        span.textContent = el.value.slice(el.selectionStart, el.selectionEnd) || "​";
        mirror.appendChild(span);

        document.body.appendChild(mirror);
        mirror.scrollTop = el.scrollTop;
        const spanRect = span.getBoundingClientRect();
        document.body.removeChild(mirror);

        return {
            x: Math.round(spanRect.left + spanRect.width / 2),
            y: Math.round(spanRect.top),
        };
    }

    // ── Inline formatting (WhatsApp markers) ────────────────────────────────────

    applyFormat(marker) {
        if (!this.canSendFreeText) return;
        this.state.body = wrapSelection(this.inputRef.el, marker);
    }

    // ── Quick replies ──────────────────────────────────────────────────────────

    get hasQuickReplies() { return (this.props.quickReplies || []).length > 0; }

    /** True when the draft starts with "/" — drives the picker's typeahead mode. */
    get qrTypeahead() { return (this.state.body || "").trimStart().startsWith("/"); }

    toggleQuickReplies() {
        if (!this.canSendFreeText) return;
        this.state.showQuickReplies = !this.state.showQuickReplies;
    }

    closeQuickReplies() { this.state.showQuickReplies = false; }

    insertQuickReply(body) {
        // Insert verbatim; if the box only holds a "/shortcut" query, replace it.
        const cur = this.state.body || "";
        this.state.body = (cur.trim().startsWith("/") || !cur.trim())
            ? body
            : (cur + (cur.endsWith(" ") ? "" : " ") + body);
        this.state.showQuickReplies = false;
    }

    sendText() {
        const body = this.state.body.trim();
        if (!body || !this.canSendFreeText) return;
        this.props.onSend(body, "freetext", {});
        this.state.body = "";
    }

    selectAttach(kind) {
        this._selectingKind = kind;
        const accept = kind === "image"    ? "image/*"
                     : kind === "video"    ? "video/*"
                     : "application/pdf,application/msword,application/vnd.ms-excel,"
                       + "application/vnd.openxmlformats-officedocument.*,"
                       + ".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.csv,.txt,.zip";
        this.fileRef.el.accept   = accept;
        this.fileRef.el.multiple = true;  // always allow multi-select
        this.fileRef.el.value    = "";
        this.fileRef.el.click();
    }

    async onFileSelected(ev) {
        const files = Array.from(ev.target.files);
        if (!files.length) return;
        const kind = this._selectingKind || "document";

        // Add all files to the pending list immediately so thumbnails appear
        const newEntries = files.map(file => ({
            id:              ++this._nextFileId,
            kind,
            name:            file.name,
            localPreviewUrl: kind === "image" ? URL.createObjectURL(file) : null,
            uploadUrl:       null,
            uploading:       true,
            error:           null,
        }));
        for (const entry of newEntries) {
            this.state.pendingFiles.push(entry);
        }
        this.state.uploadError = null;

        // Upload each file concurrently; identify by id after resolution
        await Promise.all(files.map(async (file, i) => {
            const id = newEntries[i].id;
            try {
                const formData = new FormData();
                formData.append("file", file);
                const resp = await fetch("/wa/media/upload", {
                    method:  "POST",
                    body:    formData,
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                });
                const json = await resp.json();
                if (!resp.ok || json.error) throw new Error(json.error || resp.statusText);
                const entry = this.state.pendingFiles.find(f => f.id === id);
                if (entry) { entry.uploadUrl = json.url; entry.uploading = false; }
            } catch (e) {
                const entry = this.state.pendingFiles.find(f => f.id === id);
                if (entry) { entry.error = String(e); entry.uploading = false; }
            }
        }));
    }

    async sendAllMedia() {
        if (!this.canSendFreeText) return;
        const ready = this.state.pendingFiles.filter(f => f.uploadUrl && !f.uploading);
        if (!ready.length) return;
        const caption = this.state.sharedCaption.trim();
        for (let i = 0; i < ready.length; i++) {
            const f = ready[i];
            // Caption goes only on the last file so it appears once at the end
            const body = (i === ready.length - 1) ? caption : "";
            this.props.onSend(body, f.kind, {
                media_url:      f.uploadUrl,
                media_filename: f.name,
            });
        }
        this._clearPending();
    }

    removePendingFile(id) {
        const idx = this.state.pendingFiles.findIndex(f => f.id === id);
        if (idx === -1) return;
        const f = this.state.pendingFiles[idx];
        if (f.localPreviewUrl) URL.revokeObjectURL(f.localPreviewUrl);
        this.state.pendingFiles.splice(idx, 1);
        if (!this.state.pendingFiles.length) this.state.sharedCaption = "";
    }

    cancelAllAttach() {
        this._clearPending();
    }

    _clearPending() {
        for (const f of this.state.pendingFiles) {
            if (f.localPreviewUrl) URL.revokeObjectURL(f.localPreviewUrl);
        }
        this.state.pendingFiles  = [];
        this.state.sharedCaption = "";
    }
}
