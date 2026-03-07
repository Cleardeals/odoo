from odoo import api, fields, models

# Human-readable labels for fields whose changes are posted to the parent
# lead's chatter.  Only fields listed here are audited.
_AUDIT_FIELDS = {
    "property_base_id": "Property",
    "current_status": "Status",
    "remarks": "Remarks",
    "site_visit_date": "Site Visit Date",
    "feedback_general": "Feedback",
    "feedback_site_visit_done": "Feedback (Site Visit Done)",
}


class LeadPropertyInterest(models.Model):
    _name = "lead.property.interest"
    _description = "Lead Recommended Property Interests"
    _order = "create_date desc"

    # [MIGRATION 19.0] Replaced legacy _sql_constraints with models.Constraint
    # Constraint uses property_base_id (the canonical property.base link).
    _lead_prop_uniq = models.Constraint(
        "UNIQUE(lead_id, property_base_id)",
        message="This property is already linked to the lead.",
    )

    lead_id = fields.Many2one(
        "leads.new", string="Lead", ondelete="cascade", required=True,
    )

    # Keeps pointing to property.inventory — matches the existing DB column (legacy data).
    # Never change this comodel without a proper DB migration.
    property_id = fields.Many2one(
        "property.inventory",
        string="Property (Legacy)",
    )

    # NEW field — links to the canonical property.base model.
    # Populated going forward; backfilled via the Lead Property Migration Wizard.
    property_base_id = fields.Many2one(
        "property.base",
        string="Property",
        copy=False,
        index=True,
    )

    # The models own status pipelines
    current_status = fields.Selection(
        [
            ("busy", "Busy"),
            ("lead", "Lead"),
            ("ringing", "Ringing"),
            ("call_back_later", "Call Back Later"),
            ("site_visit_scheduled", "Site Visit Scheduled"),
            ("option_not_matching_requirements", "Option Not Matching Requirements"),
            ("details_shared_of_property", "Details Shared of Property"),
            ("no_requirements", "No Requirements"),
            (
                "detail_shared_and_interested_for_site_visit",
                "Detail Shared and Interested for Site Visit",
            ),
            ("switched_off", "Switched Off"),
            ("requirement_closed", "Requirement Closed"),
            ("property_sold_out", "Property Sold Out"),
            ("rescheduled", "Rescheduled"),
            ("budget_not_sufficient", "Budget Not Sufficient"),
            ("site_visit_done", "Site Visit Done"),
            ("number_not_in_use_wrong_number", "Number Not in Use/Wrong Number"),
            ("other", "Other"),
        ],
        string="Current Status",
        default="lead",
        required=True,
    )

    remarks = fields.Text(string="Remarks")
    site_visit_date = fields.Datetime(string="Site Visit Date", copy=False)

    site_visit_date_only = fields.Date(
        string="Site Visit Date (Recommended Property)",
        compute="_compute_site_visit_date_only",
        store=True,  # Essential for filtering
        readonly=True,
    )

    # # We link to the RM of the property for the security rules
    # property_rm_user_id = fields.Many2one(
    #     related='property_id.rm_user_id',
    #     store=True,
    #     readonly=True,
    #     string="Property's RM"
    # )

    # Legacy related fields — sourced from property.inventory (property_id)
    property_bhk = fields.Char(
        related="property_id.bhk",
        string="Property BHK (Legacy)",
        readonly=True,
        store=True,
    )
    property_location = fields.Char(
        related="property_id.location",
        string="Property Location (Legacy)",
        readonly=True,
        store=True,
    )
    property_city = fields.Char(
        related="property_id.city",
        string="Property City (Legacy)",
        readonly=True,
        store=True,
    )
    property_link = fields.Char(
        related="property_id.property_link",
        string="Property Link (Legacy)",
        readonly=True,
    )

    # New related fields — sourced from property.base (property_base_id)
    base_property_bhk = fields.Char(
        related="property_base_id.bhk",
        string="Property BHK",
        readonly=True,
        store=True,
    )
    base_property_location = fields.Char(
        related="property_base_id.location",
        string="Property Location",
        readonly=True,
        store=True,
    )
    base_property_city = fields.Char(
        related="property_base_id.city",
        string="Property City",
        readonly=True,
        store=True,
    )
    base_property_link = fields.Char(
        related="property_base_id.property_link",
        string="Property Link",
        readonly=True,
        store=True,
    )
    base_property_owner_name = fields.Char(
        related="property_base_id.owner_name",
        string="Property Owner",
        readonly=True,
        store=True,
    )

    feedback_general = fields.Selection(
        [
            ("buyer_did_not_visit_property", "Buyer Did Not Visit Property"),
            ("buyer_not_interested", "Buyer Not Interested"),
            ("buyer_not_picking_call", "Buyer Not Picking Call"),
            ("visit_needs_to_be_rescheduled", "Visit Needs to be Rescheduled"),
            ("other", "Other"),
        ],
        string="Feedback",
    )

    feedback_site_visit_done = fields.Selection(
        [
            ("buyer_liked_property", "Buyer Liked Property"),
            ("buyer_requirement_closed", "Buyer Requirement Closed"),
            ("buyer_visit_from_outside", "Buyer Visit From Outside"),
            ("buyer_not_pickup_call", "Buyer Not Picking Call"),
            ("planning_for_second_visit", "Planning for Second Visit"),
            ("negotiation_stage", "Negotiation Stage"),
            ("visit_done_confirmed_by_owner", "Visit Done - Confirmed by Owner"),
            ("looking_for_more_options", "Looking for More Options"),
            ("price_is_high", "Price is High"),
            ("location_mismatch", "Location Mismatch"),
            ("deal_closed", "Deal Closed"),
            ("other", "Other"),
        ],
        string="Feedback for Site Visit Done",
    )

    @api.depends("site_visit_date")
    def _compute_site_visit_date_only(self):
        """
        Takes the 'site_visit_date' (Datetime) and stores
        just the 'date' part for easy filtering.
        """
        for rec in self:
            if rec.site_visit_date:
                rec.site_visit_date_only = rec.site_visit_date.date()
            else:
                rec.site_visit_date_only = False

    # ------------------------------------------------------------------
    # Activity tracking — changes posted to the parent lead's chatter
    # ------------------------------------------------------------------

    def _audit_format_value(self, field_name, value):
        """Return a human-readable string for *value* of *field_name*."""
        if not value:
            return "(none)"
        field = self._fields.get(field_name)
        if field and field.type == "many2one":
            return value.display_name if value else "(none)"
        if field and field.type == "selection":
            sel = field.selection
            if callable(sel):
                sel = sel(self)
            return dict(sel or {}).get(value, str(value))
        return str(value)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.lead_id:
                continue
            prop_name = rec.property_base_id.display_name or "(unnamed property)"
            rec.lead_id.message_post(
                body=(
                    f"<p>&#128204; <b>Recommended property added</b><br/>"
                    f"Property: <b>{prop_name}</b></p>"
                ),
                subtype_xmlid="mail.mt_note",
            )
        return records

    def write(self, vals):
        audited_keys = [k for k in vals if k in _AUDIT_FIELDS]

        # Snapshot old values before the write so we can diff them after.
        old_values = {}
        if audited_keys:
            for rec in self:
                old_values[rec.id] = {k: rec[k] for k in audited_keys}

        res = super().write(vals)

        if audited_keys:
            for rec in self:
                if not rec.lead_id:
                    continue
                changes = []
                for key in audited_keys:
                    old_val = old_values.get(rec.id, {}).get(key)
                    new_val = rec[key]
                    old_display = rec._audit_format_value(key, old_val)
                    new_display = rec._audit_format_value(key, new_val)
                    if old_display != new_display:
                        label = _AUDIT_FIELDS[key]
                        changes.append(
                            f"&#8226; <b>{label}:</b> {old_display} \u2192 {new_display}",
                        )
                if changes:
                    prop_name = (
                        rec.property_base_id.display_name or "(unnamed property)"
                    )
                    lines = "<br/>".join(changes)
                    body = (
                        f"<p>&#9998; <b>Recommended property updated</b><br/>"
                        f"Property: <b>{prop_name}</b><br/>{lines}</p>"
                    )
                    rec.lead_id.message_post(body=body, subtype_xmlid="mail.mt_note")

        return res

    def unlink(self):
        # Capture identity data before the records are deleted.
        pre_unlink = [
            {
                "lead": rec.lead_id,
                "prop_name": rec.property_base_id.display_name or "(unnamed property)",
            }
            for rec in self
        ]
        res = super().unlink()
        for data in pre_unlink:
            if data["lead"]:
                data["lead"].message_post(
                    body=(
                        f"<p>&#128683; <b>Recommended property removed</b><br/>"
                        f"Property: <b>{data['prop_name']}</b></p>"
                    ),
                    subtype_xmlid="mail.mt_note",
                )
        return res
