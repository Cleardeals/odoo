/** @odoo-module */

import { Component, useState } from "@odoo/owl";
import { CdHelpTip } from "../cd_help_tip/cd_help_tip";

/**
 * CdLeaderboardTable — the shared sortable table for the By-RM / By-Property /
 * By-Campaign lenses. Typed cells (num / pct / money / secs / datetime / bar /
 * chip), click-to-sort headers, and optional row drill-down.
 *
 * Props:
 *   columns {Array}  [{key, label, type, align, max}] — type defaults to "num".
 *   rows    {Array}  Plain dicts keyed by column.key (raw values; formatting +
 *                    sorting are handled here).
 *   defaultSort {String}  Column key to sort by initially (desc).
 *   onRowClick  {Function} Optional, called with the row.
 *   onAction    {Function} Optional, called with the row from a "toggle" cell
 *                          (e.g. pause/resume a workflow); does not trigger row-click.
 *   emptyText   {String}
 */
export class CdLeaderboardTable extends Component {
    static template = "cleardeals_ui.CdLeaderboardTable";
    static components = { CdHelpTip };

    static props = {
        columns:     { type: Array },
        rows:        { type: Array },
        defaultSort: { type: String, optional: true },
        onRowClick:  { type: Function, optional: true },
        onAction:    { type: Function, optional: true },
        emptyText:   { type: String, optional: true },
    };

    static defaultProps = { emptyText: "No data for this period." };

    setup() {
        this.state = useState({
            sortKey: this.props.defaultSort || this._firstSortable(),
            sortDir: "desc",
        });
    }

    _firstSortable() {
        const c = this.props.columns.find((x) => (x.type || "num") !== "text")
            || this.props.columns[0];
        return c ? c.key : "";
    }

    onSort(col) {
        if (this.state.sortKey === col.key) {
            this.state.sortDir = this.state.sortDir === "desc" ? "asc" : "desc";
        } else {
            this.state.sortKey = col.key;
            this.state.sortDir = "desc";
        }
    }

    get sortedRows() {
        const k = this.state.sortKey;
        const dir = this.state.sortDir === "desc" ? -1 : 1;
        const col = this.props.columns.find((c) => c.key === k);
        const isText = col && (col.type || "num") === "text";
        return [...this.props.rows].sort((a, b) => {
            let va = a[k];
            let vb = b[k];
            if (va == null) va = isText ? "" : -Infinity;
            if (vb == null) vb = isText ? "" : -Infinity;
            if (va < vb) return -1 * dir;
            if (va > vb) return 1 * dir;
            return 0;
        });
    }

    onClick(row) {
        if (this.props.onRowClick) {
            this.props.onRowClick(row);
        }
    }

    onAction(row) {
        if (this.props.onAction) {
            this.props.onAction(row);
        }
    }

    barPct(col, row) {
        const v = row[col.key] || 0;
        const max = col.max || 100;
        return Math.max(0, Math.min(100, (v / max) * 100));
    }

    /**
     * Funnel segment width as a % of the first (largest) part. `col.parts` is an
     * array of row keys in decreasing order, e.g. ["obligations","answered","sustained"].
     */
    funnelPct(col, row, idx) {
        const held = row[col.parts[0]] || 0;
        if (!held) return 0;
        const v = row[col.parts[idx]] || 0;
        return Math.max(0, Math.min(100, (v / held) * 100));
    }

    /** Hover label spelling out every funnel number (held / answered / sustained / missed). */
    funnelTitle(col, row) {
        const held = row[col.parts[0]] || 0;
        if (col.parts.length < 3) return "";
        const ans = row[col.parts[1]] || 0;
        const sus = row[col.parts[2]] || 0;
        return `Held ${held}  ·  Answered in SLA ${ans}  ·  Sustained ${sus}  ·  Missed ${held - ans}`;
    }

    /** Score tone by threshold: good ≥ col.good (def 90), warn ≥ col.warn (def 70), else bad. */
    scoreTone(col, row) {
        const v = row[col.key];
        if (v == null) return "is-flat";
        const good = col.good == null ? 90 : col.good;
        const warn = col.warn == null ? 70 : col.warn;
        if (v >= good) return "is-good";
        if (v >= warn) return "is-warn";
        return "is-bad";
    }

    /** Trend arrow tone: up is good unless col.invert (then down is good). */
    trendTone(col, row) {
        const v = row[col.key];
        if (v == null || v === 0) return "is-flat";
        const positive = v > 0;
        const good = col.invert ? !positive : positive;
        return good ? "is-good" : "is-bad";
    }

    trendText(col, row) {
        const v = row[col.key];
        if (v == null) return "—";
        return `${Math.abs(v).toFixed(1)} pts`;
    }

    /** Format a cell value for display by column type. */
    fmt(col, row) {
        const v = row[col.key];
        switch (col.type) {
            case "text":
                return v || "—";
            case "pct":
            case "chip":
                return v == null ? "—" : `${v.toFixed(1)}%`;
            case "money":
                return `₹${(v || 0).toFixed(2)}`;
            case "secs":
                return this._secs(v);
            case "datetime":
                return this._ist(v);
            case "bar":
            case "score":
                return v == null ? "—" : `${v.toFixed(1)}%`;
            case "alertnum":
                return v == null ? "—" : Math.round(v).toLocaleString();
            default:
                return v == null ? "—" : Math.round(v).toLocaleString();
        }
    }

    _secs(v) {
        if (v == null) return "—";
        if (v < 60) return `${Math.round(v)}s`;
        if (v < 3600) return `${Math.round(v / 60)}m`;
        return `${(v / 3600).toFixed(1)}h`;
    }

    _ist(iso) {
        if (!iso) return "—";
        let s = iso.includes("T") ? iso : iso.replace(" ", "T");
        if (!/[zZ]|[+-]\d\d:?\d\d$/.test(s)) s += "Z";
        return new Date(s).toLocaleString("en-GB", {
            day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
            timeZone: "Asia/Kolkata",
        });
    }
}
