/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { onWillUnmount } from "@odoo/owl";

export class LeadsNewListController extends ListController {
    setup() {
        super.setup();
        this._refreshTimeout = null;
        this._refreshInProgress = false;
        this.isDestroyed = false;

        onWillUnmount(() => {
            this.isDestroyed = true;
            if (this._refreshTimeout) {
                clearTimeout(this._refreshTimeout);
                this._refreshTimeout = null;
            }
        });

        this._scheduleNextRefresh();
    }

    _scheduleNextRefresh() {
        if (this.isDestroyed) return;

        // Schedule the next refresh AFTER the previous one completes.
        // Using setTimeout instead of setInterval prevents overlapping loads.
        this._refreshTimeout = setTimeout(() => this._doRefresh(), 50000);
    }

    async _doRefresh() {
        const root = this.model?.root;
        if (
            this.isDestroyed ||
            this._refreshInProgress ||
            document.visibilityState !== "visible" ||
            !root ||
            root.editedRecord ||
            // Don't reload while the user has rows selected (manual ticks or
            // "select all matching") — a reload clears the selection and would
            // wipe out a large in-progress bulk action (e.g. Bulk Reassign RM).
            root.selection.length ||
            root.isDomainSelected
        ) {
            // Skip this tick but schedule the next one.
            this._scheduleNextRefresh();
            return;
        }

        this._refreshInProgress = true;
        try {
            await this.model.root.load();
        } catch {
            // Component was destroyed during load, or network error — ignore.
        } finally {
            this._refreshInProgress = false;
            // Only schedule the next refresh if the component is still alive.
            if (!this.isDestroyed) {
                this._scheduleNextRefresh();
            }
        }
    }
}

export const leadsNewListView = {
    ...listView,
    Controller: LeadsNewListController,
};

registry.category("views").add("leads_new_list_controller", leadsNewListView);