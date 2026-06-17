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
 *   buckets   {Array}    Optional chips [{label, value, tone, key}]. When
 *                        onBucketClick is set the chips act as toggle filters.
 *   activeBucket{String} Optional key of the currently-active bucket filter.
 *   onBucketClick{Function} Optional, called with the bucket object (toggle filter).
 *   rows      {Array}    [{title, sub, meta, tone}] — passed back to onRowClick.
 *                        `tone` ("good"|"warn"|"bad") colours the row's left rail.
 *   onRowClick{Function} Optional, called with the row object.
 *   emptyText {String}   Shown when there are no rows.
 */
export class CdWorklistPanel extends Component {
    static template = "cleardeals_ui.CdWorklistPanel";

    static props = {
        title:         { type: String },
        icon:          { type: String, optional: true },
        count:         { type: Number, optional: true },
        accent:        { type: String, optional: true },
        buckets:       { type: Array, optional: true },
        activeBucket:  { type: String, optional: true },
        onBucketClick: { type: Function, optional: true },
        rows:          { type: Array, optional: true },
        onRowClick:    { type: Function, optional: true },
        emptyText:     { type: String, optional: true },
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

    onBucket(bucket) {
        if (this.props.onBucketClick) {
            this.props.onBucketClick(bucket);
        }
    }
}
