from odoo import models, api
import logging

_logger = logging.getLogger(__name__)

class PropertyDashboard(models.TransientModel):
    _name = 'property.dashboard'
    _description = 'Dashboard Backend Model'

    @api.model
    def get_kpis(self):
        
        try:
            # Get the model - add error handling
            if 'property.listing' not in self.env:
                _logger.error("❌ Model 'property.listing' not found!")
                return {'active_listings': 0, 'sold_listings': 0, 'error': 'Model not found'}
            
            listings_model = self.env['property.listing']
            _logger.info(f"📦 Using model: {listings_model._name}")

            # Check if model has records
            total_records = listings_model.search_count([])
            _logger.info(f"📊 Total records in property.listing: {total_records}")

            # Find ALL unique property_status values
            try:
                statuses = listings_model.read_group(
                    [], 
                    ['property_status'], 
                    ['property_status']
                )
                _logger.info(f"📋 All property_status values found: {statuses}")
            except Exception as e:
                _logger.error(f"❌ Error reading property_status groups: {e}")
                statuses = []

            # Count active and sold with error handling
            try:
                active_count = listings_model.search_count([('property_status', '=', 'live')])
                sold_count = listings_model.search_count([('property_status', '=', 'sold')])
                
                _logger.info(f"📊 Active count (searching for 'live'): {active_count}")
                _logger.info(f"📊 Sold count (searching for 'sold'): {sold_count}")
                
                # Use actual counts instead of hardcoded values
                result = {
                    'active_listings': active_count,
                    'sold_listings': sold_count,
                    'total_records': total_records,
                    'available_statuses': [status['property_status'] for status in statuses if status['property_status']]
                }
                
            except Exception as e:
                _logger.error(f"❌ Error counting records: {e}")
                result = {
                    'active_listings': 0,
                    'sold_listings': 0,
                    'error': str(e)
                }

            _logger.info(f"📤 Returning KPIs: {result}")
            return result
            
        except Exception as e:
            _logger.error(f"❌ Fatal error in get_kpis: {e}")
            return {
                'active_listings': 0,
                'sold_listings': 0,
                'error': str(e)
            }