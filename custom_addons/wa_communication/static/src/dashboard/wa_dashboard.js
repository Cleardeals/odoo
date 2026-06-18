/** @odoo-module */

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

import {
    CdMetricCard,
    CdChart,
    CdKpiCard,
    CdWorklistPanel,
    CdLeaderboardTable,
} from "@cleardeals_ui/index";

// ─────────────────────────────────────────────────────────────────────────────
// WaDashboard — WhatsApp Dashboard client action
//
// Registered as:  registry.category('actions').add('wa_dashboard', WaDashboard)
// XML action tag: 'wa_dashboard'  (ir.actions.client)
// ─────────────────────────────────────────────────────────────────────────────

export class WaDashboard extends Component {
    static template = "wa_communication.WaDashboard";
    static props    = { "*": true };  // client actions receive arbitrary Odoo props

    static components = {
        CdMetricCard,
        CdChart,
        CdKpiCard,
        CdWorklistPanel,
        CdLeaderboardTable,
    };

    // ── Services ─────────────────────────────────────────────────────────────

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading:           true,
            workflows:         [],
            // Global date filter
            dateFrom:          this._todayStart(),
            dateTo:            this._todayEnd(),
            dateLabel:         "Today",
            // Workflow multi-select filter (empty array = all workflows)
            workflowSlugs:     [],
            workflowSearch:    "",
            // Dropdown visibility
            showDatePicker:    false,
            showWorkflowMenu:  false,
            // Global custom date range inputs
            customFrom:        "",
            customTo:          "",
            // Last refresh timestamp
            lastFetched:       null,
            // ── tabs ── 'command' | 'rm' | 'property' | 'campaign'
            activeTab:         "command",
            // ── Command Center ──
            command:           null,
            trends:            [],
            worklists:         null,
            commandLoading:    false,
            // Needs-reply aging filter ("" = all, else "0-4h" | "4-24h" | ">24h")
            needsReplyAge:     "",
            // ── By RM ──
            rmRows:            [],
            rmLoading:         false,
            rmSearch:          "",
            // ── By Campaign ──
            campaign:          null,
            campaignLoading:   false,
            campaignSearch:    "",
            // ── "By Property" view ──
            propertyRows:      [],
            propertyTotal:     0,
            propertySearch:    "",
            propertySort:      "messages",
            propertyLoading:   false,
            rescue:            null,
            expandedPropertyId: null,
            inquiryRows:       [],
            inquiryLoading:    false,
        });

        onMounted(() => {
            this._loadWorkflows();
            this._loadActiveTab();
        });
    }

    // ── Date helpers ─────────────────────────────────────────────────────────

    _todayStart() {
        const d = new Date();
        d.setHours(0, 0, 0, 0);
        return this._isoLocal(d);
    }

    _todayEnd() {
        const d = new Date();
        d.setHours(23, 59, 59, 999);
        return this._isoLocal(d);
    }

    _daysAgo(n) {
        const d = new Date();
        d.setDate(d.getDate() - n);
        d.setHours(0, 0, 0, 0);
        return this._isoLocal(d);
    }

    _startOfMonth() {
        const d = new Date();
        d.setDate(1); d.setHours(0, 0, 0, 0);
        return this._isoLocal(d);
    }

    _startOfLastMonth() {
        const d = new Date();
        d.setDate(1); d.setHours(0, 0, 0, 0);
        d.setMonth(d.getMonth() - 1);
        return this._isoLocal(d);
    }

    _endOfLastMonth() {
        const d = new Date();
        d.setDate(1); d.setHours(0, 0, 0, 0);
        d.setDate(0);  // last day of previous month
        d.setHours(23, 59, 59, 999);
        return this._isoLocal(d);
    }

    _startOfYear() {
        const d = new Date();
        d.setMonth(0, 1); d.setHours(0, 0, 0, 0);
        return this._isoLocal(d);
    }

    /** Format a Date as a local ISO datetime string (no timezone suffix). */
    _isoLocal(d) {
        const pad = (n) => String(n).padStart(2, "0");
        return (
            `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
            `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
        );
    }

    /** Format an ISO date/datetime as "25 Apr" for display in trend labels. */
    _fmtDateShort(isoStr) {
        if (!isoStr) return "—";
        const s = isoStr.includes("T") ? isoStr : isoStr + "T00:00:00";
        const d = new Date(s);
        return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
    }

    /** True when the trend series spans more than one calendar day. */
    get _trendsMultiDay() {
        const days = new Set(this.state.trends.map((t) => (t.date || "").split("T")[0]));
        return days.size > 1;
    }

    /**
     * Adaptive trend-axis label. Hourly points (≤2-day ranges) read as a clean
     * local hour ("2 PM"), prefixed with the day ("16 Jun 2 PM") when the range
     * covers more than one day. Daily points fall back to "25 Apr".
     * Backend hourly timestamps are already in business-tz, so we read the hour
     * straight from the string (no second tz conversion).
     */
    _fmtTrendLabel(isoStr, granularity) {
        if (!isoStr) return "—";
        if (granularity === "hour") {
            const [datePart, timePart = "00"] = isoStr.split("T");
            const hour = parseInt(timePart.slice(0, 2), 10) || 0;
            const ampm = hour < 12 ? "AM" : "PM";
            const h12 = ((hour + 11) % 12) + 1;
            const hourLabel = `${h12} ${ampm}`;
            if (this._trendsMultiDay) {
                const day = new Date(datePart + "T00:00:00").toLocaleDateString(
                    "en-GB", { day: "numeric", month: "short" });
                return `${day} ${hourLabel}`;
            }
            return hourLabel;
        }
        return this._fmtDateShort(isoStr);
    }

    // ── Data loaders ─────────────────────────────────────────────────────────

    async _loadWorkflows() {
        this.state.workflows = await this.orm.searchRead(
            "wa.workflow",
            [],
            ["id", "name", "slug", "is_active"],
            { order: "name" }
        );
    }

    // ── "By Property" view ─────────────────────────────────────────────────

    /** Load the ranked property table + the WhatsApp-rescue numbers together. */
    async _loadPropertyView() {
        this.state.propertyLoading = true;
        try {
            const [engagement, rescue] = await Promise.all([
                this.orm.call("wa.dashboard", "get_property_engagement", [], {
                    date_from:      this.state.dateFrom,
                    date_to:        this.state.dateTo,
                    workflow_slugs: this.state.workflowSlugs,
                    search:         this.state.propertySearch,
                    sort:           this.state.propertySort,
                }),
                this.orm.call("wa.dashboard", "get_whatsapp_rescue", [], {
                    date_from: this.state.dateFrom,
                    date_to:   this.state.dateTo,
                }),
            ]);
            this.state.propertyRows  = engagement.rows;
            this.state.propertyTotal = engagement.total;
            this.state.rescue        = rescue;
        } finally {
            this.state.propertyLoading = false;
        }
    }

    // ── Command Center / lens loaders ────────────────────────────────────────

    _dateArgs() {
        return {
            date_from:      this.state.dateFrom,
            date_to:        this.state.dateTo,
            workflow_slugs: this.state.workflowSlugs,
        };
    }

    async _loadActiveTab() {
        const tab = this.state.activeTab;
        if (tab === "command") return this._loadCommand();
        if (tab === "rm") return this._loadRm();
        if (tab === "campaign") return this._loadCampaign();
        if (tab === "property") return this._loadPropertyView();
    }

    async _loadCommand() {
        this.state.commandLoading = true;
        try {
            const [cmd, trends, worklists] = await Promise.all([
                this.orm.call("wa.dashboard", "get_command_center", [], this._dateArgs()),
                this.orm.call("wa.dashboard", "get_trends", [], this._dateArgs()),
                this.orm.call("wa.dashboard", "get_worklists", []),
            ]);
            this.state.command = cmd;
            this.state.trends = trends;
            this.state.worklists = worklists;
            this.state.lastFetched = new Date().toLocaleTimeString();
        } finally {
            this.state.commandLoading = false;
        }
    }

    async _loadRm() {
        this.state.rmLoading = true;
        try {
            const res = await this.orm.call(
                "wa.dashboard", "get_rm_leaderboard", [], this._dateArgs());
            this.state.rmRows = res.rows;
        } finally {
            this.state.rmLoading = false;
        }
    }

    async _loadCampaign() {
        this.state.campaignLoading = true;
        try {
            this.state.campaign = await this.orm.call(
                "wa.dashboard", "get_campaign_performance", [], {
                    date_from: this.state.dateFrom, date_to: this.state.dateTo,
                });
        } finally {
            this.state.campaignLoading = false;
        }
    }

    async onSwitchTab(tab) {
        this.state.activeTab = tab;
        await this._loadActiveTab();
    }

    // ── Navigation (analytics → action) ──────────────────────────────────────

    openConversation(row) {
        // Open the WhatsApp inbox focused on this exact conversation. We pass the
        // conversation id (to auto-open the thread) and the phone (so the inbox can
        // widen its list filter and surface just this chat, even if it's days old).
        this.action.doAction(
            { type: "ir.actions.client", tag: "wa_inbox" },
            { additionalContext: {
                default_conversation_id: row.conversation_id,
                default_phone: row.phone || "",
            } },
        );
    }

    // ── Command Center derived data (KPI cards, charts, worklists) ────────────

    get kpiCards() {
        const m = this.state.command;
        if (!m) return [];
        const d = m.deltas || {};
        const dl = (k) => (d[k] == null ? undefined : d[k]);   // null → absent (OWL props)
        const u = m.delta_units || {};
        const spark = (key) => this.state.trends.map((t) => t[key]);
        return [
            { label: "Reply rate", value: this.fmtRate(m.reply_rate), delta: dl("reply_rate"),
              unit: u.reply_rate, sub: `${m.replied} of ${m.leads_messaged} messaged`,
              spark: spark("replies"),
              tooltip: "Of leads we messaged on WhatsApp, the share that replied." },
            { label: "Median response", value: this.fmtSecs(m.first_response_median),
              delta: dl("first_response_median"), unit: u.first_response_median, invert: true,
              sub: `p90 ${this.fmtSecs(m.first_response_p90)}`,
              tooltip: "Median time for an RM's first reply, counted in business hours only." },
            { label: "SLA adherence", value: this.fmtRate(m.sla_pct), delta: dl("sla_pct"),
              unit: u.sla_pct, sub: `within ${m.sla_minutes}m`,
              tooltip: "Share of customers first-replied-to within the SLA target (business hours)." },
            { label: "Delivery rate", value: this.fmtRate(m.delivery_rate), delta: dl("delivery_rate"),
              unit: u.delivery_rate, sub: `${m.delivered} delivered`,
              tooltip: "Delivered (or read) messages as a share of those sent." },
            { label: "Failure rate", value: this.fmtRate(m.failure_rate), delta: dl("failure_rate"),
              unit: u.failure_rate, invert: true,
              sub: m.opt_outs ? `${m.opt_outs} opt-outs` : "channel health",
              spark: spark("failed"),
              tooltip: "Failed sends (blocked / invalid / opted-out / rate-limited / template errors) as a share of sent." },
            { label: "WhatsApp spend", value: this.fmtMoney(m.spend), delta: dl("spend"),
              unit: u.spend, invert: true,
              sub: `₹${m.cost_per_reply}/reply`, spark: spark("spend"),
              tooltip: "Total WhatsApp message cost, and cost per reply earned." },
            { label: "Failure reasons", value: this.fmt(m.failed), accent: "bad",
              breakdown: this._failureBreakdown(m),
              sub: m.failed ? "" : "no failed sends",
              tooltip: "Why sends failed in this period, by Meta reason — biggest cause first." },
            { label: "Quality risk", value: this.fmtRate(m.opt_out_rate), delta: dl("opt_out_rate"),
              unit: u.opt_out_rate, invert: true, accent: "warn",
              sub: `${m.opt_outs} opt-outs · ${m.blocks} blocks`,
              tooltip: "Opt-out rate and blocks — rising values threaten your WhatsApp sender quality (Meta can throttle you)." },
        ];
    }

    /** failed_breakdown {label: count} → [{label, value}] biggest-first for the mini bars. */
    _failureBreakdown(m) {
        return Object.entries(m.failed_breakdown || {})
            .map(([label, value]) => ({ label, value }))
            .sort((a, b) => b.value - a.value);
    }

    get volumeChart() {
        const t = this.state.trends;
        const labels = t.map((x) => this._fmtTrendLabel(x.date, x.granularity));
        return {
            data: {
                labels,
                datasets: [
                    { label: "Sent", data: t.map((x) => x.sent), borderColor: "#7c3aed",
                      backgroundColor: "rgba(124,58,237,0.08)", fill: true, tension: 0.3,
                      pointRadius: 2, borderWidth: 2 },
                    { label: "Replies", data: t.map((x) => x.replies), borderColor: "#2563eb",
                      backgroundColor: "rgba(37,99,235,0.06)", fill: true, tension: 0.3,
                      pointRadius: 2, borderWidth: 2 },
                ],
            },
            options: { scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } },
        };
    }

    get healthChart() {
        const t = this.state.trends;
        return {
            data: {
                labels: t.map((x) => this._fmtTrendLabel(x.date, x.granularity)),
                datasets: [
                    { label: "Failed", data: t.map((x) => x.failed), backgroundColor: "#ef4444" },
                ],
            },
            options: { scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } },
        };
    }

    get needsReplyBuckets() {
        const b = (this.state.worklists && this.state.worklists.needs_reply.buckets) || {};
        // Three wall-clock "how long waiting" buckets that partition the total,
        // plus a cross-cutting SLA "Overdue" filter — the breach count managers act on.
        return [
            { label: "Overdue", key: "overdue", value: b["overdue"] || 0, tone: "alert" },
            { label: "0–4h", key: "0-4h", value: b["0-4h"] || 0, tone: "good" },
            { label: "4–24h", key: "4-24h", value: b["4-24h"] || 0, tone: "warn" },
            { label: ">24h", key: ">24h", value: b[">24h"] || 0, tone: "bad" },
        ];
    }

    /** Toggle the needs-reply aging filter (click an active chip again to clear). */
    onNeedsReplyBucket(bucket) {
        this.state.needsReplyAge =
            this.state.needsReplyAge === bucket.key ? "" : bucket.key;
    }

    /** "good" | "warn" | "bad" colour rail from a row's age in hours. */
    _ageTone(hours) {
        if (hours == null) return "";
        if (hours < 4) return "good";
        if (hours < 24) return "warn";
        return "bad";
    }

    _worklistRows(key, metaFn, opts = {}) {
        const wl = this.state.worklists;
        if (!wl) return [];
        return wl[key].rows.map((r) => {
            // CRM owner context: an unclaimed chat whose lead already has an RM
            // isn't truly ownerless — show "RM <name>" so the row is self-explanatory.
            const ownerCtx = r.lead_rm ? `RM ${r.lead_rm}` : "Unassigned";
            const sub = opts.showOwner
                ? (r.lead_name ? `${r.phone} · ${ownerCtx}` : ownerCtx)
                : (r.lead_name ? r.phone : "");
            return {
                ...r,
                title: r.lead_name || r.phone || "Unknown",
                sub,
                meta: metaFn(r),
                tone: opts.tone ? opts.tone(r) : "",
            };
        });
    }

    /** Human "waiting for" duration with minute granularity: 45m · 1h 20m · 3h · 1d 5h · 29d. */
    _fmtAge(row) {
        const mins = row.age_minutes != null
            ? row.age_minutes
            : Math.round((row.age_hours || 0) * 60);
        if (mins < 60) return `${mins}m`;
        const hours = mins / 60;
        if (hours < 24) {
            const h = Math.floor(hours);
            const m = mins - h * 60;
            return m ? `${h}h ${m}m` : `${h}h`;
        }
        let d = Math.floor(hours / 24);
        let h = Math.round(hours - d * 24);
        if (h >= 24) { d += 1; h = 0; }
        return h ? `${d}d ${h}h` : `${d}d`;
    }

    get needsReplyRows() {
        const age = this.state.needsReplyAge;
        const rows = this._worklistRows(
            "needs_reply", (r) => this._fmtAge(r),
            { tone: (r) => (r.overdue ? "bad" : this._ageTone(r.age_hours)) },
        );
        if (!age) return rows;
        if (age === "overdue") return rows.filter((r) => r.overdue);
        return rows.filter((r) => this._ageTone(r.age_hours) === this._bucketTone(age));
    }

    /** Map a bucket key to its tone so the filter and the row rails agree. */
    _bucketTone(key) {
        return key === "0-4h" ? "good" : key === "4-24h" ? "warn" : "bad";
    }

    get windowClosingRows() {
        return this._worklistRows(
            "window_closing", (r) => this.fmtDateTime(r.expires_at), { showOwner: true });
    }

    get unassignedRows() {
        return this._worklistRows(
            "unassigned", (r) => this.fmtDateTime(r.last_message_at), { showOwner: true });
    }

    // ── Lens column configs + filtered rows ──────────────────────────────────

    get rmColumns() {
        return [
            { key: "rm_name", label: "RM", type: "text", align: "left" },
            { key: "conversations", label: "Convs", type: "num" },
            { key: "msgs_sent", label: "Sent", type: "num" },
            { key: "reply_rate", label: "Reply rate", type: "bar" },
            { key: "first_response_median", label: "Response", type: "secs" },
            { key: "sla_pct", label: "SLA", type: "pct" },
            { key: "spend", label: "Cost", type: "money" },
        ];
    }

    get rmFilteredRows() {
        const q = (this.state.rmSearch || "").toLowerCase();
        if (!q) return this.state.rmRows;
        return this.state.rmRows.filter((r) => (r.rm_name || "").toLowerCase().includes(q));
    }

    /** Shared metric columns for both campaign tables (name label varies). */
    _campaignBaseColumns(nameLabel) {
        return [
            { key: "name", label: nameLabel, type: "text", align: "left" },
            { key: "sent", label: "Sent", type: "num" },
            { key: "delivery_rate", label: "Delivered", type: "pct" },
            { key: "reply_rate", label: "Reply rate", type: "bar" },
            { key: "failure_rate", label: "Fail %", type: "pct" },
            { key: "opt_out", label: "Opt-outs", type: "num" },
            { key: "cost", label: "Cost", type: "money" },
        ];
    }

    get campaignWorkflowColumns() {
        // Workflow rows additionally carry a pause/resume control (is_active).
        return [...this._campaignBaseColumns("Workflow"),
            { key: "is_active", label: "Status", type: "toggle" }];
    }

    get campaignTemplateColumns() {
        return this._campaignBaseColumns("Template");
    }

    _campaignFilter(rows) {
        const q = (this.state.campaignSearch || "").toLowerCase();
        if (!q) return rows;
        return rows.filter((r) => (r.name || "").toLowerCase().includes(q));
    }

    get campaignWorkflowRows() {
        return this.state.campaign ? this._campaignFilter(this.state.campaign.workflows) : [];
    }

    get campaignTemplateRows() {
        return this.state.campaign ? this._campaignFilter(this.state.campaign.templates) : [];
    }

    async onPropertySort(sort) {
        this.state.propertySort = sort;
        await this._loadPropertyView();
    }

    onPropertySearchInput(value) {
        this.state.propertySearch = value;
    }

    async onApplyPropertySearch() {
        this.state.expandedPropertyId = null;
        await this._loadPropertyView();
    }

    /** Toggle the per-inquiry drill-down for a property row. */
    async onToggleProperty(propertyId) {
        if (!propertyId) return;  // the "Unassigned" bucket has no drill-down
        if (this.state.expandedPropertyId === propertyId) {
            this.state.expandedPropertyId = null;
            this.state.inquiryRows = [];
            return;
        }
        this.state.expandedPropertyId = propertyId;
        this.state.inquiryLoading = true;
        try {
            this.state.inquiryRows = await this.orm.call(
                "wa.dashboard", "get_inquiry_engagement",
                [propertyId, this.state.dateFrom, this.state.dateTo],
            );
        } finally {
            this.state.inquiryLoading = false;
        }
    }

    /** Rescue numbers for a property row (per_property is keyed by id string). */
    rescueForProperty(propertyId) {
        if (!this.state.rescue || !propertyId) return null;
        return this.state.rescue.per_property[String(propertyId)] || null;
    }

    // ── Actions ──────────────────────────────────────────────────────────────

    async onRefresh() {
        this._loadWorkflows();
        await this._loadActiveTab();
    }

    onRmSearchInput(value) { this.state.rmSearch = value; }
    onCampaignSearchInput(value) { this.state.campaignSearch = value; }

    /** Money — compact rupee for spend (₹k / ₹L), plain otherwise. */
    fmtMoney(val) {
        if (val == null) return "₹0";
        if (val >= 100000) return `₹${(val / 100000).toFixed(1)}L`;
        if (val >= 1000) return `₹${(val / 1000).toFixed(1)}k`;
        return `₹${val.toFixed(0)}`;
    }

    // --- Date picker presets ---

    _applyPreset(label, dateFrom, dateTo) {
        this.state.dateLabel      = label;
        this.state.dateFrom       = dateFrom;
        this.state.dateTo         = dateTo;
        this.state.showDatePicker = false;
        this.state.expandedPropertyId = null;
        this._loadActiveTab();
    }

    onPresetToday()         { this._applyPreset("Today",          this._todayStart(), this._todayEnd()); }
    onPresetYesterday()     { this._applyPreset("Yesterday",      this._daysAgo(1),   this._todayStart()); }
    onPresetCurrentMonth()  { this._applyPreset("Current Month",  this._startOfMonth(), this._todayEnd()); }
    onPresetLastMonth()     { this._applyPreset("Last Month",     this._startOfLastMonth(), this._endOfLastMonth()); }
    onPresetLast30Days()    { this._applyPreset("Last 30 Days",   this._daysAgo(30),  this._todayEnd()); }
    onPresetLast90Days()    { this._applyPreset("Last 90 Days",   this._daysAgo(90),  this._todayEnd()); }
    onPresetYearToDate()    { this._applyPreset("Year to Date",   this._startOfYear(), this._todayEnd()); }

    onApplyCustomRange() {
        if (!this.state.customFrom || !this.state.customTo) return;
        this._applyPreset("Custom", this.state.customFrom, this.state.customTo);
    }

    // --- Workflow multi-select filter ---

    /**
     * Toggle a single workflow slug in/out of the active filter set.
     * Menu stays open to allow multi-selection.
     */
    onFilterWorkflow(wf) {
        const slugs = [...this.state.workflowSlugs];
        const idx   = slugs.indexOf(wf.slug);
        if (idx >= 0) {
            slugs.splice(idx, 1);
        } else {
            slugs.push(wf.slug);
        }
        this.state.workflowSlugs = slugs;
        this._loadActiveTab();
    }

    /** Clear all workflow filters and close the dropdown. */
    onClearWorkflowFilter() {
        this.state.workflowSlugs   = [];
        this.state.showWorkflowMenu = false;
        this.state.workflowSearch   = "";
        this._loadActiveTab();
    }

    /** Close the workflow dropdown without changing selection. */
    onCloseWorkflowMenu() {
        this.state.showWorkflowMenu = false;
        this.state.workflowSearch   = "";
    }

    get filteredWorkflows() {
        const q = (this.state.workflowSearch || "").toLowerCase();
        if (!q) return this.state.workflows;
        return this.state.workflows.filter(
            (wf) => wf.name.toLowerCase().includes(q) || wf.slug.toLowerCase().includes(q)
        );
    }

    // --- Workflow pause/resume (By-Campaign toggle) ---

    /** Pause/resume a workflow from the By-Campaign table, then reload its rows. */
    async onCampaignToggle(row) {
        if (!row || !row.id) return;   // template rows / unmatched slugs have no record
        await this.orm.call("wa.workflow", "action_toggle_active", [[row.id]]);
        await Promise.all([this._loadCampaign(), this._loadWorkflows()]);
    }

    // --- Lead navigation ---

    onOpenLead(leadId) {
        this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: "leads.new",
            res_id:    leadId,
            views:     [[false, "form"]],
            target:    "current",
        });
    }

    // ── Computed getters ─────────────────────────────────────────────────────

    /**
     * Label shown on the workflow filter button:
     *   0 selected → "All Workflows"
     *   1 selected → workflow name
     *   n selected → "n Workflows"
     */
    get workflowFilterLabel() {
        const n = this.state.workflowSlugs.length;
        if (n === 0) return "All Workflows";
        if (n === 1) {
            const wf = this.state.workflows.find(
                (w) => w.slug === this.state.workflowSlugs[0]
            );
            return wf ? wf.name : "1 Workflow";
        }
        return `${n} Workflows`;
    }

    // ── Template helpers ─────────────────────────────────────────────────────

    /** Format a metric value as a compact string (e.g. 1200 → "1.2k"). */
    fmt(val) {
        if (val == null) return "—";
        if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(1)}M`;
        if (val >= 1_000)     return `${(val / 1_000).toFixed(1)}k`;
        return String(val);
    }

    /** Format a rate as "n.n%" or "—". */
    fmtRate(val) {
        if (val == null) return "—";
        return `${val.toFixed(1)}%`;
    }

    /** Format a duration in seconds as "Ns" / "Nm" / "Nh", or "—". */
    fmtSecs(val) {
        if (val == null) return "—";
        if (val < 60)   return `${Math.round(val)}s`;
        if (val < 3600) return `${Math.round(val / 60)}m`;
        return `${(val / 3600).toFixed(1)}h`;
    }

    /** Format a backend (naive-UTC) ISO datetime as "25 Apr, 14:30" in IST, or "—". */
    fmtDateTime(isoStr) {
        if (!isoStr) return "—";
        // The server returns naive UTC (no tz suffix). Mark it UTC, then render
        // in Asia/Kolkata so RMs see IST, not the browser's local/UTC guess.
        let s = isoStr.includes("T") ? isoStr : isoStr.replace(" ", "T");
        if (!/[zZ]|[+-]\d\d:?\d\d$/.test(s)) {
            s += "Z";
        }
        return new Date(s).toLocaleString("en-GB", {
            day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
            timeZone: "Asia/Kolkata",
        });
    }

    /** Money — plain rupee amount with 2 decimals. */
    fmtCost(val) {
        if (!val) return "₹0";
        return `₹${val.toFixed(2)}`;
    }
}

registry.category("actions").add("wa_dashboard", WaDashboard);
