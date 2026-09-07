"""WhatsApp Quick Replies — saved canned messages an RM can insert in the composer.

Two scopes:
  * **Personal** — ``user_id`` set; visible only to that RM.
  * **Shared**   — ``user_id`` empty; visible to the whole WA team. Only WA
                   managers may create/edit shared replies (enforced by record
                   rules in ``security/wa_quick_reply_rules.xml``).

Static text only — selecting a reply inserts ``body`` verbatim into the composer
for the RM to edit before sending. No placeholder substitution.
"""

import json

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .wa_conversation_outbound import (
    WA_LIST_BUTTON_MAX,
    WA_LIST_ROW_DESC_MAX,
    WA_LIST_ROW_TITLE_MAX,
    WA_LIST_SECTION_TITLE_MAX,
)


class WaQuickReply(models.Model):
    _name = 'wa.quick.reply'
    _description = 'WhatsApp Quick Reply'
    _order = 'sequence, title'

    title = fields.Char(
        'Title',
        required=True,
        help="Short label shown in the quick-reply picker.",
    )
    kind = fields.Selection(
        [('text', 'Text'), ('list', 'List Message')],
        string='Type',
        required=True,
        default='text',
        help="'text' inserts the body into the composer; 'list' sends an "
             "interactive WhatsApp list message built from list_payload.",
    )
    list_payload = fields.Text(
        'List Payload (JSON)',
        help="For kind='list': JSON {'button', 'sections':[{'title','rows':"
             "[{'id','title','description'}]}]}. 'body' holds the list body text.",
    )
    shortcut = fields.Char(
        'Shortcut',
        help="Optional typeahead key, e.g. '/visit'. When the RM types '/' in "
             "the composer the picker filters by this.",
    )
    body = fields.Text(
        'Message',
        required=True,
        help="The text inserted verbatim into the composer.",
    )
    user_id = fields.Many2one(
        'res.users',
        string='Owner',
        index=True,
        ondelete='cascade',
        default=lambda self: self.env.user,
        help="Owner of a personal quick reply. Leave empty to make it a shared "
             "team-wide reply (managers only).",
    )
    is_shared = fields.Boolean(
        'Shared',
        compute='_compute_is_shared',
        store=True,
        help="True when this reply has no owner and is visible to the whole team.",
    )
    active = fields.Boolean('Active', default=True)
    sequence = fields.Integer('Sequence', default=10)

    @api.depends('user_id')
    def _compute_is_shared(self):
        for rec in self:
            rec.is_shared = not rec.user_id

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    @api.model
    def get_for_composer(self):
        """Return the current user's own + all shared replies for the picker.

        Record rules already restrict visibility, but we filter explicitly so
        the return shape is small and ordered.
        """
        replies = self.search([
            '|',
            ('user_id', '=', self.env.uid),
            ('user_id', '=', False),
        ])
        return [{
            'id': r.id,
            'title': r.title,
            'shortcut': r.shortcut or '',
            'body': r.body or '',
            'kind': r.kind,
            'list_payload': r._parsed_list_payload(),
            'is_shared': r.is_shared,
        } for r in replies]

    @api.constrains('kind', 'list_payload')
    def _check_list_payload_limits(self):
        """Reject a saved list that WhatsApp would refuse to deliver.

        Without this a quick reply can be stored with, say, a 38-character row
        title and only blow up months later at send time with an opaque Interakt
        400 — far from whoever authored it.  Same caps as
        :meth:`wa.conversation._owa_assert_list_limits`.
        """
        for rec in self:
            if rec.kind != 'list' or not rec.list_payload:
                continue
            # Unparseable payloads stay tolerated (_parsed_list_payload returns
            # None and the reply simply never sends as a list) — this constraint
            # is only about lengths WhatsApp would reject.
            try:
                data = json.loads(rec.list_payload)
            except (ValueError, TypeError):
                continue
            if not isinstance(data, dict):
                continue
            button = (data.get('button') or '').strip()
            if len(button) > WA_LIST_BUTTON_MAX:
                raise ValidationError(
                    "The list button label is %d characters — WhatsApp allows at most %d."
                    % (len(button), WA_LIST_BUTTON_MAX)
                )
            for section in data.get('sections') or []:
                if not isinstance(section, dict):
                    continue
                s_title = (section.get('title') or '').strip()
                if len(s_title) > WA_LIST_SECTION_TITLE_MAX:
                    raise ValidationError(
                        "The section title “%s” is %d characters — WhatsApp allows "
                        "at most %d." % (s_title, len(s_title), WA_LIST_SECTION_TITLE_MAX)
                    )
                for row in section.get('rows') or []:
                    if not isinstance(row, dict):
                        continue
                    title = (row.get('title') or '').strip()
                    if len(title) > WA_LIST_ROW_TITLE_MAX:
                        raise ValidationError(
                            "The list item “%s” is %d characters — WhatsApp allows at "
                            "most %d. Please shorten it."
                            % (title, len(title), WA_LIST_ROW_TITLE_MAX)
                        )
                    desc = (row.get('description') or '').strip()
                    if len(desc) > WA_LIST_ROW_DESC_MAX:
                        raise ValidationError(
                            "The description for “%s” is %d characters — WhatsApp "
                            "allows at most %d."
                            % (title, len(desc), WA_LIST_ROW_DESC_MAX)
                        )

    def _parsed_list_payload(self):
        """Return the list_payload as a dict, or None for non-list replies."""
        self.ensure_one()
        if self.kind != 'list' or not self.list_payload:
            return None
        try:
            data = json.loads(self.list_payload)
        except (ValueError, TypeError):
            return None
        return data if isinstance(data, dict) and data.get('sections') else None

    @api.model
    def get_manager_list(self):
        """Return replies for the management UI, split into personal + shared.

        A manager sees everyone's shared replies plus their own personal ones.
        A plain user sees their own personal replies plus shared (read-only for
        shared, enforced by rules).
        """
        is_manager = self.env.user.has_group('wa_communication.group_wa_manager')
        records = self.with_context(active_test=False).search([
            '|',
            ('user_id', '=', self.env.uid),
            ('user_id', '=', False),
        ])
        return {
            'is_manager': is_manager,
            'replies': [{
                'id': r.id,
                'title': r.title,
                'shortcut': r.shortcut or '',
                'body': r.body or '',
                'kind': r.kind,
                'list_payload': r._parsed_list_payload(),
                'is_shared': r.is_shared,
                'active': r.active,
                'owned': r.user_id.id == self.env.uid,
            } for r in records],
        }
