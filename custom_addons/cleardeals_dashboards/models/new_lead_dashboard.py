from odoo import models, fields, api, _
from google.cloud import bigquery
import logging
from datetime import timedelta
import json

_logger = logging.getLogger(__name__)

BIGQUERY_PROJECT_ID = 'cleardeals-459513'
EVENT_LOG_TABLE_ID = "New_Lead_Workflow.lead_event_log"


def bq_timestamp_to_odoo(dt):
    """Convert BigQuery timestamp to Odoo datetime (removing timezone info)"""
    if dt is None:
        return False
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
    lead_create_date = fields.Datetime(
        related="lead_id.create_date", 
        store=True, 
        string="Lead Created Time (UTC)"
    )
    lead_create_date_only = fields.Date(
        related="lead_id.create_date_only", 
        store=True, 
        string="Creation Date (IST)"
    )
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
    event_ids = fields.One2many('leads.new.event', 'dashboard_id', string="History")

    _sql_constraints = [
        ('lead_uniq', 'unique(lead_id)', 'This lead dashboard record already exists.')
    ]

    @api.depends('assigned_rm')
    def _compute_flags(self):
        for rec in self:
            rec.is_unassigned = not rec.assigned_rm or rec.assigned_rm.id == 1

    @api.depends('event_ids.template_name', 'event_ids.message_direction', 
                 'event_ids.correlation_id', 'event_ids.event_type', 'event_ids.event_timestamp')
    def _compute_metrics(self):
        for rec in self:
            events = rec.event_ids
            rec.is_contacted = any(e.message_direction == 'outbound' for e in events)
            rec.is_delivered = any(e.event_type in ['status_delivered', 'status_read'] for e in events)
            rec.is_read = any(e.event_type == 'status_read' for e in events)
            rec.has_replied = any(e.message_direction == 'inbound' for e in events)
            
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
        _logger.info('🔄 Starting New Leads Dashboard Sync...')
        days = 60
        self._sync_leads_from_source(days=days)
        self.fetch_bq_events(days=days)
        self.cron_fetch_template_stats(days=days)
        _logger.info("✅ New Leads Dashboard Sync Complete.")

    def _sync_leads_from_source(self, days=5):
        """Sync leads from leads.new to dashboard"""
        cutoff_date = fields.Datetime.now() - timedelta(days=days)
        recent_leads = self.env['leads.new'].search([('create_date', '>=', cutoff_date)])
        
        if not recent_leads:
            _logger.info(f"No new leads found in last {days} days")
            return
            
        existing_dash = self.search([('lead_id', 'in', recent_leads.ids)])
        existing_lead_ids = existing_dash.mapped('lead_id.id')
        leads_to_create = [l for l in recent_leads if l.id not in existing_lead_ids]
        
        if leads_to_create:
            vals_list = [{'lead_id': l.id} for l in leads_to_create]
            self.create(vals_list)
            _logger.info(f"✅ Added {len(vals_list)} new leads to dashboard.")
        else:
            _logger.info(f"All {len(recent_leads)} leads already exist in dashboard")


            

    def fetch_bq_events(self, days=5):
        _logger.info(f"Starting Dashboard Sync: Fetching BQ events for the last {days} days...")
        
        # 1. Fetch ALL Dashboards
        dashboards = self.search([])
        if not dashboards: return

        # 2. Build Phone Map (One Phone -> LIST of Dashboards)
        phone_map = {}
        for d in dashboards:
            if d.lead_phone:
                clean = ''.join(filter(str.isdigit, d.lead_phone))[-10:]
                if len(clean) == 10:
                    if clean not in phone_map:
                        phone_map[clean] = []
                    phone_map[clean].append(d)
        
        if not phone_map: return

        # 3. Build SQL "IN" Clause
        phones_list = ", ".join(f"'{p}'" for p in phone_map.keys())

        client = bigquery.Client(project=BIGQUERY_PROJECT_ID)
        
        # 4. QUERY BQ
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
            _logger.error(f"BQ Query Error: {e}")
            return

        # 5. Process Results
        Event = self.env['leads.new.event'].sudo()
        vals_list = []
        
        # Optimization: Fetch all event_ids present in Odoo to save memory
        bq_event_ids = [str(r.event_id) for r in results]
        if not bq_event_ids: return

        # Search existing events to prevent duplicates
        existing_records = Event.search([('event_id', 'in', bq_event_ids)])
        # Create a "Composite Key" set: (dashboard_id, event_id)
        existing_keys = set((r.dashboard_id.id, r.event_id) for r in existing_records)
        
        # Reset iterator
        results = client.query(query).result()

        for row in results:
            raw_bq_phone = str(row.conversation_id)
            if raw_bq_phone.endswith('.0'): raw_bq_phone = raw_bq_phone[:-2]
            clean_bq_phone = ''.join(filter(str.isdigit, raw_bq_phone))[-10:]
            
            # Get ALL dashboards for this phone
            target_dashboards = phone_map.get(clean_bq_phone, [])
            
            for dash_rec in target_dashboards:
                # Check for duplicates on THIS specific dashboard
                if (dash_rec.id, str(row.event_id)) in existing_keys:
                    continue

                vals_list.append({
                    'dashboard_id': dash_rec.id,
                    'event_id': str(row.event_id),
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
            _logger.info(f"Synced {len(vals_list)} events across {len(phone_map)} phone numbers.")

    @api.model
    def cron_fetch_template_stats(self, days=7):
        """Fetch template statistics from BigQuery with timezone awareness"""
        _logger.info("📊 Fetching New Lead Template Stats...")
        client = bigquery.Client(project=BIGQUERY_PROJECT_ID)
        
        days_int = int(days)

        query = f"""
            WITH SentMessages AS (
                SELECT DISTINCT
                    COALESCE(
                        correlation_id, 
                        JSON_EXTRACT_SCALAR(raw_payload, '$.data.message.id')
                    ) AS msg_id,
                    conversation_id,
                    -- Convert UTC to IST (UTC+5:30) for date calculation
                    DATE(DATETIME(event_timestamp, 'Asia/Kolkata')) AS event_date,
                    event_timestamp AS sent_timestamp,
                    -- Extract template name - raw_template is a JSON string that needs parsing
                    COALESCE(
                        JSON_EXTRACT_SCALAR(
                            JSON_EXTRACT_SCALAR(raw_payload, '$.data.message.raw_template'),
                            '$.name'
                        ),
                        'Unknown Template'
                    ) AS template_name
                FROM `{EVENT_LOG_TABLE_ID}`
                -- Use IST timezone for the time window calculation
                WHERE event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days_int} DAY)
                    AND message_direction = 'outbound'
                    AND event_type = 'status_sent'
            ),
            FilteredSentMessages AS (
                SELECT * FROM SentMessages
                WHERE template_name NOT IN ('sell_lead_template', 'sell_lead_yes_response', 'sell_lead_no_response')
            ),
            MessageStatuses AS (
                SELECT DISTINCT
                    sm.msg_id,
                    e.event_type
                FROM FilteredSentMessages sm
                INNER JOIN `{EVENT_LOG_TABLE_ID}` e
                    ON e.correlation_id = sm.msg_id
                    AND e.event_timestamp >= sm.sent_timestamp
                    AND e.event_timestamp <= TIMESTAMP_ADD(sm.sent_timestamp, INTERVAL 48 HOUR)
                    AND e.message_direction = 'outbound'
                    AND e.event_type IN ('status_delivered', 'status_read', 'status_failed')
            ),
            ClickEvents AS (
                SELECT DISTINCT sm.msg_id
                FROM FilteredSentMessages sm
                INNER JOIN `{EVENT_LOG_TABLE_ID}` e
                    ON e.correlation_id = sm.msg_id
                    AND e.event_timestamp >= sm.sent_timestamp
                    AND e.event_timestamp <= TIMESTAMP_ADD(sm.sent_timestamp, INTERVAL 48 HOUR)
                    AND e.event_type = 'message_api_clicked'
            ),
            InboundReplies AS (
                SELECT DISTINCT sm.msg_id
                FROM FilteredSentMessages sm
                INNER JOIN `{EVENT_LOG_TABLE_ID}` e
                    ON e.conversation_id = sm.conversation_id
                    AND e.message_direction = 'inbound'
                    AND e.event_timestamp >= sm.sent_timestamp
                    AND e.event_timestamp <= TIMESTAMP_ADD(sm.sent_timestamp, INTERVAL 48 HOUR)
            ),
            AggregatedStats AS (
                SELECT
                    sm.event_date,
                    sm.template_name,
                    sm.msg_id,
                    sm.conversation_id,  -- Passed through for Pending list
                    -- Status flags
                    MAX(CASE WHEN ms.event_type IN ('status_delivered', 'status_read') THEN 1 ELSE 0 END) as is_delivered,
                    MAX(CASE WHEN ms.event_type = 'status_read' THEN 1 ELSE 0 END) as is_read,
                    MAX(CASE WHEN ms.event_type = 'status_failed' THEN 1 ELSE 0 END) as is_failed,
                    -- Activity flags
                    MAX(CASE WHEN ce.msg_id IS NOT NULL THEN 1 ELSE 0 END) as is_clicked,
                    MAX(CASE WHEN ir.msg_id IS NOT NULL THEN 1 ELSE 0 END) as is_replied
                FROM FilteredSentMessages sm
                LEFT JOIN MessageStatuses ms ON ms.msg_id = sm.msg_id
                LEFT JOIN ClickEvents ce ON ce.msg_id = sm.msg_id
                LEFT JOIN InboundReplies ir ON ir.msg_id = sm.msg_id
                GROUP BY sm.event_date, sm.template_name, sm.msg_id, sm.conversation_id
            )
            SELECT
                event_date AS date,
                template_name,
                COUNT(DISTINCT msg_id) AS total_sent,
                SUM(is_delivered) AS total_delivered,
                SUM(is_read) AS total_read,
                SUM(is_clicked) AS total_clicked,
                SUM(is_replied) AS total_replied,
                SUM(is_failed) AS total_failed,
                -- Calculate Pending: Not delivered AND Not failed
                SUM(CASE WHEN is_delivered = 0 AND is_failed = 0 THEN 1 ELSE 0 END) as total_pending,
                -- Aggregate Phone Numbers for Pending messages
                STRING_AGG(DISTINCT CASE WHEN is_delivered = 0 AND is_failed = 0 THEN conversation_id END, ', ') as pending_numbers
            FROM AggregatedStats
            GROUP BY 1, 2
            ORDER BY 1 DESC, 2
        """

        try:
            results = list(client.query(query).result())
        except Exception as e:
            _logger.error(f"❌ Template Stats Query Failed: {e}")
            return

        if not results:
            _logger.warning("⚠️ Query executed successfully but returned 0 records.")
            return

        Stats = self.env['leads.new.template.stats'].sudo()
        updated_count = 0
        created_count = 0
        
        # Calculate totals for logging
        total_sent_all = 0
        total_pending_all = 0

        for row in results:
            if not row.template_name:
                continue
                
            vals = {
                'date': row.date,
                'template_name': row.template_name,
                'total_sent': row.total_sent,
                'total_delivered': row.total_delivered,
                'total_read': row.total_read,
                'total_clicked': row.total_clicked,
                'total_replied': row.total_replied,
                'total_failed': row.total_failed,
                # New Fields
                'total_pending': row.total_pending,
                'pending_phone_numbers': row.pending_numbers or ''
            }
            
            total_sent_all += row.total_sent
            total_pending_all += row.total_pending

            existing = Stats.search([
                ('date', '=', row.date), 
                ('template_name', '=', row.template_name)
            ], limit=1)
            
            if existing:
                existing.write(vals)
                updated_count += 1
            else:
                Stats.create(vals)
                created_count += 1

        _logger.info(
            f"✅ Template stats complete: {created_count} created, {updated_count} updated. "
            f"Total Sent: {total_sent_all}, Total Pending: {total_pending_all}"
        )