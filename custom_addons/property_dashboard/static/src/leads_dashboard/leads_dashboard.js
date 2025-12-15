/**@odoo-module **/

import { registry } from '@web/core/registry';
import { Component, useState, onWillStart, onMounted, useRef, onWillUnmount } from '@odoo/owl';
import { rpc } from '@web/core/network/rpc';
import { loadJS } from '@web/core/assets';

class LeadsDashboard extends Component {
    static template = 'property_dashboard.LeadsDashboard';

    setup() {
        this.state = useState({ 
            kpis: {}, 
            isLoading: true, 
            error: null,
            selectedTab: 'overview'
        });

        this.charts = {
            score: null,
            whatsapp_response: null,
            funnel: null
        };

        this.chartRefs = {
            score: useRef('scoreChart'),
            whatsapp_response: useRef('whatsappResponseChart'),
            funnel: useRef('funnelChart')
        };

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            await this.fetchData();
        });

        onMounted(() => {
            if (!this.state.error) {
                this.renderAllCharts();
            }
        });

        onWillUnmount(() => {
            this.destroyAllCharts();
        });
    }

    async fetchData() {
        this.state.isLoading = true;
        try {
            const data = await rpc('/web/dataset/call_kw', {
                model: 'leads.dashboard',
                method: 'get_leads_kpis',
                args: [],
                kwargs: {}
            });

            if (data.error) {
                this.state.error = data.error;
            } else {
                this.state.kpis = data;
            }
        } catch (error) {
            this.state.error = error.message;
        } finally {
            this.state.isLoading = false;
            if (!this.state.error) {
                this.renderAllCharts();
            }
        }
    }

    destroyAllCharts() {
        Object.values(this.charts).forEach(chart => {
            if (chart) chart.destroy();
        });
    }

    renderAllCharts() {
        this.renderScoreHistogram();
        this.renderWhatsAppResponseChart();
        this.renderFunnelChart();
    }

    renderScoreHistogram() {
        const ctx = this.chartRefs.score.el;
        if (!ctx || !this.state.kpis.score_histogram) return;

        if (this.charts.score) this.charts.score.destroy();

        const data = this.state.kpis.score_histogram;
        
        this.charts.score = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: data.labels,
                datasets: [{
                    label: 'Lead Distribution',
                    data: data.values,
                    backgroundColor: data.labels.map((_, i) => {
                        const colors = ['#EF4444', '#F59E0B', '#FCD34D', '#10B981', '#059669'];
                        return colors[i % colors.length];
                    }),
                    borderRadius: 8
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: (context) => `Score Range: ${context[0].label}`,
                            label: (context) => `Leads: ${context.parsed.y}`
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { display: true, color: 'rgba(0,0,0,0.05)' }
                    },
                    x: {
                        grid: { display: false }
                    }
                }
            }
        });
    }

    renderWhatsAppResponseChart() {
        const ctx = this.chartRefs.whatsapp_response.el;
        if (!ctx || !this.state.kpis.whatsapp_response_chart) return;

        if (this.charts.whatsapp_response) this.charts.whatsapp_response.destroy();

        const data = this.state.kpis.whatsapp_response_chart;
        
        this.charts.whatsapp_response = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: data.labels,
                datasets: [{
                    label: 'Responses',
                    data: data.values,
                    backgroundColor: ['#10B981', '#F59E0B', '#EF4444', '#3B82F6'],
                    borderRadius: 8
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: (context) => `Response Type: ${context[0].label}`,
                            label: (context) => `Count: ${context.parsed.y}`
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { display: true, color: 'rgba(0,0,0,0.05)' }
                    },
                    x: {
                        grid: { display: false }
                    }
                }
            }
        });
    }

    renderFunnelChart() {
        const ctx = this.chartRefs.funnel.el;
        if (!ctx || !this.state.kpis.conversion_funnel) return;

        if (this.charts.funnel) this.charts.funnel.destroy();

        const data = this.state.kpis.conversion_funnel;
        
        this.charts.funnel = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: data.map(item => item.stage),
                datasets: [{
                    label: 'Funnel Stages',
                    data: data.map(item => item.count),
                    backgroundColor: [
                        '#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6'
                    ],
                    borderRadius: 8
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            title: (context) => `Stage: ${context[0].label}`,
                            label: (context) => `Leads: ${context.parsed.y} (${data[context.dataIndex].percentage.toFixed(1)}%)`
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { display: true, color: 'rgba(0,0,0,0.05)' }
                    },
                    x: {
                        grid: { display: false }
                    }
                }
            }
        });
    }

    formatNumber(num) {
        if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
        if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
        return num.toString();
    }

    switchTab(ev) {
        const tab = ev.currentTarget.value;
        console.log('LeadsDashboard: Switching to tab:', tab);
        this.state.selectedTab = tab;
        setTimeout(() => this.renderAllCharts(), 100);
    }

    exportData() {
        console.log('Exporting data...');
    }

    refreshData() {
        this.fetchData();
    }
}

registry.category('actions').add("property_dashboard.leads_dashboard", LeadsDashboard);