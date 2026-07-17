"""WhatsApp conversation segment — a re-pointable inquiry attribution span.

A WhatsApp thread is, by WhatsApp's own design, one conversation per phone
number.  But a single phone (a *lead*) can hold many *inquiries* — one per
property (``leads.new`` is the inquiry record, deduped on ``(phone,
property_base_id)``).  Within one phone thread the discussion drifts between
properties, sometimes onto an inquiry that does not exist yet (an RM discusses
Property B inside Property A's chat, then creates B's inquiry afterwards).

Attribution is therefore a **mutable interpretation, not an immutable fact**.
The immutable facts (sender / time / body / direction) live on ``wa.message``;
*which inquiry a span of the thread is about* is captured here, as a contiguous
**segment** whose ``inquiry_id`` is nullable and re-pointable:

* a segment can be opened with only a ``label`` (e.g. "Property B") before its
  inquiry exists, then linked to the ``leads.new`` once it is created;
* re-pointing ``inquiry_id`` reclassifies the whole span at once — every
  ``wa.message`` in it recomputes its ``effective_inquiry_id`` /
  ``effective_property_id`` without ever touching the immutable ``lead_id``.

This whole layer is dormant unless ``wa_communication.segments_enabled`` is on,
so with the flag off the system behaves exactly as before.
"""

from odoo import api, fields, models


class WaConversationSegment(models.Model):
    """A contiguous span of a phone thread attributed to one inquiry."""

    _name = 'wa.conversation.segment'
    _description = 'WhatsApp Conversation Segment'
    _order = 'started_at, id'

    conversation_id = fields.Many2one(
        'wa.conversation',
        string='Conversation',
        required=True,
        ondelete='cascade',
        index=True,
    )
    inquiry_id = fields.Many2one(
        'leads.new',
        string='Inquiry',
        index=True,
        ondelete='set null',
        help="The leads.new inquiry (phone + property) this span is about.  "
             "Nullable and re-pointable: a segment may be labelled before its "
             "inquiry exists, then linked once the inquiry is created.",
    )
    label = fields.Char(
        'Label',
        help="Human label for the span, usable before inquiry_id is set "
             "(e.g. a property tag or 'Property B').",
    )
    property_base_id = fields.Many2one(
        'property.base',
        string='Property',
        index=True,
        help="The property this span is about — chosen up front (from 'New topic') "
             "and kept in sync with the inquiry once one is linked.  Unlike "
             "inquiry_id it can be set BEFORE the inquiry exists, which makes dedup "
             "and later binding deterministic instead of guessing from a free-text "
             "label.  Maintained by the segment helpers, never a raw related.",
    )
    display_name = fields.Char(
        compute='_compute_display_name',
        store=False,
    )
    is_active = fields.Boolean(
        'Active',
        default=False,
        index=True,
        copy=False,
        help="Whether new messages join this segment.  At most one active "
             "segment per conversation (maintained by the activation helpers).",
    )
    started_at = fields.Datetime(
        'Started At',
        default=fields.Datetime.now,
        index=True,
    )
    started_by = fields.Selection(
        [
            ('system', 'System'),
            ('rm', 'RM'),
            ('auto_suggested', 'Auto (deterministic signal)'),
        ],
        default='system',
        required=True,
        help="What opened this segment — a deterministic platform signal "
             "(workflow send / quoted reply), the RM, or initial bootstrap.",
    )
    message_ids = fields.One2many(
        'wa.message',
        'segment_id',
        string='Messages',
    )
    message_count = fields.Integer(
        compute='_compute_message_count',
        string='Messages',
    )

    @api.depends('label', 'inquiry_id.name',
                 'property_base_id.name', 'inquiry_id.property_base_id.name')
    def _compute_display_name(self):
        for rec in self:
            # The "DISCUSSING" chip names the PROPERTY this span is about — resolve
            # it from the span's own property_base_id or, if the span only carries
            # its inquiry, that inquiry's property.  Fall back to the lead name only
            # when there is genuinely no property (a bare label-only topic).
            prop = rec.property_base_id or rec.inquiry_id.property_base_id
            rec.display_name = (
                rec.label
                or (prop.name if prop else False)
                or (rec.inquiry_id.name if rec.inquiry_id else False)
                or 'Unassigned'
            )

    @api.depends('message_ids')
    def _compute_message_count(self):
        for rec in self:
            rec.message_count = len(rec.message_ids)
