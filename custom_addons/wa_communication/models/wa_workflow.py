"""WA Workflow registry — Odoo mirror of the WA platform's workflows table.

Synced via inbound ``workflow.registry.synced`` Pub/Sub events published by
the WA platform on every config deploy.  Managers can pause or resume
individual workflows from the WA Dashboard; each toggle publishes a
``workflow.toggled`` event to the workflow-control topic so the WA platform
picks up the change in real time.
"""

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module : wa_communication
# Model  : wa.workflow
# Purpose: Mirrors the WA platform's workflows table. Managers control
#          is_active; the toggle is propagated to the platform via Pub/Sub.
# Owner  : Cleardeals Tech
# ---------------------------------------------------------------------------

_TOPIC_WORKFLOW_CONTROL = 'wa_communication.topic_workflow_control'


class WaWorkflow(models.Model):
    """Odoo mirror of the WA platform's ``workflows`` table.

    Records are created and kept in sync by the ``workflow.registry.synced``
    inbound event.  The ``is_active`` field is the only one that Odoo writes
    to at runtime — all other fields come from the WA platform and are treated
    as read-only here.

    Toggling ``is_active`` publishes a ``workflow.toggled`` event (deferred to
    after transaction commit) so the WA platform's workflow engine starts or
    stops processing events for that workflow.
    """

    _name = 'wa.workflow'
    _description = 'WA Workflow'
    _order = 'name'
    _rec_name = 'name'

    # --- Fields -----------------------------------------------------------

    platform_id = fields.Char(
        'Platform UUID', index=True, readonly=True,
        help="UUID from the WA platform workflows.id column.",
    )
    slug = fields.Char(
        'Slug', required=True, index=True, readonly=True,
        help="Unique machine identifier. Never changes after deployment. "
             "Embedded in callback_data — changing it breaks in-flight enrollments.",
    )
    name = fields.Char('Name', required=True)
    description = fields.Text('Description')
    campaign_id = fields.Char('Campaign ID', readonly=True)
    pubsub_topic = fields.Char('Pub/Sub Topic', readonly=True)
    trigger_type = fields.Selection(
        [
            ('event_driven', 'Event Driven'),
            ('scheduled',    'Scheduled'),
            ('batch',        'Batch'),
        ],
        string='Trigger Type', readonly=True,
    )
    actor_scope = fields.Selection(
        [
            ('buyer_inquiry',   'Buyer Inquiry'),
            ('seller_inquiry',  'Seller Inquiry'),
            ('customer',        'Customer'),
            ('both',            'Both'),
        ],
        string='Actor Scope', readonly=True,
    )
    is_active = fields.Boolean('Active', default=True)
    version = fields.Integer('Version', default=1, readonly=True)
    platform_updated_at = fields.Datetime('Last Updated on Platform', readonly=True)
    updated_by = fields.Char(
        'Updated By', readonly=True,
        help="Email of the Odoo user who last toggled is_active.",
    )

    # --- Constraints ------------------------------------------------------

    _sql_constraints = [
        ('slug_unique', 'UNIQUE(slug)', 'Workflow slug must be unique.'),
    ]

    # --- Business logic ---------------------------------------------------

    def action_toggle_active(self):
        """Toggle ``is_active`` and publish a ``workflow.toggled`` Pub/Sub event.

        Called from the WA Dashboard toggle switch.  Safe to call on a
        recordset of any size; each record is toggled independently.

        The platform-side effect happens asynchronously after the transaction
        commits.  The WA platform's workflow engine checks ``is_active`` at
        the start of each message cycle and skips processing when False.

        :returns: True — allows direct call from client-action buttons.
        """
        for rec in self:
            new_state = not rec.is_active
            rec.write({
                'is_active':  new_state,
                'updated_by': self.env.user.login,
            })
            rec._wa_publish_workflow_toggle(new_state)
        return True

    def _wa_publish_workflow_toggle(self, is_active: bool) -> None:
        """Defer a ``workflow.toggled`` Pub/Sub publish to after TX commit.

        :param is_active: The new ``is_active`` value just written.

        Postconditions:
            - A ``workflow.toggled`` message is queued for delivery after commit.
            - If the topic is not configured, a warning is logged and no event fires.
        """
        self.ensure_one()
        topic = self.env['ir.config_parameter'].sudo().get_param(
            _TOPIC_WORKFLOW_CONTROL, ''
        )
        if not topic:
            _logger.warning(
                "wa_workflow: %r not configured — toggle event skipped for slug=%s",
                _TOPIC_WORKFLOW_CONTROL, self.slug,
            )
            return

        payload = {
            'event_type':    'workflow.toggled',
            'workflow_slug': self.slug,
            'is_active':     is_active,
            'updated_by':    self.env.user.login,
        }

        def _publish():
            try:
                self.env['cleardeals.pubsub'].publish_async(topic, payload)
            except Exception:
                _logger.exception(
                    "wa_workflow: publish_async failed for slug=%s topic=%s",
                    self.slug, topic,
                )

        self.env.cr.postcommit.add(_publish)

    # --- Inbound sync -----------------------------------------------------

    @api.model
    def _process_registry_sync_event(self, event: dict, pubsub_message_id: str) -> None:
        """Upsert all workflows from a ``workflow.registry.synced`` event.

        Expected event shape::

            {
                "event_type": "workflow.registry.synced",
                "workflows": [
                    {
                        "id":            "<uuid>",
                        "slug":          "nurturing_v2",
                        "name":          "Lead Nurturing",
                        "description":   "...",
                        "campaign_id":   "C1",
                        "pubsub_topic":  "lead-events",
                        "trigger_type":  "event_driven",
                        "actor_scope":   "buyer_inquiry",
                        "is_active":     true,
                        "version":       1,
                        "updated_at":    "2026-05-01T00:00:00Z"
                    }
                ]
            }

        ``is_active`` in the inbound payload is applied ONLY on first create.
        Once a manager has toggled a workflow from Odoo, Odoo owns ``is_active``
        and re-syncs never overwrite it.

        :param event:             Decoded Pub/Sub payload.
        :param pubsub_message_id: GCP message ID for the audit log.
        """
        from datetime import datetime, timezone

        workflows_data = event.get('workflows') or []
        if not workflows_data:
            _logger.info("wa_workflow: workflow.registry.synced received with empty payload")
            return

        created = updated = 0
        for wf_data in workflows_data:
            slug = (wf_data.get('slug') or '').strip()
            if not slug:
                _logger.warning(
                    "wa_workflow: skipping workflow entry with no slug in registry.synced"
                )
                continue

            vals = {
                'slug':         slug,
                'name':         wf_data.get('name') or slug,
                'description':  wf_data.get('description') or '',
                'campaign_id':  wf_data.get('campaign_id') or '',
                'pubsub_topic': wf_data.get('pubsub_topic') or '',
                'trigger_type': wf_data.get('trigger_type') or False,
                'actor_scope':  wf_data.get('actor_scope') or 'buyer_inquiry',
                'version':      int(wf_data.get('version') or 1),
                'platform_id':  wf_data.get('id') or '',
            }
            updated_at_str = wf_data.get('updated_at') or ''
            if updated_at_str:
                try:
                    dt = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
                    vals['platform_updated_at'] = dt.astimezone(timezone.utc).replace(tzinfo=None)
                except (ValueError, TypeError):
                    pass

            existing = self.sudo().search([('slug', '=', slug)], limit=1)
            if existing:
                # Never overwrite is_active on re-sync — Odoo manager owns it.
                existing.write(vals)
                updated += 1
            else:
                vals['is_active'] = bool(wf_data.get('is_active', True))
                self.sudo().create(vals)
                created += 1

        _logger.info(
            "wa_workflow: registry.synced processed — created=%d updated=%d",
            created, updated,
        )
