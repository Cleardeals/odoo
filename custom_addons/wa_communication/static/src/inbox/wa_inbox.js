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
import { CdConversationListItem } from "@cleardeals_ui/index";
import { relativeTime } from "@cleardeals_ui/utils/datetime";

const PAGE_SIZE = 50;

// Primary axis — who owns the chat. The default is role-aware (see setup()).
const OWNERSHIP_TABS = [
    { key: "mine",       label: "Mine" },
    { key: "unassigned", label: "Unassigned" },
    { key: "all",        label: "All" },
];

// Date is an optional refinement, never a hard gate. "Anytime" is the default so
// a customer waiting since days ago is never hidden from the work queue.
const DATE_RANGES = [
    { key: "anytime",    label: "Anytime" },
    { key: "today",      label: "Today" },
    { key: "yesterday",  label: "Yesterday" },
    { key: "last_7d",    label: "Last 7 days" },
    { key: "last_30d",   label: "Last 30 days" },
    { key: "this_month", label: "This month" },
];

// Objective 24h-window state (gates what can be sent) — not invented lifecycle.
const WINDOW_OPTIONS = [
    { key: "all",          label: "Any window" },
    { key: "open",         label: "Window open" },
    { key: "closing_soon", label: "Closing soon" },
    { key: "closed",       label: "Window closed" },
];

const SORT_OPTIONS = [
    { key: "waiting", label: "Longest waiting" },
    { key: "recent",  label: "Most recent" },
    { key: "unread",  label: "Unread first" },
];

// SLA band (from the server row) → list-item chip tone.
const SLA_TONE = { ok: "ok", warn: "warn", breach: "bad" };

export class WaInbox extends Component {
    static template   = "wa_communication.WaInbox";
    static props      = { "*": true };
    static components = { CdChatThread, CdChatComposer, CdWindowBadge, CdTemplatePickerModal, CdInquirySwitcher, CdConversationListItem, AutoComplete };

    setup() {
        this.orm        = useService("orm");
        this.action     = useService("action");
        this.busService = useService("bus_service");
        this.notification = useService("notification");
        this.cdNotif    = useService("cd_notification");

        this.state = useState({
            // Filters — mirror the backend get_inbox contract exactly.
            filters: {
                ownership:       "mine",     // role-aware default set on mount
                needs_reply:     false,      // WhatsApp-like: show ALL chats, not a queue
                window:          "all",      // open | closing_soon | closed | all
                assigned_rm_ids: [],         // explicit RM multi-select
                date_range:      "anytime",
                date_from:       null,
                date_to:         null,
                search:          "",
                sort:            "recent",   // WhatsApp-like: newest activity on top
            },
            showFilters: false,              // Filters popover open?
            isManager:   false,

            // List
            conversations:  [],
            total:          0,
            counts:         { ownership: {}, needs_reply: 0, closing_soon: 0, rms: [] },
            listLoading:    true,
            loadingMore:    false,
            listError:      null,

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

            // Assign-conversation picker (managers only) — mirrors the lead form.
            showAssignPicker:   false,
            assignUsers:        [],

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

        // Native AutoComplete source for the Create-lead property picker.
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

        onMounted(async () => {
            // Role-aware default: managers triage the whole team queue, RMs land on
            // their own open chats. Pick the default BEFORE the first load.
            try {
                this.state.isManager = await user.hasGroup("wa_communication.group_wa_manager");
            } catch (_) { /* default to RM view */ }
            if (this.state.isManager) this.state.filters.ownership = "all";

            this._loadInbox();
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
            this._loadInbox();
            if (this.state.activeConvId) this._loadThread(this.state.activeConvId);
        });
        const uid = user.userId || null;
        if (uid) {
            this.busService.addChannel(`cleardeals_notification_${uid}`);
            this.busService.subscribe("cd_notification", () => {
                this._loadInbox();
                if (this.state.activeConvId) this._loadThread(this.state.activeConvId);
            });
        }
    }

    // ── Data loading ─────────────────────────────────────────────────────────

    _buildFilters(offset = 0) {
        const f = this.state.filters;
        return {
            ownership:       f.ownership,
            needs_reply:     f.needs_reply || undefined,
            window:          f.window !== "all" ? f.window : undefined,
            assigned_rm_ids: f.assigned_rm_ids.length ? f.assigned_rm_ids : undefined,
            date_range:      f.date_range !== "anytime" ? f.date_range : undefined,
            date_from:       f.date_from || undefined,
            date_to:         f.date_to || undefined,
            search:          f.search || undefined,
            sort:            f.sort,
            limit:           PAGE_SIZE,
            offset,
        };
    }

    /** Load the first page. Rows, total and all counts arrive together, so the
     *  list and the badges can never disagree. */
    async _loadInbox() {
        this.state.listLoading = true;
        try {
            const data = await this.orm.call("wa.conversation", "get_inbox", [], {
                filters: this._buildFilters(0),
            });
            this.state.conversations = data.rows || [];
            this.state.total  = data.total || 0;
            this.state.counts = data.counts || this.state.counts;
            this.state.listError = null;
        } catch (e) {
            this.state.listError = String(e);
        } finally {
            this.state.listLoading = false;
        }
    }

    /** Append the next page (server-side pagination keeps "longest waiting" honest
     *  across the whole population, not just the first page). */
    async loadMore() {
        if (this.state.loadingMore) return;
        this.state.loadingMore = true;
        try {
            const data = await this.orm.call("wa.conversation", "get_inbox", [], {
                filters: this._buildFilters(this.state.conversations.length),
            });
            this.state.conversations = this.state.conversations.concat(data.rows || []);
            this.state.total  = data.total || this.state.total;
            this.state.counts = data.counts || this.state.counts;
        } catch (e) {
            this.notification.add(String(e), { type: "danger" });
        } finally {
            this.state.loadingMore = false;
        }
    }

    get hasMore() {
        return this.state.conversations.length < this.state.total;
    }

    async _loadQuickReplies() {
        try {
            this.state.quickReplies = await this.orm.call(
                "wa.quick.reply", "get_for_composer", [], {});
        } catch (_) {}
    }

    async _loadThread(convId) {
        this.state.threadLoading = true;
        try {
            const data = await this.orm.call("wa.conversation", "get_thread", [[convId]], {});
            this.state.thread = data;
            this.state.activeConvId = convId;
            this.cdNotif.setActiveSuppressKey(data?.conversation?.phone || null);
        } catch (e) {
            console.error("WaInbox._loadThread", e);
        } finally {
            this.state.threadLoading = false;
        }
        try {
            await this.orm.call("wa.conversation", "mark_as_read", [[convId]], {});
            const conv = this.state.conversations.find(c => c.id === convId);
            if (conv && conv.unread_count > 0) {
                conv.unread_count = 0;
                conv.needs_reply = false;
                // Keep the badge honest without yanking the row out from under the
                // user: drop the local needs-reply tally.
                if (this.state.counts.needs_reply > 0) this.state.counts.needs_reply -= 1;
            }
        } catch (_) {}
    }

    // ── Filter actions (every change reloads page 1) ───────────────────────────

    setOwnership(key) {
        if (this.state.filters.ownership === key) return;
        this.state.filters.ownership = key;
        this._loadInbox();
    }

    toggleNeedsReply() {
        this.state.filters.needs_reply = !this.state.filters.needs_reply;
        this._loadInbox();
    }

    /** "Closing soon" quick chip shares the window filter so the two never fight. */
    toggleClosingSoon() {
        this.state.filters.window =
            this.state.filters.window === "closing_soon" ? "all" : "closing_soon";
        this._loadInbox();
    }

    setWindow(key) {
        this.state.filters.window = key;
        this._loadInbox();
    }

    toggleRmFilter(id) {
        const ids = this.state.filters.assigned_rm_ids;
        const idx = ids.indexOf(id);
        if (idx >= 0) ids.splice(idx, 1);
        else ids.push(id);
        this._loadInbox();
    }

    setDateRange(key) {
        this.state.filters.date_range = key;
        if (key !== "custom") { this.state.filters.date_from = null; this.state.filters.date_to = null; }
        this._loadInbox();
    }

    setSort(key) {
        this.state.filters.sort = key;
        this._loadInbox();
    }

    onSearchInput(ev) {
        this.state.filters.search = ev.target.value;
        clearTimeout(this._searchDebounce);
        this._searchDebounce = setTimeout(() => this._loadInbox(), 350);
    }

    toggleFilters() {
        this.state.showFilters = !this.state.showFilters;
    }

    /** Restore the role-aware default and clear every refinement. */
    resetFilters() {
        this.state.filters.ownership       = this.state.isManager ? "all" : "mine";
        this.state.filters.needs_reply     = false;
        this.state.filters.window          = "all";
        this.state.filters.assigned_rm_ids = [];
        this.state.filters.date_range      = "anytime";
        this.state.filters.date_from       = null;
        this.state.filters.date_to         = null;
        this.state.filters.sort            = "recent";
        this.state.showFilters = false;
        this._loadInbox();
    }

    /** True when any filter departs from the role-aware default (drives the dot
     *  on the Filters button and the "no matches" empty state). */
    get hasActiveRefinements() {
        const f = this.state.filters;
        return f.window !== "all"
            || f.assigned_rm_ids.length > 0
            || f.date_range !== "anytime"
            || !!f.search;
    }

    /** Mark every loaded, unread chat as read. */
    async markAllRead() {
        const ids = this.state.conversations.filter(c => c.unread_count > 0).map(c => c.id);
        if (!ids.length) return;
        try {
            await this.orm.call("wa.conversation", "mark_as_read", [ids], {});
            this._loadInbox();
        } catch (e) {
            this.notification.add(String(e), { type: "danger" });
        }
    }

    get unreadTotal() {
        return this.state.conversations.reduce((n, c) => n + (c.unread_count || 0), 0);
    }

    // ── Quick actions from the list ────────────────────────────────────────────

    async quickClaim(convId) {
        try {
            await this.orm.call("wa.conversation", "action_claim", [[convId]], {});
            this.notification.add("Chat claimed.", { type: "success" });
            await this._loadInbox();
            if (this.state.activeConvId === convId) await this._loadThread(convId);
        } catch (e) {
            this.notification.add(e.data?.message || "Could not claim the chat.", { type: "danger" });
        }
    }

    async quickAssign(convId) {
        try {
            await this.orm.call("wa.conversation", "request_assignment", [[convId]], {});
            this.notification.add("Assignment requested — you'll be notified on approval.",
                { type: "success" });
            await this._loadInbox();
        } catch (e) {
            this.notification.add(e.data?.message || "Could not request assignment.", { type: "danger" });
        }
    }

    // ── Assign conversation (managers) — direct force-assign, mirrors lead form ──

    async openAssignPicker() {
        if (!this.state.assignUsers.length) {
            this.state.assignUsers = await this.orm.searchRead(
                "res.users", [["share", "=", false]], ["id", "name"], { limit: 50 },
            );
        }
        this.state.showAssignPicker = !this.state.showAssignPicker;
    }

    closeAssignPicker() {
        this.state.showAssignPicker = false;
    }

    async pickAssignUser(userId) {
        this.state.showAssignPicker = false;
        const convId = this.state.activeConvId;
        if (!convId) return;
        try {
            await this.orm.call("wa.conversation", "action_reassign", [[convId]], {
                user_id: userId,
            });
            this.notification.add("Assigning… the chat updates when the platform confirms.",
                { type: "success" });
            await this._loadThread(convId);
            await this._loadInbox();
        } catch (e) {
            this.notification.add(e.data?.message || "Could not assign the chat.", { type: "danger" });
        }
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
        return this.action.doAction({
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
            if (kind === "list") {
                await this.orm.call("wa.conversation", "send_list_message", [[convId]], {
                    body,
                    button_text: opts.list_button_text || "",
                    sections:    opts.list_sections || [],
                });
            } else {
                await this.orm.call("wa.conversation", "send_message", [[convId]], {
                    body, kind,
                    media_url:      opts.media_url      || "",
                    media_filename: opts.media_filename || "",
                });
            }
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

    relativeTime(isoStr) {
        return relativeTime(isoStr);
    }

    get ownershipTabs() { return OWNERSHIP_TABS; }
    get dateRanges()    { return DATE_RANGES; }
    get windowOptions() { return WINDOW_OPTIONS; }
    get sortOptions()   { return SORT_OPTIONS; }

    sortLabel(key) {
        return SORT_OPTIONS.find(s => s.key === key)?.label || key;
    }

    /** Urgency chip for a needs-reply row, built from the server-computed SLA. */
    waitingFor(conv) {
        if (!conv.needs_reply || conv.waiting_minutes == null) return null;
        return {
            label: this._fmtDuration(conv.waiting_minutes),
            tone:  SLA_TONE[conv.sla_band] || "ok",
        };
    }

    /** Compact duration: "12m", "2h 14m", "1d 3h". */
    _fmtDuration(mins) {
        if (mins < 60) return `${mins}m`;
        const h = Math.floor(mins / 60);
        if (h < 24) {
            const m = mins % 60;
            return m ? `${h}h ${m}m` : `${h}h`;
        }
        const d = Math.floor(h / 24);
        const rh = h % 24;
        return rh ? `${d}d ${rh}h` : `${d}d`;
    }

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
        // undefined (not null): CdWindowBadge's windowExpiresAt is an optional
        // String — absent is fine, null fails OWL prop validation.
        return this.activeConversation?.window_expires_at || undefined;
    }

    // Assignment gating (populated by get_thread; default open).
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

    // Lead the "View Lead" button opens — the discussing inquiry when known
    // (server-resolved), else the conversation's anchor lead.
    get viewLeadId() {
        const c = this.activeConversation;
        return c?.view_lead_id ?? c?.lead_id ?? null;
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

    get segmentsEnabled() {
        return !!this.activeConversation?.segments_enabled;
    }

    get activeSegmentLabel() {
        return this.activeConversation?.active_segment?.label || "Unassigned";
    }

    get inquiries() {
        return this.activeConversation?.inquiries || [];
    }

    get activeSegmentInquiryId() {
        return this.activeConversation?.active_segment?.inquiry_id || null;
    }

    get activeSegmentPropertyId() {
        return this.activeConversation?.active_segment?.property_base_id || null;
    }

    switchInquiry(inquiryId) {
        return this._startSegment({ inquiry_id: inquiryId });
    }

    startTopic(label) {
        return this._startSegment({ label });
    }

    async searchTopicProperties(query) {
        try {
            return await this.orm.call("wa.conversation", "search_properties", [], {
                query: query || "", limit: 20 });
        } catch (e) {
            return [];
        }
    }

    async pickTopicProperty(prop) {
        const convId = this.state.activeConvId;
        if (!convId) return;
        try {
            const res = await this.orm.call(
                "wa.conversation", "start_property_topic", [], {
                    conversation_id: convId, property_base_id: prop.id });
            if (res?.action === "exists") {
                this.notification.add(
                    "This property already has an inquiry — switched to it.",
                    { type: "info" });
            }
            await this._loadThread(convId);
            await this._loadInbox();
        } catch (e) {
            this.notification.add(e.data?.message || String(e), { type: "danger" });
        }
    }

    // "Create inquiry" CTA (active span has a property but no inquiry yet).
    // Mirrors the lead form: open the Recommend Property wizard seeded with the
    // conversation's existing inquiry as the source and the topic's property.
    async createInquiryForActive() {
        const propId = this.activeSegmentPropertyId;
        if (!propId) return;
        const conv = this.activeConversation;
        const sourceInquiryId =
            conv?.lead_id || (this.inquiries[0] && this.inquiries[0].id) || null;
        if (!sourceInquiryId) {
            // No inquiry on the number yet — fall back to the create-lead flow.
            this.openCreateLead();
            return;
        }
        const convId = this.state.activeConvId;
        await this.action.doAction(
            {
                type: "ir.actions.act_window",
                res_model: "lead.recommend.property.wizard",
                view_mode: "form",
                views: [[false, "form"]],
                target: "new",
                context: {
                    default_inquiry_id: sourceInquiryId,
                    default_property_base_id: propId,
                    active_id: sourceInquiryId,
                    active_model: "leads.new",
                },
            },
            {
                onClose: async () => {
                    await this._loadThread(convId);
                    await this._loadInbox();
                },
            },
        );
    }

    async _startSegment(kw) {
        const convId = this.state.activeConvId;
        if (!convId) return;
        try {
            await this.orm.call("wa.conversation", "start_segment", [], {
                conversation_id: convId, ...kw,
            });
            await this._loadThread(convId);
            await this._loadInbox();
        } catch (e) {
            this.notification.add(e.data?.message || String(e), { type: "danger" });
        }
    }

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
            await this._loadInbox();
        } catch (e) {
            this.notification.add(e.data?.message || String(e), { type: "danger" });
        }
    }

    dismissSuggestion(segmentId) {
        this.state.dismissedSegmentId = segmentId;
    }

    // ── Create lead from chat (orphan / phone-only conversations) ──────────────

    get isOrphanChat() {
        const c = this.activeConversation;
        return !!c && !c.lead_id;
    }

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

    onPropertyInput({ inputValue }) {
        this.state.propertyQuery = inputValue;
        this.state.selectedProperty = null;
    }

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
            await this._loadInbox();
            // Picking a property routes the lead to that property's RM, who is
            // often somebody else — and then this RM cannot open it. Navigating
            // is a convenience, so failing to do so must not read as an error:
            // stay in the inbox and say where the lead went.
            if (leadId) {
                try {
                    await this.openLead(leadId);
                } catch {
                    this.notification.add(
                        "The lead was created and routed to the property's RM, " +
                        "so it isn't yours to open.",
                        { type: "info" },
                    );
                }
            }
        } catch (e) {
            this.state.createLeadError = e.data?.message || String(e);
        } finally {
            this.state.createLeadSaving = false;
        }
    }
}

registry.category("actions").add("wa_inbox", WaInbox);
