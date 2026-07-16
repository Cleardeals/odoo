import hmac
import json
import logging

from odoo import http
from odoo.http import Response, request

_logger = logging.getLogger(__name__)


class PortalWebhookController(http.Controller):
    @http.route(
        "/api/v1/magicbricks_webhook",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def handle_magicbricks_lead(self, **kwargs):
        """
        DEDICATED "Fast Lane" webhook for MagicBricks.
        It translates their payload to our 'leads.new' model.
        """

        # API KEY AUTHENTICATION
        try:
            # Get the key from the request header
            sent_key = request.httprequest.headers.get("X-API-KEY")

            # Get the correct key from Odoo's system parameters
            correct_key = (
                request.env["ir.config_parameter"]
                .sudo()
                .get_param("magicbricks.api.key")
            )

            # Compare the keys
            if not sent_key or not correct_key or sent_key != correct_key:
                _logger.warning("MagicBricks Webook: Failed auth, invalid API key.")
                return Response(
                    "Failed to Push Lead: Invalid API Key",
                    status=401,
                    mimetype="text/plain",
                )

        except Exception as auth_err:
            _logger.error("MagicBricks Webhook: Auth check failed: %s", auth_err)
            return Response(
                "Failed to Push Lead: Internal Server Error",
                status=500,
                mimetype="text/plain",
            )

        data = json.loads(request.httprequest.data)

        try:
            # Validation
            required_fields = ["name", "mobile", "email", "property_id"]
            missing = [field for field in required_fields if not data.get(field)]

            if missing:
                _logger.warning(
                    "MagicBricks webhook rejected: Missing required Fields: %s. Data: %s",
                    missing,
                    data,
                )
                return Response(
                    "Failed to push lead: Missing required fields.",
                    status=400,
                )

            # 2. Translate MagicBricks fields to our leads.new fields
            lead_model = request.env["leads.new"].sudo().with_context(
                automated_lead_creation=True,
            )
            source = lead_model._get_or_create_source("MagicBricks", source_type="portal")

            lead_vals = {
                "name": data.get("name"),
                "phone": data.get("mobile"),
                "email": data.get("email"),
                "project_name": data.get("project"),
                "source_id": source.id,
                "portal_property_id": data.get("property_id"),
                "raw_data": json.dumps(data, indent=2),
                "state": "new",
            }

            # 3. Create the basic lead record
            new_lead = lead_model.create_lead_if_not_duplicate(lead_vals)

            # 4. Process the lead synchronously (removed queue_job dependency)
            if new_lead:
                try:
                    new_lead._process_lead_logic()
                    _logger.info(
                        f"MagicBricks Lead processed successfully: {new_lead.name}",
                    )
                except Exception as process_err:
                    _logger.error(
                        f"Failed to process MagicBricks lead {new_lead.name}: {process_err}",
                    )
                    # Lead is created but processing failed - can be retried later

            # 5. send success response
            return Response(
                "Success: Lead punched in the CRM",
                status=200,
                mimetype="text/plain",
            )

        except Exception as e:
            _logger.error("MagicBricks Webhook Exception: %s. Raw data: %s", e, data)
            return Response(
                f"Failed to Push Lead: {e!s}",
                status=500,
                mimetype="text/plain",
            )

    @http.route(
        "/api/v1/99acres_webhook",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def handle_99acres_lead(self, **kwargs):
        """
        DEDICATED "Fast Lane" webhook for 99acres.
        It translates their payload to our 'leads.new' model.
        """

        # API KEY AUTHENTICATION
        try:
            # Get the key from the request header
            sent_key = request.httprequest.headers.get("X-API-KEY")

            # Get the correct key from Odoo's system parameters
            correct_key = (
                request.env["ir.config_parameter"]
                .sudo()
                .get_param("99acres.webhook.api.key")
            )

            # Compare the keys
            if not sent_key or not correct_key or sent_key != correct_key:
                _logger.warning("99acres Webook: Failed auth, invalid API key.")
                return Response(
                    "Failed to Push Lead: Invalid API Key",
                    status=401,
                    mimetype="text/plain",
                )

        except Exception as auth_err:
            _logger.error("99acres Webhook: Auth check failed: %s", auth_err)
            return Response(
                "Failed to Push Lead: Internal Server Error",
                status=500,
                mimetype="text/plain",
            )

        data = json.loads(request.httprequest.data)

        try:
            # Validation
            required_fields = ["Name", "Phone", "ProdId"]
            missing = [field for field in required_fields if not data.get(field)]

            if missing:
                _logger.warning(
                    "99acres webhook rejected: Missing required Fields: %s. Data: %s",
                    missing,
                    data,
                )
                return Response(
                    "Failed to push lead: Missing required fields.",
                    status=400,
                )

            # 2. Translate 99acres fields to our leads.new fields
            lead_model = request.env["leads.new"].sudo().with_context(
                automated_lead_creation=True,
            )
            source = lead_model._get_or_create_source("99acres", source_type="portal")

            lead_vals = {
                "name": data.get("Name"),
                "phone": data.get("Phone"),
                "email": data.get("EmailId"),
                "project_name": data.get("Project"),
                "source_id": source.id,
                "portal_property_id": data.get("ProdId"),
                "raw_data": json.dumps(data, indent=2),
                "state": "new",
            }

            # 3. Create the basic lead record
            new_lead = lead_model.create_lead_if_not_duplicate(lead_vals)

            # 4. Process the lead synchronously (removed queue_job dependency)
            if new_lead:
                try:
                    new_lead._process_lead_logic()
                    _logger.info(
                        f"99acres Lead processed successfully: {new_lead.name}",
                    )
                except Exception as process_err:
                    _logger.error(
                        f"Failed to process 99acres lead {new_lead.name}: {process_err}",
                    )
                    # Lead is created but processing failed - can be retried later

            return Response(
                "Success: Lead punched in the CRM",
                status=200,
                mimetype="text/plain",
            )

        except Exception as e:
            _logger.error("99acres Webhook Exception: %s. Raw data: %s", e, data)
            return Response(
                f"Failed to Push Lead: {e!s}",
                status=500,
                mimetype="text/plain",
            )

    @http.route(
        "/api/v1/cleardeals_lead",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def handle_cleardeals_lead(self, **kwargs):
        """
        DEDICATED webhook for first-party leads from the Cleardeals website and
        mobile app. The payload carries our own property short-code (property_id),
        which maps directly to property.base.prop_id — no portal-listing lookup.
        """

        # API KEY AUTHENTICATION
        try:
            sent_key = request.httprequest.headers.get("X-API-KEY")
            correct_key = (
                request.env["ir.config_parameter"]
                .sudo()
                .get_param("cleardeals.lead.api.key")
            )

            if not sent_key or not correct_key or sent_key != correct_key:
                _logger.warning("Cleardeals Lead Webhook: Failed auth, invalid API key.")
                return Response(
                    "Failed to Push Lead: Invalid API Key",
                    status=401,
                    mimetype="text/plain",
                )

        except Exception as auth_err:
            _logger.error("Cleardeals Lead Webhook: Auth check failed: %s", auth_err)
            return Response(
                "Failed to Push Lead: Internal Server Error",
                status=500,
                mimetype="text/plain",
            )

        data = json.loads(request.httprequest.data)

        try:
            # Validation
            required_fields = ["name", "phone", "property_id"]
            missing = [field for field in required_fields if not data.get(field)]

            if missing:
                _logger.warning(
                    "Cleardeals Lead webhook rejected: Missing required Fields: %s. Data: %s",
                    missing,
                    data,
                )
                return Response(
                    "Failed to push lead: Missing required fields.",
                    status=400,
                )

            # Translate website fields to our leads.new fields
            lead_model = request.env["leads.new"].sudo().with_context(
                automated_lead_creation=True,
            )
            # Bifurcate the source by where the lead originated.
            #   inquiry_source == "mobile_app" -> Cleardeals app
            #   anything else / missing        -> Cleardeals website
            # Both sources share portal_code "Cleardeals" so deduplication treats
            # a website lead and an app lead as the same lead (see
            # leads.new._compute_duplicate_domain).
            inquiry_source = (data.get("inquiry_source") or "").strip().lower()
            source_name = "App Inquiry" if inquiry_source == "mobile_app" else "Website Inquiry"
            source = lead_model._get_or_create_source(
                source_name,
                source_type="portal",
            )

            prop_code = (data.get("property_id") or "").strip()

            # Resolve the property up front so the duplicate check uses the
            # phone + property_base_id criteria (same as matched portal leads).
            property_rec = lead_model._resolve_property_by_prop_id(prop_code)

            inquiry_type = data.get("inquiry_type")
            if inquiry_type not in ("primary", "recommended"):
                inquiry_type = "primary"

            lead_vals = {
                "name": data.get("name"),
                "phone": data.get("phone"),
                "email": data.get("email"),
                "remarks": data.get("message"),
                "inquiry_type": inquiry_type,
                "source_id": source.id,
                "portal_property_id": prop_code,
                "raw_data": json.dumps(data, indent=2),
                "state": "new",
            }
            if property_rec:
                lead_vals["property_base_id"] = property_rec.id

            # Create the basic lead record (dedup-aware)
            new_lead = lead_model.create_lead_if_not_duplicate(lead_vals)

            # Process the lead synchronously
            if new_lead:
                try:
                    new_lead._process_website_lead()
                    _logger.info(
                        f"Cleardeals Lead processed successfully: {new_lead.name}",
                    )
                except Exception as process_err:
                    _logger.error(
                        f"Failed to process Cleardeals lead {new_lead.name}: {process_err}",
                    )
                    # Lead is created but processing failed - can be retried later

            return Response(
                "Success: Lead punched in the CRM",
                status=200,
                mimetype="text/plain",
            )

        except Exception as e:
            _logger.error("Cleardeals Lead Webhook Exception: %s. Raw data: %s", e, data)
            return Response(
                f"Failed to Push Lead: {e!s}",
                status=500,
                mimetype="text/plain",
            )

    @http.route(
        "/api/v1/squareyards_webhook",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def handle_squareyards_lead(self, **kwargs):
        """
        DEDICATED "Fast Lane" webhook for Square Yards.
        It translates their payload to our 'leads.new' model.

        Square Yards pushes two kinds of leads:
          * WhatsApp-button leads  -> only `mobile` + `propertyId` (no name/email)
          * Standard form leads    -> name, mobile, email, propertyId

        So only `mobile` and `propertyId` are required; `name` falls back to a
        generic label when absent. `propertyId` is the single join key used to
        match the property (the "Unique PID" is intentionally ignored).

        Auth uses a constant-time comparison (hmac.compare_digest) against the
        'squareyards.webhook.api.key' system parameter. Square Yards sends the
        secret in the literal 'apikey' header; 'X-API-KEY' is accepted as a
        fallback for parity with the older portal webhooks.
        """

        # 1. API KEY AUTHENTICATION (constant-time)
        try:
            correct_key = (
                request.env["ir.config_parameter"]
                .sudo()
                .get_param("squareyards.webhook.api.key")
            )

            # Unset server key -> integration not configured yet. 503 tells the
            # caller to retry later rather than treating it as a bad credential.
            if not correct_key:
                _logger.error(
                    "SquareYards Webhook: 'squareyards.webhook.api.key' is not "
                    "configured. Rejecting until a manager sets it.",
                )
                return Response(
                    "Failed to Push Lead: Integration not configured.",
                    status=503,
                    mimetype="text/plain",
                )

            sent_key = (
                request.httprequest.headers.get("apikey")
                or request.httprequest.headers.get("X-API-KEY")
                or ""
            )

            if not hmac.compare_digest(sent_key, correct_key):
                _logger.warning("SquareYards Webhook: Failed auth, invalid API key.")
                return Response(
                    "Failed to Push Lead: Invalid API Key",
                    status=401,
                    mimetype="text/plain",
                )

        except Exception as auth_err:
            _logger.error("SquareYards Webhook: Auth check failed: %s", auth_err)
            return Response(
                "Failed to Push Lead: Internal Server Error",
                status=500,
                mimetype="text/plain",
            )

        # 2. PARSE BODY (malformed JSON -> 400, not 500)
        try:
            data = json.loads(request.httprequest.data or b"{}")
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object.")
        except (ValueError, TypeError) as parse_err:
            _logger.warning(
                "SquareYards Webhook: malformed JSON body: %s", parse_err,
            )
            return Response(
                "Failed to push lead: Malformed JSON body.",
                status=400,
                mimetype="text/plain",
            )

        try:
            # 3. VALIDATION — only mobile + propertyId are guaranteed across both
            #    Square Yards lead flows (WhatsApp-button leads carry no name).
            required_fields = ["mobile", "propertyId"]
            missing = [field for field in required_fields if not data.get(field)]

            if missing:
                _logger.warning(
                    "SquareYards webhook rejected: Missing required Fields: %s. Data: %s",
                    missing,
                    data,
                )
                return Response(
                    "Failed to push lead: Missing required fields.",
                    status=400,
                    mimetype="text/plain",
                )

            # 4. Translate Square Yards fields to our leads.new fields.
            #    - name falls back to a generic label (WhatsApp leads have none),
            #      since leads.new.name is required on the model.
            #    - phone / propertyId are cast to str so an integer in the payload
            #      cannot break phone standardisation or the Char write.
            lead_model = request.env["leads.new"].sudo().with_context(
                automated_lead_creation=True,
            )
            source = lead_model._get_or_create_source(
                "SquareYards", source_type="portal",
            )

            lead_vals = {
                "name": data.get("name") or "SquareYards Lead",
                "phone": str(data.get("mobile") or ""),
                "email": data.get("email"),
                "project_name": data.get("projectName"),
                "source_id": source.id,
                "portal_property_id": str(data.get("propertyId") or ""),
                "raw_data": json.dumps(data, indent=2),
                "state": "new",
            }

            # 5. Create the lead (deduplicated) and process it synchronously.
            new_lead = lead_model.create_lead_if_not_duplicate(lead_vals)

            if new_lead:
                try:
                    new_lead._process_lead_logic()
                    _logger.info(
                        "SquareYards Lead processed successfully: %s",
                        new_lead.name,
                    )
                except Exception as process_err:
                    _logger.error(
                        "Failed to process SquareYards lead %s: %s",
                        new_lead.name,
                        process_err,
                    )
                    # Lead is created but processing failed - can be retried later.
            else:
                # Duplicate within the suppression window: acknowledged, not an error.
                _logger.info(
                    "SquareYards Webhook: duplicate lead skipped "
                    "(phone: %s, propertyId: %s).",
                    data.get("mobile"),
                    data.get("propertyId"),
                )

            # 6. Success response (covers both new and de-duplicated leads).
            return Response(
                "Success: Lead punched in the CRM",
                status=200,
                mimetype="text/plain",
            )

        except Exception as e:
            _logger.error("SquareYards Webhook Exception: %s. Raw data: %s", e, data)
            return Response(
                f"Failed to Push Lead: {e!s}",
                status=500,
                mimetype="text/plain",
            )
