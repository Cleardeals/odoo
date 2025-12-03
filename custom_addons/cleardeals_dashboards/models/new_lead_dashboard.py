from odoo import models, fields, api, _
from google.cloud import bigquery
import logging
from datetime import timedelta

_logger = logging.getLogger(__name__)

BIGQUERY_PROJECT_ID = 'cleardeals-459513'
EVENT_LOG_TABLE_ID = "New_Lead_Workflow.lead_event_log"


def bq_timestamp_to_odoo(dt):
    if dt is None: return False
    return dt.replace(tzinfo=None) if hasattr(dt, 'tzinfo') and dt.tzinfo else dt

class NewLeadDashboard(models.Model):
    _name = "leads.new.dashboard"
    _description = "New Portal Lead Dashboard"
    _order = "create_date desc"
    _rec_name = "lead_name"

    # --- Link to Main data ---
    lead_id = fields.Many2one('leads.new', string="Original Lead", required=True, ondelete='cascade')

    # --- Snapshot Fields ---
    lead_name = fields.Char(related='lead_id.name', store=True)
    lead_phone = fields.Char(related='lead_id.phone', store=True)
    portal_name = fields.Char(related='lead_id.portal_name', store=True)
    assigned_rm = fields.Many2one(related="lead_id.user_id", store=True)
    create_date = fields.Datetime(related="lead_id.create_date", store=True)
    current_status = fields.Selection(related="lead_id.current_status", store=True, string="Current Status")

    # --- Computed Metrics ---
    is_unassigned = fields.Boolean(string="Is Unassigned", compute="_compute_flags", store=True)
    is_contacted = fields.Boolean(string="Is Contacted", compute="_compute_metrics", store=True)
    is_delivered = fields.Boolean(string="Is Delivered", compute="_compute_metrics", store=True)
    is_read = fields.Boolean(string="Is Read", compute="_compute_metrics", store=True)
    has_replied = fields.Boolean(string="Replied", compute="_compute_metrics", store=True)
    last_event_date = fields.Datetime(string="Last Event", compute="_compute_metrics", store=True)

    cnt_initial_msg = fields.Integer(string="Sent: Engagement", compute="_compute_metrics", store=True)
    cnt_unassigned_msg = fields.Integer(string="Sent: Unassigned", compute="_compute_metrics", store=True)
    cnt_reply_plan_visit = fields.Integer(string="Reply: Plan Visit", compute="_compute_metrics", store=True)
    cnt_reply_similar = fields.Integer(string="Reply: Similar Options", compute="_compute_metrics", store=True)
    cnt_reply_call_now = fields.Integer(string="Reply: Call Now", compute="_compute_metrics", store=True)
    cnt_reply_chat_wa = fields.Integer(string="Reply: Chat/WhatsApp", compute="_compute_metrics", store=True)
    cnt_reply_call_opts = fields.Integer(string="Reply: Call for Options", compute="_compute_metrics", store=True)
    cnt_reply_send_wa = fields.Integer(string="Reply: Send WhatsApp", compute="_compute_metrics", store=True)

    # --- Relationship ---
    # This works because leads.new.event is defined in the other file and loaded in __init__
    event_ids = fields.One2many('leads.new.event', 'dashboard_id', string="History")

    _sql_constraints = [
        ('lead_uniq', 'unique(lead_id)', 'This lead dashboard record already exists.')
    ]

    @api.depends('assigned_rm')
    def _compute_flags(self):
        for rec in self:
            rec.is_unassigned = not rec.assigned_rm or rec.assigned_rm.id == 1

    @api.depends('event_ids.template_name', 'event_ids.message_direction', 'event_ids.correlation_id', 'event_ids.event_type', 'event_ids.event_timestamp')
    def _compute_metrics(self):
        for rec in self:
            events = rec.event_ids
            rec.is_contacted = any(e.message_direction == 'outbound' for e in events)
            rec.is_delivered = any(e.event_type in ['status_delivered', 'status_read'] for e in events)
            rec.is_read = any(e.event_type == 'status_read' for e in events)
            
            if events:
                rec.last_event_date = max(events.mapped('event_timestamp'))
            else:
                rec.last_event_date = False

            outbound = events.filtered(lambda e: e.message_direction == 'outbound' and e.template_name)

            def count_tmpl(name):
                msgs = outbound.filtered(lambda e: e.template_name == name)
                return len(set(msgs.mapped('correlation_id')))
            
            rec.cnt_initial_msg = count_tmpl('new_lead_engagement_message_v2_4q')
            rec.cnt_unassigned_msg = count_tmpl('unassigned_leads_message')
            rec.cnt_reply_plan_visit = count_tmpl('plan_site_visit_response_55')
            rec.cnt_reply_similar = count_tmpl('see_similar_options_response')
            rec.cnt_reply_call_now = count_tmpl('yes_call_me_now_option')
            rec.cnt_reply_chat_wa = count_tmpl('chat_on_whatsapp_option')
            rec.cnt_reply_call_opts = count_tmpl('call_for_options_response')
            rec.cnt_reply_send_wa = count_tmpl('send_on_whatsapp_option')

    # =============== CRON JOBS ===============
    @api.model
    def _cron_sync_new_leads_dashboard(self):
        _logger.info('Starting New Leads Dashboard Sync...')
        days = 5
        self._sync_leads_from_source(days=days)
        self.fetch_bq_events(days=days)
        self.cron_fetch_template_stats(days=days)
        _logger.info("New Leads Dashboard Sync Complete.")

    def _sync_leads_from_source(self, days=5):
        cutoff_date = fields.Datetime.now() - timedelta(days=days)
        recent_leads = self.env['leads.new'].search([('create_date', '>=', cutoff_date)])
        existing_dash = self.search([('lead_id', 'in', recent_leads.ids)])
        existing_lead_ids = existing_dash.mapped('lead_id.id')
        leads_to_create = [l for l in recent_leads if l.id not in existing_lead_ids]
        if leads_to_create:
            vals_list = [{'lead_id': l.id} for l in leads_to_create]
            self.create(vals_list)
            _logger.info(f"Added {len(vals_list)} new leads to dashboard.")

    def fetch_bq_events(self, days=5):
        dash_records = self.search([('create_date', '>=', fields.Datetime.now() - timedelta(days=days))])
        if not dash_records: return

        phone_map = {}
        for r in dash_records:
            if r.lead_phone:
                clean = ''.join(filter(str.isdigit, r.lead_phone))[-10:]
                if len(clean) == 10: phone_map[clean] = r
        if not phone_map: return
        phones_list = ", ".join(f"'{p}'" for p in phone_map.keys())

        client = bigquery.Client(project=BIGQUERY_PROJECT_ID)
        
        # Optimized Query with JSON Parsing in SQL
        query = f"""
            SELECT event_id, event_timestamp, event_type, message_direction, message_content, conversation_id, raw_payload, failure_reason,
                COALESCE(
                    JSON_VALUE(raw_payload, '$.data.message.raw_template.name'),
                    JSON_VALUE(JSON_VALUE(raw_payload, '$.data.message.raw_template'), '$.name')
                ) AS template_name,
                COALESCE(correlation_id, JSON_VALUE(raw_payload, '$.data.message.id')) AS correlation_id
            FROM `{EVENT_LOG_TABLE_ID}`
            WHERE RIGHT(conversation_id, 10) IN ({phones_list})
              AND ingestion_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
        """
        try:
            results = client.query(query).result()
        except Exception as e:
            _logger.error(f"BQ Error: {e}")
            return

        Event = self.env['leads.new.event'].sudo()
        vals_list = []
        existing_event_ids = set(Event.search([('event_id', 'in', [row.event_id for row in results])]).mapped('event_id'))

        for row in results:
            if row.event_id in existing_event_ids: continue
            phone10 = str(row.conversation_id)[-10:]
            dash_rec = phone_map.get(phone10)
            if dash_rec:
                vals_list.append({
                    'dashboard_id': dash_rec.id,
                    'event_id': row.event_id,
                    'correlation_id': row.correlation_id or False,
                    'event_timestamp': bq_timestamp_to_odoo(row.event_timestamp),
                    'event_type': row.event_type,
                    'message_direction': row.message_direction,
                    'message_content': row.message_content or "",
                    'template_name': row.template_name or False,
                    'failure_reason': row.failure_reason or False,
                    'raw_payload': row.raw_payload or ""
                })
        if vals_list:
            Event.create(vals_list)
            _logger.info(f"Synced {len(vals_list)} events from BigQuery.")

    @api.model
    def cron_fetch_template_stats(self, days=5):
        client = bigquery.Client(project=BIGQUERY_PROJECT_ID)
        query = f"""
            WITH AllEvents AS (
                SELECT DATE(event_timestamp) AS event_date,
                    COALESCE(correlation_id, JSON_VALUE(raw_payload, '$.data.message.id')) AS correlation_id,
                    message_direction, event_type,
                    COALESCE(JSON_VALUE(raw_payload, '$.data.message.raw_template.name'), JSON_VALUE(JSON_VALUE(raw_payload, '$.data.message.raw_template'), '$.name')) AS template_name
                FROM `{EVENT_LOG_TABLE_ID}`
                WHERE ingestion_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
            ),
            TemplateMessages AS (
                SELECT correlation_id, ANY_VALUE(event_date) as send_date, ANY_VALUE(template_name) as template_name
                FROM AllEvents WHERE message_direction = 'outbound' AND template_name IS NOT NULL AND correlation_id IS NOT NULL GROUP BY correlation_id
            ),
            MessageStats AS (
                SELECT tm.correlation_id, tm.send_date, tm.template_name,
                    MAX(CASE WHEN ae.event_type IN ('status_delivered', 'status_read') THEN 1 ELSE 0 END) as is_delivered,
                    MAX(CASE WHEN ae.event_type = 'status_read' THEN 1 ELSE 0 END) as is_read,
                    MAX(CASE WHEN ae.event_type = 'status_failed' THEN 1 ELSE 0 END) as is_failed,
                    MAX(CASE WHEN ae.message_direction = 'inbound' THEN 1 WHEN ae.event_type = 'message_api_clicked' THEN 1 ELSE 0 END) as is_clicked
                FROM TemplateMessages tm JOIN AllEvents ae ON tm.correlation_id = ae.correlation_id GROUP BY 1, 2, 3
            )
            SELECT send_date AS date, template_name, COUNT(*) AS total_sent, SUM(is_delivered) AS total_delivered, SUM(is_read) AS total_read, SUM(is_clicked) AS total_clicked, SUM(is_failed) AS total_failed
            FROM MessageStats GROUP BY 1, 2 ORDER BY 1 DESC, 2
        """
        try:
            results = client.query(query).result()
        except Exception as e:
            _logger.error(f"Template Stats Query Failed: {e}")
            return
        Stats = self.env['leads.new.template.stats'].sudo()
        for row in results:
            if not row.template_name: continue
            vals = {'date': row.date, 'template_name': row.template_name, 'total_sent': row.total_sent, 'total_delivered': row.total_delivered, 'total_read': row.total_read, 'total_clicked': row.total_clicked, 'total_failed': row.total_failed}
            existing = Stats.search([('date', '=', row.date), ('template_name', '=', row.template_name)], limit=1)
            if existing: existing.write(vals)
            else: Stats.create(vals)