"""Inquiry segments — correctable per-inquiry attribution for a phone thread.

Part of the ``wa.conversation`` model — see wa_conversation.py for the base
definition (fields, constraints, inbound push dispatcher).
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

class WaConversation(models.Model):
    _inherit = 'wa.conversation'

    @api.model
    def _owa_segments_enabled(self) -> bool:
        """Master feature flag.  When off, no segment is created or attached and
        the conversation behaves exactly as before this feature existed."""
        return self.env['ir.config_parameter'].sudo().get_param(
            'wa_communication.segments_enabled', '') in ('1', 'true', 'True')

    def _owa_activate_segment(self, segment) -> None:
        """Make *segment* the sole active segment of this conversation."""
        self.ensure_one()
        (self.segment_ids - segment).filtered('is_active').write({'is_active': False})
        if not segment.is_active:
            segment.is_active = True
        if self.active_segment_id != segment:
            self.active_segment_id = segment

    @staticmethod
    def _owa_normalize_label(label):
        """Canonical form for label dedup — trimmed, case-folded, or False."""
        return (label or '').strip().casefold() or False

    def _owa_ensure_segment(self, inquiry=None, property=None, label=None,
                            started_by='system', activate=True):
        """Return the segment for this *(inquiry / property / label)*, creating one
        only if no match exists.  Deterministic and idempotent.

        Dedup priority — the strongest available key wins so the same span is never
        duplicated:
          1. **inquiry** — reuse the segment already pointing at this inquiry;
          2. **property** (inquiry-less) — reuse the pre-inquiry span for the same
             property (this is what makes "New topic" for the same property
             idempotent instead of spawning a second orphan span);
          3. **label** (inquiry-less, property-less) — reuse a label-only span with
             the same normalized label (legacy off-catalog topics).

        ``property_base_id`` is always set from ``inquiry.property_base_id`` (when an
        inquiry is given) or the explicit *property*, so the span knows what it is
        about before its inquiry exists.  ``activate=False`` files a message under a
        span without hijacking the RM's active context (e.g. a swipe-reply to an
        older property's message).  Returns ``False`` when the flag is off so callers
        become no-ops.
        """
        self.ensure_one()
        if not self._owa_segments_enabled():
            return False
        Segment = self.env['wa.conversation.segment'].sudo()
        prop = (inquiry.property_base_id if inquiry else False) or property or False

        seg = False
        if inquiry:
            seg = self.segment_ids.filtered(
                lambda s: s.inquiry_id.id == inquiry.id
            )[:1]
        if not seg and prop:
            seg = self.segment_ids.filtered(
                lambda s: not s.inquiry_id and s.property_base_id.id == prop.id
            )[:1]
        if not seg and label and not prop:
            norm = self._owa_normalize_label(label)
            seg = self.segment_ids.filtered(
                lambda s: not s.inquiry_id and not s.property_base_id
                and self._owa_normalize_label(s.label) == norm
            )[:1]

        if not seg:
            seg = Segment.create({
                'conversation_id': self.id,
                'inquiry_id': inquiry.id if inquiry else False,
                'property_base_id': prop.id if prop else False,
                # Store only an explicit human label; the property NAME is derived
                # from property_base_id at display time (never the raw tag slug).
                'label': label or False,
                'started_by': started_by,
            })
        else:
            # Enrich an existing span without ever downgrading known facts.
            patch = {}
            if inquiry and not seg.inquiry_id:
                patch['inquiry_id'] = inquiry.id
            if prop and not seg.property_base_id:
                patch['property_base_id'] = prop.id
            if label and not seg.label:
                patch['label'] = label
            if patch:
                seg.write(patch)
        if activate:
            self._owa_activate_segment(seg)
        return seg

    @api.model
    def start_segment(self, conversation_id, inquiry_id=None, property_base_id=None,
                      label=None):
        """RM action: open/activate a segment for an inquiry, a property, or a bare
        label.  Returns the segment id."""
        conv = self.browse(conversation_id)
        inquiry = self.env['leads.new'].browse(inquiry_id) if inquiry_id else None
        prop = (self.env['property.base'].browse(property_base_id)
                if property_base_id else None)
        seg = conv._owa_ensure_segment(
            inquiry=inquiry, property=prop, label=label, started_by='rm')
        return seg.id if seg else False

    @api.model
    def start_property_topic(self, conversation_id, property_base_id, label=None):
        """RM action for "New topic": begin discussing *property_base_id*.

        Guards against duplication (consideration #4): if an inquiry for this
        (phone, property) already exists on the thread, do NOT open a new span —
        return ``{'action': 'exists', ...}`` so the UI guides the RM to *switch* to
        the existing inquiry instead.  Otherwise open (or reuse) the property-anchored
        pre-inquiry span and return ``{'action': 'started', ...}``.
        """
        conv = self.browse(conversation_id)
        if not (conv.exists() and conv._owa_segments_enabled() and property_base_id):
            return {'action': 'noop'}
        prop = self.env['property.base'].browse(int(property_base_id))
        if not prop.exists():
            return {'action': 'noop'}

        existing = conv.inquiry_ids.filtered(
            lambda l: l.property_base_id.id == prop.id)[:1]
        if existing:
            # Prefer the real inquiry over a fresh orphan span — switch to it.
            seg = conv._owa_ensure_segment(inquiry=existing, started_by='rm')
            return {
                'action': 'exists',
                'inquiry_id': existing.id,
                'segment_id': seg.id if seg else False,
                'label': prop.property_tag or prop.display_name,
            }

        seg = conv._owa_ensure_segment(
            property=prop, label=label or prop.property_tag, started_by='rm')
        return {'action': 'started', 'segment_id': seg.id if seg else False}

    @api.model
    def relink_segment(self, segment_id, inquiry_id):
        """Point an existing segment at *inquiry_id* — reclassifies the whole span.
        Used when an RM corrects attribution or when an inquiry is created later.

        Keeps the span's ``property_base_id`` and ``label`` in sync with the inquiry
        (property_base_id is a plain field now, not a related, so it must be set
        explicitly)."""
        seg = self.env['wa.conversation.segment'].sudo().browse(segment_id)
        seg.inquiry_id = inquiry_id or False
        if inquiry_id:
            prop = seg.inquiry_id.property_base_id
            if prop:
                seg.property_base_id = prop.id
            if not seg.label and prop:
                seg.label = prop.property_tag
        return True

    @api.model
    def _owa_bind_new_inquiry(self, inquiry) -> bool:
        """Bind a pre-inquiry ("New topic") span to *inquiry* when it is created.

        Runs from the ``leads.new`` create hook, so it fires no matter HOW the
        inquiry is born — Recommend wizard, manual entry, import — closing the old
        gap where only the inbox orphan flow bound segments.  Deterministic:

          1. a property-anchored span (``property_base_id`` == the inquiry's
             property, still inquiry-less) binds — no active-segment guessing;
          2. else, if the conversation's active span is a legacy label-only one
             (no property, no inquiry), bind that as a best-effort fallback.

        No-op (returns False) when segments are off, or the inquiry has no phone or
        no property.  Never raises — the caller guards, but stay defensive.
        """
        if not (inquiry and inquiry.property_base_id and inquiry.phone
                and self._owa_segments_enabled()):
            return False
        lead_phone = self._owa_standardize_lead_phone(inquiry.phone)
        if not lead_phone:
            return False
        candidates = self.sudo().search([('phone_number', 'like', lead_phone)])
        conv = candidates.filtered(
            lambda c: self._owa_standardize_lead_phone(c.phone_number) == lead_phone
        )[:1]
        if not conv:
            return False

        seg = conv.segment_ids.filtered(
            lambda s: not s.inquiry_id
            and s.property_base_id.id == inquiry.property_base_id.id
        )[:1]
        if not seg:
            active = conv.active_segment_id
            if active and not active.inquiry_id and not active.property_base_id:
                seg = active
        if not seg:
            return False
        self.relink_segment(seg.id, inquiry.id)
        return True

    @api.model
    def move_message_to_segment(self, message_id, segment_id):
        """Move a single mis-filed message to another segment (audited)."""
        msg = self.env['wa.message'].browse(message_id)
        msg.segment_id = segment_id or False
        return True

    @api.model
    def set_active_segment(self, conversation_id, segment_id):
        """Make an existing segment the conversation's active one (RM accepting a
        'switch to <property>?' suggestion).  Returns the segment id, or False."""
        conv = self.browse(conversation_id)
        seg = self.env['wa.conversation.segment'].browse(segment_id)
        if not (conv.exists() and seg.exists() and seg.conversation_id == conv):
            return False
        conv._owa_activate_segment(seg)
        return seg.id
