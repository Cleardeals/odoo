/** @odoo-module **/

import { registry } from '@web/core/registry';
import { Component, useState, onWillStart } from '@odoo/owl';
import { rpc } from '@web/core/network/rpc';

class PropertyDashboard extends Component {
    static template = 'property_dashboard.Dashboard';

    setup() {
        this.state = useState({
            // Initialize with default values to avoid seeing 'null' or 'undefined'
            kpis: { active_listings: 0, sold_listings: 0 },
            error: null
        });

        // Use RPC directly instead of service
        this.rpc = rpc;

        onWillStart(async () => {
            try {
                // Updated RPC call format for direct usage
                const data = await this.rpc('/web/dataset/call_kw', {
                    model: 'property.dashboard',
                    method: 'get_kpis',
                    args: [],
                    kwargs: {}
                });

                // This log confirms the RPC call was successful and shows us the data
                console.log("✅ Data received from server:", data);

                this.state.kpis = data;

            } catch (err) {
                // This will catch any server or network error during the call
                console.error("❌ RPC call failed!", err);
                this.state.error = "Could not load dashboard data.";
            }
        });
    }
}

registry.category('actions').add("property_dashboard.dashboard", PropertyDashboard);