/** @odoo-module */

import { Component, useState, useRef, useExternalListener } from "@odoo/owl";

/**
 * CdInquirySwitcher — the "Discussing: <property>" attribution bar for a WhatsApp
 * thread: a custom inquiry dropdown (property tag + name, active check), a "New
 * topic" **property picker** (typeahead over property.base), an optional plain-label
 * fallback, a one-click "switch to <property>?" suggestion, and — when the active
 * span has a property but no inquiry yet — a "Create inquiry" call to action.
 *
 * Pure presentation — all persistence/search happens in the parent via callbacks.
 *
 * Props:
 *   segmentsEnabled {Boolean}  Render nothing when false (feature flag off).
 *   activeLabel     {String}   Label of the active inquiry ("Discussing: <this>").
 *   activeInquiryId {Number}   Id of the active inquiry (highlights it in the menu).
 *   activePropertyId{Number}   Property of the active span (drives the Create CTA).
 *   inquiries       {Array}    [{id, name, property, property_base_id}] on this phone.
 *   suggestion      {Object}   {segment_id, label} or null — lead's latest reply hint.
 *   searchProperties(query) => Promise<[{id, name, tag}]>   typeahead source (optional).
 *   onSwitch            (inquiryId)  => void
 *   onPickProperty      (property)   => void   New-topic property chosen.
 *   onStartTopic        (label)      => void   Optional plain-label fallback.
 *   onCreateInquiry     ()           => void   Optional — shows CTA when provided.
 *   onAcceptSuggestion  (segmentId)  => void
 *   onDismissSuggestion (segmentId)  => void
 */
export class CdInquirySwitcher extends Component {
    static template = "cleardeals_ui.InquirySwitcher";

    static props = {
        segmentsEnabled:     { type: Boolean, optional: true },
        activeLabel:         { type: String, optional: true },
        activeInquiryId:     { optional: true },
        activePropertyId:    { optional: true },
        inquiries:           { type: Array, optional: true },
        suggestion:          { optional: true },
        searchProperties:    { type: Function, optional: true },
        onSwitch:            { type: Function },
        onPickProperty:      { type: Function, optional: true },
        onStartTopic:        { type: Function, optional: true },
        onCreateInquiry:     { type: Function, optional: true },
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
        this.ui = useState({
            menuOpen: false,
            topicOpen: false,
            query: "",
            results: [],
            searching: false,
            labelMode: false,
            topicLabel: "",
        });
        this.root = useRef("root");
        this._searchSeq = 0;
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

    // The active span is about a property but has no inquiry yet → offer to create it.
    get showCreateInquiry() {
        return (
            !!this.props.onCreateInquiry &&
            !this.props.activeInquiryId &&
            !!this.props.activePropertyId
        );
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
        this.ui.query = "";
        this.ui.results = [];
        this.ui.labelMode = false;
        this.ui.topicLabel = "";
    }

    cancelTopic() {
        this.ui.topicOpen = false;
        this.ui.query = "";
        this.ui.results = [];
        this.ui.topicLabel = "";
    }

    async onQueryInput(ev) {
        const q = ev.target.value;
        this.ui.query = q;
        if (!this.props.searchProperties) return;
        const seq = ++this._searchSeq;
        this.ui.searching = true;
        try {
            const rows = await this.props.searchProperties(q);
            if (seq === this._searchSeq) this.ui.results = rows || [];
        } finally {
            if (seq === this._searchSeq) this.ui.searching = false;
        }
    }

    pickProperty(prop) {
        this.ui.topicOpen = false;
        this.ui.query = "";
        this.ui.results = [];
        if (this.props.onPickProperty) this.props.onPickProperty(prop);
    }

    // Optional plain-label fallback for off-catalog topics.
    useLabelMode() {
        this.ui.labelMode = true;
    }

    onTopicInput(ev) {
        this.ui.topicLabel = ev.target.value;
    }

    addLabelTopic() {
        const label = (this.ui.topicLabel || "").trim();
        if (!label || !this.props.onStartTopic) return;
        this.props.onStartTopic(label);
        this.cancelTopic();
    }
}
