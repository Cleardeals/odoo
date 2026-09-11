/** @odoo-module */

import { Component, useState } from "@odoo/owl";

/**
 * CdTemplatePickerModal — pick an approved WhatsApp template, fill its
 * {{N}} variables, preview, and send.
 *
 * Pure / props-driven. The host supplies a loader (live Interakt fetch) and a
 * send callback wired to wa.conversation.send_message(kind='template', …).
 *
 * Props:
 *   templates   {Array}    [{name, display_name, language, category, header,
 *                            body, footer, buttons, variables:[{scope,position,label}]}]
 *   loading     {Boolean}  true while the list is being fetched
 *   error       {String}   optional fetch error message
 *   defaultBodyValue1 {String} optional — prefill body var 1 (e.g. lead name)
 *   onSend      {Function} ({template_name, body_values, header_values}) => void
 *   onClose     {Function} () => void
 *   onRefresh   {Function} optional () => void — re-fetch templates
 */
export class CdTemplatePickerModal extends Component {
    static template = "cleardeals_ui.TemplatePickerModal";

    static props = {
        templates:         { type: Array },
        loading:           { type: Boolean, optional: true },
        error:             { type: String, optional: true },
        defaultBodyValue1: { type: String, optional: true },
        onSend:            { type: Function },
        onClose:           { type: Function },
        onRefresh:         { type: Function, optional: true },
    };

    setup() {
        this.state = useState({
            query:    "",
            selected: null,   // the chosen template object
            values:   {},     // key "scope:position" -> string
            sending:  false,
        });
    }

    get filtered() {
        const q = (this.state.query || "").trim().toLowerCase();
        if (!q) return this.props.templates;
        return this.props.templates.filter((t) =>
            (t.name || "").toLowerCase().includes(q) ||
            (t.display_name || "").toLowerCase().includes(q) ||
            (t.category || "").toLowerCase().includes(q)
        );
    }

    _key(v) { return `${v.scope}:${v.position}`; }

    selectTemplate(t) {
        this.state.selected = t;
        const values = {};
        for (const v of t.variables || []) {
            // Prefill the first body variable with the supplied default (lead name).
            values[this._key(v)] =
                (v.scope === "body" && v.position === 1 && this.props.defaultBodyValue1)
                    ? this.props.defaultBodyValue1
                    : "";
        }
        this.state.values = values;
    }

    backToList() {
        this.state.selected = null;
        this.state.values = {};
    }

    setValue(v, ev) {
        this.state.values[this._key(v)] = ev.target.value;
    }

    get bodyValues() {
        return this._collect("body");
    }
    get headerValues() {
        return this._collect("header");
    }

    _collect(scope) {
        const vars = (this.state.selected?.variables || [])
            .filter((v) => v.scope === scope)
            .sort((a, b) => a.position - b.position);
        return vars.map((v) => this.state.values[this._key(v)] || "");
    }

    /** Live preview: substitute filled values into the body skeleton. */
    get bodyPreview() {
        let body = this.state.selected?.body || "";
        const vals = this.bodyValues;
        vals.forEach((val, i) => {
            body = body.replace(new RegExp(`{{\\s*${i + 1}\\s*}}`, "g"), val || `{{${i + 1}}}`);
        });
        return body;
    }

    get headerPreview() {
        let h = this.state.selected?.header || "";
        const vals = this.headerValues;
        vals.forEach((val, i) => {
            h = h.replace(new RegExp(`{{\\s*${i + 1}\\s*}}`, "g"), val || `{{${i + 1}}}`);
        });
        return h;
    }

    get canSend() {
        // All variables must be filled.
        return (this.state.selected?.variables || []).every(
            (v) => (this.state.values[this._key(v)] || "").trim() !== ""
        );
    }

    async send() {
        if (!this.canSend || this.state.sending) return;
        this.state.sending = true;
        try {
            await this.props.onSend({
                template_name:     this.state.selected.name,
                template_language: this.state.selected.language || "en",
                body_values:       this.bodyValues,
                header_values:     this.headerValues,
            });
            this.props.onClose();
        } finally {
            this.state.sending = false;
        }
    }
}
