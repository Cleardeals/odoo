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
  ``wa_communication.topic_nudge_events``    — initial-nudge trigger (on create)

Publish timing
--------------
Most events describe a change that has already happened, so their envelope is
built when the hook fires and only the network call is deferred
(``_wa_schedule_publish``). ``nudge.initial`` is different: it is triggered by
lead *creation*, but a lead is not settled until later in the same transaction
(``_process_lead_logic`` resolves the property), so its envelope is built at
publish time instead (``_wa_schedule_publish_lazy``).
"""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# ir.config_parameter keys for each outbound topic
_TOPIC_ACTOR = 'wa_communication.topic_actor_events'
_TOPIC_VISIT = 'wa_communication.topic_visit_events'
_TOPIC_PROPERTY = 'wa_communication.topic_property_events'
_TOPIC_CUSTOMER = 'wa_communication.topic_customer_events'
# nudge.initial — the single settled-state trigger for the initial-nudge
# WhatsApp workflows (property vs no-property variants filter on has_property).
_TOPIC_NUDGE = 'wa_communication.topic_nudge_events'

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
            # Initial-nudge trigger. Lead creation is the trigger, so this is
            # the only hook — and it needs no once-only guard, because create()
            # runs exactly once per record. The envelope is resolved at publish
            # time, not here; see _wa_emit_initial_nudge.
            rec._wa_emit_initial_nudge()
            # If a phone-only (orphan) WhatsApp conversation already exists for
            # this lead's number, attach it now so prior inbound history isn't
            # stranded. Defensive: a WA hiccup must never block lead creation.
            try:
                self.env['wa.conversation'].sudo()._owa_relink_orphan_for_lead(rec)
            except Exception:  # noqa: BLE001
                _logger.warning(
                    "wa: orphan-conversation relink failed for lead %s",
                    rec.id, exc_info=True)
            # Bind any pre-inquiry ("New topic") segment for this (phone, property)
            # to the freshly-created inquiry — deterministic, and covers EVERY
            # creation path (Recommend wizard, manual, import), not just the inbox
            # orphan flow. Defensive for the same reason as above.
            try:
                self.env['wa.conversation'].sudo()._owa_bind_new_inquiry(rec)
            except Exception:  # noqa: BLE001
                _logger.warning(
                    "wa: segment binding failed for new inquiry %s",
                    rec.id, exc_info=True)
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

        Flat keys (``assigned_rm_email``, ``assigned_rm_id``, ``property_id``,
        ``portal_source``) are included so the workflow engine can capture them
        as ``meta.*`` fields via the ``meta_fields`` YAML list.

        Nested ``rm`` and ``property`` sub-dicts allow YAML vars to reference
        ``actor.rm.email``, ``actor.property.tag``, etc.
        """
        self.ensure_one()
        # sudo() so the snapshot can be built regardless of the calling user's
        # ACLs on property.base / res.users — this is read-only metadata for
        # Pub/Sub events and never surfaces to the UI.
        prop = self.property_base_id.sudo()
        rm = self.user_id.sudo()
        return {
            # ── Core identity ──────────────────────────────────────────────
            'id':             self.id,
            'name':           self.name or '',
            'phone':          self.phone or '',
            'current_status': self.current_status or '',
            # ── Flat keys for meta_fields capture ─────────────────────────
            'assigned_rm_id':    rm.id or None,
            'assigned_rm_email': rm.email or '',
            'property_id':       prop.id or None,
            'portal_source':     self.source_id.name or '',
            # ── Nested RM dict — actor.rm.* var resolution ─────────────────
            'rm': {
                'id':    rm.id or None,
                'name':  rm.name or '',
                'email': rm.email or '',
            },
            # ── Nested property dict — actor.property.* var resolution ──────
            # Enriched so the initial-nudge templates can render entirely from
            # the event snapshot (the engine never fetches Odoo).
            'property': {
                'id':          prop.id or None,
                'tag':         prop.property_tag or '',
                # Clean project name — `name` excludes the "[...]" tag that
                # display_name appends; strip defensively in case it ever leaks in.
                'name':        (prop.name or '').split('[')[0].strip(),
                'locality':    prop.location or '',
                'link':        prop.property_link or '',
                # Composed "Type": "<BHK> <sub_type>" when a BHK is present
                # (e.g. "3 BHK Apartment"), else just the sub-type (e.g. "Shop").
                'type_label':  (
                    f"{prop.bhk} {prop.prop_sub_type}".strip()
                    if prop.bhk and prop.prop_sub_type
                    else (prop.prop_sub_type or prop.bhk or '')
                ),
                'size':        prop.property_size or '',
                'furnishing':  prop.furnishing_type or '',
                'image_url':   prop.primary_image_url or '',
                'tour_360_url': prop.tour_360_url or '',
            },
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

    def _wa_emit_initial_nudge(self) -> None:
        """Schedule the ``nudge.initial`` trigger for the initial-nudge workflows.

        Lead creation is the trigger, so this is called from ``create`` only —
        which is also why it needs no once-only bookkeeping: ``create`` runs
        exactly once per record.

        The envelope is built at *publish* time rather than now, because a lead
        is not settled at creation. A portal lead is created ``state='new'``
        with no property, and ``_process_lead_logic`` resolves and writes
        ``property_base_id`` later in the *same* transaction. Deciding
        ``has_property`` here would therefore route every portal lead to the
        no-property variant. Post-commit, the lead has settled.
        """
        self.ensure_one()
        self._wa_schedule_publish_lazy(
            _TOPIC_NUDGE, self._wa_build_initial_nudge_event,
        )

    def _wa_build_initial_nudge_event(self) -> dict | None:
        """Build the ``nudge.initial`` envelope from the lead's settled state.

        Adds ``payload.has_property`` = ``'yes'``/``'no'`` so the two workflow
        variants route on a simple ``==`` condition; the enriched
        ``payload.actor.property`` snapshot carries everything the templates need.

        Returns ``None`` — skipping the publish — when the lead turned out not
        to be nudgeable. Eligibility is judged here, at publish time, for the
        same reason the payload is: it is only true of the settled lead.
        """
        self.ensure_one()
        # Only leads the system ingested.  The initial-nudge copy opens by
        # referring to an enquiry the buyer just submitted on a portal, so on a
        # lead an RM created by hand (or recommended, or imported, or triaged
        # out of the inbox) it is simply untrue.  It would also hand that lead a
        # WhatsApp attempt the RM never made, defeating the status gate.
        if not self.is_auto_created:
            return None
        if self.current_status != 'lead':
            return None
        if not self.phone:
            return None

        event = self._wa_build_event('nudge.initial')
        event['payload']['has_property'] = 'yes' if self.property_base_id else 'no'
        return event

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

    def _wa_schedule_publish_lazy(self, topic_key: str, build_event) -> None:
        """Schedule a publish whose envelope is built *after* the transaction.

        Same deferral as :meth:`_wa_schedule_publish`, except ``build_event`` is
        invoked at publish time. Use this when the event must describe the
        record's settled state rather than its state at the moment the hook
        fired — e.g. a lead whose property is resolved by a later write in the
        same transaction.

        ``build_event`` returning a falsy value skips the publish, so it doubles
        as the eligibility check.

        :param topic_key:   ``ir.config_parameter`` key for the topic name.
        :param build_event: Zero-arg callable returning an event envelope dict,
                            or ``None`` to publish nothing.
        """
        self.ensure_one()
        topic = self.env['ir.config_parameter'].sudo().get_param(topic_key, '')
        if not topic:
            _logger.debug(
                "wa_lead_event: topic key %r not configured — deferred event "
                "skipped for lead %s",
                topic_key,
                self.id,
            )
            return

        def _publish():
            try:
                event = build_event()
                if not event:
                    return
                self.env['cleardeals.pubsub'].publish_async(topic, event)
            except Exception:
                _logger.exception(
                    "wa_lead_event: deferred publish failed for lead=%s topic=%s",
                    self.id,
                    topic,
                )

        self.env.cr.postcommit.add(_publish)
