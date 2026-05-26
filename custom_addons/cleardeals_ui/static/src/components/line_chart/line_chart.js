/** @odoo-module */

import { Component } from "@odoo/owl";

// ── SVG coordinate constants ─────────────────────────────────────────────────
// ViewBox: 0 0 1000 220.  Chart area: x 20–980 (960 wide), y 15–165 (150 tall).
// X-axis labels sit at y ≈ 193 (28 px below chart bottom).
const W = 1000, H = 220;
const PL = 20, PR = 20, PT = 15, PB = 55;
const CW = W - PL - PR;   // 960
const CH = H - PT - PB;   // 150

/**
 * CdLineChart — SVG line chart for time-series WA send volume.
 *
 * Props:
 *   bars  {Array}   Each element: {hour_label (ISO string), sent, failed}
 *   title {String}  Optional — not rendered (section title lives in parent).
 *
 * hour_label format:
 *   "2026-05-25T14:00:00" → rendered as "14:00"   (hourly bucket)
 *   "2026-05-25"          → rendered as "25 May"   (daily bucket)
 */
export class CdLineChart extends Component {
    static template = "cleardeals_ui.LineChart";

    static props = {
        bars:  { type: Array },
        title: { type: String, optional: true },
    };

    // ── Coordinate helpers ────────────────────────────────────────────────────

    get _maxSent() {
        return Math.max(...this.props.bars.map((b) => b.sent || 0), 1);
    }

    _px(i) {
        const n = this.props.bars.length;
        if (n <= 1) return PL + CW / 2;
        return PL + (i / (n - 1)) * CW;
    }

    _py(val) {
        return PT + CH - (val / this._maxSent) * CH;
    }

    // ── SVG path data ─────────────────────────────────────────────────────────

    get sentPolyline() {
        return this.props.bars
            .map((b, i) => `${this._px(i)},${this._py(b.sent || 0)}`)
            .join(" ");
    }

    /** Closed polygon for the area fill below the sent line. */
    get areaPolygon() {
        const n = this.props.bars.length;
        if (n === 0) return "";
        const pts = this.props.bars
            .map((b, i) => `${this._px(i)},${this._py(b.sent || 0)}`)
            .join(" ");
        const baseY = PT + CH;
        return `${this._px(0)},${baseY} ${pts} ${this._px(n - 1)},${baseY}`;
    }

    // ── Enriched data ─────────────────────────────────────────────────────────

    get enrichedBars() {
        return this.props.bars.map((b, i) => ({
            ...b,
            cx:    this._px(i),
            cy:    this._py(b.sent || 0),
            label: this._fmtLabel(b.hour_label),
        }));
    }

    /** Subset of bars whose labels are displayed on the x-axis (max ~10). */
    get labeledBars() {
        const bars = this.enrichedBars;
        const n = bars.length;
        if (n <= 10) return bars;
        const step = Math.ceil(n / 10);
        return bars.filter((_, i) => i % step === 0 || i === n - 1);
    }

    /** Faint horizontal reference lines at 0 %, 50 %, 100 % of max. */
    get gridLines() {
        const max = this._maxSent;
        return [0, 0.5, 1.0].map((pct) => ({
            y:     PT + CH - pct * CH,
            label: pct === 0 ? "0" : Math.round(pct * max),
        }));
    }

    // ── Fixed SVG coordinates exposed to the template ─────────────────────────
    get labelY() { return PT + CH + 28; }
    get baseY()  { return PT + CH; }

    // ── Label formatter ───────────────────────────────────────────────────────

    _fmtLabel(isoStr) {
        if (!isoStr) return "";
        if (isoStr.includes("T")) {
            // Hourly bucket: "2026-05-25T14:00:00" → "14:00"
            return isoStr.split("T")[1].slice(0, 5);
        }
        // Daily bucket: "2026-05-25" → "25 May"
        const d = new Date(isoStr + "T00:00:00");
        return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
    }
}
