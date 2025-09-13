from odoo import models, api
from datetime import date
from dateutil.relativedelta import relativedelta
import logging

_logger = logging.getLogger(__name__)

class PropertyDashboard(models.TransientModel):
    _name = 'property.dashboard'
    _description = 'Dashboard Backend Model'

    @api.model
    def get_kpis(self):
        
        try:
            # Get the model - add error handling
            
            listings_model = self.env['property.listing']
            _logger.info(f"📦 Using model: {listings_model._name}")


            active_count = listings_model.search_count([('property_status', '=', 'live')])
            sold_count = listings_model.search_count([('property_status', '=', 'sold')])
            
            start_of_month = date.today().replace(day=1)
            new_this_month = listings_model.search_count([('property_register_date', '>=', start_of_month)])

            # Chart Data

            type_data = listings_model.read_group(
                [('property_status', '=', 'live'), ('property_price', '>', 0)],
                ['property_type'],
                ['property_type']
            )

            chart_data = {
                'labels': [d.get('property_type') for d in type_data],
                'values': [d.get('property_type_count', 0) for d in type_data],
            }

            result = {
                'active_listings': active_count,
                'sold_listings': sold_count,
                'new_this_month': new_this_month,
                'listings_by_type': chart_data,
            }
            
            _logger.info(f"📤 Returning KPIs: {result}")
            return result
            
        except Exception as e:
            _logger.error(f"❌ Fatal error in get_kpis: {e}")
            return {
                'active_listings': 0,
                'sold_listings': 0,
                'new_this_month': 0,
                'listings_by_type': {
                    'labels': [],
                    'values': []
                },
                'error': str(e)
            }