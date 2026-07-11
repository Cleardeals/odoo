"""WhatsApp Message model — append-only log of every WA message in either direction.

Architecture notes
------------------
This table is the single source of truth for all WhatsApp message events in
Odoo.  It is intentionally **append-only**: core structural fields (direction,
kind, occurred_at, body, conversation_id, lead_id) are immutable after
creation.  Only lifecycle fields (status, status_updated_at, wa_message_id,
cost_inr) are written after the initial insert.

Timestamps
----------
``occurred_at`` records the *actual event time* from the Interakt/WA webhook
(delivered_at_utc, seen_at_utc, received_at_utc, etc.).  It is NOT the time
the Odoo record was created.  Use this field for timeline ordering and all
time-based analytics.

``received_at`` records when this Odoo record was created.  The delta
``occurred_at - received_at`` measures webhook processing latency.

Status lifecycle for outbound messages::

    queued → sent → delivered → read
                  ↘ failed | meta_blocked | invalid_number | opted_out
                    | rate_limited | template_error | expired | skipped

Inbound messages are created with ``status='delivered'`` (WA guarantees
delivery when we receive the inbound push event).

Actor fields
------------
``lead_id`` links to ``leads.new`` for ``actor_type='buyer_inquiry'`` actors.
When ``customer.base`` is built, add ``customer_id = Many2one('customer.base')``
alongside it — exactly one of the two should be set per row.

``platform_actor_id`` stores the WA platform's internal actor record ID
(e.g. ``workflow_enrollments.inquiry_id``) for cross-referencing event logs.
It is an integer, not a FK.
"""

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

# Structural fields that must never change after a record is created.
# Lifecycle fields (status, status_updated_at, wa_message_id, cost_inr)
# are deliberately excluded — they are updated by the delivery pipeline.
_IMMUTABLE_FIELDS = frozenset({
    'direction',
    'kind',
    'occurred_at',
    'conversation_id',
    'body',
    'lead_id',
})


class WaMessage(models.Model):
    """A single WhatsApp message in either direction.

    The ``kind`` and ``initiator`` fields together describe what happened:

    ==================  ===========  ============================================
    kind                initiator    Meaning
    ==================  ===========  ============================================
    template            workflow     Automated template step in a workflow
    template            rm           RM manually sent a template
    freetext            rm           RM typed a free-text reply
    image/document/…    rm           RM sent a media attachment
    text_reply          buyer        Buyer typed a message
    button_reply        buyer        Buyer tapped a quick-reply button
    system              system       Enrollment / assignment pill in timeline
    ==================  ===========  ============================================
    """

    _name = 'wa.message'
    _description = 'WhatsApp Message'
    _order = 'occurred_at desc, id desc'
    _rec_name = 'wa_message_id'

    # ------------------------------------------------------------------
    # Core identity
    # ------------------------------------------------------------------

    conversation_id = fields.Many2one(
        'wa.conversation',
        string='Conversation',
        required=True,
        ondelete='cascade',
        index=True,
    )
    wa_message_id = fields.Char(
        'WA Message ID',
        index=True,
        copy=False,
        help="WhatsApp-assigned message ID (wamid.*).  Null for outbound "
             "messages until the bridge ACKs the send.",
    )
    request_id = fields.Char(
        'Request ID',
        index=True,
        copy=False,
        help="OdooWaRequest.request_id UUID for outbound sends.  "
             "Used to correlate the Odoo send request with delivery receipts.",
    )

    # ------------------------------------------------------------------
    # Direction and initiator
    # ------------------------------------------------------------------

    direction = fields.Selection(
        [('inbound', 'Inbound'), ('outbound', 'Outbound')],
        required=True,
        index=True,
    )
    initiator = fields.Selection(
        [
            ('buyer',    'Buyer'),
            ('rm',       'RM (Manual)'),
            ('workflow', 'Workflow Automation'),
            ('system',   'System'),
        ],
        required=True,
        index=True,
        help="Who initiated this message.\n"
             "buyer    — inbound from the lead / customer.\n"
             "rm       — RM sent manually from the WA activity tab.\n"
             "workflow — automated template step executed by the workflow engine.\n"
             "system   — internal event pill (enrollment, assignment, etc.).",
    )

    # ------------------------------------------------------------------
    # Message type
    # ------------------------------------------------------------------

    kind = fields.Selection(
        [
            ('template',     'Template'),       # outbound automated / RM template
            ('freetext',     'Free Text'),       # outbound RM plain-text reply
            ('image',        'Image'),           # media: JPG / PNG / WebP
            ('document',     'Document'),        # media: PDF / Office file
            ('video',        'Video'),           # media: MP4 / 3GP
            ('audio',        'Audio'),           # media: audio / voice note
            ('list',         'List Message'),     # outbound: RM sent an interactive list
            ('button_reply', 'Button Reply'),    # inbound: buyer tapped a button
            ('text_reply',   'Text Reply'),      # inbound: buyer typed text
            ('list_reply',   'List Reply'),      # inbound: buyer picked a list option
            ('location',     'Location'),        # inbound: shared location pin
            ('contact',      'Contact'),         # inbound: shared contact card
            ('sticker',      'Sticker'),         # inbound: sticker (WebP image)
            ('system',       'System Event'),    # enrollment / assignment pill
            ('unknown',      'Unknown'),         # unrecognised WA message type
        ],
        string='Type',
        required=True,
        index=True,
    )

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    body = fields.Text('Body')
    sender_name = fields.Char(
        'Sender Name',
        help="Display name from the WA contact profile (inbound only).",
    )

    # ------------------------------------------------------------------
    # Template / workflow context
    # ------------------------------------------------------------------

    template_name = fields.Char(
        'Template Name',
        help="WA template identifier (e.g. 'site_visit_reminder_v2').  "
             "Populated for kind='template'.",
    )
    template_body = fields.Text(
        'Template Body',
        help="Rendered template body text (placeholders substituted), extracted "
             "from the Interakt status webhook's raw_template.  Kept separate from "
             "the immutable 'body' field so it can be backfilled when the receipt "
             "(sent/delivered) arrives.",
    )
    template_header = fields.Char(
        'Template Header',
        help="Rendered template header text (placeholders substituted), "
             "extracted from the Interakt status webhook's raw_template.",
    )
    template_footer = fields.Char(
        'Template Footer',
        help="Static template footer text, from the Interakt raw_template.",
    )
    template_buttons = fields.Json(
        'Template Buttons',
        help="List of quick-reply / CTA button labels for a template message, "
             "from the Interakt raw_template.",
    )
    workflow_slug = fields.Char(
        'Workflow',
        help="Slug of the WA workflow that triggered this message "
             "(from OdooWaEvent.workflow_slug).  Null for RM-initiated sends.",
    )
    step_id = fields.Char(
        'Workflow Step',
        help="Internal step ID within the workflow "
             "(from OdooWaEvent.step_id).",
    )
    enrollment_id = fields.Char(
        'Enrollment ID',
        help="UUID of the workflow_enrollments row on the WA platform "
             "(from OdooWaEvent.enrollment_id).",
    )

    # ------------------------------------------------------------------
    # Actor link
    # ------------------------------------------------------------------

    lead_id = fields.Many2one(
        'leads.new',
        string='Lead',
        index=True,
        ondelete='set null',
        copy=False,
        help="The leads.new record for this actor (actor_type='buyer_inquiry').  "
             "Null until auto-linked by the push handler or _get_or_create_for_phone.  "
             "TODO: add customer_id = Many2one('customer.base') once that module exists.",
    )
    platform_actor_id = fields.Integer(
        'Platform Actor ID',
        help="WA platform's internal actor record ID (workflow_enrollments.inquiry_id).  "
             "Integer, not a FK — used to cross-reference WA platform event logs.",
    )

    # ------------------------------------------------------------------
    # Inquiry attribution (additive, correctable — see wa.conversation.segment)
    # ------------------------------------------------------------------
    #
    # ``lead_id`` above is the immutable create-time best-guess and is never
    # touched.  ``segment_id`` is a *mutable* overlay: re-pointing a segment (or
    # moving a message to another segment) reclassifies the message for analytics
    # via ``effective_inquiry_id`` / ``effective_property_id`` WITHOUT mutating any
    # immutable fact.  With no segment set, the effective_* fields fall back to
    # ``lead_id`` — i.e. today's behaviour, unchanged.

    segment_id = fields.Many2one(
        'wa.conversation.segment',
        string='Segment',
        index=True,
        ondelete='set null',
        copy=False,
        help="The attribution segment this message belongs to.  Writable/audited "
             "so an RM can move a mis-filed message to the right inquiry.  Null "
             "behaves exactly as before (effective_* fall back to lead_id).",
    )
    effective_inquiry_id = fields.Many2one(
        'leads.new',
        string='Effective Inquiry',
        compute='_compute_effective_attribution',
        store=True,
        index=True,
        help="The corrected inquiry for analytics: segment's inquiry if set, "
             "else the create-time lead_id.  Group analytics on this, not lead_id.",
    )
    effective_property_id = fields.Many2one(
        'property.base',
        string='Effective Property',
        compute='_compute_effective_attribution',
        store=True,
        index=True,
        help="Property of the effective inquiry — the analytics group key for "
             "'messages per property' that stays correct after re-pointing.",
    )

    @api.depends(
        'segment_id', 'segment_id.inquiry_id', 'segment_id.inquiry_id.property_base_id',
        'lead_id', 'lead_id.property_base_id',
    )
    def _compute_effective_attribution(self):
        for rec in self:
            inquiry = rec.segment_id.inquiry_id or rec.lead_id
            rec.effective_inquiry_id = inquiry
            rec.effective_property_id = inquiry.property_base_id if inquiry else False

    # ------------------------------------------------------------------
    # Delivery status
    # ------------------------------------------------------------------

    status = fields.Selection(
        [
            ('queued',         'Queued'),          # inserted before API call
            ('sent',           'Sent'),             # Interakt accepted
            ('delivered',      'Delivered'),        # webhook: message_api_delivered
            ('read',           'Read'),             # webhook: message_api_read
            ('failed',         'Failed'),           # retryable failure
            ('meta_blocked',   'Meta Blocked'),     # error code 131026 — permanent
            ('invalid_number', 'Invalid Number'),   # error code 131052 — permanent
            ('opted_out',      'Opted Out'),        # error code 131047
            ('rate_limited',   'Rate Limited'),     # error code 130429 — transient
            ('template_error', 'Template Error'),   # error codes 132000 / 132001
            ('skipped',        'Skipped'),          # pre-send check blocked
            ('expired',        'Expired'),          # 24-hour window passed
            ('enrolled',       'Enrolled'),         # system: enrollment started
            ('enrollment_completed', 'Enrollment Completed'),  # system: enrollment done
        ],
        required=True,
        default='queued',
        index=True,
    )
    status_updated_at = fields.Datetime('Status Updated At', readonly=True)

    # ------------------------------------------------------------------
    # Media
    # ------------------------------------------------------------------

    media_url = fields.Char(
        'Media URL',
        help="Public URL of the media file for image/document/video/audio messages.",
    )
    media_filename = fields.Char(
        'Media Filename',
        help="Filename derived from the media URL path (e.g. 'photo.jpeg', 'doc.pdf').",
    )

    # ------------------------------------------------------------------
    # Interactive list message (kind='list')
    # ------------------------------------------------------------------

    list_payload = fields.Text(
        'List Payload (JSON)',
        readonly=True,
        help="For kind='list': JSON {'button': <menu button label>, "
             "'sections': [{'title', 'rows': [{'id','title','description'}]}]}.",
    )

    # ------------------------------------------------------------------
    # Delivery timestamps
    # ------------------------------------------------------------------

    delivered_at = fields.Datetime(
        'Delivered At',
        readonly=True,
        help="When the recipient's device confirmed delivery (from OdooWaEvent).",
    )
    seen_at = fields.Datetime(
        'Seen At',
        readonly=True,
        help="When the recipient read the message (from OdooWaEvent).",
    )

    # ------------------------------------------------------------------
    # CTA context
    # ------------------------------------------------------------------

    template_replied_to = fields.Char(
        'Template Replied To',
        help="Template name the button-reply was triggered from (CTA replies only).",
    )

    quoted_message_id = fields.Many2one(
        'wa.message',
        string='Quoted Message',
        ondelete='set null',
        index=True,
        help="The exact earlier message this reply quotes (swipe / button reply), "
             "resolved from the Interakt message_context id.  Drives click-to-scroll.",
    )
    quoted_body = fields.Text(
        'Quoted Body',
        help="Body of the message this inbound is a swipe-reply to.",
    )
    quoted_sender = fields.Char(
        'Quoted Sender',
        help="Display name of the sender of the quoted message.",
    )

    # ------------------------------------------------------------------
    # Cost
    # ------------------------------------------------------------------

    cost_inr = fields.Float(
        'Cost (INR)',
        digits=(10, 4),
        help="Delivery cost in INR from the Interakt webhook.  "
             "Stored to 4 decimal places to match NUMERIC(8,4) on the WA platform.",
    )

    # ------------------------------------------------------------------
    # Timestamps
    # ------------------------------------------------------------------

    occurred_at = fields.Datetime(
        'Occurred At (UTC)',
        required=True,
        index=True,
        help="Time of the actual event from Interakt/WA (delivered_at_utc, "
             "seen_at_utc, received_at_utc, etc.).  NOT the time this record "
             "was created.  Use this field for timeline ordering and all "
             "time-based analytics.",
    )
    received_at = fields.Datetime(
        'Received At (Odoo)',
        default=fields.Datetime.now,
        readonly=True,
        copy=False,
        help="When this Odoo record was created.  "
             "occurred_at − received_at = webhook processing latency.",
    )

    # ------------------------------------------------------------------
    # Raw audit data
    # ------------------------------------------------------------------

    raw_payload = fields.Json(
        'Raw Payload',
        help="Full event payload for debugging.  Not indexed.  "
             "Do not use in domain filters — use structured fields instead.",
    )

    # ------------------------------------------------------------------
    # Append-only enforcement
    # ------------------------------------------------------------------

    def write(self, vals):
        """Reject writes to immutable structural fields after creation."""
        immutable_attempted = _IMMUTABLE_FIELDS & vals.keys()
        if immutable_attempted and not self.env.context.get('_wa_message_allow_write'):
            raise ValidationError(
                "wa.message records are append-only.  "
                "The following fields cannot be changed after creation: %s"
                % sorted(immutable_attempted)
            )
        result = super().write(vals)
        # Broadcast status changes to the message-log live channel so the
        # OWL Message Log client action can update in real time.
        if 'status' in vals:
            self._broadcast_message_log_update()
        return result

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Broadcast new messages to the message-log live channel.
        records._broadcast_message_log_update()
        return records

    def _broadcast_message_log_update(self):
        """Send a lightweight bus.bus notification to the wa_message_log channel.

        The OWL Message Log component subscribes to this channel and triggers
        a data refresh when it receives this notification.  We send only a
        minimal signal — the component fetches fresh data itself.
        """
        try:
            self.env['bus.bus']._sendone(
                'wa_message_log',
                'wa_message_update',
                {'ts': fields.Datetime.now().isoformat()},
            )
        except Exception:
            pass  # never let broadcast failures break the write/create path

    def unlink(self):
        """Block direct ORM deletion to protect the audit trail.

        Records are only removed via DB-level cascade when their parent
        ``wa.conversation`` is deleted.  Direct ORM deletes are rejected.
        Pass ``{'_wa_message_allow_delete': True}`` in context only for
        test teardown or data-migration scripts.
        """
        if not self.env.context.get('_wa_message_allow_delete'):
            raise UserError(
                "WhatsApp message records cannot be deleted individually.  "
                "Delete the parent conversation to remove all its messages."
            )
        return super().unlink()
