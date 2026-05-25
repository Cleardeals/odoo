/** @odoo-module */

import { Component } from "@odoo/owl";

/**
 * CdBarChart — pure CSS flexbox bar chart for hourly WA send volume.
 *
 * Props:
 *   bars  {Array}   Each element: {hour, hour_label, sent, failed}
 *   title {String}  Optional section title rendered above the chart.
 *
 * Not a field widget — imported directly by WaDashboard.
 */
export class CdBarChart extends Component {
    static template = "cleardeals_ui.BarChart";

    static props = {
        bars:  { type: Array },
        title: { type: String, optional: true },
    };

    /** Largest (sent + failed) value across all bars; minimum 1 to avoid /0. */
    get maxValue() {
        let max = 1;
        for (const b of this.props.bars) {
            const total = (b.sent || 0) + (b.failed || 0);
            if (total > max) max = total;
        }
        return max;
    }

    /** Bars with pixel-percentage heights pre-computed (0–100 integers). */
    get enrichedBars() {
        const max = this.maxValue;
        return this.props.bars.map((b) => ({
            ...b,
            sentPct:   Math.round(((b.sent   || 0) / max) * 100),
            failedPct: Math.round(((b.failed || 0) / max) * 100),
        }));
    }
}
