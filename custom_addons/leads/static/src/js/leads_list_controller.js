/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { onWillUnmount } from "@odoo/owl";

export class LeadsNewListController extends ListController {
    setup() {
        super.setup();
        this.autoRefreshInterval = null;
        this.isDestroyed = false;
        
        // Use Owl's onWillUnmount hook
        onWillUnmount(() => {
            this.isDestroyed = true;
            if (this.autoRefreshInterval) {
                clearInterval(this.autoRefreshInterval);
                this.autoRefreshInterval = null;
            }
        });
        
        this.startAutoRefresh();
    }

    startAutoRefresh() {
        // Clear any existing interval
        if (this.autoRefreshInterval) {
            clearInterval(this.autoRefreshInterval);
        }

        // Set auto-refresh interval (50 second)
        const refreshInterval = 50000; // 50 second in milliseconds
        
        this.autoRefreshInterval = setInterval(() => {
            // Only refresh if component is not destroyed, view is visible and not in edit mode
            if (!this.isDestroyed && 
                document.visibilityState === "visible" && 
                this.model?.root && 
                !this.model.root.editedRecord) {
                try {
                    this.model.root.load();
                } catch (error) {
                    // Component was destroyed during load, clear interval
                    console.log("Auto-refresh stopped due to component destruction");
                    clearInterval(this.autoRefreshInterval);
                    this.autoRefreshInterval = null;
                }
            }
        }, refreshInterval);
    }
}

export const leadsNewListView = {
    ...listView,
    Controller: LeadsNewListController,
};

registry.category("views").add("leads_new_list_controller", leadsNewListView);