-- Connect explicitly to postgres on a new private demo cluster.
\set ON_ERROR_STOP on
BEGIN READ ONLY;
SET LOCAL search_path TO pg_catalog;
DO $guard$
BEGIN
    IF current_database() <> 'postgres'
        OR EXISTS (SELECT FROM pg_database WHERE NOT datistemplate AND datname <> 'postgres')
        OR EXISTS (SELECT FROM pg_roles WHERE rolname = 'aqua_sales_demo_reader')
        OR EXISTS (SELECT FROM pg_namespace WHERE nspname !~ '^pg_' AND nspname NOT IN ('public','information_schema'))
        OR EXISTS (SELECT FROM pg_depend WHERE refclassid = 'pg_namespace'::regclass
                   AND refobjid = 'public'::regnamespace) THEN
        RAISE EXCEPTION 'Requires the postgres maintenance database on a new dedicated demo cluster; no sales database was created';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = current_user
                   AND (rolsuper OR (rolcreatedb AND rolcreaterole))) THEN
        RAISE EXCEPTION 'Demo administrator must be able to create both the database and its reader';
    END IF;
END
$guard$;
COMMIT;
-- PostgreSQL requires CREATE DATABASE to be outside an explicit transaction.
CREATE DATABASE aqua_sales_demo TEMPLATE template0;
