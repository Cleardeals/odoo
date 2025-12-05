from odoo import models, fields, api, _

class NewLeadTemplateStats(models.Model):
    _name = "leads.new.template.stats"
    _description = "New Lead Template Performance"
    _order = "date desc, template_name"
    _rec_name = "template_name"

    template_name = fields.Char(string="Template Name", readonly=True, index=True)
    date = fields.Date(string="Date", readonly=True, index=True)

    # --- Aggregated Metrics ---
    total_sent = fields.Integer(string="Total Sent", readonly=True)
    total_delivered = fields.Integer(string="Total Delivered", readonly=True)
    total_read = fields.Integer(string="Total Read", readonly=True)
    total_failed = fields.Integer(string="Total Failed", readonly=True)
    
    # --- NEW FIELDS (Added to match Lead Scoring) ---
    total_clicked = fields.Integer(string="Total Clicked", readonly=True) 
    total_replied = fields.Integer(string="Total Replied", readonly=True)

    # --- Computed Rates ---
    delivery_rate = fields.Float(string="Delivery Rate %", compute="_compute_rates", store=True, group_operator="avg")
    read_rate = fields.Float(string="Read Rate %", compute="_compute_rates", store=True, group_operator="avg")
    click_rate = fields.Float(string="Click Rate %", compute="_compute_rates", store=True, group_operator="avg")
    reply_rate = fields.Float(string="Reply Rate %", compute="_compute_rates", store=True, group_operator="avg")

    _sql_constraints = [
        ('date_tmpl_uniq_new', 'unique(date, template_name)',
         'The statistics for this template on this date already exist.')
    ]

    @api.depends('total_sent', 'total_delivered', 'total_read', 'total_clicked', 'total_replied', 'total_failed')
    def _compute_rates(self):
        for record in self:
            # 1. Delivery Rate = Delivered / Sent
            if record.total_sent > 0:
                val = (record.total_delivered / record.total_sent) * 100
                record.delivery_rate = min(val, 100.0)
            else:
                record.delivery_rate = 0.0
            
            # 2. Read Rate = Read / Delivered
            if record.total_delivered > 0:
                val = (record.total_read / record.total_delivered) * 100
                record.read_rate = min(val, 100.0)
            else:
                record.read_rate = 0.0

            # 3. Click Rate = Clicked / Read (Matching your reference logic)
            if record.total_read > 0:
                val = (record.total_clicked / record.total_read) * 100
                record.click_rate = min(val, 100.0)
            else:
                record.click_rate = 0.0

            # 4. Reply Rate = Replied / Delivered
            if record.total_delivered > 0:
                val = (record.total_replied / record.total_delivered) * 100
                record.reply_rate = min(val, 100.0)
            else:
                record.reply_rate = 0.0