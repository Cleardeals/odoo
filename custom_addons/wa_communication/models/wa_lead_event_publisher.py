"""Lead event publisher — hooks into leads.new to publish Pub/Sub events.

Inherits ``leads.new`` and overrides ``create`` / ``write`` to publish
events to the configured Pub/Sub topics whenever meaningful lead state
changes occur.

All publishes are deferred to after the SQL transaction commits via
``env.cr.postcommit`` so that a rollback never triggers a spurious WA event.

Event envelope structure (matches WorkflowEngine expectations)
--------------------------------------------------------------
Top-level routing keys (read directly by the engine):
    event_type        — canonical event name e.g. ``actor.created``
    actor_type        — ``buyer_inquiry`` for leads.new
    actor_id          — Odoo lead record id
    phone             — WA phone number (E.164 without +)
    actor_property_id — property id, only for property_promotion.lead_queued

Nested payload (used by the engine for conditions and var resolution):
    payload.<field>   — accessible as ``event.<field>`` in YAML var sources
    payload.actor     — actor snapshot, accessible as ``actor.<field>``

Configurable topics (ir.config_parameter):
  ``wa_communication.topic_actor_events``    — lead created / RM / status changes
  ``wa_communication.topic_visit_events``    — site visit scheduled / done
  ``wa_communication.topic_property_events`` — property linked to lead
  ``wa_communication.topic_customer_events`` — customer data updates
"""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# ir.config_parameter keys for each outbound topic
_TOPIC_ACTOR = 'wa_communication.topic_actor_events'
_TOPIC_VISIT = 'wa_communication.topic_visit_events'
_TOPIC_PROPERTY = 'wa_communication.topic_property_events'
_TOPIC_CUSTOMER = 'wa_communication.topic_customer_events'

# current_status values → visit event_type (canonical platform names)
_VISIT_STATUS_MAP = {
    'site_visit_scheduled': 'visit.scheduled',
    'site_visit_done':      'visit.done',
    'rescheduled':          'visit.rescheduled',
}

# current_status values that trigger actor.status_changed
_ACTOR_STATUS_SET = {
    'lead', 'busy', 'call_back_later', 'requirement_closed', 'no_requirements',
}


class WaLeadEventPublisher(models.Model):
    """Pub/Sub event hooks on leads.new.

    Each published event is a two-level envelope:
    ``{event_type, actor_type, actor_id, phone, [actor_property_id], payload: {...}}``.
    Downstream consumers (workflow engine, analytics, WA bridge) read
    routing keys from the top level and domain data from ``payload``.
    """

    _inherit = 'leads.new'

    # ------------------------------------------------------------------
    # Create hook — actor.created
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._wa_schedule_publish(
                _TOPIC_ACTOR,
                rec._wa_build_event('actor.created'),
            )
        return records

    # ------------------------------------------------------------------
    # Write hook — status changes, property linking, customer updates
    # ------------------------------------------------------------------

    def write(self, vals):
        # Snapshot pre-write state for fields we need to diff
        if any(k in vals for k in ('current_status', 'property_base_id', 'user_id', 'phone', 'name')):
            pre = {
                rec.id: {
                    'current_status': rec.current_status,
                    'property_base_id': rec.property_base_id.id,
                    'user_id': rec.user_id.id,
                    'phone': rec.phone,
                    'name': rec.name,
                }
                for rec in self
            }
        else:
            pre = {}

        result = super().write(vals)

        for rec in self:
            snap = pre.get(rec.id, {})

            # -- current_status changes -----------------------------------
            new_status = vals.get('current_status')
            if new_status and new_status != snap.get('current_status'):

                if new_status in _VISIT_STATUS_MAP:
                    event = rec._wa_build_event(_VISIT_STATUS_MAP[new_status])
                    event['payload']['site_visit_date'] = (
                        rec.site_visit_date.isoformat()
                        if rec.site_visit_date
                        else None
                    )
                    rec._wa_schedule_publish(_TOPIC_VISIT, event)

                elif new_status in _ACTOR_STATUS_SET:
                    event = rec._wa_build_event('actor.status_changed')
                    event['payload']['new_status'] = new_status
                    rec._wa_schedule_publish(_TOPIC_ACTOR, event)

            # -- property linked / changed --------------------------------
            if (
                'property_base_id' in vals
                and rec.property_base_id.id != snap.get('property_base_id')
                and rec.property_base_id
            ):
                event = rec._wa_build_event('property_promotion.lead_queued')
                # actor_property_id is a top-level enrollment key in the engine
                event['actor_property_id'] = rec.property_base_id.id
                event['payload'].update({
                    'property_base_id': rec.property_base_id.id,
                    'property_tag': rec.property_base_id.property_tag,
                    'property_location': rec.property_base_id.location,
                })
                rec._wa_schedule_publish(_TOPIC_PROPERTY, event)

            # -- RM reassigned --------------------------------------------
            if (
                'user_id' in vals
                and rec.user_id.id != snap.get('user_id')
            ):
                event = rec._wa_build_event('actor.status_changed')
                event['payload'].update({
                    'new_status': rec.current_status or '',
                    'rm_user_id': rec.user_id.id,
                    'rm_name': rec.user_id.name or '',
                })
                rec._wa_schedule_publish(_TOPIC_ACTOR, event)

            # -- customer phone / name changed ----------------------------
            if (
                any(k in vals for k in ('phone', 'name'))
                and (
                    vals.get('phone', snap.get('phone')) != snap.get('phone')
                    or vals.get('name', snap.get('name')) != snap.get('name')
                )
            ):
                rec._wa_schedule_publish(
                    _TOPIC_CUSTOMER,
                    rec._wa_build_event('customer.updated'),
                )

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _wa_actor_snapshot(self) -> dict:
        """Current lead fields as a plain dict.

        Used both as ``payload.actor`` (for ``actor.*`` var sources) and
        spread into the top of ``payload`` (for ``event.*`` var sources).
        """
        self.ensure_one()
        return {
            'lead_id':        self.id,
            'customer_name':  self.name,
            'phone':          self.phone or '',
            'current_status': self.current_status or '',
            'rm_user_id':     self.user_id.id or None,
            'rm_name':        self.user_id.name or '',
            'source':         self.source_id.name or '',
        }

    def _wa_build_event(self, event_type: str) -> dict:
        """Build a workflow-engine-compatible event envelope for this lead.

        Returns a mutable dict so callers can add extra ``payload`` fields::

            event = rec._wa_build_event('actor.status_changed')
            event['payload']['new_status'] = 'busy'
            rec._wa_schedule_publish(_TOPIC_ACTOR, event)

        :param event_type: Canonical platform event name, e.g. ``'actor.created'``.
        :return:           Mutable event envelope dict.
        """
        self.ensure_one()
        snapshot = self._wa_actor_snapshot()
        return {
            'event_type': event_type,
            'actor_type': 'buyer_inquiry',
            'actor_id':   self.id,
            'phone':      self.phone or '',
            'payload': {
                **snapshot,
                'actor': snapshot,
            },
        }

    def _wa_schedule_publish(self, topic_key: str, event: dict) -> None:
        """Schedule a Pub/Sub publish to run after the current transaction.

        Uses ``env.cr.postcommit`` so that a transaction rollback never
        triggers a spurious outbound event.

        Silently skips if the topic config parameter is not set.

        :param topic_key: ``ir.config_parameter`` key for the topic name.
        :param event:     Event envelope dict (will be JSON-serialised).
        """
        self.ensure_one()
        topic = self.env['ir.config_parameter'].sudo().get_param(topic_key, '')
        if not topic:
            _logger.debug(
                "wa_lead_event: topic key %r not configured — event %r skipped for lead %s",
                topic_key,
                event.get('event_type'),
                self.id,
            )
            return

        def _publish():
            try:
                self.env['cleardeals.pubsub'].publish_async(topic, event)
            except Exception:
                _logger.exception(
                    "wa_lead_event: publish_async failed for event=%r lead=%s topic=%s",
                    event.get('event_type'),
                    self.id,
                    topic,
                )

        self.env.cr.postcommit.add(_publish)
