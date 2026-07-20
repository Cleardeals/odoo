/** @odoo-module */

import { Component } from "@odoo/owl";

/**
 * CdMetricCard — headline KPI card for the WA Dashboard.
 *
 * Props:
 *   label      {String}         Card title ("Messages Sent", etc.)
 *   value      {Number|String}  Primary metric value.
 *   subValue   {String}         Optional secondary value shown after ·
 *   trend      {Number}         Optional % change vs previous period.
 *   trendLabel {String}         Optional label appended to the trend line.
 *   variant    {String}         "default" | "warning" | "danger"
 *   breakdown  {String}         Optional small text below the trend line.
 *   hint       {String}         Optional explanation — shows an ⓘ marker next
 *                               to the label with this text as a hover tooltip.
 *
 * Not a field widget — imported directly by WaDashboard.
 */
export class CdMetricCard extends Component {
    static template = "cleardeals_ui.MetricCard";

    static props = {
        label:      { type: String },
        value:      { type: [Number, String] },
        subValue:   { type: String,  optional: true },
        trend:      { type: Number,  optional: true },
        trendLabel: { type: String,  optional: true },
        variant:    { type: String,  optional: true },
        breakdown:  { type: String,  optional: true },
        hint:       { type: String,  optional: true },
    };

    static defaultProps = {
        variant: "default",
    };

    get variantClass() {
        return `cd-metric-card--${this.props.variant || "default"}`;
    }

    /** "up" | "down" | null */
    get trendDirection() {
        if (this.props.trend == null) return null;
        return this.props.trend >= 0 ? "up" : "down";
    }

    /** Absolute trend value with %, e.g. "12.3%" */
    get trendDisplay() {
        if (this.props.trend == null) return "";
        return `${Math.abs(this.props.trend).toFixed(1)}%`;
    }
}
