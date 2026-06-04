/** @odoo-module */

import { Component, useState, onMounted, onWillUpdateProps } from "@odoo/owl";
import { registry }   from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { CdChatThread }   from "@cleardeals_ui/index";
import { CdChatComposer } from "@cleardeals_ui/index";
import { CdWindowBadge }  from "@cleardeals_ui/index";
import { CdTemplatePickerModal } from "@cleardeals_ui/index";

const WF_STATUS_MAP = {
    active:   { label: "Active",   key: "active" },
    waiting:  { label: "Active",   key: "active" },
    paused:   { label: "Paused",   key: "paused" },
    pending:  { label: "Pending",  key: "pending" },
    done:     { label: "Done",     key: "done" },
    opted_out:{ label: "Done",     key: "done" },
};

export class WaLeadTab extends Component {
    static template   = "wa_communication.WaLeadTab";
    static props      = { ...standardWidgetProps };
    static components = { CdChatThread, CdChatComposer, CdWindowBadge, CdTemplatePickerModal };

    setup() {
        this.orm        = useService("orm");
        this.action     = useService("action");
        this.busService = useService("bus_service");
        this.notification = useService("notification");

        this.state = useState({
            convId:    null,
            thread:    null,
            loading:   true,
            error:     null,
            sendError: null,
            quickReplies: [],
            // Inline pickers
            showAssignPicker: false,
            assignUsers:      [],
            // Template picker
            showTemplatePicker: false,
            templates:          [],
            tplLoading:         false,
            tplError:           "",
        });

        onMounted(() => {
            this._load();
            this._loadQuickReplies();
            this._subscribeBus();
        });

        onWillUpdateProps((nextProps) => {
            const newPhone = this._phone(nextProps);
            if (newPhone !== this._phone(this.props)) this._load(newPhone);
        });
    }

    _phone(props) { return props.record?.data?.phone || ""; }
    get phone()   { return this._phone(this.props); }
    get leadId()  { return this.props.record?.data?.id || null; }

    _subscribeBus() {
        this.busService.addChannel("wa_message_log");
        this.busService.subscribe("wa_message_update", () => {
            if (this.state.convId) this._loadThread(this.state.convId);
        });
    }

    async _load(phone) {
        const p = phone || this.phone;
        if (!p) { this.state.loading = false; return; }
        this.state.loading = true;
        try {
            const fullPhone = p.length === 10 ? `91${p}` : p;
            const convs = await this.orm.searchRead(
                "wa.conversation",
                [["phone_number", "=", fullPhone]],
                ["id"], { limit: 1 }
            );
            if (convs.length) {
                this.state.convId = convs[0].id;
                await this._loadThread(this.state.convId);
            } else {
                this.state.convId = null;
                this.state.thread = null;
            }
        } catch (e) {
            this.state.error = String(e);
        } finally {
            this.state.loading = false;
        }
    }

    async _loadThread(convId) {
        try {
            const data = await this.orm.call("wa.conversation", "get_thread", [[convId]], {});
            this.state.thread = data;
            this.state.error = null;
        } catch (e) {
            this.state.error = String(e);
        }
    }

    async _loadQuickReplies() {
        try {
            this.state.quickReplies = await this.orm.call(
                "wa.quick.reply", "get_for_composer", [], {});
        } catch (_) {}
    }

    async onSend(body, kind, opts = {}) {
        const convId = this.state.convId;
        if (!convId) return;
        this.state.sendError = null;
        try {
            await this.orm.call("wa.conversation", "send_message", [[convId]], {
                body, kind,
                media_url:      opts.media_url      || "",
                media_filename: opts.media_filename || "",
            });
            await this._loadThread(convId);
        } catch (e) {
            this.state.sendError = e.data?.message || String(e);
        }
    }

    openInInterakt() {
        const url = this.state.thread?.conversation?.interakt_url;
        if (url) window.open(url, "_blank", "noopener");
    }

    // ── Send Template ──────────────────────────────────────────────────────────

    async openTemplatePicker() {
        this.state.showTemplatePicker = true;
        await this._loadTemplates();
    }

    async _loadTemplates() {
        this.state.tplLoading = true;
        this.state.tplError = "";
        try {
            this.state.templates = await this.orm.call(
                "wa.conversation", "fetch_templates", [], {});
        } catch (e) {
            this.state.tplError = e.data?.message || String(e);
            this.state.templates = [];
        } finally {
            this.state.tplLoading = false;
        }
    }

    closeTemplatePicker() { this.state.showTemplatePicker = false; }

    get leadName() {
        return this.props.record?.data?.name || "";
    }

    async sendTemplate({ template_name, template_language, body_values, header_values }) {
        const convId = this.state.convId;
        if (!convId) return;
        this.state.sendError = null;
        try {
            await this.orm.call("wa.conversation", "send_message", [[convId]], {
                body: "", kind: "template",
                template_name, template_language, body_values, header_values,
            });
            await this._loadThread(convId);
        } catch (e) {
            this.state.sendError = e.data?.message || String(e);
            throw e;
        }
    }

    async openAssignPicker() {
        this.state.assignUsers = await this.orm.searchRead(
            "res.users", [["share", "=", false]], ["id", "name"], { limit: 50 }
        );
        this.state.showAssignPicker = true;
    }

    async pickAssignUser(userId) {
        this.state.showAssignPicker = false;
        try {
            await this.orm.call("wa.conversation", "action_reassign", [[this.state.convId]], {
                lead_id: this.leadId,
                user_id: userId,
            });
            await this._loadThread(this.state.convId);
        } catch (e) {
            this.state.sendError = e.data?.message || String(e);
        }
    }

    closePickers() {
        this.state.showAssignPicker = false;
    }

    // Assignment gating (populated by get_thread in Feature 3; default open).
    get canSend() {
        const c = this.conversation;
        return !c || c.can_send !== false;
    }
    get sendGateReason() {
        return this.conversation?.send_gate_reason || "";
    }
    get assignmentPending() {
        return !!this.conversation?.assignment_pending;
    }
    get isUnassigned() {
        return !this.conversation?.assigned_user_id;
    }

    async claimChat() {
        if (!this.state.convId) return;
        try {
            await this.orm.call("wa.conversation", "action_claim", [[this.state.convId]], {});
            await this._loadThread(this.state.convId);
        } catch (e) {
            this.state.sendError = e.data?.message || String(e);
        }
    }

    async requestAssignment() {
        if (!this.state.convId) return;
        const assignee = this.conversation?.assigned_user_name || "the current owner";
        try {
            await this.orm.call("wa.conversation", "request_assignment", [[this.state.convId]], {});
            this.notification.add(
                `Assignment requested from ${assignee}. You'll be notified when they approve.`,
                { type: "success" }
            );
            await this._loadThread(this.state.convId);
        } catch (e) {
            const msg = e.data?.message || String(e);
            this.state.sendError = msg;
            this.notification.add(msg, { type: "danger" });
        }
    }

    async approveRequest(reqId) {
        try {
            await this.orm.call("wa.reassignment.request", "approve", [[reqId]], {});
            this.notification.add("Chat handed over.", { type: "success" });
            await this._loadThread(this.state.convId);
        } catch (e) {
            this.notification.add(e.data?.message || "Could not approve the request.", { type: "danger" });
        }
    }

    async declineRequest(reqId) {
        try {
            await this.orm.call("wa.reassignment.request", "decline", [[reqId]], {});
            this.notification.add("Request declined.", { type: "warning" });
            await this._loadThread(this.state.convId);
        } catch (e) {
            this.notification.add(e.data?.message || "Could not decline the request.", { type: "danger" });
        }
    }

    // ── Derived from thread ───────────────────────────────────────────────────

    get conversation()    { return this.state.thread?.conversation || null; }
    get myOpenRequest()   { return !!this.conversation?.my_open_request; }
    get incomingRequests(){ return this.conversation?.incoming_requests || []; }
    get messages()       { return this.state.thread?.messages     || []; }
    get stats()          { return this.state.thread?.stats        || {}; }
    get windowState()    { return this.conversation?.window_state || "closed"; }
    get windowExpiresAt(){ return this.conversation?.window_expires_at || null; }

    get enrollments() {
        // Derive from messages: collect unique workflow_slug entries with last known status
        const seen = new Map();
        for (const msg of this.messages) {
            if (!msg.workflow_slug) continue;
            const slug = msg.workflow_slug;
            if (!seen.has(slug)) {
                seen.set(slug, {
                    slug,
                    name: this._wfDisplayName(slug),
                    step: msg.initiator === "workflow" ? (msg.template_name || "") : "",
                    status_key: "active",
                    status_label: "Active",
                    active: true,
                });
            }
            // Update step from the latest message
            const e = seen.get(slug);
            if (msg.template_name) e.step = msg.template_name;
        }
        // Also pick up system events that mark enrollment status
        for (const msg of this.messages) {
            if (msg.kind !== "system" || !msg.body) continue;
            // e.g. "Enrolled in Lead Nurturing" → rough parse
            const m = msg.body.match(/enrolled in (.+)/i);
            if (m) {
                const slug = m[1].toLowerCase().replace(/\s+/g, "_");
                if (!seen.has(slug)) {
                    seen.set(slug, {
                        slug,
                        name: m[1],
                        step: "",
                        status_key: "active",
                        status_label: "Active",
                        active: true,
                    });
                }
            }
        }
        return [...seen.values()];
    }

    _wfDisplayName(slug) {
        return slug.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    }
}

registry.category("view_widgets").add("wa_whatsapp_tab", {
    component: WaLeadTab,
});
