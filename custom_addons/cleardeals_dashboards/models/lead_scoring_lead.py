# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from google.cloud import bigquery
import logging
import json

_logger = logging.getLogger(__name__)

BIGQUERY_PROJECT_ID = 'cleardeals-459513'
EVENT_LOG_TABLE_ID = "lead_scoring.interakt_events"
LEAD_SOURCE_TABLE_ID = "lead_scoring.daily_scored_leads_final" 

def bq_timestamp_to_odoo(dt):
    if dt is None: return False
    return dt.replace(tzinfo=None) if hasattr(dt, 'tzinfo') and dt.tzinfo else dt

class LeadScoringLead(models.Model):
    _name = "lead.scoring.lead"
    _description = "Lead Scoring Workflow Lead"
    _order = "last_activity desc"
    _rec_name = "lead_name"

    # --- Lead Details ---
    lead_name = fields.Char(string="Lead Name", index=True)
    lead_phone = fields.Char(string="Phone Number", required=True, index=True)
    property_tag = fields.Char(string="Property Tag")
    assigned_rm = fields.Char(string="Assigned RM")
    predicted_score = fields.Float(string="Score")
    current_status = fields.Char(string="Status")
    
    # --- Workflow Status ---
    workflow_stage = fields.Selection([
        ('ringing', 'Ringing / Busy'),
        ('detail_share_of_property', 'Details Shared'),
        ('site_visit_schedule_reminder', 'Site Visit Today'),
        ('site_visit_schedule_after_visit', 'Site Visit Yesterday'),
        ('other', 'Other')
    ], string="Current Stage", index=True)

    # --- Funnel Metrics ---
    is_delivered = fields.Boolean(string="Delivered", compute="_compute_metrics", store=True)
    is_read = fields.Boolean(string="Read", compute="_compute_metrics", store=True)
    has_replied = fields.Boolean(string="Replied", compute="_compute_metrics", store=True)
    
    last_response = fields.Char(string="Last Response", readonly=True)
    last_activity = fields.Datetime(string="Last Activity", index=True)

    # --- Detailed Template Tracking ---
    # 1. Initial Triggers
    cnt_ringing = fields.Integer(string="Sent: Ringing", compute="_compute_metrics", store=True)
    cnt_details = fields.Integer(string="Sent: Details Shared", compute="_compute_metrics", store=True)
    cnt_visit_reminder = fields.Integer(string="Sent: Visit Reminder", compute="_compute_metrics", store=True)
    cnt_visit_feedback = fields.Integer(string="Sent: Visit Feedback", compute="_compute_metrics", store=True)
    
    # 2. Response Handling
    cnt_resp_visited = fields.Integer(string="Reply: Successfully Visited", compute="_compute_metrics", store=True)
    cnt_resp_liked = fields.Integer(string="Reply: Liked Property", compute="_compute_metrics", store=True)
    cnt_resp_call_rm_visit = fields.Integer(string="Reply: Call RM (Visit)", compute="_compute_metrics", store=True)
    cnt_resp_reschedule = fields.Integer(string="Reply: Need Reschedule", compute="_compute_metrics", store=True)
    cnt_resp_call_back = fields.Integer(string="Reply: Call Me Back", compute="_compute_metrics", store=True)
    cnt_resp_convenient = fields.Integer(string="Reply: Pick Time", compute="_compute_metrics", store=True)
    cnt_resp_schedule_visit = fields.Integer(string="Reply: Schedule Visit", compute="_compute_metrics", store=True)
    cnt_resp_more_info = fields.Integer(string="Reply: Need Info", compute="_compute_metrics", store=True)
    cnt_resp_going = fields.Integer(string="Reply: Going for Visit", compute="_compute_metrics", store=True)
    cnt_resp_assistance = fields.Integer(string="Reply: Need Assistance", compute="_compute_metrics", store=True)

    # --- Relations ---
    event_ids = fields.One2many('lead.scoring.event', 'lead_id', string="History")

    _sql_constraints = [
        ('lead_phone_uniq', 'unique(lead_phone)', 'This lead already exists in the dashboard.')
    ]

    @api.depends('event_ids.event_type', 'event_ids.message_direction', 'event_ids.message_content', 'event_ids.template_name', 'event_ids.correlation_id')
    def _compute_metrics(self):
        for lead in self:
            # Basic Funnel
            lead.is_delivered = any(e.event_type in ('status_delivered', 'status_read') for e in lead.event_ids)
            lead.is_read = any(e.event_type == 'status_read' for e in lead.event_ids)
            
            inbound = lead.event_ids.filtered(lambda e: e.message_direction == 'inbound')
            lead.has_replied = bool(inbound)
            
            if inbound:
                lead.last_response = inbound.sorted(key=lambda r: r.event_timestamp, reverse=True)[0].message_content
            else:
                lead.last_response = False

            if lead.event_ids:
                lead.last_activity = max(lead.event_ids.mapped('event_timestamp'))
            else:
                lead.last_activity = False

            # Detailed Metrics
            outbound = lead.event_ids.filtered(lambda e: e.message_direction == 'outbound' and e.template_name)
            
            def count_unique_msgs(name):
                events = outbound.filtered(lambda e: e.template_name == name)
                return len(set(events.mapped('correlation_id')))
            
            lead.cnt_ringing = count_unique_msgs('ringing')
            lead.cnt_details = count_unique_msgs('detail_share_of_property')
            lead.cnt_visit_reminder = count_unique_msgs('site_visit_schedule_reminder')
            lead.cnt_visit_feedback = count_unique_msgs('site_visit_schedule_after_visit')
            lead.cnt_resp_visited = count_unique_msgs('site_visit_schedule_after_visit__successfully_visited')
            lead.cnt_resp_liked = count_unique_msgs('site_visit_schedule_after_visit__successfully_visited_i_liked_the_property')
            lead.cnt_resp_call_rm_visit = count_unique_msgs('site_visit_schedule_after_visit__successfully_visited_call_rm')
            lead.cnt_resp_reschedule = count_unique_msgs('site_visit_schedule_after_visit_need_to_reschedule')
            lead.cnt_resp_call_back = count_unique_msgs('ringing_call_me_back')
            lead.cnt_resp_convenient = count_unique_msgs('ringing_pick_a_convenient_time')
            lead.cnt_resp_schedule_visit = count_unique_msgs('detail_share_of_property_schedule_visit')
            lead.cnt_resp_more_info = count_unique_msgs('detail_share_of_property_need_more_information')
            lead.cnt_resp_going = count_unique_msgs('site_visit_schedule__going_for_the_visit')
            lead.cnt_resp_assistance = count_unique_msgs('site_visit_schedule_need_assistance')

    # ==================== CRON JOBS ====================

    @api.model
    def _cron_sync_lead_scoring(self):
        _logger.info("Starting Lead Scoring Sync...")
        self._fetch_leads_from_triggers(days=30)
        self._fetch_lead_events(days=30)
        self._cron_fetch_template_stats(days=30) # Also sync stats
        _logger.info("Lead Scoring Sync Complete.")

    @api.model
    def _fetch_leads_from_triggers(self, days=30):
        client = bigquery.Client(project=BIGQUERY_PROJECT_ID)
        templates = ['ringing', 'detail_share_of_property', 'site_visit_schedule_reminder', 'site_visit_schedule_after_visit']
        templates_sql = ", ".join(f"'{t}'" for t in templates)

        query = f"""
            WITH TriggerEvents AS (
                SELECT 
                    conversation_id,
                    event_timestamp,
                    COALESCE(
                        JSON_VALUE(raw_payload, '$.data.message.raw_template.name'),
                        JSON_VALUE(JSON_VALUE(raw_payload, '$.data.message.raw_template'), '$.name')
                    ) AS template_name
                FROM `{EVENT_LOG_TABLE_ID}`
                WHERE message_direction = 'outbound'
                  AND ingestion_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
            ),
            LatestTriggers AS (
                SELECT 
                    conversation_id, template_name, event_timestamp,
                    ROW_NUMBER() OVER(PARTITION BY conversation_id ORDER BY event_timestamp DESC) as rn
                FROM TriggerEvents
                WHERE template_name IN ({templates_sql})
            )
            SELECT 
                lt.conversation_id AS lead_phone,
                lt.template_name AS workflow_stage,
                lt.event_timestamp AS last_sent,
                COALESCE(src.customer_name, 'Unknown') as lead_name,
                src.assigned_rm,
                src.property_tag,
                src.predicted_score,
                src.current_status
            FROM LatestTriggers lt
            LEFT JOIN `{LEAD_SOURCE_TABLE_ID}` src
                ON RIGHT(CAST(lt.conversation_id AS STRING), 10) = RIGHT(CAST(src.standardized_phone AS STRING), 10)
            WHERE lt.rn = 1
        """
        
        try:
            results = client.query(query).result()
        except Exception as e:
            _logger.error(f"Lead Discovery Query Failed: {e}")
            return

        count = 0
        for row in results:
            phone_clean = ''.join(filter(str.isdigit, str(row.lead_phone)))[-10:]
            lead = self.search([('lead_phone', 'like', f'%{phone_clean}')], limit=1)
            vals = {
                'lead_name': row.lead_name,
                'assigned_rm': row.assigned_rm,
                'property_tag': row.property_tag,
                'predicted_score': row.predicted_score,
                'current_status': row.current_status,
                'workflow_stage': row.workflow_stage,
                'last_activity': bq_timestamp_to_odoo(row.last_sent)
            }
            if lead:
                lead.write(vals)
            else:
                vals['lead_phone'] = row.lead_phone
                try:
                    self.create(vals)
                    count += 1
                except Exception:
                    continue
        _logger.info(f"Synced {count} new leads.")

    @api.model
    def _fetch_lead_events(self, days=30):
        leads = self.search([])
        if not leads: return
        phone_map = {}
        for l in leads:
            clean = ''.join(filter(str.isdigit, l.lead_phone))[-10:]
            if len(clean) == 10: phone_map[clean] = l
        if not phone_map: return
        phones_list = ", ".join(f"'{p}'" for p in phone_map.keys())
        
        query = f"""
            SELECT 
                event_id, event_timestamp, event_type, message_direction, message_content, conversation_id, raw_payload, failure_reason,
                COALESCE(
                    JSON_VALUE(raw_payload, '$.data.message.raw_template.name'),
                    JSON_VALUE(JSON_VALUE(raw_payload, '$.data.message.raw_template'), '$.name')
                ) AS template_name,
                COALESCE(
                    correlation_id,
                    JSON_VALUE(raw_payload, '$.data.message.id')
                ) AS correlation_id
            FROM `{EVENT_LOG_TABLE_ID}`
            WHERE RIGHT(conversation_id, 10) IN ({phones_list})
              AND ingestion_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
        """
        
        Event = self.env['lead.scoring.event'].sudo()
        try:
            results = bigquery.Client(project=BIGQUERY_PROJECT_ID).query(query).result()
        except Exception as e:
            _logger.error(f"Event Fetch Error: {e}")
            return

        for row in results:
            phone10 = str(row.conversation_id)[-10:]
            lead = phone_map.get(phone10)
            if not lead: continue
            if Event.search_count([('event_id', '=', row.event_id)]): continue
            
            try:
                Event.create({
                    'lead_id': lead.id,
                    'event_id': row.event_id,
                    'correlation_id': row.correlation_id or False,
                    'event_timestamp': bq_timestamp_to_odoo(row.event_timestamp),
                    'event_type': row.event_type,
                    'message_direction': row.message_direction,
                    'message_content': row.message_content or "",
                    'raw_payload': row.raw_payload or "",
                    'template_name': row.template_name or False,
                    'failure_reason': row.failure_reason or False
                })
            except Exception:
                pass

    @api.model
    def _cron_fetch_template_stats(self, days=30):
        """Fetches aggregated stats for Lead Scoring workflow."""
        _logger.info("Fetching Lead Scoring Template Stats...")
        client = bigquery.Client(project=BIGQUERY_PROJECT_ID)
        
        query = f"""
            WITH ParsedEvents AS (
                SELECT
                    DATE(event_timestamp) AS event_date,
                    COALESCE(correlation_id, JSON_VALUE(raw_payload, '$.data.message.id')) AS correlation_id,
                    event_type,
                    COALESCE(
                        JSON_VALUE(raw_payload, '$.data.message.raw_template.name'),
                        JSON_VALUE(JSON_VALUE(raw_payload, '$.data.message.raw_template'), '$.name')
                    ) AS template_name,
                    JSON_VALUE(raw_payload, '$.type') AS payload_type
                FROM `{EVENT_LOG_TABLE_ID}`
                WHERE message_direction = 'outbound'
                  AND ingestion_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
            ),
            SentMessages AS (
                SELECT DISTINCT event_date, template_name, correlation_id
                FROM ParsedEvents
                WHERE template_name IS NOT NULL AND correlation_id IS NOT NULL
                  AND payload_type = 'message_api_sent'
            )
            SELECT
                s.event_date AS date,
                s.template_name,
                COUNT(DISTINCT s.correlation_id) AS total_sent,
                COUNT(DISTINCT CASE WHEN e.event_type IN ('status_delivered', 'status_read') THEN e.correlation_id ELSE NULL END) AS total_delivered,
                COUNT(DISTINCT CASE WHEN e.event_type = 'status_read' THEN e.correlation_id ELSE NULL END) AS total_read,
                COUNT(DISTINCT CASE WHEN e.event_type = 'status_failed' THEN e.correlation_id ELSE NULL END) AS total_failed
            FROM SentMessages s
            LEFT JOIN ParsedEvents e ON s.correlation_id = e.correlation_id
            GROUP BY 1, 2
        """
        
        try:
            results = client.query(query).result()
        except Exception as e:
            _logger.error(f"Template Stats Query Failed: {e}")
            return

        Stats = self.env['lead.scoring.template.stats'].sudo()
        for row in results:
            if not row.template_name: continue
            vals = {
                'date': row.date,
                'template_name': row.template_name,
                'total_sent': row.total_sent,
                'total_delivered': row.total_delivered,
                'total_read': row.total_read,
                'total_failed': row.total_failed
            }
            existing = Stats.search([('date', '=', row.date), ('template_name', '=', row.template_name)], limit=1)
            if existing:
                existing.write(vals)
            else:
                Stats.create(vals)