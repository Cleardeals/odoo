from odoo import models, fields, api, _
from datetime import datetime, time

class RenewalTemplateStats(models.Model):
    _name = "renewal.template.stats"
    _description = "Renewal Template Performance"
    _order = "date desc, template_name"
    _rec_name = "template_name"

    template_name = fields.Char(string="Template Name", readonly=True, index=True)
    date = fields.Date(string="Date", readonly=True, index=True)

    # --- Aggregated Metrics ---
    total_sent = fields.Integer(string="Total Sent", readonly=True)
    total_delivered = fields.Integer(string="Total Delivered", readonly=True)
    total_read = fields.Integer(string="Total Read", readonly=True)
    total_failed = fields.Integer(string="Total Failed", readonly=True)

    # --- Computed Rates ---
    delivery_rate = fields.Float(string="Delivery Rate %", compute="_compute_rates", store=True, group_operator="avg")
    read_rate = fields.Float(string="Read Rate %", compute="_compute_rates", store=True, group_operator="avg")

    _sql_constraints = [
        ('date_template_uniq', 'unique(date, template_name)',
         'The statistics for this template on this date already exist.')
    ]

    @api.depends('total_sent', 'total_delivered', 'total_read', 'total_failed')
    def _compute_rates(self):
        """Calculates the delivery and read rates."""
        for record in self:
            # Fixed Formula: Delivered / Total Sent
            if record.total_sent > 0:
                record.delivery_rate = (record.total_delivered / record.total_sent) * 100
            else:
                record.delivery_rate = 0.0
            
            # Read Rate: Read / Delivered
            if record.total_delivered > 0:
                record.read_rate = (record.total_read / record.total_delivered) * 100
            else:
                record.read_rate = 0.0

    def action_view_owners(self):
        """Opens a list of owners who received this template on this date."""
        self.ensure_one()
        
        # 1. Define the time range for the specific date (00:00:00 to 23:59:59)
        start_dt = datetime.combine(self.date, time.min)
        end_dt = datetime.combine(self.date, time.max)

        # 2. Find events matching this template and date
        # We look for 'outbound' messages (sent to owner)
        events = self.env['renewal.interakt.event'].search([
            ('template_name', '=', self.template_name),
            ('event_timestamp', '>=', start_dt),
            ('event_timestamp', '<=', end_dt),
            ('message_direction', '=', 'outbound'),
            ('owner_id', '!=', False)
        ])

        # 3. Get unique Owner IDs
        owner_ids = events.mapped('owner_id').ids

        # 4. Return action to view those owners
        return {
            'name': f"Owners: {self.template_name} ({self.date})",
            'type': 'ir.actions.act_window',
            'res_model': 'renewal.property.owner',
            'view_mode': 'list,form',
            'domain': [('id', 'in', owner_ids)],
            'context': {'create': False} # Disable creation in this drill-down
        }