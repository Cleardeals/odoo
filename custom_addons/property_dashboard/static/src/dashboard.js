/** @odoo-module **/

import { registry } from '@web/core/registry';
import { Component, useState, onWillStart, onMounted } from '@odoo/owl';
import { rpc } from '@web/core/network/rpc';
import { formatFloat } from "@web/core/utils/numbers";
import { loadJS } from '@web/core/assets';



class PropertyDashboard extends Component {
    static template = 'property_dashboard.Dashboard';

    setup() {
        this.state = useState({
            // Initialize with default values to avoid seeing 'null' or 'undefined'
            kpis: { active_listings: 0, sold_listings: 0 },
            isLoading: true, // For loading Indicator
            lastUpdateTime: "", // To show last update time
            error: null
        });

        this.chart = null; // To hold the Chart instance

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            await this.fetchData()
        });

        onMounted(() => {
            // Render the chart once the component is in the DOM
            if(!this.state.error){
                this.renderChart();
            }
        });
    }

    async fetchData(){
        this.state.isLoading = true;
        this.state.error = null;
        try {
            const data = await rpc('/web/dataset/call_kw', {
                model: 'property.dashboard',
                method: 'get_kpis',
                args: [],
                kwargs: {}
            });

            console.log("✅Data received from server:", data);

            if (data.error){
                this.state.error = data.error;
            } else {
    
                this.state.kpis = data;
                this.state.lastUpdateTime = new Date().toLocaleTimeString();

                // If chart already exists, update it with new data
                if(this.chart){
                    this.renderChart();
                }
            }
        } catch (error) {
            console.error("RPC call Failed!:", error);
            this.state.error = "Failed to load data. Please try again later.";
        }
        this.state.isLoading = false;
    }

    renderChart() {
        const ctx = document.getElementById('listingsChart');
        if (!ctx || !this.state.kpis.listings_by_type){
            return;
        }

        const data = this.state.kpis.listings_by_type;

        // If chart already exists, destroy it before creating a new one
        if (this.chart) {
            this.chart.destroy();
        }

        this.chart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: data.labels,
                datasets: [{
                    label: 'Listings',
                    data: data.values,
                    backgroundColor: [
                        'rgba(54, 162, 235, 0.8)',
                        'rgba(255, 99, 132, 0.8)',
                    ],
                    borderColor: '#fff',
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false
            }
        });
    }
}

registry.category('actions').add("property_dashboard.dashboard", PropertyDashboard);