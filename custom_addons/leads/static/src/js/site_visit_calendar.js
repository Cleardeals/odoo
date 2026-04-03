/** @odoo-module **/

// ---------------------------------------------------------------------------
// Module : leads
// File   : static/src/js/site_visit_calendar.js
// Purpose: Custom calendar view for lead.site.visit with a Reschedule button
//          in the event popover.
//
// Architecture (Odoo 19 calendar stack):
//   CalendarController
//     └─ CalendarRenderer          ← top-level Renderer; picks sub by scale
//          └─ CalendarCommonRenderer  (day / week / month)
//               └─ CalendarCommonPopover  ← popover shown on event click
//
// To inject a custom Reschedule button we must:
//   1. Extend CalendarCommonPopover → SiteVisitCalendarPopover
//   2. Extend CalendarCommonRenderer → SiteVisitCalendarCommonRenderer
//      and swap its Popover component
//   3. Extend CalendarRenderer → SiteVisitCalendarRenderer and swap the
//      day/week/month sub-components with our custom common renderer
//   4. Register the whole stack as js_class="site_visit_calendar"
//
// Owner  : Cleardeals Tech
// ---------------------------------------------------------------------------

import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { calendarView } from "@web/views/calendar/calendar_view";
import { CalendarRenderer } from "@web/views/calendar/calendar_renderer";
import { CalendarCommonRenderer } from "@web/views/calendar/calendar_common/calendar_common_renderer";
import { CalendarCommonPopover } from "@web/views/calendar/calendar_common/calendar_common_popover";

// ─────────────────────────────────────────────────────────────────────────────
// SiteVisitCalendarPopover
//
// Adds a "Reschedule" button to the event popover. Renders the standard
// footer template except for the footer sub-template, which is replaced with
// leads.SiteVisitCalendarPopover.footer (defined in site_visit_calendar.xml).
//
// The Reschedule button is only shown for open visits (scheduled or
// rescheduled status). Terminal-status visits (completed, cancelled,
// superseded, did_not_show_up) hide the button via isRescheduleVisible.
// ─────────────────────────────────────────────────────────────────────────────
export class SiteVisitCalendarPopover extends CalendarCommonPopover {
    static subTemplates = {
        ...CalendarCommonPopover.subTemplates,
        // Override only the footer; the base template dispatches to this name
        // via constructor.subTemplates.footer at render time.
        footer: "leads.SiteVisitCalendarPopover.footer",
    };

    setup() {
        super.setup();
        this.actionService = useService("action");
        this.orm = useService("orm");
    }

    /**
     * Open the Quick Update wizard for this visit in reschedule mode.
     *
     * IMPORTANT: We capture all needed references (close, model, recordId)
     * BEFORE awaiting the ORM call.  useService("orm") returns a proxy that is
     * tied to the component's lifecycle — calling this.props.close() first
     * unmounts the component, which aborts in-flight requests made through the
     * lifecycle-bound orm proxy.  By capturing references first and closing
     * only after the ORM call resolves, we keep the component alive long enough
     * for the network request to complete.
     */
    async onRescheduleEvent() {
        const close = this.props.close;
        const model = this.props.model;
        const recordId = this.props.record.id;

        let action;
        try {
            action = await this.orm.call(
                "lead.site.visit",
                "action_open_quick_update_wizard",
                [[recordId]],
            );
        } catch {
            // ORM error already surfaces via the notification service; just bail.
            return;
        }

        // Close the popover only after the ORM call has resolved so the
        // component stays mounted (and orm alive) during the await above.
        close();

        await this.actionService.doAction(action, {
            onClose: () => model.load(),
        });
    }

    /**
     * Returns true when the Reschedule button should be rendered.
     *
     * Reads status_is_terminal from rawRecord — a related field preloaded via
     * the calendar arch (invisible="1").  Hiding the button when the visit is
     * already terminal avoids opening the wizard on closed records.
     */
    get isRescheduleVisible() {
        const raw = this.props.record.rawRecord;
        return !raw.status_is_terminal;
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// SiteVisitCalendarCommonRenderer
//
// Inner renderer (one per scale: day / week / month). Swaps only the Popover
// component; all FullCalendar wiring is inherited unchanged.
// ─────────────────────────────────────────────────────────────────────────────
export class SiteVisitCalendarCommonRenderer extends CalendarCommonRenderer {
    static components = {
        ...CalendarCommonRenderer.components,
        Popover: SiteVisitCalendarPopover,
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// SiteVisitCalendarRenderer
//
// Top-level Renderer (used directly by CalendarController). Extends the outer
// CalendarRenderer wrapper and replaces all scale sub-components (day/week/
// month) with the custom inner renderer that carries our popover.
// ─────────────────────────────────────────────────────────────────────────────
export class SiteVisitCalendarRenderer extends CalendarRenderer {
    static components = {
        ...CalendarRenderer.components,
        day: SiteVisitCalendarCommonRenderer,
        week: SiteVisitCalendarCommonRenderer,
        month: SiteVisitCalendarCommonRenderer,
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// View registration
//
// Inherits all standard calendar view components (Model, Controller,
// ArchParser) and replaces only the Renderer.
// ─────────────────────────────────────────────────────────────────────────────
registry.category("views").add("site_visit_calendar", {
    ...calendarView,
    Renderer: SiteVisitCalendarRenderer,
});

