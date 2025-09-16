from odoo import models, api
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import logging

_logger = logging.getLogger(__name__)

class PropertyDashboard(models.TransientModel):
    _name = 'property.dashboard'
    _description = 'Dashboard Backend Model'

    @api.model
    def get_kpis(self):
        try:
            listings_model = self.env['property.listing']
            _logger.info(f"📦 Using model: {listings_model._name}")

            # Date calculations
            today = date.today()
            start_of_month = today.replace(day=1)
            start_of_quarter = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
            thirty_days_ago = today - timedelta(days=30)
            
            # Basic counts by status
            total_listings = listings_model.search_count([])
            active_count = listings_model.search_count([('property_status', '=', 'live')])
            sold_count = listings_model.search_count([('property_status', '=', 'sold')])
            expired_count = listings_model.search_count([('property_status', '=', 'expired')])
            
            # Time-based metrics
            new_this_month = listings_model.search_count([('property_register_date', '>=', start_of_month)])
            sold_this_month = listings_model.search_count([
                ('property_status', '=', 'sold'),
                ('property_sold_date', '>=', start_of_month)
            ])
            
            # Business performance metrics
            conversion_rate = (sold_count / total_listings * 100) if total_listings > 0 else 0
            
            # Expiring soon (next 30 days)
            expiring_soon = 0
            live_properties = listings_model.search([('property_status', '=', 'live')])
            for prop in live_properties:
                if prop.service_validity and prop.property_register_date:
                    validity_months = int(prop.service_validity)
                    expiry_date = prop.property_register_date + relativedelta(months=validity_months)
                    if today <= expiry_date <= (today + timedelta(days=30)):
                        expiring_soon += 1

            # Chart Data 1: Property Type Distribution (Active only)
            type_data = listings_model.read_group(
                [('property_status', '=', 'live')],
                ['property_type'],
                ['property_type']
            )
            property_type_chart = {
                'labels': [d.get('property_type', 'Unknown') for d in type_data],
                'values': [d.get('property_type_count', 0) for d in type_data],
            }

            # Chart Data 2: Listing Type Distribution (Sell vs Rent)
            listing_type_data = listings_model.read_group(
                [('property_status', '=', 'live')],
                ['listing_type'],
                ['listing_type']
            )
            listing_type_chart = {
                'labels': [d.get('listing_type', 'Unknown') for d in listing_type_data],
                'values': [d.get('listing_type_count', 0) for d in listing_type_data],
            }

            # Chart Data 3: Monthly Registration Trend (Last 6 months)
            monthly_registrations = []
            monthly_labels = []
            for i in range(5, -1, -1):  # Last 6 months
                month_start = (today - relativedelta(months=i)).replace(day=1)
                month_end = (month_start + relativedelta(months=1)) - timedelta(days=1)
                count = listings_model.search_count([
                    ('property_register_date', '>=', month_start),
                    ('property_register_date', '<=', month_end)
                ])
                monthly_registrations.append(count)
                monthly_labels.append(month_start.strftime('%b %Y'))

            monthly_trend_chart = {
                'labels': monthly_labels,
                'values': monthly_registrations,
            }

            # Chart Data 4: Current Status Distribution
            status_data = listings_model.read_group(
                [('property_status', '=', 'live')],
                ['current_status'],
                ['current_status']
            )
            current_status_chart = {
                'labels': [d.get('current_status', 'Unknown') for d in status_data],
                'values': [d.get('current_status_count', 0) for d in status_data],
            }

            # Chart Data 5: Service Validity Distribution
            validity_data = listings_model.read_group(
                [('property_status', '=', 'live')],
                ['service_validity'],
                ['service_validity']
            )
            validity_labels = []
            for d in validity_data:
                validity = d.get('service_validity')
                if validity == '1':
                    validity_labels.append('1 Month')
                elif validity == '3':
                    validity_labels.append('3 Months')
                elif validity == '6':
                    validity_labels.append('6 Months')
                elif validity == '12':
                    validity_labels.append('12 Months')
                else:
                    validity_labels.append('Unknown')
            
            service_validity_chart = {
                'labels': validity_labels,
                'values': [d.get('service_validity_count', 0) for d in validity_data],
            }

            # Top performing locations (by number of listings)
            location_data = listings_model.read_group(
                [('property_status', '=', 'live'), ('city_id', '!=', False)],
                ['city_id'],
                ['city_id']
            )[:5]  # Top 5 cities
            
            top_cities_chart = {
                'labels': [],
                'values': []
            }
            
            for d in location_data:
                city_name = 'Unknown'
                if d.get('city_id'):
                    city = self.env['res.city'].browse(d['city_id'][0])
                    city_name = city.name if city.exists() else 'Unknown'
                top_cities_chart['labels'].append(city_name)
                top_cities_chart['values'].append(d.get('city_id_count', 0))

            
            # Group Properties by RM_id and get corresponding counts
            rm_property_data = listings_model.read_group(
                [('property_status', '=', 'live'), ('rm_id', '!=', False)],
                ['rm_id'],
                ['rm_id'],
                orderby='rm_id_count DESC',
            )

            result = {
                # Main KPIs
                'total_listings': total_listings,
                'active_listings': active_count,
                'sold_listings': sold_count,
                'expired_listings': expired_count,
                'new_this_month': new_this_month,
                'sold_this_month': sold_this_month,
                'conversion_rate': round(conversion_rate, 1),
                'expiring_soon': expiring_soon,
                
                # Charts data
                'property_type_chart': property_type_chart,
                'listing_type_chart': listing_type_chart,
                'monthly_trend_chart': monthly_trend_chart,
                'current_status_chart': current_status_chart,
                'service_validity_chart': service_validity_chart,
                'top_cities_chart': top_cities_chart,

                # RM-wise property counts
                'rm_property_table': rm_property_data
            }
            
            _logger.info(f"📤 Returning Enhanced KPIs: {result}")
            return result
            
        except Exception as e:
            _logger.error(f"❌ Fatal error in get_kpis: {e}")
            return {
                'total_listings': 0,
                'active_listings': 0,
                'sold_listings': 0,
                'expired_listings': 0,
                'new_this_month': 0,
                'sold_this_month': 0,
                'conversion_rate': 0,
                'expiring_soon': 0,
                'property_type_chart': {'labels': [], 'values': []},
                'listing_type_chart': {'labels': [], 'values': []},
                'monthly_trend_chart': {'labels': [], 'values': []},
                'current_status_chart': {'labels': [], 'values': []},
                'service_validity_chart': {'labels': [], 'values': []},
                'top_cities_chart': {'labels': [], 'values': []},
                'error': str(e)
            }