from odoo import models, api
import logging

_logger = logging.getLogger(__name__)

class LeadsDashboard(models.TransientModel):
    _name = 'leads.dashboard'
    _description = 'Simplified Leads Dashboard'

    @api.model
    def get_leads_kpis(self):
        try:
            leads = self.env['lead.score'].search([])
            listings = self.env['property.listing'].search([('property_status', '=', 'live')])
            _logger.info(f"📦 Using models: lead.score, property.listing")

            # Basic Metrics
            total_leads = len(leads)
            actionable_leads = len(leads.filtered(lambda l: l.is_actionable_today))

            # Lead Quality Metrics
            high_quality_leads = len(leads.filtered(lambda l: l.predicted_score >= 0.7))
            medium_quality_leads = len(leads.filtered(lambda l: 0.4 <= l.predicted_score < 0.7))
            low_quality_leads = len(leads.filtered(lambda l: l.predicted_score < 0.4))

            # Conversion Metrics
            conversion_metrics = self._calculate_conversion_metrics(leads)

            # Lead Score Distribution Chart
            score_histogram = self._prepare_score_histogram(leads)

            # WhatsApp Response Chart
            response_metrics = self._calculate_response_metrics(leads)

            # RM Performance
            rm_performance = self._calculate_rm_performance(leads)

            # Property Performance
            property_metrics = self._calculate_property_metrics(leads)

            # Stage Distribution
            stage_distribution = self._prepare_stage_distribution(leads)

            result = {
                # Basic Metrics
                'total_leads': total_leads,
                'actionable_leads': actionable_leads,
                'high_quality_leads': high_quality_leads,
                'medium_quality_leads': medium_quality_leads,
                'low_quality_leads': low_quality_leads,
                'site_visit_scheduled': conversion_metrics.get('site_visit_scheduled', 0),
                
                # Conversion Metrics
                'overall_conversion': conversion_metrics.get('overall_conversion', 0),
                'conversion_funnel': conversion_metrics.get('funnel', []),
                
                # Charts and Tables
                'score_histogram': score_histogram,
                'whatsapp_response_chart': response_metrics.get('chart', {}),
                'stage_distribution': stage_distribution,
                
                # RM and Property Data
                'rm_metrics': rm_performance.get('by_rm', {}),
                'rm_list': rm_performance.get('rm_list', []),
                'property_performance': property_metrics.get('by_property', {}),
                'property_list': property_metrics.get('property_list', [])
            }
            
            _logger.info(f"📤 Returning Simplified KPIs: {result}")
            return result

        except Exception as e:
            _logger.error(f"❌ Fatal error in get_leads_kpis: {e}")
            return {
                'total_leads': 0,
                'actionable_leads': 0,
                'high_quality_leads': 0,
                'medium_quality_leads': 0,
                'low_quality_leads': 0,
                'site_visit_scheduled': 0,
                'overall_conversion': 0,
                'conversion_funnel': [],
                'score_histogram': {'labels': [], 'values': []},
                'whatsapp_response_chart': {'labels': [], 'values': []},
                'stage_distribution': {'labels': [], 'values': []},
                'rm_metrics': {},
                'rm_list': [],
                'property_performance': {},
                'property_list': [],
                'error': str(e)
            }

    def _calculate_conversion_metrics(self, leads):
        """Calculate simplified conversion funnel metrics with site visit tracking"""
        funnel_stages = [
            ('lead', 'Initial Lead'),
            ('details_shared_of_property', 'Details Shared'),
            ('details_shared_and_interested_for_site_visit', 'Interested in Visit'),
            ('site_visit_scheduled', 'Visit Scheduled'),
            ('requirement_closed', 'Closed Won')
        ]
        
        funnel_data = []
        site_visit_scheduled = 0
        for status, label in funnel_stages:
            count = len(leads.filtered(lambda l: l.current_status == status))
            if status == 'site_visit_scheduled':
                site_visit_scheduled = count
            funnel_data.append({
                'stage': label,
                'count': count,
                'percentage': (count / len(leads) * 100) if leads else 0
            })
        
        overall_conversion = funnel_data[-1]['percentage'] if funnel_data else 0
        
        return {
            'funnel': funnel_data,
            'overall_conversion': round(overall_conversion, 2),
            'site_visit_scheduled': site_visit_scheduled
        }

    def _calculate_response_metrics(self, leads):
        """Calculate WhatsApp response metrics"""
        all_responses = self.env['whatsapp.response'].search([])
        
        response_counts = {}
        for response in all_responses:
            response_type = response.response_type or 'unknown'
            response_counts[response_type] = response_counts.get(response_type, 0) + 1
        
        return {
            'chart': {
                'labels': list(response_counts.keys()),
                'values': list(response_counts.values())
            }
        }

    def _calculate_rm_performance(self, leads):
        """Calculate RM performance metrics, return all RMs sorted by lead count"""
        rm_metrics = {}
        
        for rm in leads.mapped('assigned_rm_id'):
            rm_leads = leads.filtered(lambda l: l.assigned_rm_id == rm)
            if rm_leads:
                rm_metrics[rm.name] = {
                    'total_leads': len(rm_leads),
                    'avg_score': sum(rm_leads.mapped('predicted_score')) / len(rm_leads),
                    'conversion_rate': len(rm_leads.filtered(lambda l: l.current_status in ['site_visit_scheduled', 'requirement_closed'])) / len(rm_leads)
                }
        
        rm_list = sorted(rm_metrics.items(), key=lambda x: x[1]['total_leads'], reverse=True)
        
        return {
            'by_rm': rm_metrics,
            'rm_list': [{'name': name, **metrics} for name, metrics in rm_list]
        }

    def _calculate_property_metrics(self, leads):
        """Calculate property-based metrics, return all properties sorted by lead count"""
        property_groups = {}
        
        for lead in leads:
            if lead.project_name:
                if lead.project_name not in property_groups:
                    property_groups[lead.project_name] = []
                property_groups[lead.project_name].append(lead)
        
        property_performance = {}
        for project, project_leads in property_groups.items():
            property_performance[project] = {
                'leads': len(project_leads),
                'avg_score': sum([l.predicted_score for l in project_leads]) / len(project_leads)
            }
        
        property_list = sorted(property_performance.items(), key=lambda x: x[1]['leads'], reverse=True)
        
        return {
            'by_property': property_performance,
            'property_list': [{'name': name, **metrics} for name, metrics in property_list]
        }

    def _prepare_score_histogram(self, leads):
        """Prepare score distribution histogram"""
        bins = [0, 0.2, 0.4, 0.6, 0.8, 1.0]
        histogram = {'0-0.2': 0, '0.2-0.4': 0, '0.4-0.6': 0, '0.6-0.8': 0, '0.8-1.0': 0}
        
        for lead in leads:
            score = lead.predicted_score
            if score < 0.2:
                histogram['0-0.2'] += 1
            elif score < 0.4:
                histogram['0.2-0.4'] += 1
            elif score < 0.6:
                histogram['0.4-0.6'] += 1
            elif score < 0.8:
                histogram['0.6-0.8'] += 1
            else:
                histogram['0.8-1.0'] += 1
        
        return {
            'labels': list(histogram.keys()),
            'values': list(histogram.values())
        }

    def _prepare_stage_distribution(self, leads):
        """Prepare data for stage distribution table"""
        stage_counts = {}
        for lead in leads:
            status = lead.current_status or 'unknown'
            stage_counts[status] = stage_counts.get(status, 0) + 1
        
        return {
            'labels': list(stage_counts.keys()),
            'values': list(stage_counts.values())
        }