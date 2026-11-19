-- Run as the demo application's analytical reader after bootstrap and authentication.
\set ON_ERROR_STOP on
BEGIN READ ONLY;
SET LOCAL search_path TO pg_catalog;
DO $check$
DECLARE
    tables text[];
    high_count integer;
    small_band integer;
    large_band integer;
    earliest date;
    latest date;
BEGIN
    IF current_database() <> 'aqua_sales_demo' OR current_user <> 'aqua_sales_demo_reader' THEN
        RAISE EXCEPTION 'Connect to aqua_sales_demo as aqua_sales_demo_reader';
    END IF;
    IF current_setting('default_transaction_read_only') <> 'on'
        OR NOT EXISTS (SELECT FROM pg_settings WHERE name = 'statement_timeout' AND setting = '10000' AND unit = 'ms') THEN
        RAISE EXCEPTION 'Sales demo reader requires read-only transactions by default and a 10-second statement timeout';
    END IF;
    SELECT array_agg(c.relname::text ORDER BY c.relname) INTO tables
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
      AND has_any_column_privilege(c.oid, 'SELECT');
    IF tables IS DISTINCT FROM ARRAY['account','card','client','disp','district','loan','order','trans']
        OR has_database_privilege(current_database(), 'CREATE,TEMP')
        OR NOT has_schema_privilege('public', 'USAGE') OR has_schema_privilege('public', 'CREATE')
        OR EXISTS (SELECT FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                   WHERE n.nspname = 'public' AND c.relname::text = ANY(tables)
                   AND NOT has_table_privilege(c.oid, 'SELECT'))
        OR EXISTS (SELECT FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                   WHERE n.nspname = 'public' AND c.relkind IN ('r','p')
                   AND (has_any_column_privilege(c.oid, 'INSERT,UPDATE,REFERENCES')
                        OR has_table_privilege(c.oid, 'DELETE,TRUNCATE,TRIGGER'))) THEN
        RAISE EXCEPTION 'Demo reader privileges differ from the eight read-only sales tables';
    END IF;
    SELECT count(*) FILTER (WHERE amount > 997), count(*) FILTER (WHERE amount <= 250),
           count(*) FILTER (WHERE amount > 250), min(date), max(date)
        INTO high_count, small_band, large_band, earliest, latest
    FROM public.trans;
    IF (high_count, small_band, large_band) <> (3, 250, 750) THEN
        RAISE EXCEPTION 'Sales demo counts differ from the presenter guide';
    END IF;
    IF (earliest, latest) IS DISTINCT FROM (DATE '1996-11-01', DATE '1996-11-16') THEN
        RAISE EXCEPTION 'Sales demo posting dates differ from the November 1996 ledger';
    END IF;
    RAISE NOTICE 'Verified 8 readable tables, 3 transactions above 997 CZK, and amount bands of 250 and 750';
END
$check$;
COMMIT;
