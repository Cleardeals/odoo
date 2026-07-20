/** @odoo-module */

import { Component, useState } from "@odoo/owl";

// ── SVG coordinate constants ─────────────────────────────────────────────────
// ViewBox: 0 0 1000 240.  Chart area: x 46–980 (left gutter holds the Y labels),
// y 15–175.  X-axis labels sit ~26 px below the chart bottom.
const W = 1000, H = 240;
const PL = 46, PR = 20, PT = 15, PB = 65;
const CW = W - PL - PR;   // 934
const CH = H - PT - PB;   // 160

/**
 * CdLineChart — SVG line chart for time-series WA send volume.
 *
 * Props:
 *   bars  {Array}   Each element: {hour_label (ISO string, already IST), sent, failed}
 *   title {String}  Optional — not rendered (section title lives in parent).
 *
 * hour_label format (server buckets in Asia/Kolkata):
 *   "2026-05-25T14:00:00" → rendered as "2:00 PM"  (hourly bucket)
 *   "2026-05-25"          → rendered as "25 May"    (daily bucket)
 */
export class CdLineChart extends Component {
    static template = "cleardeals_ui.LineChart";

    static props = {
        bars:  { type: Array },
        title: { type: String, optional: true },
    };

    setup() {
        // Index of the currently hovered data point (-1 = none).
        this.hover = useState({ index: -1 });
    }

    // ── Coordinate helpers ────────────────────────────────────────────────────

    get _max() {
        // Scale to the tallest point across BOTH series so neither clips.
        return Math.max(
            ...this.props.bars.map((b) => b.sent || 0),
            ...this.props.bars.map((b) => b.failed || 0),
            1,
        );
    }

    _px(i) {
        const n = this.props.bars.length;
        if (n <= 1) return PL + CW / 2;
        return PL + (i / (n - 1)) * CW;
    }

    _py(val) {
        return PT + CH - (val / this._max) * CH;
    }

    /** Points [{x, y}] for a series keyed by ``field``. */
    _points(field) {
        return this.props.bars.map((b, i) => ({ x: this._px(i), y: this._py(b[field] || 0) }));
    }

    /**
     * A smooth SVG path through the given points using a Catmull-Rom spline
     * converted to cubic béziers — gives the flowing curve of the reference
     * chart instead of hard straight segments.
     */
    _smoothPath(pts) {
        if (pts.length === 0) return "";
        if (pts.length === 1) return `M ${pts[0].x} ${pts[0].y}`;
        const t = 0.2; // tension — lower is straighter, higher is loopier
        let d = `M ${pts[0].x} ${pts[0].y}`;
        for (let i = 0; i < pts.length - 1; i++) {
            const p0 = pts[i - 1] || pts[i];
            const p1 = pts[i];
            const p2 = pts[i + 1];
            const p3 = pts[i + 2] || p2;
            const c1x = p1.x + (p2.x - p0.x) * t;
            const c1y = p1.y + (p2.y - p0.y) * t;
            const c2x = p2.x - (p3.x - p1.x) * t;
            const c2y = p2.y - (p3.y - p1.y) * t;
            d += ` C ${c1x} ${c1y}, ${c2x} ${c2y}, ${p2.x} ${p2.y}`;
        }
        return d;
    }

    // ── SVG path data ─────────────────────────────────────────────────────────

    get sentPath() {
        return this._smoothPath(this._points("sent"));
    }

    get failedPath() {
        // Only draw the failed line if there's at least one failure to show.
        return this.props.bars.some((b) => (b.failed || 0) > 0)
            ? this._smoothPath(this._points("failed"))
            : "";
    }

    get hasFailures() {
        return this.props.bars.some((b) => (b.failed || 0) > 0);
    }

    /** Smooth area under the sent line, closed to the baseline for the gradient fill. */
    get sentAreaPath() {
        const pts = this._points("sent");
        if (pts.length === 0) return "";
        const baseY = PT + CH;
        const line = this._smoothPath(pts);
        return `${line} L ${pts[pts.length - 1].x} ${baseY} L ${pts[0].x} ${baseY} Z`;
    }

    // ── Enriched data ─────────────────────────────────────────────────────────

    get enrichedBars() {
        return this.props.bars.map((b, i) => ({
            ...b,
            index:  i,
            cx:     this._px(i),
            cy:     this._py(b.sent || 0),
            cyFail: this._py(b.failed || 0),
            label:  this._fmtLabel(b.hour_label),
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

    /**
     * Y-axis reference lines with numeric labels. Uses "nice" rounded values so
     * the gridline numbers are readable (e.g. 0 / 25 / 50 / 75 / 100), and the
     * top line sits at the smallest nice value ≥ the data max.
     */
    get gridLines() {
        const niceTop = this._niceMax;
        const steps = 4;
        return Array.from({ length: steps + 1 }, (_, k) => {
            const pct = k / steps;               // 0 … 1 bottom→top
            const value = Math.round(niceTop * pct);
            return {
                y:     PT + CH - pct * CH,
                label: String(value),
            };
        });
    }

    /** Smallest "nice" round number ≥ the data max, so gridline labels stay clean. */
    get _niceMax() {
        const max = this._max;
        if (max <= 4) return 4;
        const pow = Math.pow(10, Math.floor(Math.log10(max)));
        const norm = max / pow;                  // 1 … 10
        const nice = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
        return nice * pow;
    }

    // ── Hover / tooltip ───────────────────────────────────────────────────────

    onPointEnter(index) {
        this.hover.index = index;
    }

    onPointLeave() {
        this.hover.index = -1;
    }

    /** The hovered bar (enriched) or null. */
    get hoveredBar() {
        const i = this.hover.index;
        if (i < 0) return null;
        return this.enrichedBars[i] || null;
    }

    /**
     * In-SVG tooltip geometry for the hovered point, or null. Rendered as a
     * <g> so it scales with the chart and its text is never distorted. Flips to
     * the left of the point past the midline and clamps vertically to the plot.
     */
    get tooltip() {
        const bar = this.hoveredBar;
        if (!bar) return null;
        const hasFail = this.hasFailures;
        const boxW = 190;
        const boxH = hasFail ? 92 : 66;
        const flip = bar.cx > W * 0.6;
        const bx = flip ? bar.cx - 14 - boxW : bar.cx + 14;
        const anchorY = Math.min(bar.cy, bar.cyFail);
        const by = Math.max(PT, Math.min(anchorY - boxH / 2, PT + CH - boxH));
        return {
            bx, by, boxW, boxH,
            tx: bx + 14,
            titleY:  by + 26,
            sentY:   by + 50,
            failedY: by + 74,
            hasFail,
            label:  bar.label,
            sent:   bar.sent || 0,
            failed: bar.failed || 0,
            cx: bar.cx, cy: bar.cy,
        };
    }

    // ── Fixed SVG coordinates exposed to the template ─────────────────────────
    get labelY()   { return PT + CH + 28; }
    get baseY()    { return PT + CH; }
    get axisX()    { return PL; }
    get chartRight() { return W - PR; }

    // ── Label formatter ───────────────────────────────────────────────────────

    _fmtLabel(isoStr) {
        if (!isoStr) return "";
        if (isoStr.includes("T")) {
            // Hourly bucket (IST): "2026-05-25T14:00:00" → "2:00 PM"
            const [h, m] = isoStr.split("T")[1].slice(0, 5).split(":");
            const hh = parseInt(h, 10);
            const ampm = hh >= 12 ? "PM" : "AM";
            const h12 = hh % 12 === 0 ? 12 : hh % 12;
            return `${h12}:${m} ${ampm}`;
        }
        // Daily bucket: "2026-05-25" → "25 May"
        const d = new Date(isoStr + "T00:00:00");
        return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
    }
}
