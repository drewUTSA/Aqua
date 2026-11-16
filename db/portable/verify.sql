-- Catalog/privilege checks only; no prompts, provider calls or index contents.
SET LOCAL search_path = pg_catalog;
DO $$
BEGIN
    IF (SELECT count(*) FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_type t ON t.oid = a.atttypid
        JOIN pg_namespace tn ON tn.oid = t.typnamespace
        WHERE n.nspname = 'retrieval'
          AND c.relname IN ('schema_doc','example_query')
          AND a.attname = 'embedding' AND NOT a.attisdropped
          AND t.typname = 'vector' AND tn.nspname = 'public'
          AND a.atttypmod = 768 AND a.attnotnull) <> 2
       OR EXISTS (
           SELECT FROM pg_index i
           JOIN pg_class c ON c.oid = i.indrelid
           JOIN pg_namespace n ON n.oid = c.relnamespace
           JOIN pg_class x ON x.oid = i.indexrelid
           JOIN pg_am a ON a.oid = x.relam
           WHERE n.nspname = 'retrieval'
             AND (a.amname <> 'btree' OR i.indexprs IS NOT NULL)
       ) THEN
        RAISE EXCEPTION 'portable_retrieval_profile_invalid';
    END IF;

    IF (SELECT count(*) FROM pg_roles
        WHERE rolname IN ('nl2sql_reader','nl2sql_indexer') AND rolcanlogin
          AND NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication
                   OR rolbypassrls)) <> 2
       OR NOT has_table_privilege('nl2sql_reader','public.film','SELECT')
       OR NOT has_column_privilege('nl2sql_reader','public.staff','first_name','SELECT')
       OR has_column_privilege('nl2sql_reader','public.staff','password','SELECT')
       OR has_column_privilege('nl2sql_reader','public.staff','picture','SELECT')
       OR has_table_privilege('nl2sql_reader','public.staff_list','SELECT')
       OR has_schema_privilege('nl2sql_reader','public','CREATE')
       OR has_schema_privilege('nl2sql_indexer','public','CREATE')
       OR has_schema_privilege('nl2sql_reader','retrieval','CREATE')
       OR has_schema_privilege('nl2sql_indexer','retrieval','CREATE') THEN
        RAISE EXCEPTION 'portable_reader_privileges_invalid';
    END IF;

    IF EXISTS (
        SELECT FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m')
          AND (has_table_privilege('nl2sql_reader',c.oid,'INSERT,UPDATE,DELETE,TRUNCATE')
               OR has_any_column_privilege('nl2sql_reader',c.oid,'INSERT,UPDATE')
               OR has_any_column_privilege('nl2sql_indexer',c.oid,'SELECT,INSERT,UPDATE')
               OR has_table_privilege('nl2sql_indexer',c.oid,'DELETE,TRUNCATE'))
    ) OR EXISTS (
        SELECT FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'retrieval' AND c.relkind = 'r'
          AND (NOT has_table_privilege('nl2sql_reader',c.oid,'SELECT')
               OR has_table_privilege('nl2sql_reader',c.oid,'INSERT,UPDATE,DELETE,TRUNCATE')
               OR has_any_column_privilege('nl2sql_reader',c.oid,'INSERT,UPDATE')
               OR NOT (has_table_privilege('nl2sql_indexer',c.oid,'SELECT')
                       AND has_table_privilege('nl2sql_indexer',c.oid,'INSERT')
                       AND has_table_privilege('nl2sql_indexer',c.oid,'UPDATE')
                       AND has_table_privilege('nl2sql_indexer',c.oid,'DELETE')))
    ) THEN
        RAISE EXCEPTION 'portable_role_separation_invalid';
    END IF;
END $$;
