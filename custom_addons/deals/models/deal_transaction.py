from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .deal import CITY_CODE_MAP, STATE_CODE_MAP


class DealTransaction(models.Model):
    _name = "deal.transaction"
    _description = "Contain information related to transaction with deal"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "transaction_id"
    _rec_name = "transaction_id"

    transaction_id = fields.Char(
        string="Transaction ID",
        required=True,
        copy=False,
        readonly=True,
        index=True,
    )
    deal_id = fields.Many2one(
        "deal",
        string="Deal Id",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    invoice_id = fields.Char(string="Invoice ID")
    gross_amount = fields.Monetary(
        string="Gross Amount",
        required=True,
        tracking=True,
        currency_field="currency_id",
    )
    net_amount = fields.Monetary(
        string="Net Amount",
        compute="_compute_net_amount",
        store=True,
        readonly=True,
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: self.env.ref("base.INR"),
    )
    payment_channel = fields.Selection(
        [
            ("cash", "Cash"),
            ("cheque", "Cheque"),
            ("online", "Online"),
            ("bank_transfer", "Bank Transfer"),
        ],
        string="Payment Channel",
        required=True,
    )
    transaction_type = fields.Selection(
        [
            ("registration", "Registration"),
            ("sold", "Sold"),
            ("refund", "Refund"),
        ],
        string="Transaction Type",
        required=True,
    )
    transaction_time = fields.Datetime(
        string="Transaction Time",
        default=fields.Datetime.now,
    )
    deal_status = fields.Selection(
        related="deal_id.deal_status",
        string="Deal Status",
        store=False,
        readonly=True,
    )

    @api.depends("gross_amount")
    def _compute_net_amount(self):
        for record in self:
            record.net_amount = record.gross_amount / 1.18

    @api.onchange("deal_status", "deal_id")
    def _onchange_deal_status(self):
        if self.deal_status == "registration":
            self.transaction_type = "registration"
        elif self.deal_status == "sold":
            self.transaction_type = "sold"
        elif (
            self.deal_status == "closed"
            and self.deal_id.closed_reason == "deal_cancelled"
        ):
            self.transaction_type = "refund"
        else:
            self.transaction_type = False

    @api.constrains("transaction_type", "deal_id")
    def _check_transaction_type_deal_status(self):
        for record in self:
            if record.deal_id.deal_status in ["live", "renewed"]:
                raise ValidationError(
                    "Transactions are not allowed when deal status is Live or Renewed",
                )
            if (
                record.transaction_type == "registration"
                and record.deal_id.deal_status != "registration"
            ):
                raise ValidationError(
                    "Registration transactions can only be created when the deal is in registration status",
                )
            if (
                record.transaction_type == "sold"
                and record.deal_id.deal_status != "sold"
            ):
                raise ValidationError(
                    "Sold transactions can only be created when the deal is in sold status",
                )
            if record.transaction_type == "refund" and not (
                record.deal_id.deal_status == "closed"
                and record.deal_id.closed_reason == "deal_cancelled"
            ):
                raise ValidationError(
                    "Refund transactions can only be created when the deal is closed due to cancellation",
                )

    @api.constrains("gross_amount", "transaction_type")
    def _check_gross_amount_for_transaction_type(self):
        for record in self:
            if record.transaction_type == "refund" and record.gross_amount >= 0:
                raise ValidationError(
                    "Gross amount for refund transactions must be negative",
                )
            if (
                record.transaction_type in ["registration", "sold"]
                and record.gross_amount <= 0
            ):
                raise ValidationError(
                    "Gross amount for registration and sold transactions must be positive",
                )

    @api.constrains("gross_amount", "transaction_type", "deal_id")
    def _check_full_payment_registration_amount(self):
        for record in self:
            if (
                record.transaction_type == "registration"
                and record.deal_id.is_full_payment
            ):
                total_registration_amount = sum(
                    rec.gross_amount
                    for rec in record.deal_id.transaction_ids
                    if rec.transaction_type == "registration"
                )
                if total_registration_amount > record.deal_id.gross_amount:
                    raise ValidationError(
                        "Total registration amount cannot exceed the gross amount of the deal when full payment is selected",
                    )

    @api.constrains("transaction_type", "deal_id")
    def _check_full_payment_sold_transaction(self):
        for record in self:
            if record.transaction_type == "sold" and record.deal_id.is_full_payment:
                raise ValidationError(
                    "Sold transactions are not allowed when full payment is selected for the deal",
                )

    @api.constrains("deal_id", "gross_amount", "transaction_type")
    def _check_total_transaction_amount(self):
        for record in self:
            total_registration_and_sold = sum(
                rec.gross_amount
                for rec in record.deal_id.transaction_ids
                if rec.transaction_type in ["registration", "sold"]
            )
            if total_registration_and_sold > record.deal_id.gross_amount:
                raise ValidationError(
                    "Total amount of registration and sold transactions cannot exceed the gross amount of the deal",
                )

    @api.constrains("gross_amount", "transaction_type", "deal_id")
    def _check_refund_amount(self):
        for record in self:
            if record.transaction_type == "refund":
                total_received = sum(
                    rec.gross_amount
                    for rec in record.deal_id.transaction_ids
                    if rec.transaction_type in ["registration", "sold"]
                )

                total_refunded = sum(
                    abs(rec.gross_amount)
                    for rec in record.deal_id.transaction_ids
                    if rec.transaction_type == "refund"
                )

                if total_refunded > total_received:
                    raise ValidationError(
                        "Refund amount cannot exceed the total amount received from registration and sold transactions",
                    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("transaction_id") or vals.get("transaction_id") == "/":
                deal_id = vals.get("deal_id")
                if not deal_id:
                    raise ValidationError("Deal is required to generate Transaction ID")

                deal_rec = self.env["deal"].browse(deal_id)
                property_rec = deal_rec.property_id
                city = (property_rec.city or "").strip() if property_rec else ""
                state = (property_rec.state or "").strip() if property_rec else ""

                city_code = CITY_CODE_MAP.get(city)
                state_code = STATE_CODE_MAP.get(state)
                if city_code and state_code:
                    vals["transaction_id"] = self._get_next_transaction_sequence(
                        state_code,
                        city_code,
                    )
                else:
                    vals["transaction_id"] = (
                        self.env["ir.sequence"].sudo().next_by_code("deal.transaction")
                        or "/"
                    )

        return super().create(vals_list)

    def _get_financial_year(self):
        today = fields.Date.context_today(self)
        if today.month >= 4:
            start_yr = today.year
            end_yr = today.year + 1
        else:
            start_yr = today.year - 1
            end_yr = today.year
        return f"{str(start_yr)[-2:]}-{str(end_yr)[-2:]}"

    def _get_next_transaction_sequence(self, state_code, city_code):
        fy = self._get_financial_year()
        seq_code = f"transaction.{fy}.{state_code}.{city_code}"
        sequence = (
            self.env["ir.sequence"]
            .sudo()
            .search(
                [("code", "=", seq_code)],
                limit=1,
            )
        )
        if not sequence:
            sequence = (
                self.env["ir.sequence"]
                .sudo()
                .create(
                    {
                        "name": f"Transaction Sequence - {fy} - {state_code} - {city_code}",
                        "code": seq_code,
                        "implementation": "no_gap",
                        "prefix": f"{fy}/{state_code}/{city_code}/",
                        "padding": 4,
                        "number_increment": 1,
                        "number_next": 1,
                        "company_id": False,
                    },
                )
            )
        return sequence.next_by_code(seq_code) or "/"

    def write(self, vals):
        raise ValidationError("Transactions cannot be modified")

    def unlink(self):
        raise ValidationError("Transactions cannot be deleted")
