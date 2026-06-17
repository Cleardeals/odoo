/** @odoo-module */

import { Component, useRef, onWillStart, onMounted, onPatched, onWillUnmount } from "@odoo/owl";
import { loadJS } from "@web/core/assets";

/**
 * CdChart — a thin OWL wrapper over the Odoo-bundled Chart.js.
 *
 * Props:
 *   type      {String}  Chart.js type ("line", "bar", "doughnut", …).
 *   data      {Object}  Chart.js data ({labels, datasets}).
 *   options   {Object}  Optional Chart.js options (merged over sensible defaults).
 *   height    {Number|String}  Wrapper height (px number or CSS string). Default 240.
 *   ariaLabel {String}  Accessible summary of the chart.
 *
 * Re-renders only when the (type, data) signature actually changes, so it is
 * cheap to keep mounted while the surrounding dashboard re-renders (search, etc.).
 */
export class CdChart extends Component {
    static template = "cleardeals_ui.CdChart";

    static props = {
        type:      { type: String },
        data:      { type: Object },
        options:   { type: Object, optional: true },
        height:    { type: [Number, String], optional: true },
        ariaLabel: { type: String, optional: true },
    };

    static defaultProps = {
        height: 240,
        ariaLabel: "Chart",
    };

    setup() {
        this.canvasRef = useRef("canvas");
        this._sig = null;
        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
        });
        onMounted(() => this._render());
        onPatched(() => {
            if (this._signature() !== this._sig) {
                this._render();
            }
        });
        onWillUnmount(() => this._destroy());
    }

    get heightStyle() {
        const h = this.props.height;
        return `height: ${typeof h === "number" ? h + "px" : h};`;
    }

    _signature() {
        return this.props.type + "|" + JSON.stringify(this.props.data);
    }

    _destroy() {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
    }

    _render() {
        this._destroy();
        const el = this.canvasRef.el;
        if (!el || typeof Chart === "undefined") {
            return;
        }
        this.chart = new Chart(el, {
            type: this.props.type,
            data: this.props.data,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                ...(this.props.options || {}),
            },
        });
        this._sig = this._signature();
    }
}
