/** @odoo-module */

import { Component } from "@odoo/owl";

/**
 * CdHeatmap — a weekday × hour coverage grid for the By-RM operations band.
 *
 * Each cell is a (weekday, hour) bucket of buyer-message *arrivals* coloured by
 * how many were *answered* within SLA — so staffing gaps (high arrivals, low
 * answer rate) light up red and managers can see *when* to add cover. Cell
 * intensity scales with volume so a busy problem-hour dominates a quiet one.
 *
 * Props:
 *   cells     {Array}  [{weekday(0=Mon..6=Sun), hour(0-23), arrivals, answered}]
 *   startHour {Number} Business-window start hour (display hint).
 *   endHour   {Number} Business-window end hour (display hint).
 *   emptyText {String}
 */
export class CdHeatmap extends Component {
    static template = "cleardeals_ui.CdHeatmap";

    static props = {
        cells:     { type: Array },
        startHour: { type: Number, optional: true },
        endHour:   { type: Number, optional: true },
        emptyText: { type: String, optional: true },
    };

    static defaultProps = {
        startHour: 9,
        endHour: 19,
        emptyText: "No buyer messages in this period.",
    };

    static DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

    setup() {
        // Index cells by "wd:hr" for O(1) grid lookup.
        this._byKey = {};
        let maxArrivals = 0;
        for (const c of this.props.cells || []) {
            this._byKey[`${c.weekday}:${c.hour}`] = c;
            if (c.arrivals > maxArrivals) maxArrivals = c.arrivals;
        }
        this._maxArrivals = maxArrivals;
    }

    get hasData() {
        return (this.props.cells || []).length > 0;
    }

    /** Hours to render: the business window widened to cover any off-hours data. */
    get hours() {
        let lo = this.props.startHour;
        let hi = this.props.endHour;
        for (const c of this.props.cells || []) {
            if (c.arrivals > 0) {
                if (c.hour < lo) lo = c.hour;
                if (c.hour > hi) hi = c.hour;
            }
        }
        const out = [];
        for (let h = lo; h <= hi; h++) out.push(h);
        return out;
    }

    get days() {
        return CdHeatmap.DAYS;
    }

    cell(wd, hr) {
        return this._byKey[`${wd}:${hr}`] || null;
    }

    hourLabel(h) {
        return String(h).padStart(2, "0");
    }

    cellClass(wd, hr) {
        const c = this.cell(wd, hr);
        if (!c || !c.arrivals) return "cd-hm__cell is-empty";
        const rate = c.answered / c.arrivals;
        const tone = rate >= 0.9 ? "is-good" : rate >= 0.7 ? "is-warn" : "is-bad";
        return `cd-hm__cell ${tone}`;
    }

    cellStyle(wd, hr) {
        const c = this.cell(wd, hr);
        if (!c || !c.arrivals || !this._maxArrivals) return "";
        // Floor at 0.5 so the count stays legible; scale up with volume.
        const intensity = 0.5 + 0.5 * (c.arrivals / this._maxArrivals);
        return `opacity: ${intensity.toFixed(2)};`;
    }

    cellTitle(wd, hr) {
        const c = this.cell(wd, hr);
        const day = CdHeatmap.DAYS[wd];
        if (!c || !c.arrivals) return `${day} ${this.hourLabel(hr)}:00 — no messages`;
        const pct = Math.round((c.answered / c.arrivals) * 100);
        return `${day} ${this.hourLabel(hr)}:00 — ${c.arrivals} in, ${c.answered} answered (${pct}%)`;
    }
}
