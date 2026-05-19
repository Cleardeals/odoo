"""Lead event publisher — hooks into leads.new to publish Pub/Sub events.

Inherits ``leads.new`` and overrides ``create`` / ``write`` to publish
events to the configured Pub/Sub topics whenever meaningful lead state
changes occur.

All publishes are deferred to after the SQL transaction commits via
``env.cr.postcommit`` so that a rollback never triggers a spurious WA event.

Configurable topics (ir.config_parameter):
  ``wa_communication.topic_actor_events``    — lead created / RM changes
  ``wa_communication.topic_visit_events``    — site visit scheduled / done
  ``wa_communication.topic_property_events`` — property linked to lead
  ``wa_communication.topic_customer_events`` — customer data updates
"""

import json
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# ir.config_parameter keys for each outbound topic
_TOPIC_ACTOR = 'wa_communication.topic_actor_events'
_TOPIC_VISIT = 'wa_communication.topic_visit_events'
_TOPIC_PROPERTY = 'wa_communication.topic_property_events'
_TOPIC_CUSTOMER = 'wa_communication.topic_customer_events'

# current_status values that trigger visit events
_VISIT_STATUS_EVENTS = {
    'site_visit_scheduled': 'site_visit_scheduled',
    'site_visit_done': 'site_visit_done',
    'rescheduled': 'site_visit_rescheduled',
}

# current_status values that trigger actor events (RM workflow updates)
_ACTOR_STATUS_EVENTS = {
    'lead': 'lead_contacted',
    'busy': 'lead_busy',
    'call_back_later': 'lead_call_back_later',
    'requirement_closed': 'lead_closed',
    'no_requirements': 'lead_no_requirements',
}


class WaLeadEventPublisher(models.Model):
    """Pub/Sub event hooks on leads.new.

    Each published event carries a ``event_type`` string and the relevant
    lead fields so downstream consumers (WA bridge, analytics, etc.) have
    enough context without querying Odoo back.
    """

    _inherit = 'leads.new'

    # ------------------------------------------------------------------
    # Create hook — lead_created
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._wa_schedule_publish(
                _TOPIC_ACTOR,
                rec._wa_lead_payload('lead_created'),
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

                if new_status in _VISIT_STATUS_EVENTS:
                    rec._wa_schedule_publish(
                        _TOPIC_VISIT,
                        {
                            **rec._wa_lead_payload(_VISIT_STATUS_EVENTS[new_status]),
                            'site_visit_date': (
                                rec.site_visit_date.isoformat()
                                if rec.site_visit_date
                                else None
                            ),
                        },
                    )

                elif new_status in _ACTOR_STATUS_EVENTS:
                    rec._wa_schedule_publish(
                        _TOPIC_ACTOR,
                        rec._wa_lead_payload(_ACTOR_STATUS_EVENTS[new_status]),
                    )

            # -- property linked / changed --------------------------------
            if (
                'property_base_id' in vals
                and rec.property_base_id.id != snap.get('property_base_id')
                and rec.property_base_id
            ):
                rec._wa_schedule_publish(
                    _TOPIC_PROPERTY,
                    {
                        **rec._wa_lead_payload('lead_property_linked'),
                        'property_base_id': rec.property_base_id.id,
                        'property_tag': rec.property_base_id.property_tag,
                        'property_location': rec.property_base_id.location,
                    },
                )

            # -- RM reassigned --------------------------------------------
            if (
                'user_id' in vals
                and rec.user_id.id != snap.get('user_id')
            ):
                rec._wa_schedule_publish(
                    _TOPIC_ACTOR,
                    {
                        **rec._wa_lead_payload('lead_rm_assigned'),
                        'rm_user_id': rec.user_id.id,
                        'rm_name': rec.user_id.name,
                    },
                )

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
                    rec._wa_lead_payload('customer_updated'),
                )

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _wa_lead_payload(self, event_type: str) -> dict:
        """Build a standard outbound event payload dict for this lead.

        :param event_type: Snake_case event identifier, e.g. ``'lead_created'``.
        :return:           Payload dict ready to be JSON-serialised.
        """
        self.ensure_one()
        return {
            'event_type': event_type,
            'lead_id': self.id,
            'customer_name': self.name,
            'phone': self.phone or '',
            'current_status': self.current_status or '',
            'rm_user_id': self.user_id.id or None,
            'rm_name': self.user_id.name or '',
            'source': self.source_id.name or '',
        }

    def _wa_schedule_publish(self, topic_key: str, payload: dict) -> None:
        """Schedule a Pub/Sub publish to run after the current transaction.

        Uses ``env.cr.postcommit`` so that a transaction rollback never
        triggers a spurious outbound event.

        Silently skips if the topic config parameter is not set.

        :param topic_key: ``ir.config_parameter`` key for the topic name.
        :param payload:   Event payload dict (will be JSON-serialised).
        """
        self.ensure_one()
        topic = self.env['ir.config_parameter'].sudo().get_param(topic_key, '')
        if not topic:
            _logger.debug(
                "wa_lead_event: topic key %r not configured — event %r skipped for lead %s",
                topic_key,
                payload.get('event_type'),
                self.id,
            )
            return

        data = json.dumps(payload).encode()

        def _publish():
            try:
                self.env['cleardeals.pubsub'].publish_async(topic, data)
            except Exception:
                _logger.exception(
                    "wa_lead_event: publish_async failed for event=%r lead=%s topic=%s",
                    payload.get('event_type'),
                    self.id,
                    topic,
                )

        self.env.cr.postcommit.add(_publish)
