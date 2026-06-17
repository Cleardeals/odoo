/** @odoo-module */

import { Component, useState } from "@odoo/owl";

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
 *   emptyText   {String}
 */
export class CdLeaderboardTable extends Component {
    static template = "cleardeals_ui.CdLeaderboardTable";

    static props = {
        columns:     { type: Array },
        rows:        { type: Array },
        defaultSort: { type: String, optional: true },
        onRowClick:  { type: Function, optional: true },
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

    barPct(col, row) {
        const v = row[col.key] || 0;
        const max = col.max || 100;
        return Math.max(0, Math.min(100, (v / max) * 100));
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
                return v == null ? "—" : `${v.toFixed(1)}%`;
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
