-- Included only by bootstrap_pagila.psql, inside its bounded transaction.
-- Declared dataset revision is not a proof of source bytes; verify asset hashes
-- before loading the separately owned candidate (see the operator document).
SELECT current_database() = :'aqua_expected_database'
       AND :'aqua_expected_database' = 'aqua_analytics_pagila'
       AND :'aqua_dataset_revision' =
           'pagila_v3_1_0_fef9675714cfba1756df4719b5e36075a7ddf90e'
       AND :'aqua_portable_index' = 'exact'
       AND :'aqua_vector_version' ~ '^[0-9]+\.[0-9]+\.[0-9]+$'
       AND current_setting('server_version_num')::integer / 10000 = 18
       AS portable_request_valid \gset
\if :portable_request_valid
\else
    DO $$ BEGIN RAISE EXCEPTION 'portable_request_scope_invalid'; END $$;
\endif

-- The expected pgvector version comes from an independently reviewed immutable
-- image/extension inventory. Never substitute the newest available version.
SELECT EXISTS (
           SELECT FROM pg_available_extension_versions
           WHERE name = 'vector' AND version = :'aqua_vector_version'
       ) AND NOT EXISTS (
           SELECT FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace
           WHERE e.extname = 'vector'
             AND (n.nspname <> 'public' OR e.extversion <> :'aqua_vector_version')
       ) AS portable_vector_valid \gset
\if :portable_vector_valid
\else
    DO $$ BEGIN RAISE EXCEPTION 'portable_vector_extension_invalid'; END $$;
\endif

DO $$
DECLARE
    tables text[];
    partitions text[];
    views text[];
BEGIN
    IF NOT EXISTS (
        SELECT FROM pg_database
        WHERE datname = current_database() AND datdba = current_user::regrole
    ) OR EXISTS (
        SELECT FROM pg_roles WHERE rolname IN ('nl2sql_reader','nl2sql_indexer')
    ) OR EXISTS (
        SELECT FROM pg_namespace
        WHERE nspname !~ '^pg_' AND nspname NOT IN ('public','information_schema')
    ) OR EXISTS (
        SELECT FROM pg_extension WHERE extname NOT IN ('plpgsql','vector')
    ) OR EXISTS (
        SELECT FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'f'
    ) THEN
        RAISE EXCEPTION 'portable_fresh_destination_required';
    END IF;

    SELECT array_agg(c.relname::text ORDER BY c.relname) INTO tables
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('r','p')
      AND NOT c.relispartition;
    IF tables IS DISTINCT FROM ARRAY[
        'actor','address','category','city','country','customer','film',
        'film_actor','film_category','inventory','language','payment',
        'rental','staff','store'
    ]::text[] THEN
        RAISE EXCEPTION 'portable_pagila_table_scope_invalid';
    END IF;

    SELECT array_agg(c.relname::text ORDER BY c.relname) INTO partitions
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('r','p')
      AND c.relispartition;
    IF partitions IS DISTINCT FROM ARRAY[
        'payment_p2022_01','payment_p2022_02','payment_p2022_03',
        'payment_p2022_04','payment_p2022_05','payment_p2022_06',
        'payment_p2022_07'
    ]::text[] THEN
        RAISE EXCEPTION 'portable_pagila_partition_scope_invalid';
    END IF;

    SELECT array_agg(c.relname::text ORDER BY c.relname) INTO views
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('v','m');
    IF views IS DISTINCT FROM ARRAY[
        'actor_info','customer_list','film_list','nicer_but_slower_film_list',
        'rental_by_category','sales_by_film_category','sales_by_store','staff_list'
    ]::text[] THEN
        RAISE EXCEPTION 'portable_pagila_view_scope_invalid';
    END IF;

    IF (SELECT count(*) FROM public.actor) <> 200
       OR (SELECT count(*) FROM public.film) <> 1000
       OR (SELECT count(*) FROM public.customer) <> 599
       OR (SELECT count(*) FROM public.store) <> 2
       OR (SELECT count(*) FROM public.rental) <> 16044
       OR (SELECT count(*) FROM public.payment) <> 16049 THEN
        RAISE EXCEPTION 'portable_pagila_counts_invalid';
    END IF;
END $$;
