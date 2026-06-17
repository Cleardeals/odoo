/** @odoo-module */

import { Component } from "@odoo/owl";

/**
 * CdWorklistPanel — a compact, action-oriented list (needs-reply, window
 * closing, unassigned, failures to fix). Title + count + optional aging chips
 * + clickable rows that drill into the inbox / lead.
 *
 * Props:
 *   title     {String}
 *   icon      {String}   Font-Awesome class (e.g. "fa-reply").
 *   count     {Number}
 *   accent    {String}   Optional "danger" | "warn" | "info".
 *   buckets   {Array}    Optional chips [{label, value, tone}].
 *   rows      {Array}    [{title, sub, meta}] — passed back to onRowClick.
 *   onRowClick{Function} Optional, called with the row object.
 *   emptyText {String}   Shown when there are no rows.
 */
export class CdWorklistPanel extends Component {
    static template = "cleardeals_ui.CdWorklistPanel";

    static props = {
        title:      { type: String },
        icon:       { type: String, optional: true },
        count:      { type: Number, optional: true },
        accent:     { type: String, optional: true },
        buckets:    { type: Array, optional: true },
        rows:       { type: Array, optional: true },
        onRowClick: { type: Function, optional: true },
        emptyText:  { type: String, optional: true },
    };

    static defaultProps = {
        rows: [],
        buckets: [],
        emptyText: "Nothing here — all clear.",
    };

    onClick(row) {
        if (this.props.onRowClick) {
            this.props.onRowClick(row);
        }
    }
}
