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
     * Delegates entirely to the server-side action method so the wizard's
     * default_get gets the correct visit context without coupling JS to Python
     * internals. Returns an ir.actions.act_window which actionService opens as
     * a dialog. The calendar reloads when the dialog closes.
     */
    async onRescheduleEvent() {
        this.props.close();
        const action = await this.orm.call(
            "lead.site.visit",
            "action_open_quick_update_wizard",
            [[this.props.record.id]],
        );
        await this.actionService.doAction(action, {
            onClose: () => {
                this.props.model.load();
            },
        });
    }

    /**
     * Returns true when the Reschedule button should be rendered.
     *
     * Reads pre-loaded boolean fields from rawRecord to avoid an extra RPC.
     * These fields are included as invisible="1" in the calendar view arch so
     * they are always fetched and present on rawRecord.
     */
    get isRescheduleVisible() {
        const raw = this.props.record.rawRecord;
        return raw.status_is_scheduled || raw.status_is_rescheduled;
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

