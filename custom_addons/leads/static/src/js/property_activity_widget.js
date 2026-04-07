/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// ─── Status display metadata ───────────────────────────────────────────────
const STATUS_META = {
    lead:                                        { label: "Lead",               cls: "cd-badge-grey" },
    busy:                                        { label: "Busy",               cls: "cd-badge-grey" },
    ringing:                                     { label: "Ringing",            cls: "cd-badge-grey" },
    call_back_later:                             { label: "Call Back Later",    cls: "cd-badge-grey" },
    switched_off:                                { label: "Switched Off",       cls: "cd-badge-grey" },
    details_shared_of_property:                  { label: "Details Shared",     cls: "cd-badge-blue" },
    detail_shared_and_interested_for_site_visit: { label: "Details Shared",         cls: "cd-badge-blue" },
    site_visit_scheduled:                        { label: "SV Scheduled",       cls: "cd-badge-purple" },
    rescheduled:                                 { label: "Rescheduled",        cls: "cd-badge-purple" },
    site_visit_done:                             { label: "SV Done",            cls: "cd-badge-green" },
    option_not_matching_requirements:            { label: "Not Matching",       cls: "cd-badge-red" },
    no_requirements:                             { label: "No Requirements",    cls: "cd-badge-red" },
    requirement_closed:                          { label: "Req. Closed",        cls: "cd-badge-red" },
    property_sold_out:                           { label: "Sold Out",           cls: "cd-badge-red" },
    budget_not_sufficient:                       { label: "Budget Issue",       cls: "cd-badge-red" },
    number_not_in_use_wrong_number:              { label: "Wrong Number",       cls: "cd-badge-red" },
    other:                                       { label: "Other",              cls: "cd-badge-grey" },
};

const ALL_STATUSES = Object.keys(STATUS_META);

// Groups for the filter bar (order matters — displayed left → right)
const FILTER_GROUPS = [
    { key: "all",                   label: "All" },
    { key: "contacted",             label: "Contacted",        statuses: ["busy","ringing","call_back_later","switched_off","other"] },
    { key: "details_shared",        label: "Details Shared",   statuses: ["details_shared_of_property","detail_shared_and_interested_for_site_visit"] },
    { key: "site_visit_scheduled",  label: "SV Scheduled",     statuses: ["site_visit_scheduled","rescheduled"] },
    { key: "site_visit_done",       label: "SV Done",          statuses: ["site_visit_done"] },
    { key: "not_interested",        label: "Not Interested",   statuses: ["option_not_matching_requirements","no_requirements","requirement_closed","property_sold_out","budget_not_sufficient","number_not_in_use_wrong_number"] },
];

const FEEDBACK_GENERAL_LABELS = {
    buyer_did_not_visit_property:   "Buyer Did Not Visit",
    buyer_not_interested:           "Not Interested",
    buyer_not_picking_call:         "Not Picking Call",
    visit_needs_to_be_rescheduled:  "Needs Rescheduling",
    other:                          "Other",
};

const FEEDBACK_SV_LABELS = {
    buyer_liked_property:           "Liked Property",
    buyer_requirement_closed:       "Req. Closed",
    buyer_visit_from_outside:       "Outside Visit",
    buyer_not_pickup_call:          "Not Picking Call",
    planning_for_second_visit:      "2nd Visit Planned",
    negotiation_stage:              "Negotiation",
    visit_done_confirmed_by_owner:  "Owner Confirmed",
    looking_for_more_options:       "More Options",
    price_is_high:                  "Price Too High",
    location_mismatch:              "Location Mismatch",
    deal_closed:                    "Deal Closed ✓",
    other:                          "Other",
};

export class PropertyActivityWidget extends Component {
    static template = "leads.PropertyActivityWidget";
    static props = { ...standardFieldProps };

    setup() {
        this.state = useState({
            loading: true,
            error: null,
            data: null,
            // Filters
            activeFilter: "all",       // filter group key
            activeType: "all",         // "all" | "primary" | "recommended"
            searchText: "",
            // Tab
            activeTab: "activity",     // "activity" | "site_visits" | "summary"
            // Site visit sub-tab
            svTab: "all",
        });
        onWillStart(() => this._load(this.props.record.resId));
        onWillUpdateProps((nextProps) => {
            if (nextProps.record.resId !== this.props.record.resId) {
                this._load(nextProps.record.resId);
            }
        });
    }

    get propertyId() {
        return this.props.record.resId;
    }

    async _load(propertyId) {
        const pid = propertyId;
        if (!pid) return;
        this.state.loading = true;
        this.state.error = null;
        try {
            const result = await rpc("/web/leads/property_activity/" + pid, {});
            if (result && result.error) {
                this.state.error = result.error;
            } else {
                this.state.data = result;
            }
        } catch (e) {
            this.state.error = "Failed to load property activity.";
        } finally {
            this.state.loading = false;
        }
    }

    get filteredActivity() {
        if (!this.state.data) return [];
        let rows = this.state.data.activity || [];

        // Type filter
        if (this.state.activeType !== "all") {
            rows = rows.filter(r => r.type === this.state.activeType);
        }

        // Status group filter
        if (this.state.activeFilter !== "all") {
            const group = FILTER_GROUPS.find(g => g.key === this.state.activeFilter);
            if (group && group.statuses) {
                rows = rows.filter(r => group.statuses.includes(r.current_status));
            }
        }

        // Text search (name, phone, source)
        const q = this.state.searchText.trim().toLowerCase();
        if (q) {
            rows = rows.filter(r =>
                (r.lead_name || "").toLowerCase().includes(q) ||
                (r.lead_phone || "").toLowerCase().includes(q) ||
                (r.source || "").toLowerCase().includes(q) ||
                (r.assigned_rm || "").toLowerCase().includes(q)
            );
        }
        return rows;
    }

    get kpi() {
        return this.state.data?.kpi || {};
    }
    get sourceBreakdown() {
        return Object.entries(this.state.data?.source_breakdown || {})
            .sort((a, b) => (b[1].primary + b[1].recommended) - (a[1].primary + a[1].recommended));
    }
    get siteVisits() {
        return this.state.data?.site_visits || {};
    }
    // Builds visit chain groups using previous_visit_id linked-list linkage.
    // This is more reliable than root_visit_id grouping because root_visit_id
    // may not be populated transitively in all DB states.
    //
    // Algorithm:
    //   1. Build a "who follows whom" map from previous_visit_id.
    //   2. Root visits = those with no previous_visit_id in our set.
    //   3. Walk each root forward to collect the full chain.
    //   4. latest = last visit in the chain; history = everything before it.
    //   5. Tab is determined solely by latest.sv_bucket (computed in Python).
    //
    // Rules per user spec:
    //   - NEVER break a chain mid-way — all reschedules stay inside the chain.
    //   - Terminal visits (completed/cancelled) end the chain as the root row.
    //   - The tab shown is always based on the LAST visit in the chain.
    get groupedSiteVisits() {
        const all = this.siteVisits.all || [];
        if (!all.length) return [];

        // Index by visit_id for O(1) lookup.
        const byId = {};
        for (const row of all) byId[row.visit_id] = row;

        // Map: previous_visit_id → the visit that follows it.
        const nextOf = {};
        for (const row of all) {
            if (row.previous_visit_id && byId[row.previous_visit_id]) {
                nextOf[row.previous_visit_id] = row;
            }
        }

        // Root visits: those whose previous_visit_id is absent or not in our set.
        const roots = all.filter(
            r => !r.previous_visit_id || !byId[r.previous_visit_id]
        );

        const groups = [];
        for (const root of roots) {
            const chain = [];
            let cur = root;
            while (cur) {
                chain.push(cur);
                cur = nextOf[cur.visit_id] || null;
            }
            const latest = chain[chain.length - 1];
            groups.push({
                rootId:          root.visit_id,
                latest,
                history:         chain.slice(0, -1),  // everything before latest
                rescheduleCount: chain.length - 1,
            });
        }

        groups.sort((a, b) =>
            (b.latest.scheduled_datetime || "").localeCompare(a.latest.scheduled_datetime || "")
        );
        return groups;
    }

    // Tab badge counts — keyed on sv_bucket from controller.
    get svGroupCounts() {
        let upcoming = 0, pending = 0, completed = 0, cancelled = 0;
        for (const g of this.groupedSiteVisits) {
            const b = g.latest.sv_bucket;
            if (b === "completed")             completed++;
            else if (b === "cancelled")        cancelled++;
            else if (b === "upcoming")         upcoming++;
            else if (b === "pending_feedback") pending++;
        }
        return { upcoming, pending_feedback: pending, completed, cancelled };
    }

    // Returns the subset of groups relevant to the active sub-tab.
    get currentSvList() {
        if (this.state.svTab === "all") return this.groupedSiteVisits;
        return this.groupedSiteVisits.filter(g => g.latest.sv_bucket === this.state.svTab);
    }
    get filterGroups() {
        return FILTER_GROUPS;
    }

    statusLabel(key) {
        return STATUS_META[key]?.label || key;
    }
    statusCls(key) {
        return STATUS_META[key]?.cls || "cd-badge-grey";
    }
    // CSS class for site visit status — uses status_type from lead.site.visit.status model
    svStatusCls(status_type) {
        const map = {
            scheduled:   "cd-badge-purple",
            rescheduled: "cd-badge-orange",
            completed:   "cd-badge-green",
            cancelled:   "cd-badge-red",
            no_show:     "cd-badge-red",
            custom:      "cd-badge-grey",
        };
        return map[status_type] || "cd-badge-grey";
    }
    feedbackLabel(key) {
        return FEEDBACK_GENERAL_LABELS[key] || FEEDBACK_SV_LABELS[key] || key;
    }
    formatDate(iso) {
        if (!iso) return "—";
        return iso.substring(0, 10);
    }

    setFilter(key) { this.state.activeFilter = key; }
    setType(t) { this.state.activeType = t; }
    setTab(t) { this.state.activeTab = t; }
    setSvTab(t) { this.state.svTab = t; }
    onSearch(ev) { this.state.searchText = ev.target.value; }

    exportCsv() {
        // Triggers GET download — browser handles the file save
        window.location.href = "/web/leads/property_activity/" + this.propertyId + "/export.csv";
    }
}

// Register as a field widget so it can be used in XML views with widget="property_activity_widget".
// No extractProps override — let Odoo pass the full standardFieldProps (including `record`).
registry.category("fields").add("property_activity_widget", {
    component: PropertyActivityWidget,
    displayName: "Property Activity",
    supportedTypes: ["integer"],
});
