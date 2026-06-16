/** @odoo-module */

import { Component, useState, useRef, useExternalListener } from "@odoo/owl";

/**
 * CdInquirySwitcher — the "Discussing: <property>" attribution bar for a WhatsApp
 * thread: a custom inquiry dropdown (property tag + name, active check), an inline
 * "New topic" creator, and a one-click "switch to <property>?" suggestion.
 *
 * Pure presentation — all persistence happens in the parent via callbacks.
 *
 * Props:
 *   segmentsEnabled {Boolean}  Render nothing when false (feature flag off).
 *   activeLabel     {String}   Label of the active inquiry ("Discussing: <this>").
 *   activeInquiryId {Number}   Id of the active inquiry (highlights it in the menu).
 *   inquiries       {Array}    [{id, name, property}] — every inquiry on this phone.
 *   suggestion      {Object}   {segment_id, label} or null — lead's latest reply hint.
 *   onSwitch            (inquiryId) => void
 *   onStartTopic        (label)     => void
 *   onAcceptSuggestion  (segmentId) => void
 *   onDismissSuggestion (segmentId) => void
 */
export class CdInquirySwitcher extends Component {
    static template = "cleardeals_ui.InquirySwitcher";

    static props = {
        segmentsEnabled:     { type: Boolean, optional: true },
        activeLabel:         { type: String, optional: true },
        activeInquiryId:     { optional: true },
        inquiries:           { type: Array, optional: true },
        suggestion:          { optional: true },
        onSwitch:            { type: Function },
        onStartTopic:        { type: Function },
        onAcceptSuggestion:  { type: Function },
        onDismissSuggestion: { type: Function },
    };

    static defaultProps = {
        segmentsEnabled: false,
        activeLabel: "Unassigned",
        inquiries: [],
        suggestion: null,
    };

    setup() {
        this.ui = useState({ menuOpen: false, topicOpen: false, topicLabel: "" });
        this.root = useRef("root");
        // Close the dropdown on any click outside the component.
        useExternalListener(window, "mousedown", (ev) => {
            if (this.ui.menuOpen && this.root.el && !this.root.el.contains(ev.target)) {
                this.ui.menuOpen = false;
            }
        });
    }

    get displayLabel() {
        return this.props.activeLabel || "Unassigned";
    }

    isActive(inq) {
        return inq.id === this.props.activeInquiryId;
    }

    toggleMenu() {
        this.ui.menuOpen = !this.ui.menuOpen;
        this.ui.topicOpen = false;
    }

    pick(inq) {
        this.ui.menuOpen = false;
        if (!this.isActive(inq)) this.props.onSwitch(inq.id);
    }

    openTopic() {
        this.ui.menuOpen = false;
        this.ui.topicOpen = true;
        this.ui.topicLabel = "";
    }

    cancelTopic() {
        this.ui.topicOpen = false;
        this.ui.topicLabel = "";
    }

    onTopicInput(ev) {
        this.ui.topicLabel = ev.target.value;
    }

    addTopic() {
        const label = (this.ui.topicLabel || "").trim();
        if (!label) return;
        this.props.onStartTopic(label);
        this.ui.topicOpen = false;
        this.ui.topicLabel = "";
    }
}
