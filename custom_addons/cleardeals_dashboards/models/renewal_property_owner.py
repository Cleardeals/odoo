# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from google.cloud import bigquery
import logging
import json

_logger = logging.getLogger(__name__)

BIGQUERY_PROJECT_ID = 'cleardeals-459513'
ASSIGNMENT_TABLE_ID = "Property_Matching.Routed_Lead_Assignments"
EVENT_LOG_TABLE_ID = "Property_Matching.Interakt_Event_Log"
CUSTOMER_DATA_TABLE_ID = "cleardeals_dataset.Customer_Data"


def bq_timestamp_to_odoo(dt):
    """Convert BigQuery aware UTC timestamp -> Odoo naive UTC datetime"""
    if dt is None:
        return False
    return dt.replace(tzinfo=None) if hasattr(dt, 'tzinfo') and dt.tzinfo else dt


class RenewalPropertyOwner(models.Model):
    _name = "renewal.property.owner"
    _description = "Expired Property Owner - Renewal Campaign"
    _order = "last_activity_date desc"
    _rec_name = "owner_name"

    # --- Core Owner / Property Details ---
    owner_name = fields.Char(string="Owner Name", readonly=True, index=True)
    owner_phone = fields.Char(string="Owner Phone", readonly=True, index=True)
    expired_property_tag = fields.Char(string="Expired Property Tag", required=True, index=True)

    # --- Aggregated Metrics ---
    total_leads_sent = fields.Integer(string="Total Leads Sent", compute="_compute_metrics", store=True)
    total_leads_delivered = fields.Integer(string="Leads Delivered", compute="_compute_metrics", store=True)
    total_leads_read = fields.Integer(string="Leads Read", compute="_compute_metrics", store=True)
    total_leads_clicked = fields.Integer(string="Leads Clicked", compute="_compute_metrics", store=True)
    total_details_shared = fields.Integer(string="Full Details Shared", compute="_compute_metrics", store=True)
    total_failures = fields.Integer(string="Total Failures", compute="_compute_metrics", store=True)
    total_not_interested = fields.Integer(string="Total Not Interested", compute="_compute_metrics", store=True)

    # --- Engagement Rates ---
    delivery_rate = fields.Float(string="Delivery Rate %", compute="_compute_rates", store=True, group_operator="avg")
    read_rate = fields.Float(string="Read Rate %", compute="_compute_rates", store=True, group_operator="avg")
    click_rate = fields.Float(string="Click Rate %", compute="_compute_rates", store=True, group_operator="avg")

    # --- Owner Response Status ---
    overall_status = fields.Selection([
        ('active', 'Active - Responding'),
        ('engaged', 'Engaged - Reading'),
        ('passive', 'Passive - Not Responding'),
        ('not_interested', 'Explicitly Not Interested'),
        ('failed', 'Messages Failed'),
        ('renewed', 'Service Renewed')
    ], string="Overall Status", default='passive', compute="_compute_overall_status", store=True)

    # --- Renewal Tracking ---
    renewal_request_sent = fields.Boolean(string="Renewal Request Sent", compute="_compute_renewal_status", store=True)
    renewal_request_date = fields.Datetime(string="Renewal Request Date", compute="_compute_renewal_status", store=True)
    renewal_response = fields.Selection([
        ('pending', 'Pending'),
        ('interested', 'Interested'),
        ('not_interested', 'Not Interested'),
        ('renewed', 'Renewed')
    ], string="Renewal Response", default='pending', tracking=True)

    # --- Activity Tracking ---
    last_activity_date = fields.Datetime(string="Last Activity", compute="_compute_last_activity", store=True)
    last_message_sent = fields.Datetime(string="Last Message Sent", compute="_compute_last_activity", store=True)
    last_message_read = fields.Datetime(string="Last Message Read", compute="_compute_last_activity", store=True)
    last_button_clicked = fields.Datetime(string="Last Button Clicked", compute="_compute_last_activity", store=True)

    # --- Relations ---
    assignment_ids = fields.One2many('renewal.lead.assignment', 'owner_id', string="Lead Assignments")
    event_ids = fields.One2many('renewal.interakt.event', 'owner_id', string="Interakt Events")

    _sql_constraints = [
        ('property_tag_uniq', 'unique(expired_property_tag)',
         'This property tag already exists in the campaign.')
    ]
    
    # ==================== COMPUTE METHODS ====================
    
    @api.depends('assignment_ids', 'event_ids.event_type', 'event_ids.template_name', 'event_ids.correlation_id',
                 'event_ids.message_direction', 'event_ids.message_content')
    def _compute_metrics(self):
        for owner in self:
            owner.total_leads_sent = len(owner.assignment_ids)

            teaser = owner.event_ids.filtered(lambda e: e.template_name == 'daily_lead_teaser')
            delivered = {c for c in teaser.filtered(lambda e: e.event_type == 'status_delivered').mapped('correlation_id') if c}
            read = {c for c in teaser.filtered(lambda e: e.event_type == 'status_read').mapped('correlation_id') if c}
            failed = {c for c in teaser.filtered(lambda e: e.event_type == 'status_failed').mapped('correlation_id') if c}

            owner.total_leads_delivered = len(delivered)
            owner.total_leads_read = len(read)
            owner.total_failures = len(failed)

            inbound_clicks = owner.event_ids.filtered(lambda e: e.message_direction == 'inbound' and e.message_content)
            
            clicks = {e.correlation_id for e in inbound_clicks.filtered(lambda e: 'see lead information' in (e.message_content or '').lower()) if e.correlation_id}
            owner.total_leads_clicked = len(clicks)

            not_int = {e.correlation_id for e in inbound_clicks.filtered(lambda e: 'not interested' in (e.message_content or '').lower()) if e.correlation_id}
            owner.total_not_interested = len(not_int)

            details = {c for c in owner.event_ids.filtered(
                lambda e: e.template_name == 'full_lead_details' and e.event_type in ('status_sent', 'status_delivered', 'status_read')
            ).mapped('correlation_id') if c}
            owner.total_details_shared = len(details)

    @api.depends('total_leads_sent', 'total_leads_delivered', 'total_leads_read', 'total_leads_clicked')
    def _compute_rates(self):
        for owner in self:
            owner.delivery_rate = (owner.total_leads_delivered / owner.total_leads_sent * 100) if owner.total_leads_sent else 0.0
            owner.read_rate = (owner.total_leads_read / owner.total_leads_delivered * 100) if owner.total_leads_delivered else 0.0
            owner.click_rate = (owner.total_leads_clicked / owner.total_leads_read * 100) if owner.total_leads_read else 0.0

    @api.depends('event_ids.event_timestamp', 'event_ids.event_type', 'event_ids.message_direction', 'event_ids.message_content')
    def _compute_last_activity(self):
        for owner in self:
            all_events = owner.event_ids
            if not all_events:
                owner.last_message_sent = False
                owner.last_message_read = False
                owner.last_button_clicked = False
                owner.last_activity_date = False
                continue

            owner.last_message_sent = max(all_events.filtered(lambda e: e.message_direction == 'outbound').mapped('event_timestamp'), default=False)
            owner.last_message_read = max(all_events.filtered(lambda e: e.event_type == 'status_read').mapped('event_timestamp'), default=False)
            
            owner.last_button_clicked = max(all_events.filtered(
                lambda e: e.message_direction == 'inbound' and e.message_content 
            ).mapped('event_timestamp'), default=False)
            
            owner.last_activity_date = max(all_events.mapped('event_timestamp'), default=False)

    @api.depends('event_ids.event_timestamp', 'event_ids.template_name', 'event_ids.event_type')
    def _compute_renewal_status(self):
        renewal_template_name = "rm_renewal_offer"
        for owner in self:
            pitch_events = owner.event_ids.filtered(
                lambda e: e.template_name == renewal_template_name and e.event_type in ('status_sent', 'status_delivered', 'status_read')
            )
            owner.renewal_request_sent = bool(pitch_events)
            owner.renewal_request_date = max(pitch_events.mapped('event_timestamp'), default=False)

    @api.depends(
        'renewal_response',
        'total_not_interested',
        'total_leads_clicked',
        'total_leads_read',
        'total_leads_delivered',
        'total_failures'
    )
    def _compute_overall_status(self):
        for owner in self:
            if owner.renewal_response == "renewed":
                owner.overall_status = 'renewed'
            elif owner.renewal_response == "not_interested" or owner.total_not_interested > 0:
                owner.overall_status = 'not_interested'
            elif owner.renewal_response == "interested" or owner.total_leads_clicked > 0:
                owner.overall_status = 'active'
            elif owner.total_leads_read > 0:
                owner.overall_status = 'engaged'
            elif owner.total_leads_delivered > 0:
                owner.overall_status = 'passive'
            elif owner.total_failures > 0:
                owner.overall_status = 'failed'
            else:
                owner.overall_status = 'passive'

    # ==================== ADMIN ACTIONS ====================
    def action_purge_all_renewal_data(self):
        """Delete ALL renewal data — use before full backfill"""
        if not self.env.is_admin():
            raise UserError(_("Only administrators can delete all renewal data!"))
        
        _logger.warning("PURGING all renewal data by user: %s", self.env.user.name)
        self.env['renewal.interakt.event'].sudo().search([]).unlink()
        self.env['renewal.lead.assignment'].sudo().search([]).unlink()
        self.env['renewal.template.stats'].sudo().search([]).unlink()
        self.sudo().search([]).unlink()
        
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': 'All Data Purged', 'message': 'All renewal dashboard data has been deleted.', 'type': 'danger', 'sticky': True}}

    def action_full_backfill_renewal_data(self):
        """ONE-TIME: Pull ALL historical data from BigQuery (Unlimited time window)"""
        if not self.env.is_admin():
            raise UserError(_("Only administrators can run full backfill!"))
        
        _logger.warning("=== FULL RENEWAL BACKFILL STARTED BY %s ===", self.env.user.name)
        
        # 1. Fetch ALL assignments ever
        self._fetch_assignments_base(full=True)
        
        # 2. Fetch ALL events for found owners
        owners = self.sudo().search([])
        self._fetch_events_base(owners, full=True)
        
        # 3. Fetch ALL template stats
        self._cron_fetch_template_stats(full=True)
        
        _logger.warning("=== FULL BACKFILL COMPLETED – %d owners loaded ===", len(owners))
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': 'Backfill Complete', 'message': f'Full backfill complete! Loaded {len(owners)} owners.', 'type': 'success', 'sticky': True}}

    # ==================== DAILY CRON (incremental) ====================
    @api.model
    def _cron_fetch_renewal_data(self):
        """Scheduled action for daily incremental sync."""
        _logger.info("Daily incremental renewal sync started...")
        self._fetch_assignments_base(full=False, days=30)
        owners = self.sudo().search([]) 
        self._fetch_events_base(owners, full=False, days=30)
        self._cron_fetch_template_stats(full=False, days=30)
        _logger.info("Daily renewal sync completed.")

    # ==================== ASSIGNMENTS (FIXED) ====================
    @api.model
    def _fetch_assignments_base(self, full=False, days=30):
        """Fetches new lead assignments and creates/updates owners and assignments"""
        client = bigquery.Client(project=BIGQUERY_PROJECT_ID)
        
        where = "" if full else f"WHERE TIMESTAMP(assignment_timestamp) >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)"
        
        # FIXED QUERY: Properly handle tags, filter "Not Filled", extract last 10 digits
        query = f"""
            WITH ValidAssignments AS (
              SELECT 
                assignment_id, 
                lead_phone, 
                lead_name, 
                routed_to_expired_property_tag,
                -- Remove trailing index (_123) to get canonical tag
                REGEXP_REPLACE(routed_to_expired_property_tag, r'_\\d+$', '') AS canonical_tag,
                assignment_timestamp
              FROM `{ASSIGNMENT_TABLE_ID}`
              {where}
            ),
            FilteredAssignments AS (
              SELECT *
              FROM ValidAssignments
              WHERE routed_to_expired_property_tag IS NOT NULL
                AND routed_to_expired_property_tag != ''
                -- CRITICAL: Exclude "Not Filled" tags (case insensitive)
                AND LOWER(canonical_tag) NOT LIKE '%not filled%'
                AND LOWER(canonical_tag) NOT LIKE '%notfilled%'
            ),
            UniqueCustomerData AS (
              SELECT 
                Tag, 
                Phone, 
                Name,
                Service_Expiry_Date,
                ROW_NUMBER() OVER(PARTITION BY Tag ORDER BY Service_Expiry_Date DESC) AS rn
              FROM `{CUSTOMER_DATA_TABLE_ID}`
            )
            SELECT 
              fa.assignment_id,
              fa.lead_phone,
              fa.lead_name,
              fa.routed_to_expired_property_tag,
              fa.canonical_tag,
              fa.assignment_timestamp,
              -- Extract last 10 digits from phone (remove +91 prefix and any non-digits)
              RIGHT(REGEXP_REPLACE(cd.Phone, r'[^0-9]', ''), 10) AS owner_phone,
              -- Clean owner name (remove titles like Mr., Mrs., Dr.)
              TRIM(COALESCE(
                REGEXP_EXTRACT(cd.Name, r'(?:Mr\\.|Mrs\\.|Dr\\.)\\s*(.+)$'),
                cd.Name,
                'Unknown Owner'
              )) AS owner_name
            FROM FilteredAssignments fa
            LEFT JOIN UniqueCustomerData cd 
              ON fa.canonical_tag = cd.Tag 
              AND cd.rn = 1
        """
        
        _logger.info("Fetching assignments (%s mode)...", "full" if full else f"{days} days")
        
        try:
            query_job = client.query(query)
            results = query_job.result()
        except Exception as e:
            _logger.error(f"BigQuery assignment query failed: {e}")
            return

        OwnerModel = self.env['renewal.property.owner'].sudo()
        AssignmentModel = self.env['renewal.lead.assignment'].sudo()
        owners_created = 0
        assigns_created = 0

        for row in results:
            if not row.routed_to_expired_property_tag:
                continue
            
            # Use canonical tag (without index) to find/create owner
            owner = OwnerModel.search([('expired_property_tag', '=', row.canonical_tag)], limit=1)

            if not owner:
                try:
                    owner = OwnerModel.create({
                        'owner_name': row.owner_name or "Unknown Owner",
                        'owner_phone': row.owner_phone or False, 
                        'expired_property_tag': row.canonical_tag  # Store canonical tag
                    })
                    owners_created += 1
                except Exception as e:
                    _logger.error(f"Failed to create RenewalPropertyOwner for tag {row.canonical_tag}: {e}")
                    self.env.cr.rollback()
                    continue
            
            # Check if assignment already exists
            exists = AssignmentModel.search_count([('assignment_id', '=', row.assignment_id)])
            if not exists:
                try:
                    AssignmentModel.create({
                        'assignment_id': row.assignment_id,
                        'lead_phone': row.lead_phone,
                        'lead_name': row.lead_name,
                        'assignment_timestamp': bq_timestamp_to_odoo(row.assignment_timestamp),
                        'owner_id': owner.id
                    })
                    assigns_created += 1
                except Exception as e:
                    _logger.error(f"Failed to create RenewalLeadAssignment {row.assignment_id}: {e}")
                    self.env.cr.rollback()
        
        _logger.info(f"Assignments sync complete. Created {owners_created} owners, {assigns_created} assignments.")

    # ==================== EVENTS (FIXED WITH PROPER JSON PARSING) ====================
    @api.model
    def _fetch_events_base(self, owners, full=False, days=30):
        """Fetches Interakt events and updates renewal_response field based on clicks"""
        if not owners: 
            return
            
        # Build phone map with last 10 digits
        phone_map = {}
        for o in owners:
            if o.owner_phone:
                clean = ''.join(filter(str.isdigit, o.owner_phone))[-10:]
                if len(clean) == 10:
                    phone_map[clean] = o 
                
        if not phone_map: 
            _logger.warning("No valid owner phone numbers found to fetch events.")
            return

        phones = ", ".join(f"'{p}'" for p in phone_map.keys())
        where_date = "" if full else f"AND ingestion_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)"

        # FIXED QUERY: Extract template_name using DOUBLE JSON parsing
        query = f"""
            SELECT 
              event_id, 
              correlation_id, 
              conversation_id, 
              event_timestamp, 
              ingestion_timestamp,
              event_type, 
              message_direction, 
              message_content, 
              failure_reason, 
              raw_payload,
              -- CRITICAL FIX: Double-parse JSON to extract template name
              -- First extract the string, then parse that string to get 'name'
              JSON_EXTRACT_SCALAR(
                JSON_EXTRACT_SCALAR(raw_payload, '$.data.message.raw_template'),
                '$.name'
              ) AS template_name,
              -- Also get message ID for better correlation
              JSON_EXTRACT_SCALAR(raw_payload, '$.data.message.id') AS message_id
            FROM `{EVENT_LOG_TABLE_ID}`
            WHERE RIGHT(conversation_id, 10) IN ({phones})
              {where_date}
        """
        
        EventModel = self.env['renewal.interakt.event'].sudo()
        count = 0
        
        _logger.info("Fetching Interakt events (%s mode)...", "full" if full else f"{days} days")
        
        try:
            client = bigquery.Client(project=BIGQUERY_PROJECT_ID)
            query_job = client.query(query)
            results = query_job.result()
        except Exception as e:
            _logger.error(f"BigQuery event query failed: {e}")
            return
        
        for row in results:
            phone10 = str(row.conversation_id)[-10:]
            owner = phone_map.get(phone10)
            
            if not owner:
                continue
            
            if EventModel.search_count([('event_id', '=', row.event_id), ('owner_id', '=', owner.id)]):
                continue
                
            try:
                event = EventModel.create({
                    'owner_id': owner.id,
                    'event_id': row.event_id,
                    'correlation_id': row.correlation_id or row.message_id,  # Fallback to message_id
                    'conversation_id': row.conversation_id,
                    'event_timestamp': bq_timestamp_to_odoo(row.event_timestamp),
                    'ingestion_timestamp': bq_timestamp_to_odoo(row.ingestion_timestamp),
                    'event_type': row.event_type,
                    'message_direction': row.message_direction,
                    'message_content': row.message_content or False,
                    'failure_reason': row.failure_reason,
                    'raw_payload': row.raw_payload or False,
                    'template_name': row.template_name or 'unknown_template',
                })
                
                # Update renewal response based on inbound messages
                if event.message_direction == 'inbound' and event.message_content:
                    content = event.message_content.lower().strip()
                    if 'renew my service' in content and owner.renewal_response == 'pending':
                        owner.sudo().write({'renewal_response': 'interested'})
                    elif 'not interested' in content and owner.renewal_response in ('pending', 'interested'):
                        owner.sudo().write({'renewal_response': 'not_interested'})
                count += 1
            except Exception as e:
                _logger.error(f"Event create failed for event {row.event_id}: {e}")
                self.env.cr.rollback()
                
        _logger.info("Loaded %d new events (%s mode)", count, "full" if full else "incremental")

# ==================== TEMPLATE STATS ====================
    @api.model
    def _cron_fetch_template_stats(self, full=False, days=30):
        _logger.info("Starting Bigquery data fetch for Template Stats (%s mode)...", "full" if full else "incremental")

        try:
            client = bigquery.Client(project=BIGQUERY_PROJECT_ID)
        except Exception as e:
            _logger.error(f"Failed to create BigQuery client: {e}")
            return
        
        where_date = "" if full else f"AND event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)"
        
        # RESTORED YOUR WORKING EXTRACTION LOGIC + FIXED MATH
        stats_query = f"""
            WITH ParsedEvents AS (
                SELECT
                    DATE(event_timestamp) AS event_date,
                    
                    -- RESTORED: Fallback to message.id if correlation_id is missing
                    COALESCE(
                      correlation_id,
                      JSON_EXTRACT_SCALAR(raw_payload, '$.data.message.id')
                    ) AS correlation_id,
                    
                    event_type,
                    
                    -- RESTORED: Your specific double-parsing for stringified JSON templates
                    JSON_EXTRACT_SCALAR(
                        JSON_EXTRACT_SCALAR(raw_payload, '$.data.message.raw_template'),
                        '$.name'
                    ) AS template_name,
                    
                    JSON_EXTRACT_SCALAR(raw_payload, '$.type') AS payload_type
                FROM
                    `{EVENT_LOG_TABLE_ID}`
                WHERE
                    message_direction = 'outbound'
                    {where_date}
            ),
            SentMessages AS (
                SELECT DISTINCT
                    event_date,
                    template_name,
                    correlation_id
                FROM ParsedEvents
                WHERE template_name IS NOT NULL
                  AND template_name != ''
                  AND correlation_id IS NOT NULL
                  -- RESTORED: Only count initial sends as the denominator
                  AND payload_type = 'message_api_sent'
            )
            SELECT
                s.event_date AS date,
                s.template_name,
                COUNT(DISTINCT s.correlation_id) AS total_sent,
                
                -- FIXED MATH: Count as Delivered if 'status_delivered' OR 'status_read' exists
                -- This fixes the >100% issue by ensuring Reads are included in Delivery count
                COUNT(DISTINCT CASE 
                    WHEN e.event_type IN ('status_delivered', 'status_read') THEN e.correlation_id 
                    ELSE NULL 
                END) AS total_delivered,
                
                COUNT(DISTINCT CASE 
                    WHEN e.event_type = 'status_read' THEN e.correlation_id 
                    ELSE NULL 
                END) AS total_read,
                
                COUNT(DISTINCT CASE 
                    WHEN e.event_type = 'status_failed' THEN e.correlation_id 
                    ELSE NULL 
                END) AS total_failed
            FROM SentMessages s
            LEFT JOIN ParsedEvents e
                ON s.correlation_id = e.correlation_id
            GROUP BY
                s.event_date, s.template_name
            ORDER BY
                date DESC, template_name
        """

        _logger.info("Fetching template stats from BigQuery...")
        try:
            results = client.query(stats_query).result()
        except Exception as e:
            _logger.error(f"BigQuery template stats query failed: {e}")
            return
        
        StatsModel = self.env['renewal.template.stats'].sudo()
        count = 0

        for row in results:
            if not row.template_name: continue
            vals = {
                'date': row.date,
                'template_name': row.template_name,
                'total_sent': row.total_sent,
                'total_delivered': row.total_delivered,
                'total_read': row.total_read,
                'total_failed': row.total_failed,
            }
            try:
                existing = StatsModel.search([('date', '=', row.date), ('template_name', '=', row.template_name)], limit=1)
                if existing: existing.write(vals)
                else: StatsModel.create(vals)
                count += 1
            except Exception as e:
                _logger.error(f"Error creating/updating RenewalTemplateStats: {e}")
                self.env.cr.rollback()
        
        _logger.info(f"Template stats fetch complete. Processed {count} records.")