"""Thin Interakt REST helper used by Odoo for the **templates GET only**.

Odoo holds the Interakt API key (system params) and fetches the approved
template catalogue on demand when an RM opens the Send-Template picker.  All
*write* actions to Interakt (sends, chat assignment) still go through the
wa-platform services — only the read-only template listing is done here.

System parameters:
  wa_communication.interakt_api_key   — Basic-auth key (Interakt > Developer Settings)
  wa_communication.interakt_base_url  — default https://api.interakt.ai
"""

import json
import logging
import re

import requests

from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = 'https://api.interakt.ai'
_TEMPLATES_PATH = '/v1/public/track/organization/templates'
_TIMEOUT = 20
_MAX_PAGES = 20          # safety cap on pagination
_PLACEHOLDER_RE = re.compile(r'{{\s*(\d+)\s*}}')


def _get_credentials(env):
    """Read (api_key, base_url) from system params; raise if key missing."""
    icp = env['ir.config_parameter'].sudo()
    api_key = (icp.get_param('wa_communication.interakt_api_key') or '').strip()
    base_url = (icp.get_param('wa_communication.interakt_base_url')
                or _DEFAULT_BASE_URL).strip().rstrip('/')
    if not api_key:
        raise UserError(
            "WhatsApp templates can't be loaded: the Interakt API key is not "
            "configured. Set 'wa_communication.interakt_api_key' in Settings → "
            "Technical → System Parameters."
        )
    return api_key, base_url


def _parse_buttons(raw):
    """Interakt returns ``buttons`` as a (sometimes double-encoded) JSON string.

    Examples seen: ``"\\"{}\\""`` (empty), or a JSON list/obj of button defs.
    Returns a list of button label strings (best-effort, never raises).
    """
    if not raw:
        return []
    val = raw
    # Unwrap up to two layers of JSON-string encoding.
    for _ in range(2):
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except (ValueError, TypeError):
                break
        else:
            break
    labels = []
    if isinstance(val, list):
        for b in val:
            if isinstance(b, dict) and b.get('text'):
                labels.append(b['text'])
            elif isinstance(b, str) and b:
                labels.append(b)
    elif isinstance(val, dict):
        # Some payloads key buttons by index/type.
        for b in val.values():
            if isinstance(b, dict) and b.get('text'):
                labels.append(b['text'])
    return labels


def _extract_variables(header, body):
    """Return ordered variable slots from {{N}} placeholders in header + body."""
    slots = []
    for scope, text in (('header', header or ''), ('body', body or '')):
        positions = sorted({int(m) for m in _PLACEHOLDER_RE.findall(text)})
        for pos in positions:
            slots.append({
                'scope': scope,
                'position': pos,
                'label': '%s variable %d' % (scope.capitalize(), pos),
            })
    return slots


def _normalize_template(t):
    """Map one raw Interakt template dict to the picker's shape."""
    header = t.get('header') or ''
    body = t.get('body') or ''
    return {
        'name': t.get('name'),
        'display_name': t.get('display_name') or t.get('name'),
        'language': t.get('language') or 'en',
        'category': t.get('category') or '',
        'header_format': t.get('header_format'),
        'header': header,
        'body': body,
        'footer': t.get('footer') or '',
        'buttons': _parse_buttons(t.get('buttons')),
        'approval_status': t.get('approval_status'),
        'variables': _extract_variables(header, body),
    }


def fetch_templates(env, template_name=None):
    """Fetch APPROVED templates from Interakt, normalized for the picker.

    Paginates on ``has_next`` / ``offset``. Raises ``UserError`` on missing key
    or HTTP/transport failure so the RM sees a clear toast.
    """
    api_key, base_url = _get_credentials(env)
    url = base_url + _TEMPLATES_PATH
    headers = {
        'Authorization': 'Basic %s' % api_key,
        'Content-Type': 'application/json',
    }
    results = []
    offset = 0
    for _page in range(_MAX_PAGES):
        params = {
            'offset': offset,
            'autosubmitted_for': 'all',
            'approval_status': 'APPROVED',
            'language': 'all',
        }
        if template_name:
            params['template_name'] = template_name
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            _logger.warning("Interakt templates fetch failed: %s", exc)
            raise UserError("Could not reach Interakt to load templates: %s" % exc)
        if resp.status_code == 401:
            raise UserError("Interakt rejected the API key (401). Check the "
                            "'wa_communication.interakt_api_key' system parameter.")
        if resp.status_code >= 400:
            raise UserError("Interakt returned %s while loading templates: %s"
                            % (resp.status_code, resp.text[:200]))
        try:
            data = resp.json()
        except ValueError:
            raise UserError("Interakt returned a non-JSON template response.")
        payload = data.get('results') or {}
        batch = payload.get('templates') or []
        for t in batch:
            if t.get('name'):
                results.append(_normalize_template(t))
        if not data.get('has_next'):
            break
        offset += len(batch) or 1
    return results
