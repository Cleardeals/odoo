/** @odoo-module */

/**
 * WaWebhookLog — Raw Webhook Log developer panel
 *
 * Full-screen overlay opened from the Message Log header.
 * Shows the wa.event.log table in a two-panel layout:
 *   Left:  list of events (Processed/Error, event type, phone, excerpt, timestamp)
 *   Right: selected event detail (lead info, JSON payload, Copy JSON button)
 *
 * Accessed via:  Raw Webhook Log button in the Message Log header.
 * Closed via:    Back to Message Log link.
 */

import { Component, useState, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

function _todayStr() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// Maps event type to the filter tab category shown in the UI
function eventCategory(eventType) {    if (!eventType) return "other";
    if (eventType.includes("click") || eventType.includes("button_reply")) return "cta";
    if (eventType.includes("inbound") || eventType === "wa_message_inbound") return "inbound";
    if (eventType.includes("outbound") || eventType === "wa_message_outbound") return "outbound";
    if (eventType.includes("failed") || eventType.includes("error")) return "failed";
    return "other";
}

export class WaWebhookLog extends Component {
    static template = "wa_communication.WaWebhookLog";
    static props = {
        onClose: Function,
    };

    setup() {
        this.orm   = useService("orm");

        this.state = useState({
            rows:          [],
            total:         0,
            loading:       true,
            error:         null,
            selectedRow:   null,
            categoryFilter: "",   // '' | 'cta' | 'inbound' | 'outbound' | 'failed'
            searchText:    "",
            copySuccess:   false,
            // Date range — defaults to today
            dateFrom:      _todayStr(),
            dateTo:        _todayStr(),
            showCustomDate: false,
        });

        onMounted(() => {
            this._loadData();
        });
    }

    // ── Data loading ─────────────────────────────────────────────────────────

    async _loadData() {
        this.state.loading = true;
        this.state.error   = null;
        try {
            const result = await this.orm.call(
                "wa.message.log",
                "get_webhook_events",
                [],
                {
                    date_from:           this.state.dateFrom,
                    date_to:             this.state.dateTo,
                    search:              this.state.searchText,
                    event_type_filter:   "",
                    limit:               200,
                    offset:              0,
                }
            );
            this.state.rows  = result.rows || [];
            this.state.total = result.total || 0;
            // Auto-select the first row
            if (this.state.rows.length > 0 && !this.state.selectedRow) {
                this.state.selectedRow = this.state.rows[0];
            }
        } catch (e) {
            this.state.error = e.message || "Failed to load webhook events";
        } finally {
            this.state.loading = false;
        }
    }

    // ── Date range ───────────────────────────────────────────────────────────

    openCustomDate() { this.state.showCustomDate = !this.state.showCustomDate; }

    onDateFrom(ev) { this.state.dateFrom = ev.target.value; }
    onDateTo(ev)   { this.state.dateTo   = ev.target.value; }

    applyDateRange() {
        this.state.showCustomDate = false;
        this._loadData();
    }

    // ── Filter + selection ───────────────────────────────────────────────────

    setCategoryFilter(cat) {
        this.state.categoryFilter = cat;
        this.state.selectedRow    = null;
    }

    selectRow(row) {
        this.state.selectedRow  = row;
        this.state.copySuccess  = false;
    }

    onSearchInput(ev) {
        this.state.searchText = ev.target.value;
        if (this._searchTimer) clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(() => this._loadData(), 350);
    }

    // ── Copy JSON ────────────────────────────────────────────────────────────

    async copyJson() {
        const payload = this.state.selectedRow?.payload || "{}";
        try {
            await navigator.clipboard.writeText(payload);
            this.state.copySuccess = true;
            setTimeout(() => { this.state.copySuccess = false; }, 2000);
        } catch (_) { /* clipboard not available */ }
    }

    // ── Computed getters ─────────────────────────────────────────────────────

    get filteredRows() {
        const rows = this.state.rows;
        if (!this.state.categoryFilter) return rows;
        return rows.filter(r => eventCategory(r.event_type) === this.state.categoryFilter);
    }

    get categoryCounts() {
        const counts = { "": 0, cta: 0, inbound: 0, outbound: 0, failed: 0 };
        for (const r of this.state.rows) {
            counts[""] += 1;
            const cat = eventCategory(r.event_type);
            if (counts[cat] !== undefined) counts[cat] += 1;
        }
        return counts;
    }

    get prettyPayload() {
        if (!this.state.selectedRow) return "";
        try {
            return JSON.stringify(JSON.parse(this.state.selectedRow.payload || "{}"), null, 2);
        } catch (_) {
            return this.state.selectedRow.payload || "";
        }
    }

    statusIcon(row) {
        return row.status === "processed" ? "✓ Processed" : "✗ Error";
    }

    statusClass(row) {
        return row.status === "processed"
            ? "cd-webhook-log__event-status cd-webhook-log__event-status--ok"
            : "cd-webhook-log__event-status cd-webhook-log__event-status--err";
    }

    eventLabel(eventType) {
        if (!eventType) return "Unknown";
        // Convert snake_case to Title Case
        return eventType.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    }

    payloadExcerpt(row) {
        try {
            const p = JSON.parse(row.payload || "{}");
            const phone = p?.data?.customer?.channel_phone_number
                || p?.phone
                || "";
            const msg   = p?.data?.message?.message
                || p?.message_text
                || "";
            return { phone, msg: (msg || "").slice(0, 40) };
        } catch (_) {
            return { phone: "", msg: "" };
        }
    }
}
