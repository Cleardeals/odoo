from odoo import models, fields, api, _
from odoo.exceptions import UserError
from google.cloud import bigquery
import logging

_logger = logging.getLogger(__name__)

# CONFIG
BIGQUERY_PROJECT_ID = "cleardeals-459513"
# Use the new eligibility log table
ELIGIBILITY_LOG_TABLE_ID = "cleardeals-459513.active_to_active.daily_eligibility_log"
ASSIGNMENT_TABLE_ID = "cleardeals-459513.active_to_active.odoo_lead_assignments"

class PropertyDailyStat(models.Model):
    _name = 'property.daily.stat'
    _description = 'Property Daily Statistics'
    _order = 'date desc, property_tag'
    _rec_name = 'property_tag'

    property_tag = fields.Char(string="Property Tag", readonly=True, index=True)
    date = fields.Date(string="Date", readonly=True, index=True)
    assignment_count = fields.Integer(string="Assignments This Day", readonly=True)
    
    # This boolean is computed from the count, so it's fast.
    assignment_status = fields.Selection(
        [('unassigned', 'Unassigned (0 Leads)'), 
         ('assigned', 'Assigned (1+ Leads)')], 
        string="Assignment Status", 
        compute='_compute_assignment_status', 
        store=True,
        index=True
    )

    # --- Compute method for the Selection field ---
    @api.depends('assignment_count')
    def _compute_assignment_status(self):
        """Set the status based on assignment count."""
        for rec in self:
            if rec.assignment_count == 0:
                rec.assignment_status = 'unassigned'
            else:
                rec.assignment_status = 'assigned'

    _sql_constraints = [
        ('property_date_uniq', 'unique(property_tag, date)', 'Property Tag + Date must be unique.')
    ]

    @api.model
    def _cron_sync_daily_stats(self):
        """
        Syncs property stats from BigQuery.
        Joins the daily eligibility log with daily assignment counts.
        """
        _logger.info("Starting Property Daily Stat sync from BigQuery...")
        
        try:
            client = bigquery.Client(project=BIGQUERY_PROJECT_ID)
        except Exception as e:
            _logger.error(f"Failed to create BigQuery client: {e}")
            raise UserError(_(f"Failed to authenticate with BigQuery. Check server logs. Error: {e}"))

        # This is the new, powerful query.
        # It joins the daily log with a daily count of assignments.
        query = f"""
            WITH DailyAssignments AS (
                -- First, count assignments per property, per day
                SELECT
                    assigned_property_tag,
                    assignment_date,
                    COUNT(*) AS daily_assignment_count
                FROM
                    `{ASSIGNMENT_TABLE_ID}`
                -- We only need to process recent history
                WHERE assignment_date >= DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL 90 DAY)
                GROUP BY 1, 2
            )
            -- Now, join the full eligibility log with the counts
            SELECT
                log.property_tag,
                log.eligible_date,
                COALESCE(da.daily_assignment_count, 0) AS assignment_count
            FROM
                `{ELIGIBILITY_LOG_TABLE_ID}` AS log
            LEFT JOIN DailyAssignments AS da
                ON log.property_tag = da.assigned_property_tag
                AND log.eligible_date = da.assignment_date
            -- Fetch all data from the last 90 days to populate the dashboard
            WHERE log.eligible_date >= DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL 90 DAY)
        """
        
        try:
            query_job = client.query(query)
            results = query_job.result()
            
            synced_count = 0
            for row in results:
                vals = {
                    'property_tag': row.property_tag,
                    'date': row.eligible_date,
                    'assignment_count': row.assignment_count,
                }
                
                existing = self.search([
                    ('property_tag', '=', row.property_tag),
                    ('date', '=', row.eligible_date)
                ])
                if existing:
                    existing.write(vals) # Update count if it changed
                else:
                    self.create(vals)
                synced_count += 1
            
            _logger.info(f"Successfully synced {synced_count} daily property statistics.")

        except Exception as e:
            _logger.error(f"Error during Property Daily Stat sync: {e}")
            self.env.cr.rollback()