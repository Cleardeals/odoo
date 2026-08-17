"""Generate the curated Cleardeals Odoo ER diagram.

Reads the introspected schema (schema.json, produced from the throwaway Odoo 19
database) and emits ONE layout model rendered two ways:

  * cleardeals-odoo-erd.drawio  — editable mxGraph XML (draw.io / diagrams.net)
  * cleardeals-odoo-erd.svg     — the same layout, rendered directly

Only relationships that actually exist as PostgreSQL foreign keys are drawn, so
the diagram cannot drift from the database. Odoo audit columns
(create_uid/write_uid/create_date/write_date) are omitted throughout.
"""

import html
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("ERD_OUT", HERE)

schema = json.load(open(os.path.join(HERE, "schema.json")))
COLS = schema["columns"]
FKS = schema["fks"]

# ── Palette (module → header fill, border, band tint) ────────────────────────
PALETTE = {
    "core":       ("#5B6770", "#3D454C", "#EEF0F2", "Odoo core"),
    "properties": ("#1F6FB2", "#154E7D", "#E8F1F9", "properties"),
    "leads_cfg":  ("#2E7D52", "#1F5738", "#E9F4EE", "leads — configuration"),
    "leads":      ("#2E7D52", "#1F5738", "#E9F4EE", "leads — core"),
    "visits":     ("#B26B00", "#7D4B00", "#FBF1E3", "leads — site visits"),
    "legacy":     ("#8A8A8A", "#5E5E5E", "#F2F2F2", "legacy / superseded"),
    "wa":         ("#128C7E", "#0B6157", "#E6F4F2", "wa_communication"),
    "notif":      ("#6A4C93", "#4A3567", "#F0EBF6", "cleardeals_notification"),
}

# ── Which tables appear, in which band, and which columns to surface ─────────
# Business columns worth showing; every FK column is added automatically.
ENTITIES = [
    # (table, band, [business columns], note)
    ("res_company",       "core",       ["name"], None),
    ("res_partner",       "core",       ["name", "email", "phone"], None),
    ("res_users",         "core",       ["login", "active"], "RM / manager"),

    ("property_base",     "properties", ["name", "prop_id", "city", "is_active"], "inventory master"),
    ("property_portal_listing", "properties", ["portal_name", "portal_listing_id"], None),
    ("property_inventory", "legacy",    ["name"], "lead_suggestor (archived)"),

    ("lead_source_category", "leads_cfg", ["name", "code", "source_type"], None),
    ("lead_source",       "leads_cfg",  ["name", "portal_code", "source_type"], None),
    ("leads_bde",         "leads_cfg",  ["name"], "business dev exec"),

    ("leads_new",         "leads",      ["name", "phone", "current_status",
                                         "inquiry_type", "state"], "the enquiry"),
    ("lead_property_interest", "leads", ["interest_level"], None),
    ("lead_reassignment_log", "leads",  ["reassigned_on"], "batch audit"),

    ("lead_site_visit",   "visits",     ["scheduled_date", "phone_type"], None),
    ("lead_site_visit_status", "visits", ["name", "code", "active"], None),
    ("lead_site_visit_feedback_option", "visits", ["name"], None),

    ("lead_score",        "legacy",     ["lead_name", "score"], "pre-leads_new"),
    ("whatsapp_response", "legacy",     ["response"], None),

    ("wa_conversation",   "wa",         ["phone_number", "state", "window_state",
                                         "unread_count"], "one per phone"),
    ("wa_conversation_segment", "wa",   ["started_at", "ended_at"], "attribution"),
    ("wa_message",        "wa",         ["direction", "kind", "status",
                                         "occurred_at"], "append-only"),
    ("wa_workflow",       "wa",         ["name", "slug", "active"], None),
    ("wa_enrollment",     "wa",         ["state"], None),
    ("wa_reassignment_request", "wa",   ["state"], "chat handover"),
    ("wa_quick_reply",    "wa",         ["title", "is_shared"], None),

    ("cleardeals_notification", "notif", ["notif_type", "title", "is_read"], None),
]

# Many-to-many link tables, drawn smaller.
LINK_TABLES = [
    ("leads_new_property_base_rel", "leads"),
    ("leads_bde_allowed_rm_rel", "leads_cfg"),
]

SHOWN = {t for t, *_ in ENTITIES} | {t for t, _ in LINK_TABLES}

# ── Column layout ───────────────────────────────────────────────────────────
by_table = {}
for c in COLS:
    by_table.setdefault(c["table_name"], []).append(c)

fk_by_table = {}
for f in FKS:
    fk_by_table.setdefault(f["src_table"], []).append(f)

AUDIT = {"create_uid", "write_uid", "create_date", "write_date"}


def short_type(t):
    return {
        "character varying": "varchar", "timestamp without time zone": "timestamp",
        "double precision": "float", "integer": "int", "boolean": "bool",
        "text": "text", "numeric": "numeric", "date": "date", "jsonb": "jsonb",
        "bytea": "bytea",
    }.get(t, t)


def build_rows(table, business):
    """Return [(name, type, kind)] where kind is pk | fk | plain."""
    cols = {c["column_name"]: c for c in by_table.get(table, [])}
    fks = {f["src_col"]: f for f in fk_by_table.get(table, [])}
    rows, seen = [], set()

    if "id" in cols:
        rows.append(("id", short_type(cols["id"]["data_type"]), "pk"))
        seen.add("id")
    for name in sorted(fks):
        if name in cols and name not in seen and name not in AUDIT:
            rows.append((name, short_type(cols[name]["data_type"]), "fk"))
            seen.add(name)
    for name in business:
        if name in cols and name not in seen:
            rows.append((name, short_type(cols[name]["data_type"]), "plain"))
            seen.add(name)

    hidden = len([c for c in cols if c not in seen and c not in AUDIT])
    return rows, hidden


# ── Geometry ────────────────────────────────────────────────────────────────
BAND_X = {
    "core": 40, "properties": 400, "legacy": 400,
    "leads_cfg": 780, "leads": 1160, "visits": 1540,
    "wa": 1960, "notif": 2360,
}
W, ROW_H, HEAD_H, GAP = 300, 19, 30, 34

boxes = {}


def place():
    # Cursor is keyed by COLUMN (x position), not band name — several bands
    # deliberately share a column (legacy stacks under properties), and keying
    # by band would make them overlap.
    cursor = {}
    order = ENTITIES + [(t, b, [], None) for t, b in LINK_TABLES]
    for table, band, business, note in order:
        rows, hidden = build_rows(table, business)
        h = HEAD_H + ROW_H * (len(rows) + (1 if hidden else 0)) + 8
        x = BAND_X[band]
        y = cursor.get(x, 70)
        boxes[table] = {
            "x": x, "y": y, "w": W, "h": h, "band": band,
            "rows": rows, "hidden": hidden, "note": note,
        }
        cursor[x] = y + h + GAP


place()

# Edges: only real FKs between two shown tables, audit columns already gone.
edges = []
for f in FKS:
    if f["src_table"] in SHOWN and f["tgt_table"] in SHOWN:
        if f["src_col"] in AUDIT:
            continue
        edges.append(f)

CANVAS_W = max(b["x"] + b["w"] for b in boxes.values()) + 60
CANVAS_H = max(b["y"] + b["h"] for b in boxes.values()) + 120


# ── SVG renderer ────────────────────────────────────────────────────────────
def anchor(a, b):
    """Pick left/right anchors so edges flow between columns."""
    ax, aw = a["x"], a["w"]
    bx = b["x"]
    if bx >= ax + aw:
        return (ax + aw, "r"), (bx, "l")
    if bx + b["w"] <= ax:
        return (ax, "l"), (bx + b["w"], "r")
    return (ax + aw, "r"), (bx + b["w"], "r")


def row_y(box, col):
    for i, (n, _t, _k) in enumerate(box["rows"]):
        if n == col:
            return box["y"] + HEAD_H + ROW_H * i + ROW_H / 2
    return box["y"] + HEAD_H + 8


def svg():
    p = []
    p.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS_W}" '
        f'height="{CANVAS_H}" viewBox="0 0 {CANVAS_W} {CANVAS_H}" '
        f'font-family="Inter,Helvetica,Arial,sans-serif">'
    )
    p.append('<rect width="100%" height="100%" fill="#ffffff"/>')
    p.append(
        '<defs>'
        '<marker id="crow" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="11" '
        'markerHeight="11" orient="auto-start-reverse">'
        '<path d="M12,6 L1,1 M12,6 L1,11 M12,6 L1,6" stroke="#5A6570" '
        'stroke-width="1.3" fill="none"/></marker>'
        '<marker id="one" viewBox="0 0 12 12" refX="2" refY="6" markerWidth="11" '
        'markerHeight="11" orient="auto-start-reverse">'
        '<path d="M4,1 L4,11" stroke="#5A6570" stroke-width="1.6" fill="none"/></marker>'
        '</defs>'
    )

    # Title
    p.append(
        f'<text x="40" y="42" font-size="24" font-weight="700" fill="#1B2733">'
        f'Cleardeals Odoo 19 — Custom Domain ER Diagram</text>'
    )

    # Band labels
    seen_bands = {}
    for t, b in boxes.items():
        seen_bands.setdefault(b["band"], []).append(b)
    for band, bs in seen_bands.items():
        x = min(v["x"] for v in bs)
        y = min(v["y"] for v in bs) - 16
        _, _, _, label = PALETTE[band]
        p.append(
            f'<text x="{x}" y="{y}" font-size="12" font-weight="700" '
            f'fill="#6B7885" letter-spacing="0.9">{html.escape(label.upper())}</text>'
        )

    # Edges first (under boxes)
    for f in edges:
        a, b = boxes[f["src_table"]], boxes[f["tgt_table"]]
        (ax, aside), (bx, bside) = anchor(a, b)
        ay = row_y(a, f["src_col"])
        by = b["y"] + HEAD_H / 2 + 4
        midx = (ax + bx) / 2
        dash = ' stroke-dasharray="5,4"' if f["tgt_table"] == "property_inventory" else ""
        colour = "#C0392B" if f["on_delete"] == "CASCADE" else "#5A6570"
        p.append(
            f'<path d="M{ax},{ay} C{midx},{ay} {midx},{by} {bx},{by}" '
            f'fill="none" stroke="{colour}" stroke-width="1.25" opacity="0.75"'
            f'{dash} marker-start="url(#crow)" marker-end="url(#one)"/>'
        )

    # Boxes
    for table, b in boxes.items():
        head, border, tint, _ = PALETTE[b["band"]]
        x, y, w, h = b["x"], b["y"], b["w"], b["h"]
        p.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" '
            f'fill="#fff" stroke="{border}" stroke-width="1.4"/>'
        )
        p.append(
            f'<path d="M{x},{y+6} a6,6 0 0 1 6,-6 h{w-12} a6,6 0 0 1 6,6 v{HEAD_H-6} '
            f'h{-w} z" fill="{head}"/>'
        )
        p.append(
            f'<text x="{x+10}" y="{y+20}" font-size="13" font-weight="700" '
            f'fill="#fff">{html.escape(table)}</text>'
        )
        if b["note"]:
            p.append(
                f'<text x="{x+w-10}" y="{y+20}" font-size="10" text-anchor="end" '
                f'fill="#ffffff" opacity="0.85">{html.escape(b["note"])}</text>'
            )
        for i, (name, typ, kind) in enumerate(b["rows"]):
            ry = y + HEAD_H + ROW_H * i
            if i % 2 == 0:
                p.append(
                    f'<rect x="{x+1}" y="{ry}" width="{w-2}" height="{ROW_H}" '
                    f'fill="{tint}" opacity="0.5"/>'
                )
            badge = {"pk": "PK", "fk": "FK", "plain": ""}[kind]
            weight = "700" if kind == "pk" else "400"
            p.append(
                f'<text x="{x+10}" y="{ry+13}" font-size="11" font-weight="600" '
                f'fill="#8A6D1F">{badge}</text>'
            )
            p.append(
                f'<text x="{x+34}" y="{ry+13}" font-size="11.5" font-weight="{weight}" '
                f'fill="#1B2733">{html.escape(name)}</text>'
            )
            p.append(
                f'<text x="{x+w-10}" y="{ry+13}" font-size="10.5" text-anchor="end" '
                f'fill="#7C8894">{html.escape(typ)}</text>'
            )
        if b["hidden"]:
            ry = y + HEAD_H + ROW_H * len(b["rows"])
            p.append(
                f'<text x="{x+34}" y="{ry+13}" font-size="10.5" font-style="italic" '
                f'fill="#9AA5B1">+{b["hidden"]} more columns</text>'
            )

    # Legend
    ly = CANVAS_H - 80
    p.append(
        f'<rect x="40" y="{ly-22}" width="880" height="64" rx="6" fill="#F7F9FA" '
        f'stroke="#D5DCE2"/>'
    )
    p.append(
        f'<text x="56" y="{ly-4}" font-size="12" font-weight="700" fill="#1B2733">Legend</text>'
    )
    items = [
        "PK primary key",
        "FK foreign key",
        "crow's foot = many",
        "bar = one",
        "red edge = ON DELETE CASCADE",
        "dashed = link into an archived module",
    ]
    for i, s in enumerate(items):
        cx = 56 + (i % 3) * 290
        cy = ly + 16 + (i // 3) * 18
        p.append(
            f'<text x="{cx}" y="{cy}" font-size="11" fill="#4A5560">{html.escape(s)}</text>'
        )
    p.append(
        f'<text x="{CANVAS_W-40}" y="{CANVAS_H-24}" font-size="10.5" text-anchor="end" '
        f'fill="#9AA5B1">Generated from PostgreSQL foreign keys — Odoo 19. '
        f'Audit columns omitted.</text>'
    )
    p.append("</svg>")
    return "\n".join(p)


# ── draw.io renderer (same coordinates) ─────────────────────────────────────
def drawio():
    cells = []
    cid = 2

    def esc(s):
        return html.escape(s, quote=True)

    ids = {}
    for table, b in boxes.items():
        head, border, tint, _ = PALETTE[b["band"]]
        # Build the HTML label with real markup and real characters, then escape
        # the WHOLE string once — draw.io stores html labels entity-escaped
        # inside the value attribute, and raw '<' is illegal in XML attributes.
        label_rows = "".join(
            f"<br/>{'PK ' if k == 'pk' else ('FK ' if k == 'fk' else '&nbsp;&nbsp;&nbsp; ')}"
            f"{n} : {t}"
            for n, t, k in b["rows"]
        )
        extra = f"<br/><i>+{b['hidden']} more columns</i>" if b["hidden"] else ""
        note = f" — {b['note']}" if b["note"] else ""
        value = esc(f"<b>{table}</b>{note}{label_rows}{extra}")
        ids[table] = cid
        cells.append(
            f'<mxCell id="{cid}" value="{value}" style="verticalAlign=top;align=left;'
            f'overflow=hidden;html=1;rounded=1;fillColor=#ffffff;strokeColor={border};'
            f'fontSize=11;spacingLeft=6;spacingTop=2;" vertex="1" parent="1">'
            f'<mxGeometry x="{b["x"]}" y="{b["y"]}" width="{b["w"]}" '
            f'height="{b["h"]}" as="geometry"/></mxCell>'
        )
        cid += 1

    for f in edges:
        s, t = ids[f["src_table"]], ids[f["tgt_table"]]
        colour = "#C0392B" if f["on_delete"] == "CASCADE" else "#5A6570"
        dash = "dashed=1;" if f["tgt_table"] == "property_inventory" else ""
        cells.append(
            f'<mxCell id="{cid}" value="{esc(f["src_col"])}" style="edgeStyle=orthogonalEdgeStyle;'
            f'rounded=1;html=1;{dash}strokeColor={colour};fontSize=9;'
            f'startArrow=ERmany;startFill=0;endArrow=ERone;endFill=0;" '
            f'edge="1" parent="1" source="{s}" target="{t}">'
            f'<mxGeometry relative="1" as="geometry"/></mxCell>'
        )
        cid += 1

    body = "".join(cells)
    return (
        '<mxfile host="app.diagrams.net" type="device">'
        '<diagram name="Cleardeals Odoo ERD">'
        f'<mxGraphModel dx="1400" dy="900" grid="1" gridSize="10" guides="1" '
        f'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        f'pageWidth="{CANVAS_W}" pageHeight="{CANVAS_H}" math="0" shadow="0">'
        '<root><mxCell id="0"/><mxCell id="1" parent="0"/>'
        f'{body}'
        '</root></mxGraphModel></diagram></mxfile>'
    )


os.makedirs(OUT, exist_ok=True)
open(os.path.join(OUT, "cleardeals-odoo-erd.svg"), "w").write(svg())
open(os.path.join(OUT, "cleardeals-odoo-erd.drawio"), "w").write(drawio())

print(f"entities : {len(boxes)}")
print(f"edges    : {len(edges)}")
print(f"canvas   : {CANVAS_W} x {CANVAS_H}")
print("wrote    : cleardeals-odoo-erd.svg, cleardeals-odoo-erd.drawio")
