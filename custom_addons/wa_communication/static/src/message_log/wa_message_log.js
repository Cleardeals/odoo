/** @odoo-module */

/**
 * WaMessageLog — Message Log client action
 *
 * Registered as: registry.category('actions').add('wa_message_log', WaMessageLog)
 * XML action tag: 'wa_message_log'  (ir.actions.client)
 *
 * Features:
 *  - Period filter bar (Today / Yesterday / Last 7d / Last 30d / This Month)
 *  - Direction+type tab filters (All / Inbound / Outbound / CTA Reply / Failed)
 *  - Template and Workflow dropdown filters
 *  - Free-text phone/lead search
 *  - Sortable, expandable table rows (click a row → full detail panel)
 *  - Summary stats bar (records / inbound / CTA replies / failed / total cost)
 *  - Live updates via bus.bus 'wa_message_log' channel
 *  - Raw Webhook Log button → opens the webhook log sub-view
 *  - Export button → opens standard list view for export
 */

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { WaMessageRow } from "./wa_message_row";
import { WaWebhookLog } from "../webhook_log/wa_webhook_log";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function todayStart() {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return _isoDate(d);
}

function todayEnd() {
    const d = new Date();
    d.setHours(23, 59, 59, 999);
    return _isoDate(d);
}

function daysAgo(n) {
    const d = new Date();
    d.setDate(d.getDate() - n);
    d.setHours(0, 0, 0, 0);
    return _isoDate(d);
}

function startOfMonth() {
    const d = new Date();
    d.setDate(1);
    d.setHours(0, 0, 0, 0);
    return _isoDate(d);
}

function _isoDate(d) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function fmtLastFetched(ts) {
    if (!ts) return "";
    const diff = Math.floor((Date.now() - ts) / 1000);
    if (diff < 5)  return "Just now";
    if (diff < 60) return `${diff} secs ago`;
    const m = Math.floor(diff / 60);
    return `${m} min${m > 1 ? "s" : ""} ago`;
}

// ─── Component ────────────────────────────────────────────────────────────────

export class WaMessageLog extends Component {
    static template = "wa_communication.WaMessageLog";
    static props    = { "*": true };  // client actions receive arbitrary Odoo props

    static components = { WaMessageRow, WaWebhookLog };

    setup() {
        this.orm        = useService("orm");
        this.busService = useService("bus_service");

        this.state = useState({
            // Data
            rows:          [],
            total:         0,
            totals:        { total: 0, inbound: 0, cta: 0, failed: 0, total_cost: 0 },
            loading:       true,
            error:         null,

            // Pagination
            limit:         100,
            offset:        0,

            // Period filter
            dateFrom:      todayStart(),
            dateTo:        todayEnd(),
            dateLabel:     "Today",
            showCustomDate: false,

            // Tab filter  ('' | 'inbound' | 'outbound' | 'button_reply' | 'failed')
            kindFilter:    "",

            // Secondary filters
            templateFilter:  "",
            workflowFilter:  "",
            searchText:      "",

            // Dropdown options (loaded once)
            templates:     [],
            workflows:     [],
            showTemplateMenu: false,
            showWorkflowMenu: false,

            // Expanded row
            expandedRowId: null,

            // Sub-view
            showWebhookLog: false,

            // Last fetched
            lastFetchedAt: null,
            lastFetchedLabel: "",
        });

        // Refresh the "X mins ago" label every 30 s
        this._tickInterval = null;

        onMounted(() => {
            this._loadFilterOptions();
            this._loadData();
            this._subscribeBus();
            this._tickInterval = setInterval(() => {
                if (this.state.lastFetchedAt) {
                    this.state.lastFetchedLabel = fmtLastFetched(this.state.lastFetchedAt);
                }
            }, 30000);
        });

        onWillUnmount(() => {
            if (this._tickInterval) {
                clearInterval(this._tickInterval);
            }
        });
    }

    // ── Bus.bus live updates ──────────────────────────────────────────────────

    _subscribeBus() {
        this.busService.subscribe("wa_message_update", () => {
            // Throttle: only refresh if we're on the first page and not already loading
            if (this.state.offset === 0 && !this.state.loading) {
                this._loadData();
            }
        });
        this.busService.addChannel("wa_message_log");
    }

    // ── Data loading ─────────────────────────────────────────────────────────

    async _loadData() {
        this.state.loading = true;
        this.state.error   = null;
        try {
            const result = await this.orm.call(
                "wa.message.log",
                "get_messages",
                [],
                {
                    date_from: this.state.dateFrom,
                    date_to:   this.state.dateTo,
                    direction: this._directionFilter(),
                    kind:      this._kindFilter(),
                    search:    this.state.searchText,
                    workflow:  this.state.workflowFilter,
                    template:  this.state.templateFilter,
                    limit:     this.state.limit,
                    offset:    this.state.offset,
                }
            );
            this.state.rows   = result.rows || [];
            this.state.total  = result.total || 0;
            this.state.totals = result.totals || {};
        } catch (e) {
            this.state.error = e.message || "Failed to load messages";
        } finally {
            this.state.loading = false;
            this.state.lastFetchedAt    = Date.now();
            this.state.lastFetchedLabel = "Just now";
        }
    }

    async _loadFilterOptions() {
        try {
            const [templates, workflows] = await Promise.all([
                this.orm.call("wa.message.log", "get_templates", [], {}),
                this.orm.call("wa.message.log", "get_workflows", [], {}),
            ]);
            this.state.templates = templates || [];
            this.state.workflows = workflows || [];
        } catch (_) {
            // non-critical — filters still work without options
        }
    }

    _directionFilter() {
        if (this.state.kindFilter === "inbound")  return "inbound";
        if (this.state.kindFilter === "outbound") return "outbound";
        return "";
    }

    _kindFilter() {
        if (["inbound", "outbound", ""].includes(this.state.kindFilter)) return "";
        return this.state.kindFilter;   // 'button_reply', 'failed'
    }

    // ── Period presets ───────────────────────────────────────────────────────

    setPreset(label, from, to) {
        this.state.dateLabel = label;
        this.state.dateFrom  = from;
        this.state.dateTo    = to;
        this.state.offset    = 0;
        this._loadData();
    }

    onPresetToday()     { this.setPreset("Today",      todayStart(), todayEnd()); }
    onPresetYesterday() { this.setPreset("Yesterday",  daysAgo(1),   daysAgo(1).replace("00:00", "23:59")); }
    onPresetLast7d()    { this.setPreset("Last 7d",    daysAgo(7),   todayEnd()); }
    onPresetLast30d()   { this.setPreset("Last 30d",   daysAgo(30),  todayEnd()); }
    onPresetThisMonth() { this.setPreset("This Month", startOfMonth(), todayEnd()); }

    openCustomDate() {
        this.state.showCustomDate = true;
    }

    onCustomDateFrom(ev) {
        this.state.dateFrom = ev.target.value;
    }

    onCustomDateTo(ev) {
        this.state.dateTo = ev.target.value;
    }

    applyCustomDate() {
        this.state.dateLabel = `${this.state.dateFrom} → ${this.state.dateTo}`;
        this.state.showCustomDate = false;
        this.state.offset = 0;
        this._loadData();
    }

    // ── Tab filter ───────────────────────────────────────────────────────────

    setKindFilter(kind) {
        this.state.kindFilter = kind;
        this.state.offset     = 0;
        this._loadData();
    }

    // ── Secondary filters ────────────────────────────────────────────────────

    setTemplate(t) {
        this.state.templateFilter  = t;
        this.state.showTemplateMenu = false;
        this.state.offset          = 0;
        this._loadData();
    }

    setWorkflow(w) {
        this.state.workflowFilter  = w;
        this.state.showWorkflowMenu = false;
        this.state.offset          = 0;
        this._loadData();
    }

    onSearchInput(ev) {
        this.state.searchText = ev.target.value;
        if (this._searchTimer) clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(() => {
            this.state.offset = 0;
            this._loadData();
        }, 350);
    }

    // ── Row expand ───────────────────────────────────────────────────────────

    toggleRow(id) {
        this.state.expandedRowId = this.state.expandedRowId === id ? null : id;
    }

    // ── Refresh ──────────────────────────────────────────────────────────────

    onRefresh() {
        this.state.offset = 0;
        this._loadData();
    }

    // ── Pagination ───────────────────────────────────────────────────────────

    get hasPrev() { return this.state.offset > 0; }
    get hasNext()  { return this.state.offset + this.state.limit < this.state.total; }

    onPrev() {
        this.state.offset = Math.max(0, this.state.offset - this.state.limit);
        this._loadData();
    }

    onNext() {
        this.state.offset += this.state.limit;
        this._loadData();
    }

    // ── Webhook log ──────────────────────────────────────────────────────────

    openWebhookLog()  { this.state.showWebhookLog = true;  }
    closeWebhookLog() { this.state.showWebhookLog = false; }

    // ── Computed getters ─────────────────────────────────────────────────────

    get costDisplay() {
        const c = this.state.totals.total_cost || 0;
        return `₹${c.toFixed(2)}`;
    }

    get templateLabel() {
        return this.state.templateFilter || "Template";
    }

    get workflowLabel() {
        return this.state.workflowFilter || "Workflow";
    }
}

registry.category("actions").add("wa_message_log", WaMessageLog);
