import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module : leads
# Model  : lead.olx.account
# Purpose: Stores OLX dealer login credentials and polling state.
#          Passwords are never written to the DB — they are kept in
#          ir.config_parameter under the key olx.account.<login>.password.
# Owner  : Cleardeals Tech
# ---------------------------------------------------------------------------

_CONFIG_PREFIX = "olx.account."
_CONFIG_SUFFIX = ".password"

# Number of consecutive API failures before an account is auto-disabled.
# Reset to 0 by any successful poll. Raise this value with caution —
# a higher threshold delays detection of permanently broken credentials.
_CONSECUTIVE_FAILURE_THRESHOLD = 5


class LeadOlxAccount(models.Model):
    _name = "lead.olx.account"
    _description = "OLX Dealer Account"
    _order = "sequence, id"

    _login_uniq = models.Constraint(
        "UNIQUE(login)",
        message="An OLX account with this phone number already exists.",
    )

    name = fields.Char(
        string="Label",
        required=True,
        index=True,
        help="Human-readable name, e.g. 'Khushi – 8160745862'",
    )
    login = fields.Char(
        string="Phone (Login)",
        required=True,
        index=True,
        help="OLX phone number used as login credential.",
    )
    # password is never stored as a DB column.
    # Writes go to ir.config_parameter; reads always return False.
    password = fields.Char(
        string="Password",
        store=False,
        compute="_compute_password",
        inverse="_inverse_password",
        help="Write-only. Stored securely in system parameters.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True, index=True)

    last_fetch_at = fields.Datetime(
        string="Last Fetched At",
        readonly=True,
        copy=False,
        help="Timestamp of the most recent successful OLX API poll.",
    )
    consecutive_failures = fields.Integer(
        string="Consecutive Failures",
        default=0,
        readonly=True,
        copy=False,
    )
    last_error = fields.Text(
        string="Last Error",
        readonly=True,
        copy=False,
    )
    process_notes = fields.Text(
        string="Audit Notes",
        readonly=True,
        copy=False,
        help="Auto-populated record of auto-disable events and manual interventions.",
    )

    # ------------------------------------------------------------------
    # Password: write-only via ir.config_parameter
    # ------------------------------------------------------------------

    @api.depends("login")
    def _compute_password(self):
        """Always return False — password is write-only in the UI."""
        for rec in self:
            rec.password = False

    def _inverse_password(self):
        """Persist the password in ir.config_parameter, never in the DB column."""
        config = self.env["ir.config_parameter"].sudo()
        for rec in self:
            if not rec.login:
                continue
            key = _CONFIG_PREFIX + rec.login + _CONFIG_SUFFIX
            if rec.password:
                config.set_param(key, rec.password)
                _logger.info(
                    "OLX account '%s': password updated in system parameters.",
                    rec.login,
                )

    @api.model
    def _get_olx_password(self, login):
        """Retrieve the stored password for a given login. Returns empty string if not set."""
        key = _CONFIG_PREFIX + login + _CONFIG_SUFFIX
        return self.env["ir.config_parameter"].sudo().get_param(key, default="")

    # ------------------------------------------------------------------
    # Failure tracking
    # ------------------------------------------------------------------

    def _record_success(self):
        """Call after a successful API poll. Updates fetch timestamp, resets failure state."""
        self.ensure_one()
        self.sudo().write(
            {
                "last_fetch_at": fields.Datetime.now(),
                "consecutive_failures": 0,
                "last_error": False,
            }
        )

    def _record_failure(self, error_msg):
        """Call after a failed API poll. Increments failure counter; auto-disables at 5."""
        self.ensure_one()
        new_count = self.consecutive_failures + 1
        vals = {
            "consecutive_failures": new_count,
            "last_error": str(error_msg)[:2048],  # Guard against very long stack traces
        }
        if new_count >= _CONSECUTIVE_FAILURE_THRESHOLD:
            timestamp = fields.Datetime.now()
            note = (
                f"[{timestamp}] Auto-disabled after {new_count} consecutive failures. "
                f"Last error: {str(error_msg)[:500]}\n"
            )
            vals["active"] = False
            vals["process_notes"] = (self.process_notes or "") + note
            _logger.warning(
                "OLX account '%s' (login: %s) auto-disabled after %d consecutive failures.",
                self.name,
                self.login,
                new_count,
            )
        self.sudo().write(vals)

    # ------------------------------------------------------------------
    # Rotation helper
    # ------------------------------------------------------------------

    @api.model
    def _get_next_account(self):
        """
        Return the single active account that should be processed next.

        Selection: active=True, ordered by last_fetch_at ASC NULLS FIRST,
        then sequence ASC. This distributes all accounts evenly over time.
        """
        return self.search(
            [("active", "=", True)],
            order="last_fetch_at ASC NULLS FIRST, sequence ASC, id ASC",
            limit=1,
        )
