# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from google.cloud import bigquery
import logging

_logger = logging.getLogger(__name__)

BIGQUERY_PROJECT_ID = 'cleardeals-459513'
EVENT_LOG_TABLE_ID = "active_to_active.nurture_event_log"

class ActiveTemplateStats(models.Model):
    _name = "active.template.stats"
    _description = "Active Lead Template Performance"
    _order = "date desc, template_name"
    _rec_name = "template_name"

    template_name = fields.Char(string="Template Name", readonly=True, index=True)
    date = fields.Date(string="Date", readonly=True, index=True)

    # --- Counts ---
    total_sent = fields.Integer(string="Total Sent", readonly=True)
    count_delivered = fields.Integer(string="Delivered", readonly=True)
    count_failed = fields.Integer(string="Failed", readonly=True)
    count_read = fields.Integer(string="Read", readonly=True)
    count_clicked = fields.Integer(string="Clicked", readonly=True)
    
    # --- Rates (Pre-calculated in BQ) ---
    delivery_rate = fields.Float(string="Delivery Rate %", readonly=True, group_operator="avg")
    read_rate = fields.Float(string="Read Rate %", readonly=True, group_operator="avg")
    click_rate = fields.Float(string="Click Rate %", readonly=True, group_operator="avg")
    engagement_rate = fields.Float(string="Engagement Rate %", readonly=True, group_operator="avg")

    _sql_constraints = [
        ('date_template_uniq', 'unique(date, template_name)',
         'The statistics for this template on this date already exist.')
    ]

    @api.model
    def _cron_fetch_active_template_stats(self, days=27):
        """Fetches template performance for Active-to-Active workflow."""
        _logger.info("Starting Active Template Stats Sync...")
        
        try:
            client = bigquery.Client(project=BIGQUERY_PROJECT_ID)
        except Exception as e:
            _logger.error(f"Failed to create BigQuery client: {e}")
            return

        # We limit the lookback to optimize query costs
        where_clause = f"AND event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)"

        query = f"""
            WITH TemplateMessages AS (
                SELECT
                    JSON_EXTRACT_SCALAR(raw_payload, '$.data.message.id') AS message_id,
                    JSON_EXTRACT_SCALAR(JSON_EXTRACT_SCALAR(raw_payload, '$.data.message.raw_template'), '$.name') AS template_name,
                    DATE(event_timestamp) AS sent_date
                FROM
                    `{EVENT_LOG_TABLE_ID}`
                WHERE
                    JSON_EXTRACT_SCALAR(raw_payload, '$.type') = 'message_api_sent' 
                    AND JSON_EXTRACT_SCALAR(raw_payload, '$.data.message.is_template_message') = 'true'
                    {where_clause}
            ),
            MessageOutcomes AS (
                SELECT
                    COALESCE(
                        JSON_EXTRACT_SCALAR(raw_payload, '$.data.message.id'), 
                        JSON_EXTRACT_SCALAR(raw_payload, '$.data.message.message_context.id') 
                    ) AS message_id,
                    
                    COUNTIF(JSON_EXTRACT_SCALAR(raw_payload, '$.type') IN ('message_api_delivered', 'message_api_read')) > 0 AS is_delivered,
                    COUNTIF(JSON_EXTRACT_SCALAR(raw_payload, '$.type') = 'message_api_read') > 0 AS is_read,
                    COUNTIF(JSON_EXTRACT_SCALAR(raw_payload, '$.type') = 'message_api_failed') > 0 AS is_failed,
                    COUNTIF(JSON_EXTRACT_SCALAR(raw_payload, '$.type') = 'message_api_clicked') > 0 AS is_clicked,
                    COUNTIF(JSON_EXTRACT_SCALAR(raw_payload, '$.type') = 'message_received') > 0 AS is_replied
                FROM
                    `{EVENT_LOG_TABLE_ID}`
                WHERE event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
                GROUP BY 1
            )
            SELECT
                tm.sent_date,
                tm.template_name,
                COUNT(tm.message_id) AS total_sent,
                
                COUNTIF(mo.is_delivered) AS count_delivered,
                COUNTIF(mo.is_failed) AS count_failed,
                COUNTIF(mo.is_read) AS count_read,
                COUNTIF(mo.is_clicked) AS count_clicked,
                
                -- Rates Calculation
                SAFE_DIVIDE(COUNTIF(mo.is_delivered), COUNT(tm.message_id)) * 100 AS delivery_rate,
                SAFE_DIVIDE(COUNTIF(mo.is_read), COUNTIF(mo.is_delivered)) * 100 AS read_rate,
                SAFE_DIVIDE(COUNTIF(mo.is_clicked), COUNTIF(mo.is_delivered)) * 100 AS click_rate,
                SAFE_DIVIDE(COUNTIF(mo.is_clicked OR mo.is_replied), COUNTIF(mo.is_delivered)) * 100 AS engagement_rate

            FROM TemplateMessages tm
            LEFT JOIN MessageOutcomes mo ON tm.message_id = mo.message_id
            WHERE tm.template_name IS NOT NULL
            GROUP BY 1, 2
            ORDER BY 1 DESC, 2
        """

        try:
            results = client.query(query).result()
        except Exception as e:
            _logger.error(f"Active Template Stats Query Failed: {e}")
            return

        count = 0
        Stats = self.sudo()
        
        for row in results:
            if not row.template_name: continue
            
            vals = {
                'date': row.sent_date,
                'template_name': row.template_name,
                'total_sent': row.total_sent,
                'count_delivered': row.count_delivered,
                'count_failed': row.count_failed,
                'count_read': row.count_read,
                'count_clicked': row.count_clicked,
                'delivery_rate': row.delivery_rate or 0.0,
                'read_rate': row.read_rate or 0.0,
                'click_rate': row.click_rate or 0.0,
                'engagement_rate': row.engagement_rate or 0.0
            }
            
            # Update existing or create new
            existing = Stats.search([
                ('date', '=', row.sent_date), 
                ('template_name', '=', row.template_name)
            ], limit=1)
            
            if existing:
                existing.write(vals)
            else:
                Stats.create(vals)
            count += 1
            
        _logger.info(f"Active Template Stats Sync Complete. Processed {count} records.")