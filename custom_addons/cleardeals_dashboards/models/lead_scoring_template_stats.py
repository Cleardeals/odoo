from odoo import models, fields, api, _

class LeadScoringTemplateStats(models.Model):
    _name = "lead.scoring.template.stats"
    _description = "Lead Scoring Template Performance"
    _order = "date desc, template_name"
    _rec_name = "template_name"

    template_name = fields.Char(string="Template Name", readonly=True, index=True)
    date = fields.Date(string="Date", readonly=True, index=True)

    # --- Aggregated Metrics ---
    total_sent = fields.Integer(string="Total Sent", readonly=True)
    total_delivered = fields.Integer(string="Total Delivered", readonly=True)
    total_read = fields.Integer(string="Total Read", readonly=True)
    total_clicked = fields.Integer(string="Total Clicked", readonly=True) # New Field
    total_failed = fields.Integer(string="Total Failed", readonly=True)

    # --- Computed Rates ---
    delivery_rate = fields.Float(string="Delivery Rate %", compute="_compute_rates", store=True, group_operator="avg")
    read_rate = fields.Float(string="Read Rate %", compute="_compute_rates", store=True, group_operator="avg")
    click_rate = fields.Float(string="Click Rate %", compute="_compute_rates", store=True, group_operator="avg") # New Field

    _sql_constraints = [
        ('date_tmpl_uniq', 'unique(date, template_name)',
         'The statistics for this template on this date already exist.')
    ]

    @api.depends('total_sent', 'total_delivered', 'total_read', 'total_clicked', 'total_failed')
    def _compute_rates(self):
        for record in self:
            # Delivery Rate = Delivered / Sent
            if record.total_sent > 0:
                val = (record.total_delivered / record.total_sent) * 100
                record.delivery_rate = min(val, 100.0)
            else:
                record.delivery_rate = 0.0
            
            # Read Rate = Read / Delivered
            if record.total_delivered > 0:
                val = (record.total_read / record.total_delivered) * 100
                record.read_rate = min(val, 100.0)
            else:
                record.read_rate = 0.0

            # Click Rate = Clicked / Read
            if record.total_read > 0:
                val = (record.total_clicked / record.total_read) * 100
                record.click_rate = min(val, 100.0)
            else:
                record.click_rate = 0.0