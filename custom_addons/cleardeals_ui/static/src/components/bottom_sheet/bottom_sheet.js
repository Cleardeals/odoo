/** @odoo-module */

import { Component } from "@odoo/owl";

/**
 * CdBottomSheet — the mobile replacement for an anchored popover.
 *
 * An anchored popover assumes a cursor: it opens next to its trigger and
 * expects a click elsewhere to dismiss it. On a phone that puts controls
 * under the user's own hand, half off-screen, and one mis-tap from closing.
 * A sheet slides up from the bottom edge instead — full width, thumb-height,
 * dismissed by the backdrop or the close button.
 *
 * Callers render it only when `env.isSmall`, keeping their desktop popover
 * markup untouched:
 *
 *     <t t-if="env.isSmall and state.showFilters">
 *         <CdBottomSheet title="'Filters'" onClose.bind="closeFilters">
 *             ...rows...
 *         </CdBottomSheet>
 *     </t>
 *
 * Props:
 *   title    {String}   optional heading; the header is dropped when empty
 *   onClose  {Function} called by the backdrop, the close button and Escape
 *   tall     {Boolean}  optional — pin to the maximum height rather than
 *                       hugging the content (for long, scrolling lists)
 */
export class CdBottomSheet extends Component {
    static template = "cleardeals_ui.BottomSheet";

    static props = {
        title:   { type: String, optional: true },
        onClose: { type: Function },
        tall:    { type: Boolean, optional: true },
        slots:   { type: Object, optional: true },
    };

    static defaultProps = { title: "", tall: false };

    /** Escape closes, matching the popovers this replaces. */
    onKeydown(ev) {
        if (ev.key === "Escape") {
            ev.stopPropagation();
            this.props.onClose();
        }
    }
}
