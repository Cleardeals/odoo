/** @odoo-module */

import { Component, useState, useRef, onMounted } from "@odoo/owl";
import { registry }   from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { session }    from "@web/session";
import { wrapSelection, formatWhatsApp } from "@cleardeals_ui/utils/whatsapp_format";

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

    newReply() {
        this.state.editing = { title: "", shortcut: "", body: "", is_shared: false };
    }

    editReply(r) {
        // Only owned personal or (manager) shared are editable.
        if (!r.owned && !(r.is_shared && this.state.isManager)) return;
        this.state.editing = {
            id: r.id, title: r.title, shortcut: r.shortcut,
            body: r.body, is_shared: r.is_shared,
        };
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
        this.state.saving = true;
        const vals = {
            title:    e.title.trim(),
            shortcut: e.shortcut.trim(),
            body:     e.body,
        };
        // Managers may set scope explicitly: shared ⇒ no owner, personal ⇒ self.
        // Plain users can only make personal replies (record rules enforce it).
        if (this.state.isManager) {
            vals.user_id = e.is_shared ? false : session.uid;
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
