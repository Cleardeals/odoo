from odoo import api, fields, models
from odoo.exceptions import ValidationError

STATE_CODE_MAP = {
    "Gujarat": "GU",
    "Maharashtra": "MH",
}

CITY_CODE_MAP = {
    "Ahmedabad": "AH",
    "Gandhinagar": "GA",
    "Himatnagar": "HI",
    "Kheda": "KH",
    "Pune": "PU",
    "Rajkot": "RA",
    "Surat": "SU",
    "Vadodara": "VA",
}

STATE_CITY_MAP = {
    "GU": ["AH", "GA", "HI", "KH", "RA", "SU", "VA"],
    "MH": ["PU"],
}

CITY_STARTING_NUMBER = {
    "AH": 5002,
    "PU": 101,
    "SU": 1501,
    "RA": 1501,
    "VA": 1501,
}


class Deal(models.Model):
    _name = "deal"
    _description = "Contain information related to transaction, property."
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "deal_id"
    _rec_name = "deal_id"

    deal_id = fields.Char(
        string="Deal ID",
        copy=False,
        readonly=True,
        index=True,
    )
    property_id = fields.Many2one(
        "property.base",
        string="Property",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    owner_id = fields.Many2one(
        "deal.owner",
        string="Owner",
        required=True,
        tracking=True,
    )
    bde_id = fields.Many2one("leads.bde", string="BDE", required=True, tracking=True)
    deal_type = fields.Selection(
        [
            ("regular", "Regular"),
            ("ops_sale_lead", "Ops Sale Lead"),
            ("renewal", "Renewal"),
        ],
        string="Deal Type",
        required=True,
        index=True,
        tracking=True,
        default="regular",
    )
    is_offer = fields.Boolean(string="Is Offer", default=False, tracking=True)
    offer_id = fields.Many2one(
        "deal.offer",
        string="Offer",
        tracking=True,
        domain=[("is_active", "=", True)],
    )

    package_id = fields.Many2one(
        "deal.package",
        string="Package",
        required=True,
        tracking=True,
        domain=[("is_active", "=", True)],
    )
    package_amount = fields.Monetary(
        string="Package Amount",
        related="package_id.amount",
        required=True,
        tracking=True,
        currency_field="currency_id",
    )
    gross_amount = fields.Monetary(
        string="Gross Amount",
        required=True,
        tracking=True,
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: self.env.ref("base.INR"),
    )
    transaction_ids = fields.One2many(
        "deal.transaction",
        "deal_id",
        string="Transactions",
    )
    deal_status = fields.Selection(
        [
            ("registration", "Registration"),
            ("live", "Live"),
            ("sold", "Sold"),
            ("renewed", "Renewed"),
            ("closed", "Closed"),
        ],
        string="Deal Status",
        required=True,
        tracking=True,
        index=True,
        default="registration",
    )
    closed_reason = fields.Selection(
        [("package_expired", "Package Expired"), ("deal_cancelled", "Deal Cancelled")],
        string="Closed Reason",
        tracking=True,
    )
    is_full_payment = fields.Boolean(
        string="Is Full Payment",
        default=False,
        tracking=True,
    )
    registration_date = fields.Date(
        string="Registration Date",
        required=True,
        tracking=True,
        default=fields.Date.context_today,
    )
    closed_at = fields.Datetime(string="Closed At", tracking=True, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("package_id"):
                raise ValidationError("Package is required to create a deal")

            if not vals.get("deal_id"):
                property_id = vals.get("property_id")
                state_code = None
                city_code = None

                if property_id:
                    property_rec = self.env["property.base"].browse(property_id)
                    city = (property_rec.city or "").strip()
                    state = (property_rec.state or "").strip()

                    if city:
                        city_code = CITY_CODE_MAP.get(city)
                        if not city_code:
                            raise ValidationError(
                                "No sequence code mapped for city '%s'. "
                                "Please contact admin to add this city to CITY_CODE_MAP."
                                % city,
                            )

                    if state:
                        state_code = STATE_CODE_MAP.get(state)
                        if not state_code:
                            raise ValidationError(
                                "No sequence code mapped for state '%s'. "
                                "Please contact admin to add this state to STATE_CODE_MAP."
                                % state,
                            )

                if state_code and city_code:
                    vals["deal_id"] = self._get_next_deal_sequence(state_code, city_code)
                else:
                    vals["deal_id"] = (
                        self.env["ir.sequence"].sudo().next_by_code("deal") or "/"
                    )

        return super().create(vals_list)

    def _get_next_deal_sequence(self, state_code, city_code):
        """Get or create a per-state-city no-gap sequence and return next formatted number."""
        seq_code = f"deal.{state_code}.{city_code}"
        sequence = self.env["ir.sequence"].sudo().search(
            [("code", "=", seq_code)], limit=1,
        )
        if not sequence:
            starting_number = CITY_STARTING_NUMBER.get(city_code, 1)
            sequence = self.env["ir.sequence"].sudo().create(
                {
                    "name": f"Deal Sequence - {state_code} - {city_code}",
                    "code": seq_code,
                    "implementation": "no_gap",
                    "prefix": f"CD/{state_code}/{city_code}/",
                    "padding": 6,
                    "number_increment": 1,
                    "number_next": starting_number,
                    "company_id": False,
                },
            )
        return sequence.next_by_code(seq_code) or "/"

    def _recompute_gross_amount(self):
        for record in self:
            package_amount = record.package_amount or 0.0

            if record.is_offer and record.offer_id:
                if record.offer_id.waive_off_type == "fixed":
                    discount = record.offer_id.waive_off_value

                elif record.offer_id.waive_off_type == "percentage":
                    discount = package_amount * record.offer_id.waive_off_value / 100

                else:
                    discount = 0.0
            else:
                discount = 0.0

            record.gross_amount = package_amount - discount

    @api.onchange("package_id")
    def _onchange_package_id(self):
        if self.package_id:
            self.package_amount = self.package_id.amount
        else:
            self.package_amount = 0.0
        self._recompute_gross_amount()

    @api.onchange("is_offer")
    def _onchange_is_offer(self):
        if not self.is_offer:
            self.offer_id = False
            self._recompute_gross_amount()

    @api.onchange("offer_id")
    def _onchange_offer_id(self):
        self._recompute_gross_amount()

    def action_renew_deal(self):
        self.ensure_one()
        self.deal_status = "renewed"
        new_deal = self.create(
            {
                "property_id": self.property_id.id,
                "owner_id": self.owner_id.id,
                "bde_id": self.bde_id.id,
                "deal_type": "renewal",
                "deal_status": "registration",
                "package_id": self.package_id.id,
                "is_offer": self.is_offer,
                "offer_id": self.offer_id.id if self.is_offer else False,
                "gross_amount": self.gross_amount,
            },
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "deal",
            "res_id": new_deal.id,
            "view_mode": "form",
            "target": "current",
        }

    @api.constrains("is_offer", "offer_id")
    def _check_offer_consistency(self):
        for record in self:
            if record.is_offer and not record.offer_id:
                raise ValidationError("Please associate an active offer")
            if not record.is_offer and record.offer_id:
                raise ValidationError(
                    "Please select the is_offer checkbox if you want to associate an offer",
                )

    @api.constrains("deal_status", "closed_reason")
    def _check_closed_reason(self):
        for record in self:
            if record.deal_status == "closed" and not record.closed_reason:
                raise ValidationError(
                    "Please select a closed reason when the deal status is closed",
                )
            if record.deal_status != "closed" and record.closed_reason:
                raise ValidationError(
                    "Closed reason can only be set when deal status is closed",
                )

    @api.constrains("property_id", "deal_status")
    def _check_active_deal_per_property(self):
        for record in self:
            if record.deal_status in ["registration", "live"] and record.property_id:
                active_deals = self.search(
                    [
                        ("id", "!=", record.id),
                        ("property_id", "=", record.property_id.id),
                        ("deal_status", "in", ["registration", "live"]),
                    ],
                )
                if active_deals:
                    raise ValidationError(
                        "Only one active deal can be associated with a property at a time",
                    )

    def _get_transaction_total(self, transaction_type):
        self.ensure_one()

        return sum(
            transaction.gross_amount
            for transaction in self.transaction_ids
            if transaction.transaction_type == transaction_type
        )

    def write(self, vals):
        for record in self:
            if vals.get("deal_status") == "closed":
                vals["closed_at"] = fields.Datetime.now()

            if vals.get("deal_status") in ["live", "sold"]:
                registration_amount = record._get_transaction_total("registration")

                if record.is_full_payment and registration_amount < record.gross_amount:
                    raise ValidationError(
                        "Deal status cannot be changed to Live or Sold because full payment has already been received",
                    )
        return super().write(vals)

    def action_mark_service_expired(self):
        for record in self:
            record.write(
                {
                    "deal_status": "closed",
                    "closed_reason": "package_expired",
                },
            )
        return True

    def action_set_live(self):
        for record in self:
            record.deal_status = "live"
        return True

    def action_set_sold(self):
        for record in self:
            record.deal_status = "sold"
        return True

    def action_set_closed(self):
        for record in self:
            if not record.closed_reason:
                raise ValidationError(
                    "Please select a Closed Reason before closing the deal",
                )
            record.write(
                {
                    "deal_status": "closed",
                    "closed_reason": record.closed_reason,
                },
            )
        return True
