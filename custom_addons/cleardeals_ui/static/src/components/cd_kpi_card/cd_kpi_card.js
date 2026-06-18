/** @odoo-module */

import { Component, useState } from "@odoo/owl";

/**
 * CdKpiCard — a headline KPI: big value, vs-previous delta (semantic colour),
 * a sub-line, an optional sparkline, and an optional info tooltip.
 *
 * Props:
 *   label   {String}  Metric name.
 *   value   {String}  Pre-formatted primary value ("71%", "2m 30s", "₹2.5k").
 *   sub     {String}  Optional secondary line (denominator / context).
 *   delta   {Number}  Optional % change vs previous period.
 *   invert  {Boolean} True when *lower is better* (response time, failures, cost)
 *                     — flips the delta colour so a drop reads as good.
 *   spark   {Array}   Optional numbers for a tiny sparkline.
 *   tooltip {String}  Optional plain-English definition (shown on the info icon).
 *   accent  {String}  Optional left accent: "good" | "warn" | "bad".
 *   breakdown {Array} Optional [{label, value}] — labelled mini bars under the
 *                     value (e.g. failure reasons + counts).
 */
export class CdKpiCard extends Component {
    static template = "cleardeals_ui.CdKpiCard";

    static props = {
        label:   { type: String },
        value:   { type: [String, Number] },
        sub:     { type: String, optional: true },
        delta:     { type: Number, optional: true },
        deltaUnit: { type: String, optional: true },
        invert:  { type: Boolean, optional: true },
        spark:   { type: Array, optional: true },
        tooltip: { type: String, optional: true },
        accent:  { type: String, optional: true },
        breakdown: { type: Array, optional: true },
        onClick: { type: Function, optional: true },
    };

    setup() {
        this.ui = useState({ showTip: false });
    }

    onCardClick() {
        if (this.props.onClick) {
            this.props.onClick();
        }
    }

    /** "up" | "down" | null */
    get deltaDir() {
        if (this.props.delta == null) return null;
        return this.props.delta >= 0 ? "up" : "down";
    }

    /** "good" | "bad" | null — accounts for invert (lower-is-better). */
    get deltaTone() {
        if (this.props.delta == null || this.props.delta === 0) return null;
        const rising = this.props.delta > 0;
        const good = this.props.invert ? !rising : rising;
        return good ? "good" : "bad";
    }

    get deltaText() {
        if (this.props.delta == null) return "";
        const unit = this.props.deltaUnit === "pts" ? " pts" : "%";
        const abs = Math.abs(this.props.delta);
        // A % change off a near-zero base (e.g. ₹1 → ₹17) explodes into a
        // meaningless figure — cap the display so it reads cleanly.
        if (unit === "%" && abs >= 1000) return "999%+";
        return `${abs.toFixed(1)}${unit}`;
    }

    /** Total across all breakdown items (≥1 to avoid divide-by-zero). */
    get bdTotal() {
        return (this.props.breakdown || []).reduce((s, b) => s + (b.value || 0), 0) || 1;
    }

    /** Top 3 breakdown items for the compact legend (already sorted by caller). */
    get bdTop() {
        return (this.props.breakdown || []).slice(0, 3);
    }

    /** Segment width as a share of the total (min 2% so a tiny slice is visible). */
    segPct(value) {
        return Math.max(2, (value / this.bdTotal) * 100);
    }

    /** Distinct categorical colour per breakdown segment, by position. */
    segColor(i) {
        const palette = ["#dc2626", "#ea580c", "#d97706", "#ca8a04",
            "#9333ea", "#0891b2", "#64748b"];
        return palette[i % palette.length];
    }

    /** SVG points for the sparkline polyline (0..100 viewBox). */
    get sparkPoints() {
        const s = this.props.spark || [];
        if (s.length < 2) return "";
        const max = Math.max(...s, 1);
        const min = Math.min(...s, 0);
        const span = max - min || 1;
        const stepX = 100 / (s.length - 1);
        return s
            .map((v, i) => `${(i * stepX).toFixed(1)},${(26 - ((v - min) / span) * 22).toFixed(1)}`)
            .join(" ");
    }
}
