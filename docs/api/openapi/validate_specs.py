#!/usr/bin/env python3
"""
Validate every OpenAPI document in this directory.

Two layers of checking:

1. **Schema validity** — each file is a well-formed OpenAPI 3.1 document, via
   ``openapi-spec-validator``. This catches broken ``$ref`` targets, misplaced
   keywords and structurally invalid schemas.

2. **Drift against the code** — every ``@http.route`` in ``custom_addons`` is
   documented in exactly one spec, and every documented path still exists in
   the code. This is the check that actually matters: a spec that passes layer
   one but describes endpoints that were deleted six months ago is worse than
   no spec at all.

Usage::

    make openapi-validate

That target also runs Redocly, which enforces the OpenAPI structure more
strictly than this script does, and manages the venv these dependencies live in.
To run this script alone::

    pip install pyyaml openapi-spec-validator
    python docs/api/openapi/validate_specs.py

Every stage runs; all problems found are printed, grouped by stage. Exits
non-zero if any stage failed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
    from openapi_spec_validator import validate as validate_openapi
except ImportError:  # pragma: no cover - dependency guidance, not logic
    sys.exit(
        "Missing dependencies. Install them with:\n"
        "    pip install pyyaml openapi-spec-validator"
    )

SPEC_DIR = Path(__file__).resolve().parent
REPO_ROOT = SPEC_DIR.parents[2]
ADDONS_DIR = REPO_ROOT / "custom_addons"

# Odoo route converters -> the OpenAPI path-template equivalent.
# "/web/leads/property_activity/<int:property_id>" -> ".../{property_id}"
_CONVERTER_RE = re.compile(r"<(?:\w+:)?(\w+)>")

# Matches the path string on the line following an @http.route decorator.
_ROUTE_RE = re.compile(
    r"@(?:http\.)?route\(\s*\n?\s*[\"']([^\"']+)[\"']",
    re.MULTILINE,
)

HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "patch", "head", "options", "trace"}
)

# Paths that are intentionally not documented, with the reason why.
# Keep this list empty unless there is a real justification — an undocumented
# endpoint is exactly what the OpenAPI work exists to prevent.
EXEMPT_PATHS: dict[str, str] = {}


def odoo_path_to_openapi(path: str) -> str:
    """Convert an Odoo route pattern into an OpenAPI path template."""
    return _CONVERTER_RE.sub(r"{\1}", path)


def routes_in_code() -> dict[str, str]:
    """Return ``{openapi_path: source_location}`` for every route in custom_addons."""
    found: dict[str, str] = {}
    for py_file in sorted(ADDONS_DIR.rglob("*.py")):
        source = py_file.read_text(encoding="utf-8")
        for match in _ROUTE_RE.finditer(source):
            raw_path = match.group(1)
            # The auth helper's docstring shows a placeholder route as an
            # example; it is documentation, not a real endpoint.
            if raw_path.endswith("..."):
                continue
            line_no = source.count("\n", 0, match.start()) + 1
            rel = py_file.relative_to(REPO_ROOT)
            found[odoo_path_to_openapi(raw_path)] = f"{rel}:{line_no}"
    return found


def load_specs() -> dict[Path, dict]:
    """Parse every YAML spec in this directory."""
    specs: dict[Path, dict] = {}
    for spec_file in sorted(SPEC_DIR.glob("*.yaml")):
        specs[spec_file] = yaml.safe_load(spec_file.read_text(encoding="utf-8"))
    return specs


def check_schema_validity(specs: dict[Path, dict]) -> list[str]:
    problems = []
    for spec_file, document in specs.items():
        try:
            validate_openapi(document)
        except Exception as exc:  # noqa: BLE001 - report whatever the validator raised
            problems.append(f"{spec_file.name}: {exc}")
    return problems


def check_coverage(specs: dict[Path, dict], code_routes: dict[str, str]) -> list[str]:
    """Every code route documented once; every documented path real."""
    problems = []

    documented: dict[str, list[str]] = {}
    for spec_file, document in specs.items():
        for path in (document.get("paths") or {}):
            documented.setdefault(path, []).append(spec_file.name)

    for path, location in sorted(code_routes.items()):
        if path in EXEMPT_PATHS:
            continue
        if path not in documented:
            problems.append(
                f"UNDOCUMENTED: {path} exists at {location} but is in no spec."
            )
        elif len(documented[path]) > 1:
            files = ", ".join(sorted(documented[path]))
            problems.append(
                f"DUPLICATED: {path} is documented in more than one spec ({files})."
            )

    for path, spec_files in sorted(documented.items()):
        if path not in code_routes:
            problems.append(
                f"STALE: {path} is documented in {spec_files[0]} "
                "but no route in custom_addons serves it."
            )

    return problems


def check_methods(specs: dict[Path, dict]) -> list[str]:
    """Every documented operation declares a security scheme and an operationId."""
    problems = []
    seen_ids: dict[str, str] = {}

    for spec_file, document in specs.items():
        has_global_security = "security" in document
        for path, path_item in (document.get("paths") or {}).items():
            for method, operation in path_item.items():
                if method not in HTTP_METHODS:
                    continue
                where = f"{spec_file.name} {method.upper()} {path}"

                op_id = operation.get("operationId")
                if not op_id:
                    problems.append(f"{where}: missing operationId.")
                elif op_id in seen_ids:
                    problems.append(
                        f"{where}: operationId '{op_id}' already used by {seen_ids[op_id]}."
                    )
                else:
                    seen_ids[op_id] = where

                if not has_global_security and "security" not in operation:
                    problems.append(f"{where}: no security requirement declared.")

    return problems


def main() -> int:
    specs = load_specs()
    if not specs:
        print(f"No specs found in {SPEC_DIR}")
        return 1

    print(f"Checking {len(specs)} spec(s) in {SPEC_DIR.relative_to(REPO_ROOT)}\n")

    stages = (
        ("OpenAPI 3.1 schema validity", lambda: check_schema_validity(specs)),
        ("Operation hygiene", lambda: check_methods(specs)),
        ("Coverage against custom_addons routes", lambda: check_coverage(specs, routes_in_code())),
    )

    failed = False
    for label, run in stages:
        problems = run()
        if problems:
            failed = True
            print(f"FAIL  {label}")
            for problem in problems:
                print(f"        {problem}")
        else:
            print(f"ok    {label}")

    if failed:
        print("\nValidation failed.")
        return 1

    # Several routes share a path and differ only by method (GET and PUT on
    # /api/v1/properties, for example), so paths and operations are not the
    # same number. Report both rather than conflating them.
    path_count = len(routes_in_code())
    operation_count = sum(
        1
        for document in specs.values()
        for path_item in (document.get("paths") or {}).values()
        for method in path_item
        if method in HTTP_METHODS
    )
    print(
        f"\nAll specs valid. {path_count} path(s), "
        f"{operation_count} operation(s) documented."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
