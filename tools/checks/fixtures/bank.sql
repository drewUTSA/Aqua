-- Synthetic contract fixture only. Never execute against an existing database.
CREATE TABLE district (district_id int PRIMARY KEY, a2 text, a3 text, a4 int,
 a5 int, a6 int, a7 int, a8 int, a9 int, a10 int, a11 int, a13 int, a14 int, a16 int);
CREATE TABLE account (account_id int PRIMARY KEY, district_id int REFERENCES district);
CREATE TABLE client (client_id int PRIMARY KEY, district_id int REFERENCES district);
CREATE TABLE disp (disp_id int PRIMARY KEY, account_id int REFERENCES account, client_id int REFERENCES client);
CREATE TABLE card (card_id int PRIMARY KEY, disp_id int REFERENCES disp);
CREATE TABLE loan (loan_id int PRIMARY KEY, account_id int REFERENCES account, amount numeric);
COMMENT ON TABLE loan IS 'Loans granted to accounts.';
CREATE TABLE "order" (order_id int PRIMARY KEY, account_id int REFERENCES account, k_symbol text);
CREATE TABLE trans (trans_id int PRIMARY KEY, account_id int REFERENCES account, amount numeric, type text, k_symbol text);
COMMENT ON COLUMN trans.type IS 'PRIJEM = credit';
INSERT INTO district (district_id,a2) VALUES (1,'Synthetic district');
INSERT INTO account VALUES (1,1);
INSERT INTO "order" VALUES (1,1,'');
INSERT INTO trans SELECT n,1,n,'PRIJEM',' ' FROM generate_series(1,1000) n;
GRANT USAGE ON SCHEMA public TO nl2sql_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO nl2sql_reader;
