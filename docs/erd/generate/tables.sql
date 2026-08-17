-- The in-scope table list for the ER diagram, one table name per line.
--
--   docker exec odoo-erd-db psql -U odoo -d erd -tAf tables.sql > tables.txt
--
-- Keep the module list here in sync with fingerprint.sql (see SOP.md §5).

WITH scope AS (
    -- DISTINCT ON attributes a model to the module that DEFINES it, not every
    -- module that _inherit-extends it (property_base -> properties, not leads).
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
    -- Many-to-many join tables created by the ORM. No ir_model row, so they are
    -- discovered through their foreign keys into an in-scope table.
    SELECT DISTINCT src.relname AS tbl
    FROM pg_constraint c
    JOIN pg_class src ON src.oid = c.conrelid
    JOIN pg_class tgt ON tgt.oid = c.confrelid
    WHERE c.contype = 'f'
      AND src.relname LIKE '%\_rel'
      AND tgt.relname IN (SELECT tbl FROM scope)
),
core AS (
    -- Odoo core touchpoints, plus the legacy table still referenced by
    -- leads_new.property_id (see README "Findings").
    SELECT unnest(ARRAY[
        'res_users', 'res_partner', 'res_company',
        'ir_attachment', 'property_inventory'
    ]) AS tbl
)
SELECT i.tbl
FROM (SELECT tbl FROM scope UNION SELECT tbl FROM rel UNION SELECT tbl FROM core) i
JOIN information_schema.tables t
  ON t.table_schema = 'public' AND t.table_name = i.tbl
ORDER BY i.tbl;
