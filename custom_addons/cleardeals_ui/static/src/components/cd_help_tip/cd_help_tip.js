/** @odoo-module */

import { Component, useState } from "@odoo/owl";

/**
 * CdHelpTip — a small "?" affordance that opens an explainer popover so a
 * manager can learn *what a card/section shows* and *how to interpret it*
 * without leaving the dashboard. Click to open; click anywhere (the invisible
 * backdrop) to close.
 *
 * Props:
 *   title {String}            Popover heading.
 *   intro {String}            Optional one-line summary of what this shows.
 *   items {Array}             Optional [{term, desc}] — per-metric "how to read".
 *   align {String}            Optional "left" | "right" (which edge to anchor). Default "right".
 */
export class CdHelpTip extends Component {
    static template = "cleardeals_ui.CdHelpTip";

    static props = {
        title: { type: String },
        intro: { type: String, optional: true },
        items: { type: Array, optional: true },
        align: { type: String, optional: true },
        // Optional visual explainer: a demo segmented bar + a swatch legend, so
        // managers learn to read a coloured widget (e.g. the service funnel).
        sample: { type: Array, optional: true },       // [{cls, pct}]
        sampleNote: { type: String, optional: true },
        swatches: { type: Array, optional: true },     // [{cls, label, desc}]
    };

    static defaultProps = {
        intro: "", items: [], align: "right",
        sample: [], sampleNote: "", swatches: [],
    };

    setup() {
        this.ui = useState({ open: false });
    }

    toggle() { this.ui.open = !this.ui.open; }
    close() { this.ui.open = false; }
}
