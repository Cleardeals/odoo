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

    def _owa_ensure_segment(self, inquiry=None, label=None, started_by='system',
                            activate=True):
        """Return a segment for *inquiry* (or a labelled one), creating it if needed.

        Idempotent: if a segment for the same inquiry already exists it is reused
        rather than duplicated.  When ``activate`` is True it also becomes the
        conversation's active segment; pass ``activate=False`` to file a message
        under an inquiry without hijacking the RM's current active context (e.g. a
        swipe-reply to an *older* property's message).  Returns ``False`` when the
        feature flag is off so callers become no-ops.
        """
        self.ensure_one()
        if not self._owa_segments_enabled():
            return False
        Segment = self.env['wa.conversation.segment'].sudo()
        seg = False
        if inquiry:
            seg = self.segment_ids.filtered(
                lambda s: s.inquiry_id.id == inquiry.id
            )[:1]
        if not seg:
            seg = Segment.create({
                'conversation_id': self.id,
                'inquiry_id': inquiry.id if inquiry else False,
                'label': label or (inquiry.property_base_id.property_tag if inquiry else False),
                'started_by': started_by,
            })
        elif label and not seg.label:
            seg.label = label
        if activate:
            self._owa_activate_segment(seg)
        return seg

    @api.model
    def start_segment(self, conversation_id, inquiry_id=None, label=None):
        """RM action: open/activate a segment, optionally on a not-yet-created
        inquiry (label-only).  Returns the segment id."""
        conv = self.browse(conversation_id)
        inquiry = self.env['leads.new'].browse(inquiry_id) if inquiry_id else None
        seg = conv._owa_ensure_segment(inquiry=inquiry, label=label, started_by='rm')
        return seg.id if seg else False

    @api.model
    def relink_segment(self, segment_id, inquiry_id):
        """Point an existing segment at *inquiry_id* — reclassifies the whole span.
        Used when an RM corrects attribution or when an inquiry is created later."""
        seg = self.env['wa.conversation.segment'].browse(segment_id)
        seg.inquiry_id = inquiry_id or False
        if inquiry_id and not seg.label:
            seg.label = seg.inquiry_id.property_base_id.property_tag
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
