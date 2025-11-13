/** @odoo-module **/

import { registry } from "@web/core/registry";
import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";

class LeadsNewListController extends ListController {
    setup() {
        super.setup();
        
        // 1. Get the bus service
        this.busService = useService("bus_service");

        // 2. Define our unique channel
        const channel = "leads.new";

        // 3. Listen on that channel for any notifications
        this.busService.addChannel(channel);
        this.busService.addEventListener("notification", (notifications) => {
            this._onBusNotification(notifications);
        });
    }

    _onBusNotification(notifications) {
        // This function will receive all notifications, so we filter them
        
        for (const { payload, type } of notifications) {
            if (type === "bus_notification") {
                // The payload is [channel, message]
                const channel = payload[0];
                const message = payload[1];
                
                // 4. Check if it's our channel and our model
                if (channel === "leads.new" && message.model === "leads.new") {
                    
                    // 5. If it is, just reload the view's data!
                    console.log("Real-time update received for leads.new, reloading view.");
                    this.model.load();
                }
            }
        }
    }
}

// This registers our new controller so the XML can find it
registry.category("views").add("leads_new_list_controller", {
    ...registry.category("views").get("list"),
    Controller: LeadsNewListController,
});