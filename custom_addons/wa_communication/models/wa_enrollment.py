"""WA Enrollment — tracks the lifecycle of one workflow enrollment per actor.

Created by ``enrollment_created`` push events and updated to ``completed`` or
``failed`` by ``enrollment_completed`` / ``permanent_failure`` events.

This model is the source of truth for the Active Enrollments metric on the
WA Dashboard.  One row = one distinct run of a workflow for one actor.
"""

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module : wa_communication
# Model  : wa.enrollment
# Purpose: Tracks enrollment lifecycle (active / completed / failed).
#          Populated by push event handlers in wa.conversation.
#          Enables the Active Enrollments KPI on the WA Dashboard.
# Owner  : Cleardeals Tech
# ---------------------------------------------------------------------------


class WaEnrollment(models.Model):
    """One row per workflow enrollment for one actor.

    Created by :meth:`wa.conversation._handle_odoo_enrollment_created`.
    Completed by :meth:`wa.conversation._handle_odoo_enrollment_completed`.
    Marked failed by the permanent_failure / retry_exhausted handler when
    a ``workflow_slug`` and ``enrollment_id`` are present.

    The ``enrollment_id`` field stores the UUID from the WA platform's
    ``workflow_enrollments`` table and is the dedup key.  Duplicate
    ``enrollment_created`` events for the same UUID are silently skipped.
    """

    _name = 'wa.enrollment'
    _description = 'WA Enrollment'
    _order = 'started_at desc, id desc'
    _rec_name = 'enrollment_id'

    # --- Fields -----------------------------------------------------------

    enrollment_id = fields.Char(
        'Enrollment ID', required=True, index=True, readonly=True,
        help="UUID from the WA platform's workflow_enrollments table. "
             "Used as the dedup key — duplicate events are skipped.",
    )
    workflow_slug = fields.Char(
        'Workflow Slug', index=True, readonly=True,
        help="Slug of the workflow this enrollment belongs to.",
    )
    workflow_id = fields.Many2one(
        'wa.workflow', string='Workflow',
        compute='_compute_workflow_id', store=True, readonly=True,
    )
    lead_id = fields.Many2one(
        'leads.new', string='Lead',
        index=True, ondelete='set null', readonly=True,
    )
    phone = fields.Char('Phone', readonly=True)
    platform_actor_id = fields.Integer(
        'Platform Actor ID', readonly=True,
        help="WA platform's internal actor record ID (workflow_enrollments.inquiry_id).",
    )
    state = fields.Selection(
        [
            ('active',    'Active'),
            ('completed', 'Completed'),
            ('failed',    'Failed'),
        ],
        required=True, default='active', index=True,
    )
    started_at = fields.Datetime('Started At', required=True, readonly=True)
    completed_at = fields.Datetime('Completed At')

    # --- Constraints ------------------------------------------------------

    # Odoo 19: declare DB constraints via models.Constraint (not _sql_constraints).
    _enrollment_id_unique = models.Constraint(
        'UNIQUE(enrollment_id)',
        'Enrollment ID must be unique.',
    )

    # --- Computed fields --------------------------------------------------

    @api.depends('workflow_slug')
    def _compute_workflow_id(self):
        """Link to wa.workflow via slug for joins and display."""
        WaWorkflow = self.env['wa.workflow']
        for rec in self:
            if rec.workflow_slug:
                wf = WaWorkflow.search([('slug', '=', rec.workflow_slug)], limit=1)
                rec.workflow_id = wf.id if wf else False
            else:
                rec.workflow_id = False

    # --- Factory helpers --------------------------------------------------

    @api.model
    def _get_or_create(
        self,
        enrollment_id: str,
        workflow_slug: str,
        lead,
        phone: str,
        platform_actor_id: int,
        started_at,
    ):
        """Return an existing enrollment or create a new one.

        Silently returns the existing record when ``enrollment_id`` already
        exists (dedup for fan-out duplicates from multiple engine replicas).

        :param enrollment_id:    UUID from the WA platform.
        :param workflow_slug:    Slug of the originating workflow.
        :param lead:             ``leads.new`` recordset (may be empty).
        :param phone:            WA phone number (E.164 without +).
        :param platform_actor_id: WA platform actor ID integer.
        :param started_at:       Naive UTC datetime of enrollment start.
        :returns: ``wa.enrollment`` record.
        """
        existing = self.sudo().search([('enrollment_id', '=', enrollment_id)], limit=1)
        if existing:
            return existing
        return self.sudo().create({
            'enrollment_id':    enrollment_id,
            'workflow_slug':    workflow_slug or False,
            'lead_id':          lead.id if lead else False,
            'phone':            phone or '',
            'platform_actor_id': platform_actor_id or 0,
            'started_at':       started_at,
            'state':            'active',
        })
