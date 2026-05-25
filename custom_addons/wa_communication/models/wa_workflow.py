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
    last_synced_at = fields.Datetime(
        'Last Toggle Synced At', readonly=True,
        help="Timestamp of the most recent workflow.synced ACK received from "
             "the WA platform confirming that a toggle was applied.",
    )
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
            _logger.info(
                "wa_workflow: toggle requested slug=%r %s → %s by user=%s",
                rec.slug, rec.is_active, new_state, self.env.user.login,
            )
            rec.write({
                'is_active':  new_state,
                'updated_by': self.env.user.login,
            })
            rec._wa_publish_workflow_toggle(new_state)
        return True

    def _wa_publish_workflow_toggle(self, is_active: bool) -> None:
        """Defer a ``workflow.toggled`` Pub/Sub publish to after TX commit.

        The config param ``wa_communication.topic_workflow_control`` stores the
        **topic alias** (e.g. ``workflow-control``) without any environment
        prefix.  The full topic name is built here using ``GCP_ENV``, mirroring
        the WA platform's ``shared.pubsub.publish()`` naming convention::

            local       → cd-local-workflow-control
            staging     → cd-staging-workflow-control
            production  → cd-prod-workflow-control

        :param is_active: The new ``is_active`` value just written.
        """
        import os

        _ENV_PREFIX = {'local': 'local', 'staging': 'staging', 'production': 'prod'}

        self.ensure_one()
        alias = self.env['ir.config_parameter'].sudo().get_param(
            _TOPIC_WORKFLOW_CONTROL, ''
        )
        if not alias:
            _logger.warning(
                "wa_workflow: %r not configured — toggle event skipped for slug=%s",
                _TOPIC_WORKFLOW_CONTROL, self.slug,
            )
            return

        gcp_env   = os.environ.get('GCP_ENV', 'local')
        env_pfx   = _ENV_PREFIX.get(gcp_env, gcp_env)   # unknown env → use as-is
        topic     = f'cd-{env_pfx}-{alias}'

        payload = {
            'event_type':    'workflow.toggled',
            'workflow_slug': self.slug,
            'is_active':     is_active,
            'updated_by':    self.env.user.login,
        }

        _logger.info(
            "wa_workflow: toggle event queued for postcommit slug=%r is_active=%s topic=%r gcp_env=%s",
            self.slug, is_active, topic, gcp_env,
        )

        def _publish():
            _logger.info(
                "wa_workflow: [postcommit] firing workflow.toggled publish slug=%r is_active=%s topic=%r",
                self.slug, is_active, topic,
            )
            try:
                self.env['cleardeals.pubsub'].publish_async(topic, payload)
                _logger.info(
                    "wa_workflow: [postcommit] workflow.toggled handed to publisher slug=%r topic=%r",
                    self.slug, topic,
                )
            except Exception:
                _logger.exception(
                    "wa_workflow: [postcommit] publish_async raised for slug=%r topic=%r",
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

    @api.model
    def _process_workflow_synced_event(self, event: dict, pubsub_message_id: str) -> None:
        """Handle ``workflow.synced`` — from odoo-bridge after a toggle OR initial sync.

        Two callers produce this event type with different payload shapes:

        **Toggle confirmation** (from ``handle_workflow_toggled`` in odoo-bridge)::

            {
                "event_type":    "workflow.synced",
                "workflow_slug": "nurturing_v2",
                "is_active":     false,
                "updated_by":    "admin@cleardeals.in"
            }

        **Initial / bulk sync** (from ``sync_initial.py`` in odoo-bridge)::

            {
                "event_type":    "workflow.synced",
                "workflow_slug": "nurturing_v2",
                "name":          "Lead Nurturing",
                "description":   "...",
                "campaign_id":   "C1",
                "pubsub_topic":  "lead-events",
                "trigger_type":  "event_driven",
                "actor_scope":   "buyer_inquiry",
                "is_active":     true,
                "version":       1,
                "updated_by":    "system:initial_sync"
            }

        When ``name`` is present the handler performs a full upsert (identical
        behaviour to ``workflow.registry.synced``) so that ``sync_initial.py``
        can seed Odoo's ``wa.workflow`` table.

        When ``name`` is absent (toggle confirmation) the handler only records
        ``last_synced_at``.  Odoo never overwrites its own ``is_active`` from
        either payload — Odoo remains the source of truth for the toggle state.
        If the platform-reported ``is_active`` diverges a warning is logged.

        :param event:             Decoded Pub/Sub payload.
        :param pubsub_message_id: GCP message ID for the audit log.
        """
        from datetime import datetime, timezone

        slug = (event.get('workflow_slug') or '').strip()
        if not slug:
            _logger.warning(
                "wa_workflow: workflow.synced received without workflow_slug — msg=%s",
                pubsub_message_id,
            )
            return

        is_active     = event.get('is_active')
        has_full_data = bool(event.get('name'))

        if has_full_data:
            # ── Full upsert (initial sync or re-sync from odoo-bridge) ──────
            vals = {
                'slug':         slug,
                'name':         event.get('name') or slug,
                'description':  event.get('description') or '',
                'campaign_id':  event.get('campaign_id') or '',
                'pubsub_topic': event.get('pubsub_topic') or '',
                'trigger_type': event.get('trigger_type') or False,
                'actor_scope':  event.get('actor_scope') or 'buyer_inquiry',
                'version':      int(event.get('version') or 1),
                'last_synced_at': fields.Datetime.now(),
            }
            existing = self.sudo().search([('slug', '=', slug)], limit=1)
            if existing:
                # Never overwrite is_active — Odoo manager owns it
                existing.write(vals)
                _logger.info(
                    "wa_workflow: workflow.synced updated slug=%r msg=%s",
                    slug, pubsub_message_id,
                )
            else:
                vals['is_active'] = bool(is_active) if is_active is not None else True
                self.sudo().create(vals)
                _logger.info(
                    "wa_workflow: workflow.synced created slug=%r is_active=%s msg=%s",
                    slug, vals['is_active'], pubsub_message_id,
                )
            return

        # ── Toggle confirmation (minimal payload) ────────────────────────────
        rec = self.sudo().search([('slug', '=', slug)], limit=1)
        if not rec:
            _logger.warning(
                "wa_workflow: workflow.synced (toggle ack) for unknown slug=%r — msg=%s",
                slug, pubsub_message_id,
            )
            return

        rec.write({'last_synced_at': fields.Datetime.now()})

        if is_active is not None and bool(is_active) != rec.is_active:
            _logger.warning(
                "wa_workflow: is_active divergence after toggle sync — "
                "slug=%r odoo=%s platform=%s msg=%s",
                slug, rec.is_active, is_active, pubsub_message_id,
            )
        else:
            _logger.info(
                "wa_workflow: workflow.synced toggle confirmed — slug=%r is_active=%s msg=%s",
                slug, rec.is_active, pubsub_message_id,
            )
