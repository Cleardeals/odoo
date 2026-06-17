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
    };

    setup() {
        this.ui = useState({ showTip: false });
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
        return `${Math.abs(this.props.delta).toFixed(1)}${unit}`;
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
