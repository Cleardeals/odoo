/** @odoo-module */

import { Component, useState, useRef } from "@odoo/owl";

/**
 * CdChatComposer — message compose box with file attach and send.
 *
 * Props:
 *   windowState  {String}   "open" | "closed"
 *   onSend       {Function} (body, kind, opts) => void
 *   disabled     {Boolean}  optional hard-disable
 */
export class CdChatComposer extends Component {
    static template = "cleardeals_ui.ChatComposer";

    static props = {
        windowState: { type: String },
        onSend:      { type: Function },
        disabled:    { type: Boolean, optional: true },
    };

    static defaultProps = { disabled: false };

    setup() {
        this.state = useState({
            body:           "",
            attachKind:     null,   // null | "image" | "video" | "document"
            attachName:     "",
            attachCaption:  "",
            uploading:      false,
            uploadError:    null,
        });
        this.fileRef = useRef("fileInput");
    }

    get isClosed()       { return this.props.windowState === "closed"; }
    get canSendFreeText(){ return !this.isClosed && !this.props.disabled; }
    get placeholderText(){
        return this.isClosed
            ? "Window closed — use Send Template to reach this contact"
            : "Type a message…";
    }

    onInput(ev)   { this.state.body = ev.target.value; }
    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendText();
        }
    }

    sendText() {
        const body = this.state.body.trim();
        if (!body || !this.canSendFreeText) return;
        this.props.onSend(body, "freetext", {});
        this.state.body = "";
    }

    selectAttach(kind) {
        if (this.state.attachKind === kind) {
            this.state.attachKind = null;
            return;
        }
        this.state.attachKind = kind;
        this.state.attachName = "";
        this.state.attachCaption = "";
        this.state.uploadError = null;
        // Trigger the hidden file input
        const accept = kind === "image"    ? "image/*"
                     : kind === "video"    ? "video/*"
                     : "application/pdf,application/msword,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.csv,.txt,.zip";
        this.fileRef.el.accept = accept;
        this.fileRef.el.value  = "";
        this.fileRef.el.click();
    }

    async onFileSelected(ev) {
        const file = ev.target.files[0];
        if (!file) { this.state.attachKind = null; return; }
        this.state.attachName   = file.name;
        this.state.uploadError  = null;
        this.state.uploading    = true;

        try {
            // POST multipart to /wa/media/upload — server returns web.base.url-based public URL
            const formData = new FormData();
            formData.append("file", file);
            const resp = await fetch("/wa/media/upload", {
                method: "POST",
                body:   formData,
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            const json = await resp.json();
            if (!resp.ok || json.error) {
                throw new Error(json.error || resp.statusText);
            }
            this.state.attachUrl = json.url;
        } catch (e) {
            this.state.uploadError = "Upload failed: " + String(e);
            this.state.attachKind  = null;
        } finally {
            this.state.uploading = false;
        }
    }

    async sendMedia() {
        if (!this.state.attachUrl || !this.state.attachKind || !this.canSendFreeText) return;
        this.props.onSend(this.state.attachCaption.trim(), this.state.attachKind, {
            media_url:      this.state.attachUrl,
            media_filename: this.state.attachName,
        });
        this.state.attachKind    = null;
        this.state.attachUrl     = "";
        this.state.attachName    = "";
        this.state.attachCaption = "";
    }

    cancelAttach() {
        this.state.attachKind = null;
        this.state.attachUrl  = "";
        this.state.attachName = "";
    }

}
