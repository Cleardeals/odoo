/** @odoo-module */

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { registry }      from "@web/core/registry";
import { useService }    from "@web/core/utils/hooks";
import { user }          from "@web/core/user";
import { AutoComplete }  from "@web/core/autocomplete/autocomplete";
import { CdChatThread }  from "@cleardeals_ui/index";
import { CdChatComposer } from "@cleardeals_ui/index";
import { CdWindowBadge } from "@cleardeals_ui/index";
import { CdTemplatePickerModal } from "@cleardeals_ui/index";
import { CdInquirySwitcher } from "@cleardeals_ui/index";
import { relativeTime } from "@cleardeals_ui/utils/datetime";

const DATE_RANGES = [
    { key: "today",      label: "Today" },
    { key: "yesterday",  label: "Yesterday" },
    { key: "last_7d",    label: "Last 7d" },
    { key: "last_30d",   label: "Last 30d" },
    { key: "this_month", label: "This Month" },
];

const STATUS_OPTIONS = [
    { key: "needs_reply", label: "Needs Reply" },
    { key: "active",      label: "Active" },
    { key: "completed",   label: "Completed" },
];

const STATUS_COLORS = {
    needs_reply: "cd-status-badge--red",
    active:      "cd-status-badge--green",
    completed:   "cd-status-badge--grey",
    blocked:     "cd-status-badge--orange",
};

export class WaInbox extends Component {
    static template   = "wa_communication.WaInbox";
    static props      = { "*": true };
    static components = { CdChatThread, CdChatComposer, CdWindowBadge, CdTemplatePickerModal, CdInquirySwitcher, AutoComplete };

    setup() {
        this.orm        = useService("orm");
        this.action     = useService("action");
        this.busService = useService("bus_service");
        this.notification = useService("notification");
        this.cdNotif    = useService("cd_notification");

        this.state = useState({
            // Filters (sidebar)
            statusFilters:  [],    // array of active status keys
            assignedRms:    [],    // array of active RM ids
            dateRange:      "today",
            searchText:     "",

            // List
            conversations:  [],
            totalCount:     0,
            listLoading:    true,
            listError:      null,

            // Sidebar counts (loaded once)
            counts:         { status: {}, assigned_rms: [] },

            // Thread panel (right side)
            activeConvId:   null,
            thread:         null,
            threadLoading:  false,
            sendError:      null,

            // Composer aids
            quickReplies:   [],

            // Template picker
            showTemplatePicker: false,
            templates:          [],
            tplLoading:         false,
            tplError:           "",

            // Inquiry segment: suggestion the RM dismissed this session
            dismissedSegmentId: null,

            // Create-lead-from-chat modal (orphan / phone-only conversations)
            showCreateLead:     false,
            createLeadName:     "",
            createLeadSaving:   false,
            createLeadError:    "",
            propertyQuery:      "",
            selectedProperty:   null,   // { id, name }
        });

        this._searchDebounce = null;

        // Odoo's native AutoComplete source for the Create-lead property picker:
        // a single async source backed by wa.conversation.search_properties. The
        // component handles the dropdown, scrolling, keyboard nav and highlight.
        this.propertySources = [{
            options: async (request) => {
                const rows = await this.orm.call(
                    "wa.conversation", "search_properties", [],
                    { query: request || "", limit: 20 });
                return rows.map((p) => ({
                    label: p.name,
                    onSelect: () => this.pickProperty(p),
                }));
            },
        }];

        onMounted(() => {
            this._loadCounts();
            this._loadConversations();
            this._loadQuickReplies();
            this._subscribeBus();
        });

        onWillUnmount(() => {
            this.cdNotif.clearActiveSuppressKey();
        });
    }

    // ── Bus ──────────────────────────────────────────────────────────────────

    _subscribeBus() {
        this.busService.addChannel("wa_message_log");
        this.busService.subscribe("wa_message_update", () => {
            this._loadConversations();
            if (this.state.activeConvId) this._loadThread(this.state.activeConvId);
        });
        const uid = user.userId || null;
        if (uid) {
            // Refresh the list/thread when a central notification arrives (the
            // generic center handles showing it; we just react to keep data fresh).
            this.busService.addChannel(`cleardeals_notification_${uid}`);
            this.busService.subscribe("cd_notification", () => {
                this._loadConversations();
                if (this.state.activeConvId) this._loadThread(this.state.activeConvId);
            });
        }
    }

    // ── Data loading ─────────────────────────────────────────────────────────

    async _loadCounts() {
        try {
            const counts = await this.orm.call("wa.conversation", "get_inbox_counts", [], {});
            this.state.counts = counts;
        } catch (_) {}
    }

    async _loadQuickReplies() {
        try {
            this.state.quickReplies = await this.orm.call(
                "wa.quick.reply", "get_for_composer", [], {});
        } catch (_) {}
    }

    async _loadConversations() {
        this.state.listLoading = true;
        try {
            const rows = await this.orm.call("wa.conversation", "get_inbox", [], {
                filters: {
                    status:       this.state.statusFilters[0] || undefined,
                    date_range:   this.state.dateRange || undefined,
                    assigned_rm:  this.state.assignedRms[0] || undefined,
                    search:       this.state.searchText || undefined,
                    limit:        100,
                },
            });
            this.state.conversations = rows;
            this.state.totalCount = rows.length;
            this.state.listError = null;
        } catch (e) {
            this.state.listError = String(e);
        } finally {
            this.state.listLoading = false;
        }
    }

    async _loadThread(convId) {
        this.state.threadLoading = true;
        try {
            const data = await this.orm.call("wa.conversation", "get_thread", [[convId]], {});
            this.state.thread = data;
            this.state.activeConvId = convId;
            // Suppress popups for THIS chat while it's open on screen (the user
            // sees updates live here); everywhere else still pops.
            this.cdNotif.setActiveSuppressKey(data?.conversation?.phone || null);
        } catch (e) {
            console.error("WaInbox._loadThread", e);
        } finally {
            this.state.threadLoading = false;
        }
        try {
            await this.orm.call("wa.conversation", "mark_as_read", [[convId]], {});
            const conv = this.state.conversations.find(c => c.id === convId);
            if (conv) conv.unread_count = 0;
        } catch (_) {}
    }

    // ── Filter actions ────────────────────────────────────────────────────────

    toggleStatusFilter(key) {
        const idx = this.state.statusFilters.indexOf(key);
        if (idx >= 0) this.state.statusFilters.splice(idx, 1);
        else this.state.statusFilters.push(key);
        this._loadConversations();
    }

    toggleRmFilter(id) {
        const idx = this.state.assignedRms.indexOf(id);
        if (idx >= 0) this.state.assignedRms.splice(idx, 1);
        else this.state.assignedRms.push(id);
        this._loadConversations();
    }

    setDateRange(key) {
        this.state.dateRange = key;
        this._loadConversations();
    }

    onSearchInput(ev) {
        this.state.searchText = ev.target.value;
        clearTimeout(this._searchDebounce);
        this._searchDebounce = setTimeout(() => this._loadConversations(), 350);
    }

    removeStatusChip(key) {
        const idx = this.state.statusFilters.indexOf(key);
        if (idx >= 0) this.state.statusFilters.splice(idx, 1);
        this._loadConversations();
    }

    // ── Row actions ───────────────────────────────────────────────────────────

    openThread(convId) {
        if (this.state.activeConvId !== convId) {
            this.state.thread = null;
            this._loadThread(convId);
        }
    }

    closeThread() {
        this.state.activeConvId = null;
        this.state.thread = null;
    }

    openLead(leadId) {
        this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "leads.new",
            res_id:    leadId,
            views:     [[false, "form"]],
            target:    "current",
        });
    }

    openInInterakt(url) {
        if (url) window.open(url, "_blank", "noopener");
    }

    async onSend(body, kind, opts = {}) {
        const convId = this.state.activeConvId;
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

    // ── Send Template ──────────────────────────────────────────────────────────

    async openTemplatePicker() {
        if (!this.state.activeConvId) return;
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

    async sendTemplate({ template_name, template_language, body_values, header_values }) {
        const convId = this.state.activeConvId;
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

    // ── Helpers ───────────────────────────────────────────────────────────────

    statusLabel(key) {
        return STATUS_OPTIONS.find(s => s.key === key)?.label || key;
    }

    statusBadgeClass(key) {
        return `cd-inbox-status-badge ${STATUS_COLORS[key] || ""}`;
    }

    relativeTime(isoStr) {
        return relativeTime(isoStr);
    }

    get statusOptions()  { return STATUS_OPTIONS; }
    get dateRanges()     { return DATE_RANGES; }

    get activeConversation() {
        return this.state.thread?.conversation || null;
    }

    get activeMessages() {
        return this.state.thread?.messages || [];
    }

    get activeStats() {
        return this.state.thread?.stats || {};
    }

    get windowState() {
        return this.activeConversation?.window_state || "closed";
    }

    get windowExpiresAt() {
        return this.activeConversation?.window_expires_at || null;
    }

    // Assignment gating (populated by get_thread in Feature 3; default open).
    get canSend() {
        const c = this.activeConversation;
        return !c || c.can_send !== false;
    }

    get sendGateReason() {
        return this.activeConversation?.send_gate_reason || "";
    }

    get assignmentPending() {
        return !!this.activeConversation?.assignment_pending;
    }

    get isUnassigned() {
        return !this.activeConversation?.assigned_user_id;
    }

    get myOpenRequest() {
        return !!this.activeConversation?.my_open_request;
    }

    get incomingRequests() {
        return this.activeConversation?.incoming_requests || [];
    }

    async approveRequest(reqId) {
        try {
            await this.orm.call("wa.reassignment.request", "approve", [[reqId]], {});
            this.notification.add("Chat handed over.", { type: "success" });
            await this._loadThread(this.state.activeConvId);
        } catch (e) {
            this.notification.add(e.data?.message || "Could not approve the request.", { type: "danger" });
        }
    }

    async declineRequest(reqId) {
        try {
            await this.orm.call("wa.reassignment.request", "decline", [[reqId]], {});
            this.notification.add("Request declined.", { type: "warning" });
            await this._loadThread(this.state.activeConvId);
        } catch (e) {
            this.notification.add(e.data?.message || "Could not decline the request.", { type: "danger" });
        }
    }

    async claimChat() {
        const convId = this.state.activeConvId;
        if (!convId) return;
        try {
            await this.orm.call("wa.conversation", "action_claim", [[convId]], {});
            await this._loadThread(convId);
        } catch (e) {
            this.state.sendError = e.data?.message || String(e);
        }
    }

    async requestAssignment() {
        const convId = this.state.activeConvId;
        if (!convId) return;
        const assignee = this.activeConversation?.assigned_user_name || "the current owner";
        try {
            await this.orm.call("wa.conversation", "request_assignment", [[convId]], {});
            this.notification.add(
                `Assignment requested from ${assignee}. You'll be notified when they approve.`,
                { type: "success" }
            );
            await this._loadThread(convId);
        } catch (e) {
            const msg = e.data?.message || String(e);
            this.state.sendError = msg;
            this.notification.add(msg, { type: "danger" });
        }
    }

    // ── Inquiry segments ("Discussing: <property>") ────────────────────────────

    /** Feature flag — the whole segment bar only renders when this is on. */
    get segmentsEnabled() {
        return !!this.activeConversation?.segments_enabled;
    }

    get activeSegmentLabel() {
        return this.activeConversation?.active_segment?.label || "Unassigned";
    }

    /** Inquiries (one per property) on this phone, for the switcher dropdown. */
    get inquiries() {
        return this.activeConversation?.inquiries || [];
    }

    /** The inquiry id the active segment currently points at. */
    get activeSegmentInquiryId() {
        return this.activeConversation?.active_segment?.inquiry_id || null;
    }

    /** Switch the active context to an existing inquiry (CdInquirySwitcher onSwitch). */
    switchInquiry(inquiryId) {
        return this._startSegment({ inquiry_id: inquiryId });
    }

    /** Open a label-only segment for a topic whose inquiry doesn't exist yet. */
    startTopic(label) {
        return this._startSegment({ label });
    }

    async _startSegment(kw) {
        const convId = this.state.activeConvId;
        if (!convId) return;
        try {
            await this.orm.call("wa.conversation", "start_segment", [], {
                conversation_id: convId, ...kw,
            });
            await this._loadThread(convId);
            await this._loadConversations();
        } catch (e) {
            this.notification.add(e.data?.message || String(e), { type: "danger" });
        }
    }

    /** Suggest switching the active context when the lead's latest reply is about
     *  a different inquiry than the banner shows. Returns {segment_id, label} or null. */
    get segmentSuggestion() {
        const conv = this.activeConversation;
        if (!conv?.segments_enabled) return null;
        const activeSegId = conv.active_segment?.id || null;
        const msgs = this.activeMessages;
        let last = null;
        for (let i = msgs.length - 1; i >= 0; i--) {
            if (msgs[i].direction === "inbound" && msgs[i].segment_id) { last = msgs[i]; break; }
        }
        if (!last || last.segment_id === activeSegId) return null;
        if (last.segment_id === this.state.dismissedSegmentId) return null;
        return { segment_id: last.segment_id, label: last.segment_label };
    }

    async acceptSuggestion(segmentId) {
        const convId = this.state.activeConvId;
        if (!convId) return;
        try {
            await this.orm.call("wa.conversation", "set_active_segment", [], {
                conversation_id: convId, segment_id: segmentId });
            this.state.dismissedSegmentId = null;
            await this._loadThread(convId);
            await this._loadConversations();
        } catch (e) {
            this.notification.add(e.data?.message || String(e), { type: "danger" });
        }
    }

    dismissSuggestion(segmentId) {
        this.state.dismissedSegmentId = segmentId;
    }

    // ── Create lead from chat (orphan / phone-only conversations) ──────────────

    /** The active conversation has no linked lead → offer to create one. */
    get isOrphanChat() {
        const c = this.activeConversation;
        return !!c && !c.lead_id;
    }

    /** Best-guess display name from the most recent inbound message. */
    get lastInboundName() {
        const msgs = this.activeMessages;
        for (let i = msgs.length - 1; i >= 0; i--) {
            if (msgs[i].direction === "inbound" && msgs[i].sender_name) {
                return msgs[i].sender_name;
            }
        }
        return "";
    }

    openCreateLead() {
        if (!this.isOrphanChat) return;
        this.state.createLeadName  = this.lastInboundName || "";
        this.state.createLeadError = "";
        this.state.propertyQuery   = "";
        this.state.selectedProperty = null;
        this.state.showCreateLead  = true;
    }

    closeCreateLead() {
        this.state.showCreateLead = false;
    }

    onCreateLeadName(ev) {
        this.state.createLeadName = ev.target.value;
    }

    /** AutoComplete typed input: track text + invalidate any prior selection. */
    onPropertyInput({ inputValue }) {
        this.state.propertyQuery = inputValue;
        this.state.selectedProperty = null;
    }

    /** AutoComplete option chosen. */
    pickProperty(p) {
        this.state.selectedProperty = p;
        this.state.propertyQuery = p.name;
    }

    async saveLead() {
        const convId = this.state.activeConvId;
        if (!convId || this.state.createLeadSaving) return;
        const name = (this.state.createLeadName || "").trim();
        if (!name) {
            this.state.createLeadError = "Please enter a name for the lead.";
            return;
        }
        this.state.createLeadSaving = true;
        this.state.createLeadError = "";
        try {
            const leadId = await this.orm.call(
                "wa.conversation", "create_lead_from_chat", [], {
                    conversation_id:  convId,
                    name,
                    property_base_id: this.state.selectedProperty?.id || null,
                });
            this.state.showCreateLead = false;
            this.notification.add("Lead created and linked to this chat.", { type: "success" });
            await this._loadThread(convId);
            await this._loadConversations();
            if (leadId) this.openLead(leadId);
        } catch (e) {
            this.state.createLeadError = e.data?.message || String(e);
        } finally {
            this.state.createLeadSaving = false;
        }
    }
}

registry.category("actions").add("wa_inbox", WaInbox);
