-- Export the whole public schema as JSON for gen_erd.py.
--
--   docker exec odoo-erd-db psql -U odoo -d erd -tAf schema_export.sql > schema.json
--
-- Exports every column, foreign key and unique index in the schema; gen_erd.py
-- filters down to the tables it draws. Deliberately unfiltered so the same file
-- can answer questions the diagram does not show.

SELECT json_build_object(

  'columns', (
    SELECT json_agg(row_to_json(c))
    FROM (
      SELECT table_name, column_name, data_type, is_nullable, ordinal_position
      FROM information_schema.columns
      WHERE table_schema = 'public'
      ORDER BY table_name, ordinal_position
    ) c
  ),

  'fks', (
    SELECT json_agg(row_to_json(f))
    FROM (
      SELECT src.relname  AS src_table,
             a.attname    AS src_col,
             tgt.relname  AS tgt_table,
             CASE c.confdeltype
               WHEN 'a' THEN 'NO ACTION' WHEN 'r' THEN 'RESTRICT'
               WHEN 'c' THEN 'CASCADE'   WHEN 'n' THEN 'SET NULL'
               WHEN 'd' THEN 'SET DEFAULT'
             END          AS on_delete,
             a.attnotnull AS required
      FROM pg_constraint c
      JOIN pg_class src ON src.oid = c.conrelid
      JOIN pg_class tgt ON tgt.oid = c.confrelid
      JOIN unnest(c.conkey) WITH ORDINALITY k(attnum, ord) ON true
      JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
      WHERE c.contype = 'f'
      ORDER BY src.relname, a.attname
    ) f
  ),

  'uniques', (
    SELECT json_agg(row_to_json(u))
    FROM (
      SELECT t.relname AS tbl,
             i.relname AS idx,
             array_to_json(array_agg(a.attname ORDER BY a.attname)) AS cols
      FROM pg_index x
      JOIN pg_class t ON t.oid = x.indrelid
      JOIN pg_class i ON i.oid = x.indexrelid
      JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(x.indkey)
      WHERE x.indisunique
        AND NOT x.indisprimary
        AND t.relnamespace = 'public'::regnamespace
      GROUP BY t.relname, i.relname
      ORDER BY t.relname, i.relname
    ) u
  )

);
