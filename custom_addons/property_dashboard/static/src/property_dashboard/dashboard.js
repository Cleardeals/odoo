/** @odoo-module **/

import { registry } from '@web/core/registry';
import { Component, useState, onWillStart, onMounted } from '@odoo/owl';
import { rpc } from '@web/core/network/rpc';
import { loadJS } from '@web/core/assets';

class PropertyDashboard extends Component {
    static template = 'property_dashboard.Dashboard';

    setup() {
        this.state = useState({
            kpis: {
                total_listings: 0,
                active_listings: 0,
                sold_listings: 0,
                expired_listings: 0,
                new_this_month: 0,
                sold_this_month: 0,
                conversion_rate: 0,
                expiring_soon: 0
            },
            isLoading: true,
            lastUpdateTime: "",
            error: null
        });

        this.charts = {}; // To hold multiple Chart instances

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            await this.fetchData();
        });

        onMounted(() => {
            if (!this.state.error) {
                this.renderAllCharts();
            }
        });
    }

    async fetchData() {
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

            if (data.error) {
                this.state.error = data.error;
            } else {
                this.state.kpis = data;
                this.state.lastUpdateTime = new Date().toLocaleTimeString();

                // If charts already exist, update them with new data
                if (Object.keys(this.charts).length > 0) {
                    this.renderAllCharts();
                }
            }
        } catch (error) {
            console.error("RPC call Failed!:", error);
            this.state.error = "Failed to load data. Please try again later.";
        }
        this.state.isLoading = false;
    }

    renderAllCharts() {
        this.renderPropertyTypeChart();
        this.renderListingTypeChart();
        this.renderMonthlyTrendChart();
        this.renderCurrentStatusChart();
        this.renderServiceValidityChart();
        this.renderTopCitiesChart();
    }

    renderPropertyTypeChart() {
        const ctx = document.getElementById('propertyTypeChart');
        if (!ctx || !this.state.kpis.property_type_chart) return;

        if (this.charts.propertyType) {
            this.charts.propertyType.destroy();
        }

        const data = this.state.kpis.property_type_chart;
        this.charts.propertyType = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: data.labels,
                datasets: [{
                    data: data.values,
                    backgroundColor: ['rgba(54, 162, 235, 0.8)', 'rgba(255, 99, 132, 0.8)'],
                    borderColor: '#fff',
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom'
                    }
                }
            }
        });
    }

    renderListingTypeChart() {
        const ctx = document.getElementById('listingTypeChart');
        if (!ctx || !this.state.kpis.listing_type_chart) return;

        if (this.charts.listingType) {
            this.charts.listingType.destroy();
        }

        const data = this.state.kpis.listing_type_chart;
        this.charts.listingType = new Chart(ctx, {
            type: 'pie',
            data: {
                labels: data.labels,
                datasets: [{
                    data: data.values,
                    backgroundColor: ['rgba(75, 192, 192, 0.8)', 'rgba(255, 206, 86, 0.8)'],
                    borderColor: '#fff',
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom'
                    }
                }
            }
        });
    }

    renderMonthlyTrendChart() {
        const ctx = document.getElementById('monthlyTrendChart');
        if (!ctx || !this.state.kpis.monthly_trend_chart) return;

        if (this.charts.monthlyTrend) {
            this.charts.monthlyTrend.destroy();
        }

        const data = this.state.kpis.monthly_trend_chart;
        this.charts.monthlyTrend = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.labels,
                datasets: [{
                    label: 'New Registrations',
                    data: data.values,
                    borderColor: 'rgba(54, 162, 235, 1)',
                    backgroundColor: 'rgba(54, 162, 235, 0.1)',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true
                    }
                },
                plugins: {
                    legend: {
                        display: false
                    }
                }
            }
        });
    }

    renderCurrentStatusChart() {
        const ctx = document.getElementById('currentStatusChart');
        if (!ctx || !this.state.kpis.current_status_chart) return;

        if (this.charts.currentStatus) {
            this.charts.currentStatus.destroy();
        }

        const data = this.state.kpis.current_status_chart;
        this.charts.currentStatus = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: data.labels,
                datasets: [{
                    data: data.values,
                    backgroundColor: [
                        'rgba(255, 99, 132, 0.8)',
                        'rgba(54, 162, 235, 0.8)',
                        'rgba(255, 206, 86, 0.8)'
                    ],
                    borderColor: [
                        'rgba(255, 99, 132, 1)',
                        'rgba(54, 162, 235, 1)',
                        'rgba(255, 206, 86, 1)'
                    ],
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });
    }

    renderServiceValidityChart() {
        const ctx = document.getElementById('serviceValidityChart');
        if (!ctx || !this.state.kpis.service_validity_chart) return;

        if (this.charts.serviceValidity) {
            this.charts.serviceValidity.destroy();
        }

        const data = this.state.kpis.service_validity_chart;
        this.charts.serviceValidity = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: data.labels,
                datasets: [{
                    data: data.values,
                    backgroundColor: 'rgba(75, 192, 192, 0.8)',
                    borderColor: 'rgba(75, 192, 192, 1)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });
    }

    renderTopCitiesChart() {
        const ctx = document.getElementById('topCitiesChart');
        if (!ctx || !this.state.kpis.top_cities_chart) return;

        if (this.charts.topCities) {
            this.charts.topCities.destroy();
        }

        const data = this.state.kpis.top_cities_chart;
        this.charts.topCities = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: data.labels,
                datasets: [{
                    label: 'Active Listings',
                    data: data.values,
                    backgroundColor: 'rgba(153, 102, 255, 0.8)',
                    borderColor: 'rgba(153, 102, 255, 1)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y', // This makes it horizontal
                plugins: {
                    legend: {
                        display: false
                    }
                },
                scales: {
                    x: {
                        beginAtZero: true
                    }
                }
            }
        });
    }

    async refreshData() {
        await this.fetchData();
    }
}

registry.category('actions').add("property_dashboard.dashboard", PropertyDashboard);