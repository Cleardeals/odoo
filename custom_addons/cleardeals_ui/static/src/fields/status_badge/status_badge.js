import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

import { Component } from "@odoo/owl";

/**
 * CdStatusBadge — field widget
 *
 * Renders a styled pill badge for ``selection`` and ``char`` fields.
 *
 * Basic usage (no colour):
 *   <field name="state" widget="cd_status_badge"/>
 *
 * With a colour field (integer 0–11 maps to the Cleardeals palette):
 *   <field name="state" widget="cd_status_badge" options="{'color_field': 'color'}"/>
 *
 * Props (beyond standardFieldProps):
 * @prop {string} [colorField]  Name of an integer field whose value (0–11)
 *                              drives the badge colour class.
 *
 * @extends Component
 */
export class CdStatusBadge extends Component {
    static template = "cleardeals_ui.StatusBadge";
    static props = {
        ...standardFieldProps,
        colorField: { type: String, optional: true },
    };
    static defaultProps = {
        colorField: undefined,
    };

    /**
     * The human-readable label for the current field value.
     *
     * For ``selection`` fields the stored key is mapped to its display string.
     * For ``char`` fields the raw value is returned as-is.
     *
     * @returns {string}
     */
    get displayValue() {
        const value = this.props.record.data[this.props.name];
        if (value === undefined || value === null || value === false) {
            return "";
        }
        const field = this.props.record.fields[this.props.name];
        if (field.type === "selection") {
            const pair = (field.selection || []).find(([k]) => k === value);
            return pair ? pair[1] : String(value);
        }
        return String(value);
    }

    /**
     * Colour index (0–11) used to build the ``cd-status-badge--color-N`` CSS
     * class.  Defaults to 0 (blue) when no ``colorField`` is configured.
     *
     * @returns {number}
     */
    get colorIndex() {
        if (this.props.colorField) {
            return this.props.record.data[this.props.colorField] ?? 0;
        }
        return 0;
    }
}

/**
 * Field widget descriptor registered under the key ``"cd_status_badge"``.
 *
 * @type {import("@web/views/fields/field").FieldDefinition}
 */
export const cdStatusBadgeField = {
    component: CdStatusBadge,
    displayName: _t("Status Badge"),
    supportedTypes: ["selection", "char"],
    supportedOptions: [
        {
            label: _t("Color field"),
            name: "color_field",
            type: "field",
            availableTypes: ["integer"],
            help: _t("Integer field (0–11) that controls the badge colour."),
        },
    ],
    extractProps: ({ options }) => ({
        colorField: options.color_field,
    }),
};

registry.category("fields").add("cd_status_badge", cdStatusBadgeField);
