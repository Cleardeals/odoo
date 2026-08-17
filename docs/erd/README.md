# Cleardeals Odoo 19 — ER Diagram

Entity-relationship documentation for the custom domain: `leads`, `properties`,
`wa_communication`, `cleardeals_pubsub`, `cleardeals_notification`,
`cleardeals_ui`, `cleardeals_dashboards` — plus the Odoo core tables they
actually touch.

Every relationship shown is a **real PostgreSQL foreign key**, read from a live
schema. Nothing here is hand-asserted, so the diagram cannot quietly drift from
the database.

## What is here

| Artefact | Format | Use it for |
|----------|--------|------------|
| `cleardeals-odoo-erd.svg` | SVG (63 KB) | the readable diagram — open in any browser, scales losslessly |
| `cleardeals-odoo-erd.pdf` | PDF, 1 page, 2040 × 1151 pt (132 KB) | printing, attaching to a doc or ticket. Text is selectable, not rasterised |
| `cleardeals-odoo-erd.drawio` | draw.io / diagrams.net XML (30 KB) | **editing.** Open at [app.diagrams.net](https://app.diagrams.net) or with the Draw.io VS Code extension |
| [`SOP.md`](SOP.md) | — | **how to keep this current.** Read before changing the schema |
| `generate/` | — | the generator, SQL, and the drift gate — everything needed to rebuild |

```bash
open docs/erd/cleardeals-odoo-erd.svg
```

### The exhaustive reference is generated on demand, not committed

A **SchemaSpy** site (every table, column, index, constraint, anomaly, plus
per-table relationship diagrams at 1 and 2 degrees of separation) can be built
in one command — see [SOP.md §2.7](SOP.md). It is **not** in git: 21 MB, of which
only 7.6 MB is diagrams and 13 MB is SchemaSpy's vendored front-end (pdfmake,
xlsx, admin-lte). Build output that large does not belong in version control, and
it is reproducible in about a minute. `schemaspy/` is gitignored.

Use it when you need to answer "what points at this table?" exhaustively. Its
overview diagram is a hairball — inherent to auto-layout over 58 tables — which
is why the curated diagram exists alongside it.

### Staying current

The diagram is generated from a real schema, so it cannot be *wrong* — only
**stale**. `generate/check_drift.sh` compares a live database against the
committed fingerprint and fails with the exact lines that changed:

```bash
cd docs/erd/generate
PGDATABASE=cleardeals_19_dev PGPORT=5434 ./check_drift.sh
```

**Run this by hand before opening a PR** — it is not automated yet. Wiring it
into CI is designed and verified but deliberately deferred, so that adding a
merge-blocking check stays a team decision: see [SOP §4](SOP.md).

Full procedure and triggers: [SOP.md](SOP.md).

## Scope

**58 tables**, chosen deliberately rather than dumped:

- **47** tables owned by our seven custom modules (resolved via `ir_model` →
  `ir_model_data`, so `_inherit` extensions are attributed to the module that
  *defines* the model, not every module that extends it).
- **6** many-to-many link tables those models create (`*_rel`). These have no
  `ir_model` row — they are pure join tables created by the ORM.
- **4** Odoo core touchpoints: `res_users`, `res_partner`, `res_company`,
  `ir_attachment`.
- **1** legacy table, `property_inventory` — see [Findings](#findings).

An Odoo 19 database with these modules installed has **273 tables** in total, and
a full instance around 900. A diagram of all of them is not useful, so core Odoo
(mail, bus, ir_*, res_* beyond the touchpoints) is excluded.

The curated diagram narrows further to **27 entities**, dropping transient
`TransientModel` wizards and the standalone reporting/stats tables. The complete
58 are all in the SchemaSpy site.

## Notation

The curated diagram uses standard crow's-foot ER notation.

| Mark | Meaning |
|------|---------|
| `PK` | primary key |
| `FK` | foreign key |
| crow's foot (three prongs) | the *many* end |
| bar | the *one* end |
| grey edge | `ON DELETE SET NULL` / `RESTRICT` / `NO ACTION` |
| **red edge** | `ON DELETE CASCADE` — deleting the parent deletes these rows |
| **dashed edge** | points into an archived module |
| `+N more columns` | columns not surfaced; see the SchemaSpy page for the full list |

Colour bands group entities by owning module. Header notes (`the enquiry`,
`one per phone`, `append-only`, `attribution`, `batch audit`) name the role each
entity plays.

The red CASCADE edges are worth reading as a group — they tell you the deletion
blast radius. Deleting a `wa_conversation` takes its `wa_message` and
`wa_conversation_segment` rows with it; deleting a `leads_new` takes its site
visits and property interests.

## Known limitations

These are properties of Odoo and of ER diagrams generally, not gaps in the
generation:

1. **`One2many` fields do not appear as their own relationship.** A `One2many`
   stores nothing in the database — it is the *inverse* of a `Many2one` on the
   other table. So `wa_conversation.message_ids` shows up here as
   `wa_message.conversation_id → wa_conversation`. Same relationship, seen from
   the side that owns the column.

2. **Polymorphic references have no foreign key and cannot be drawn.** Odoo's
   `Many2oneReference` (for example `ir_attachment.res_id`, paired with
   `res_model`) is an integer with no FK constraint, because its target table
   varies per row. No introspection tool can recover those edges — you have to
   read the Python.

3. **`_inherits` delegation looks like an ordinary FK.** `res_users.partner_id →
   res_partner` is drawn as a plain relationship, but semantically it is
   delegation: a user *is* a partner, and Odoo transparently proxies the
   partner's fields. The diagram cannot express that distinction.

4. **Odoo audit columns are omitted throughout** — `create_uid`, `write_uid`,
   `create_date`, `write_date`. Every Odoo table has them and `create_uid` /
   `write_uid` both FK to `res_users`, which added roughly 100 edges all
   converging on one box and made the diagram unreadable. Omitting audit and
   metadata columns is standard ER-diagram practice. They exist in the database.

5. **Row counts are not shown** (`-norows`). The schema was built from a fresh
   install with no demo data, so counts would all be zero and misleading.

6. **Stored computed fields are indistinguishable from plain columns.** A stored
   compute is a real column; nothing in the schema marks it as derived.

## Findings

Two things the FK graph surfaced that are worth knowing:

**`leads` has a live foreign key into an archived module.**
`leads_new.property_id → property_inventory`, and `property_inventory` is owned by
`lead_suggestor` — one of the archived modules. This is drawn dashed and boxed in
the *legacy / superseded* band. The FK is real and enforced, so the archived
module cannot simply be dropped without dealing with this column first.

**Our domain touches Odoo core almost entirely through `res_users`.**
Verified by querying every FK into `res_partner`, `res_company` and
`ir_attachment`: none of our 47 tables reference them directly. The only
exception is `ir_attachment_lead_csv_import_wizard_rel`, the attachment link
table for the CSV import wizard. `res_partner` and `res_company` appear in the
diagram only because `res_users` delegates to them. That is a genuinely clean
boundary and worth preserving.

Also visible: **13 of the 58 tables have no foreign keys at all** — the
reporting/stats tables (`*_template_stats`, `property_daily_stat`,
`active_lead_assignment`), several wizards, `lead_olx_account`, and
`wa_event_log`. For `wa_event_log` that is deliberate: it is a raw event sink
that must accept payloads referencing records that may not exist yet.

## Regenerating and maintaining

**The full procedure lives in [SOP.md](SOP.md)** — deliberately in one place, so
there is only one copy to keep correct.

At a glance:

| Task | Where |
|------|-------|
| Am I stale? | [SOP §0](SOP.md) — `generate/check_drift.sh` |
| Do I need to regenerate for this change? | [SOP §1](SOP.md) — the trigger table |
| How do I regenerate? | [SOP §2](SOP.md) — ~5 minutes, fully scripted |
| What do I check before committing? | [SOP §3](SOP.md) |
| How do we enforce it in CI? | [SOP §4](SOP.md) — **future plan, deferred** |
| How do I change which entities appear? | [SOP §5](SOP.md) — edit the data at the top of `gen_erd.py`, not the renderers |
| It broke | [SOP §6](SOP.md) — symptom table |

Everything needed is in `generate/`:

| File | Role |
|------|------|
| `docker-compose.erd.yml`, `odoo.erd.conf` | the throwaway stack (own Postgres, no GCP credentials, Pub/Sub at a dead port, port 8071) |
| `tables.sql` | derives the 58 in-scope tables from `ir_model` |
| `schema_export.sql` | exports columns, FKs and unique indexes as JSON |
| `gen_erd.py` | the layout model — emits both `.svg` and `.drawio` |
| `fingerprint.sql` | the deterministic drift fingerprint |
| `schema-fingerprint.txt` | the committed baseline (58 tables, 91 FKs) |
| `check_drift.sh` | the gate — regenerates the fingerprint and diffs it |
| `tables.txt`, `include.rx` | generated inputs, committed so a rebuild is reproducible |

Regenerating never touches your dev environment: `cleardeals_19_dev` and
`odoo-dev-db` are never written to.

## Related

- [`docs/odoo-handbook/`](../odoo-handbook/) — the developer handbook.
  [Chapter 04](../odoo-handbook/04-orm-and-database.md) explains how Odoo fields
  become the columns and constraints shown here; [Chapter 01](../odoo-handbook/01-what-is-odoo.md)
  has the module dependency graph that this diagram's band order follows.
