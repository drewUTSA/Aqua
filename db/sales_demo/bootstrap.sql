-- Run with psql as owner of a new aqua_sales_demo on a dedicated demo cluster.
-- All names and records here are fictional. The role has no password at creation.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL search_path TO pg_catalog;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
BEGIN
    IF current_database() <> 'aqua_sales_demo'
        OR NOT EXISTS (SELECT FROM pg_database WHERE datname = current_database()
                       AND datdba = current_user::regrole)
        OR EXISTS (SELECT FROM pg_database WHERE NOT datistemplate
                   AND datname NOT IN ('postgres', 'aqua_sales_demo')) THEN
        RAISE EXCEPTION 'Requires a new, owned aqua_sales_demo database on a dedicated demo cluster';
    END IF;
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'aqua_sales_demo_reader')
        OR EXISTS (SELECT FROM pg_namespace WHERE nspname !~ '^pg_' AND nspname NOT IN ('public', 'information_schema'))
        OR EXISTS (SELECT FROM pg_depend WHERE refclassid = 'pg_namespace'::regclass
                   AND refobjid = 'public'::regnamespace)
        OR EXISTS (SELECT FROM pg_database d, aclexplode(d.datacl) a
                   WHERE d.datname = current_database() AND a.grantee NOT IN (0, d.datdba))
        OR EXISTS (SELECT FROM pg_namespace n, aclexplode(n.nspacl) a
                   WHERE n.nspname = 'public' AND a.grantee NOT IN (0, n.nspowner))
        OR EXISTS (SELECT FROM pg_default_acl) THEN
        RAISE EXCEPTION 'Demo reader already exists or database is not fresh; choose a new disposable cluster';
    END IF;
END
$guard$;

CREATE ROLE aqua_sales_demo_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
REVOKE ALL ON DATABASE aqua_sales_demo FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;

CREATE TABLE public.district (district_id integer PRIMARY KEY, a2 text NOT NULL, a3 text NOT NULL);
CREATE TABLE public.account (account_id integer PRIMARY KEY, district_id integer NOT NULL REFERENCES public.district,
    frequency text NOT NULL, date date NOT NULL);
CREATE TABLE public.client (client_id integer PRIMARY KEY, district_id integer NOT NULL REFERENCES public.district);
CREATE TABLE public.disp (disp_id integer PRIMARY KEY, account_id integer NOT NULL REFERENCES public.account,
    client_id integer NOT NULL REFERENCES public.client, type text NOT NULL);
CREATE TABLE public.card (card_id integer PRIMARY KEY, disp_id integer NOT NULL REFERENCES public.disp,
    type text NOT NULL, issued date NOT NULL);
CREATE TABLE public.loan (loan_id integer PRIMARY KEY, account_id integer NOT NULL REFERENCES public.account,
    date date NOT NULL, amount numeric NOT NULL, duration integer NOT NULL, payments numeric NOT NULL, status text NOT NULL);
CREATE TABLE public."order" (order_id integer PRIMARY KEY, account_id integer NOT NULL REFERENCES public.account,
    bank_to text NOT NULL, account_to integer NOT NULL, amount numeric NOT NULL, k_symbol text);
CREATE TABLE public.trans (trans_id integer PRIMARY KEY, account_id integer NOT NULL REFERENCES public.account,
    date date NOT NULL, type text NOT NULL, amount numeric NOT NULL, operation text NOT NULL, k_symbol text);

INSERT INTO public.district VALUES (1, 'Cedar Quay Demo', 'Demo North'), (2, 'Willow Pier Demo', 'Demo South');
INSERT INTO public.account VALUES (1, 1, 'POPLATEK MESICNE', '1996-01-01'), (2, 2, 'POPLATEK TYDNE', '1996-01-02');
INSERT INTO public.client VALUES (1, 1), (2, 2);
INSERT INTO public.disp VALUES (1, 1, 1, 'OWNER'), (2, 2, 2, 'OWNER');
INSERT INTO public.card VALUES (1, 1, 'classic', '1996-02-01'), (2, 2, 'junior', '1996-02-02');
INSERT INTO public.loan VALUES (1, 1, '1996-04-01', 12000, 12, 1000, 'C');
INSERT INTO public."order" VALUES (1, 2, 'XX', 9001, 75, 'SIPO');
-- Each amount from 1 through 1,000 CZK occurs once in this fictional ledger.
INSERT INTO public.trans
SELECT n, 1 + (n % 2), DATE '1996-11-01' + ((n-1) % 16), 'PRIJEM', n, 'VKLAD', NULL
FROM generate_series(1, 1000) AS series(n);

GRANT CONNECT ON DATABASE aqua_sales_demo TO aqua_sales_demo_reader;
GRANT USAGE ON SCHEMA public TO aqua_sales_demo_reader;
GRANT SELECT ON public.district, public.account, public.client, public.disp,
    public.card, public.loan, public."order", public.trans TO aqua_sales_demo_reader;
ALTER ROLE aqua_sales_demo_reader IN DATABASE aqua_sales_demo SET default_transaction_read_only = on;
ALTER ROLE aqua_sales_demo_reader IN DATABASE aqua_sales_demo SET statement_timeout = '10s';
ALTER ROLE aqua_sales_demo_reader IN DATABASE aqua_sales_demo SET work_mem = '4MB';
ALTER ROLE aqua_sales_demo_reader IN DATABASE aqua_sales_demo SET temp_file_limit = '64MB';
COMMIT;
