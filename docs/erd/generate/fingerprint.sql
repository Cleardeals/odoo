-- Deterministic fingerprint of the ER-diagram surface.
--
-- Emits one sorted line per in-scope table and per foreign key between two
-- in-scope tables. Odoo audit columns are excluded, matching the diagram.
--
-- Used by check_drift.sh to detect that the schema changed without the ER
-- diagram being regenerated. Output must be byte-stable for the same schema,
-- so everything is explicitly ordered and nothing includes a timestamp,
-- row count, OID or constraint name.
--
-- Usage:
--   psql -U odoo -d <db> -tAf fingerprint.sql > schema-fingerprint.txt

WITH scope AS (
    -- Tables owned by our custom modules. DISTINCT ON attributes a model to the
    -- module that DEFINES it rather than every module that _inherit-extends it.
    SELECT DISTINCT ON (m.model) replace(m.model, '.', '_') AS tbl
    FROM ir_model m
    JOIN ir_model_data d ON d.model = 'ir.model' AND d.res_id = m.id
    WHERE d.module IN (
        'leads', 'properties', 'wa_communication', 'cleardeals_pubsub',
        'cleardeals_notification', 'cleardeals_ui', 'cleardeals_dashboards'
    )
    ORDER BY m.model, d.id
),
rel AS (
    -- Many-to-many join tables the ORM creates for those models. These have no
    -- ir_model row, so they are found through their foreign keys.
    SELECT DISTINCT src.relname AS tbl
    FROM pg_constraint c
    JOIN pg_class src ON src.oid = c.conrelid
    JOIN pg_class tgt ON tgt.oid = c.confrelid
    WHERE c.contype = 'f'
      AND src.relname LIKE '%\_rel'
      AND tgt.relname IN (SELECT tbl FROM scope)
),
core AS (
    -- Odoo core touchpoints, plus the one legacy table still referenced.
    SELECT unnest(ARRAY[
        'res_users', 'res_partner', 'res_company',
        'ir_attachment', 'property_inventory'
    ]) AS tbl
),
included AS (
    SELECT tbl FROM scope
    UNION SELECT tbl FROM rel
    UNION SELECT tbl FROM core
),
present AS (
    SELECT i.tbl
    FROM included i
    JOIN information_schema.tables t
      ON t.table_schema = 'public' AND t.table_name = i.tbl
),
audit AS (
    SELECT unnest(ARRAY['create_uid', 'write_uid', 'create_date', 'write_date']) AS col
),
-- One line per table, with its non-audit column count. Catches added or
-- removed tables, and added or removed columns.
table_lines AS (
    SELECT 'TABLE ' || p.tbl || ' cols=' || count(c.column_name)::text AS line
    FROM present p
    JOIN information_schema.columns c
      ON c.table_schema = 'public' AND c.table_name = p.tbl
    WHERE c.column_name NOT IN (SELECT col FROM audit)
    GROUP BY p.tbl
),
-- One line per foreign key between two in-scope tables, including the delete
-- rule (so a change to ondelete shows up) and whether the column is required.
fk_lines AS (
    SELECT 'FK ' || src.relname || '.' || a.attname
             || ' -> ' || tgt.relname
             || ' on_delete=' || CASE c.confdeltype
                    WHEN 'a' THEN 'noaction' WHEN 'r' THEN 'restrict'
                    WHEN 'c' THEN 'cascade'  WHEN 'n' THEN 'setnull'
                    WHEN 'd' THEN 'setdefault' END
             || ' required=' || a.attnotnull::text AS line
    FROM pg_constraint c
    JOIN pg_class src ON src.oid = c.conrelid
    JOIN pg_class tgt ON tgt.oid = c.confrelid
    JOIN unnest(c.conkey) WITH ORDINALITY k(attnum, ord) ON true
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
    WHERE c.contype = 'f'
      AND src.relname IN (SELECT tbl FROM present)
      AND tgt.relname IN (SELECT tbl FROM present)
      AND a.attname NOT IN (SELECT col FROM audit)
)
SELECT line FROM (
    SELECT line FROM table_lines
    UNION ALL
    SELECT line FROM fk_lines
) all_lines
ORDER BY line;
