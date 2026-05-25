/** @odoo-module */

import { Component } from "@odoo/owl";

/**
 * CdWorkflowHealthTable — per-workflow KPI table with manager active/pause toggle.
 *
 * Props:
 *   rows     {Array}    Each row: {id, slug, name, is_active, sent, delivery_rate, failed}
 *   onToggle {Function} Called with the workflow id when ON/OFF toggle is clicked.
 *   loading  {Boolean}  When true, table body is replaced with a loading skeleton.
 *
 * Not a field widget — imported directly by WaDashboard.
 */
export class CdWorkflowHealthTable extends Component {
    static template = "cleardeals_ui.WorkflowHealthTable";

    static props = {
        rows:     { type: Array },
        onToggle: { type: Function },
        loading:  { type: Boolean, optional: true },
    };

    static defaultProps = {
        loading: false,
    };

    handleToggle(row) {
        this.props.onToggle(row.id);
    }
}
