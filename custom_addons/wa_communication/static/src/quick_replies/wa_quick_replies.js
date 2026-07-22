/** @odoo-module */

import { Component, useState, useRef, onMounted } from "@odoo/owl";
import { registry }   from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user }       from "@web/core/user";
import { wrapSelection, formatWhatsApp } from "@cleardeals_ui/utils/whatsapp_format";
import { WA_LIST_LIMITS, findOverLongListText } from "@cleardeals_ui/utils/wa_list_limits";

/**
 * WaQuickReplies — custom management surface for WhatsApp quick replies.
 *
 * Card-grid of the current user's personal replies + the team's shared ones,
 * with an inline editor. Managers can additionally create/edit shared replies.
 */
export class WaQuickReplies extends Component {
    static template = "wa_communication.WaQuickReplies";
    static props = { "*": true };

    setup() {
        this.orm          = useService("orm");
        this.notification = useService("notification");
        this.bodyRef      = useRef("editorBody");

        this.state = useState({
            loading:   true,
            isManager: false,
            replies:   [],
            editing:   null,   // null | { id?, title, shortcut, body, is_shared }
            saving:    false,
        });

        onMounted(() => this._load());
    }

    async _load() {
        this.state.loading = true;
        try {
            const data = await this.orm.call("wa.quick.reply", "get_manager_list", [], {});
            this.state.isManager = data.is_manager;
            this.state.replies   = data.replies;
        } catch (e) {
            this.notification.add("Failed to load quick replies", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    get personalReplies() { return this.state.replies.filter(r => !r.is_shared); }
    get sharedReplies()   { return this.state.replies.filter(r =>  r.is_shared); }

    // ── Editor ──────────────────────────────────────────────────────────────

    _emptyList() {
        return { button: "", sections: [{ title: "", rows: [{ title: "", description: "" }] }] };
    }

    newReply() {
        this.state.editing = {
            title: "", shortcut: "", body: "", is_shared: false,
            kind: "text", list: this._emptyList(),
        };
    }

    editReply(r) {
        // Only owned personal or (manager) shared are editable.
        if (!r.owned && !(r.is_shared && this.state.isManager)) return;
        // Rehydrate the list builder from the saved payload (deep-copied so edits
        // don't mutate the loaded list until saved).
        let list = this._emptyList();
        if (r.kind === "list" && r.list_payload) {
            const lp = r.list_payload;
            list = {
                button: lp.button || "",
                sections: (lp.sections || []).map(s => ({
                    title: s.title || "",
                    rows: (s.rows || []).map(row => ({
                        title: row.title || "", description: row.description || "",
                    })),
                })),
            };
            if (!list.sections.length) list = this._emptyList();
        }
        this.state.editing = {
            id: r.id, title: r.title, shortcut: r.shortcut,
            body: r.body, is_shared: r.is_shared,
            kind: r.kind || "text", list,
        };
    }

    setEditorKind(kind) {
        if (this.state.editing) this.state.editing.kind = kind;
    }

    // ── List builder (mirrors the composer) ─────────────────────────────────────
    addSection()      { this.state.editing.list.sections.push({ title: "", rows: [{ title: "", description: "" }] }); }
    removeSection(i)   { const s = this.state.editing.list.sections; if (s.length > 1) s.splice(i, 1); }
    addRow(si)         { this.state.editing.list.sections[si].rows.push({ title: "", description: "" }); }
    removeRow(si, ri)  { const r = this.state.editing.list.sections[si].rows; if (r.length > 1) r.splice(ri, 1); }
    get listRowCount() {
        if (!this.state.editing || this.state.editing.kind !== "list") return 0;
        return this.state.editing.list.sections.reduce(
            (n, s) => n + s.rows.filter(r => r.title.trim()).length, 0);
    }

    /** WhatsApp interactive-list length caps (exposed to the template). */
    get LIMITS() {
        return WA_LIST_LIMITS;
    }

    /** Rows that will actually be sent, for the preview's expanded list. */
    get previewRows() {
        if (!this.state.editing || this.state.editing.kind !== "list") return [];
        const out = [];
        for (const s of this.state.editing.list.sections) {
            for (const r of s.rows) {
                if (r.title.trim()) {
                    out.push({ title: r.title.trim(), description: (r.description || "").trim() });
                }
            }
        }
        return out;
    }

    cancelEdit() { this.state.editing = null; }

    canEdit(r) { return r.owned || (r.is_shared && this.state.isManager); }

    // ── Inline formatting (WhatsApp markers) ────────────────────────────────────

    applyFormat(marker) {
        if (!this.state.editing) return;
        this.state.editing.body = wrapSelection(this.bodyRef.el, marker);
    }

    /** Card body preview rendered with WhatsApp inline formatting. */
    bodyHtml(body) { return formatWhatsApp(body); }

    async save() {
        const e = this.state.editing;
        if (!e || !e.title.trim() || !e.body.trim()) {
            this.notification.add("Title and message are required", { type: "warning" });
            return;
        }
        const vals = {
            title:    e.title.trim(),
            shortcut: e.shortcut.trim(),
            body:     e.body,
            kind:     e.kind || "text",
            list_payload: false,
        };
        // For a list reply, validate + serialize the builder into list_payload.
        if (e.kind === "list") {
            const sections = e.list.sections
                .map(s => ({
                    title: s.title.trim(),
                    rows: s.rows
                        .filter(r => r.title.trim())
                        .map(r => ({ title: r.title.trim(), description: r.description.trim() })),
                }))
                .filter(s => s.rows.length);
            const total = sections.reduce((n, s) => n + s.rows.length, 0);
            if (!e.list.button.trim()) {
                this.notification.add("Add a button label for the list", { type: "warning" });
                return;
            }
            if (!total) {
                this.notification.add("Add at least one list item with a title", { type: "warning" });
                return;
            }
            if (total > WA_LIST_LIMITS.maxRows) {
                this.notification.add(
                    `A list can have at most ${WA_LIST_LIMITS.maxRows} items`, { type: "warning" });
                return;
            }
            // Same caps the composer enforces — a saved-but-over-long list would
            // fail at send time with an Interakt 400, long after the author left.
            const tooLong = findOverLongListText(e.list.button, sections);
            if (tooLong) {
                this.notification.add(tooLong, { type: "warning" });
                return;
            }
            vals.list_payload = JSON.stringify({ button: e.list.button.trim(), sections });
        }
        this.state.saving = true;
        // Managers may set scope explicitly: shared ⇒ no owner, personal ⇒ self.
        // Plain users can only make personal replies (record rules enforce it).
        if (this.state.isManager) {
            vals.user_id = e.is_shared ? false : user.userId;
        }
        try {
            if (e.id) {
                await this.orm.write("wa.quick.reply", [e.id], vals);
            } else {
                await this.orm.create("wa.quick.reply", [vals]);
            }
            this.state.editing = null;
            await this._load();
            this.notification.add("Quick reply saved", { type: "success" });
        } catch (err) {
            this.notification.add(err.data?.message || "Save failed", { type: "danger" });
        } finally {
            this.state.saving = false;
        }
    }

    async remove(r) {
        if (!this.canEdit(r)) return;
        try {
            await this.orm.unlink("wa.quick.reply", [r.id]);
            await this._load();
        } catch (err) {
            this.notification.add(err.data?.message || "Delete failed", { type: "danger" });
        }
    }
}

registry.category("actions").add("wa_quick_replies", WaQuickReplies);
