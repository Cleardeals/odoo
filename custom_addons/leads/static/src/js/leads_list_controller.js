/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";

export class LeadsNewListController extends ListController {
    setup() {
        super.setup();
        this.autoRefreshInterval = null;
        this.startAutoRefresh();
    }

    startAutoRefresh() {
        // Clear any existing interval
        if (this.autoRefreshInterval) {
            clearInterval(this.autoRefreshInterval);
        }

        // Set auto-refresh interval (30 seconds)
        const refreshInterval = 5000; // 30 seconds in milliseconds
        
        this.autoRefreshInterval = setInterval(() => {
            // Only refresh if the view is visible and not in edit mode
            if (document.visibilityState === "visible" && !this.model.root.editedRecord) {
                this.model.root.load();
            }
        }, refreshInterval);
    }

    onWillUnmount() {
        // Clean up interval when component is unmounted
        if (this.autoRefreshInterval) {
            clearInterval(this.autoRefreshInterval);
            this.autoRefreshInterval = null;
        }
        super.onWillUnmount();
    }
}

export const leadsNewListView = {
    ...listView,
    Controller: LeadsNewListController,
};

registry.category("views").add("leads_new_list_controller", leadsNewListView);