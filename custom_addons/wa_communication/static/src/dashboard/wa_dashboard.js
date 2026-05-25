/** @odoo-module */

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

import {
    CdMetricCard,
    CdWorkflowHealthTable,
    CdBarChart,
    CdRecentFailuresTable,
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
        CdWorkflowHealthTable,
        CdBarChart,
        CdRecentFailuresTable,
    };

    // ── Services ─────────────────────────────────────────────────────────────

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading:           true,
            metrics:           null,
            workflowHealth:    [],
            hourlyData:        [],
            failures:          [],
            workflows:         [],
            // Global date filter
            dateFrom:          this._todayStart(),
            dateTo:            this._todayEnd(),
            dateLabel:         "Today",
            // Workflow filter
            workflowSlug:      "",
            workflowName:      "All Workflows",
            workflowSearch:    "",
            // Dropdown visibility
            showDatePicker:    false,
            showWorkflowMenu:  false,
            // Custom date range inputs (ISO date strings)
            customFrom:        "",
            customTo:          "",
            // Section-level time range selectors
            healthTimeRange:   "12h",
            chartTimeRange:    "12h",
            // Last refresh timestamp
            lastFetched:       null,
        });

        onMounted(() => {
            this._loadAll();
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

    _hoursAgo(n) {
        const d = new Date(Date.now() - n * 3600 * 1000);
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

    /** Return {from, to} for a named time range used by the sub-section selectors. */
    _timeRangeDates(range) {
        const now = this._isoLocal(new Date());
        switch (range) {
            case "12h": return { from: this._hoursAgo(12), to: now };
            case "24h": return { from: this._hoursAgo(24), to: now };
            case "7d":  return { from: this._daysAgo(7),   to: now };
            case "30d": return { from: this._daysAgo(30),  to: now };
            default:    return { from: this._hoursAgo(12), to: now };
        }
    }

    /** Format a Date as a local ISO datetime string (no timezone suffix). */
    _isoLocal(d) {
        const pad = (n) => String(n).padStart(2, "0");
        return (
            `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
            `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
        );
    }

    // ── Data loaders ─────────────────────────────────────────────────────────

    async _loadAll() {
        this.state.loading = true;
        try {
            await Promise.all([
                this._loadMetrics(),
                this._loadWorkflowHealth(),
                this._loadHourlyData(),
                this._loadFailures(),
                this._loadWorkflows(),
            ]);
            this.state.lastFetched = new Date().toLocaleTimeString();
        } finally {
            this.state.loading = false;
        }
    }

    async _loadMetrics() {
        this.state.metrics = await this.orm.call(
            "wa.dashboard", "get_metrics", [],
            {
                date_from:     this.state.dateFrom,
                date_to:       this.state.dateTo,
                workflow_slug: this.state.workflowSlug,
            }
        );
    }

    async _loadWorkflowHealth() {
        const { from, to } = this._timeRangeDates(this.state.healthTimeRange);
        this.state.workflowHealth = await this.orm.call(
            "wa.dashboard", "get_workflow_health", [],
            { date_from: from, date_to: to }
        );
    }

    async _loadHourlyData() {
        const { from, to } = this._timeRangeDates(this.state.chartTimeRange);
        this.state.hourlyData = await this.orm.call(
            "wa.dashboard", "get_hourly_volume", [],
            {
                date_from:     from,
                date_to:       to,
                workflow_slug: this.state.workflowSlug,
            }
        );
    }

    async _loadFailures() {
        this.state.failures = await this.orm.call(
            "wa.dashboard", "get_recent_failures", [],
            { workflow_slug: this.state.workflowSlug }
        );
    }

    async _loadWorkflows() {
        this.state.workflows = await this.orm.searchRead(
            "wa.workflow",
            [],
            ["id", "name", "slug", "is_active"],
            { order: "name" }
        );
    }

    // ── Actions ──────────────────────────────────────────────────────────────

    async onRefresh() {
        await this._loadAll();
    }

    // --- Date picker presets ---

    _applyPreset(label, dateFrom, dateTo) {
        this.state.dateLabel    = label;
        this.state.dateFrom     = dateFrom;
        this.state.dateTo       = dateTo;
        this.state.showDatePicker = false;
        this._loadMetrics();
        this._loadHourlyData();
        this._loadFailures();
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

    // --- Workflow filter ---

    onSelectWorkflow(wf) {
        this.state.workflowSlug      = wf ? wf.slug : "";
        this.state.workflowName      = wf ? wf.name : "All Workflows";
        this.state.showWorkflowMenu  = false;
        this.state.workflowSearch    = "";
        this._loadMetrics();
        this._loadHourlyData();
        this._loadFailures();
    }

    get filteredWorkflows() {
        const q = (this.state.workflowSearch || "").toLowerCase();
        if (!q) return this.state.workflows;
        return this.state.workflows.filter(
            (wf) => wf.name.toLowerCase().includes(q) || wf.slug.toLowerCase().includes(q)
        );
    }

    // --- Workflow toggle ---

    async onToggleWorkflow(workflowId) {
        await this.orm.call("wa.workflow", "action_toggle_active", [[workflowId]]);
        // Refresh health table and local workflow list so toggle state updates
        await Promise.all([this._loadWorkflowHealth(), this._loadWorkflows()]);
    }

    // --- Section time-range selectors ---

    async onHealthTimeRangeChange(range) {
        this.state.healthTimeRange = range;
        await this._loadWorkflowHealth();
    }

    async onChartTimeRangeChange(range) {
        this.state.chartTimeRange = range;
        await this._loadHourlyData();
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

    get metricsReady() {
        return !this.state.loading && this.state.metrics !== null;
    }

    get failedVariant() {
        if (!this.state.metrics) return "default";
        return this.state.metrics.failed > 0 ? "warning" : "default";
    }

    get failedBreakdownText() {
        if (!this.state.metrics || !this.state.metrics.failed_breakdown) return "";
        return Object.entries(this.state.metrics.failed_breakdown)
            .map(([label, count]) => `${label}: ${count}`)
            .join(" · ");
    }
}

registry.category("actions").add("wa_dashboard", WaDashboard);
