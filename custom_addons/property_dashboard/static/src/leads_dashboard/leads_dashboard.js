/**@odoo-module **/

import { registry } from '@web/core/registry';
import { Component, useState, onWillStart, onMounted } from '@odoo/owl';
import { rpc } from '@web/core/network/rpc';
import { loadJS } from '@web/core/assets';

class LeadsDashboard extends Component {
    static template = 'property_dashboard.LeadsDashboard';

    setup() {

        this.state = useState({ kpis: {}, isLoading:true, error:null });

        this.chart = null;

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            await this.fetchData();
        });

        onMounted(() => {
            if (!this.state.error) this.renderChart();
        });
    }

    async fetchData(){

        this.state.isLoading = true;
        const data = await rpc('/web/dataset/call_kw', {
            model:'leads.dashboard',
            method: 'get_leads_kpis',
            args: [],
            kwargs: {}
        });

        if (data.error){
            this.state.error = data.error;
        } else {
            this.state.kpis = data;
        }

        this.state.isLoading = false;
        if (!this.state.error) this.renderChart();
    }

    renderChart(){
        const ctx = document.getElementById('leadStageChart');
        if (!ctx || !this.state.kpis.stage_chart) return;

        if (this.chart) this.chart.destroy();

        this.chart = new Chart(ctx, {
            type: 'pie',
            data: {
                labels: this.state.kpis.stage_chart.labels,
                datasets: [{
                    labels: 'Leads',
                    data: this.state.kpis.stage_chart.values,
                    backgroundColor: ['#36A2EB', '#FF6384', '#FFCE56', '#4BC0C0', '#9966FF'],
                }]
            },
            options: { responsive: true, maintainAspectRatio: false}
        });
    }
}

registry.category('actions').add('property_dashboard.leads_dashboard', LeadsDashboard);