# Optional portable public analytics bootstrap

November 16, 2026. Source preparation only. This adds a separate opt-in pgvector
path for a fresh public Pagila analytical database. It does not provision a
service, migrate/restore Tiger, change production configuration or grants, enable
retrieval/hybrid, populate embeddings, call a provider or qualify a bank.

The existing `db/01_extensions.sql` still requires vector/vectorscale and the
ordinary `db/04_retrieval.sql` entrypoint still defaults to its DiskANN index.
The only shared retrieval change is a closed `diskann`/`exact` index choice; an
unknown value errors before retrieval DDL. Tables,768-dimensional vector columns,
example verification/source fields, roles and grants remain the same. The three
hidden staff grants are extracted once into `db/hidden_staff_grants.sql`;
`05_hide_columns.sql` retains its standalone transaction and uses that fragment.
The portable wrapper uses the fragment inside its own transaction, avoiding a
nested `COMMIT` that would otherwise prematurely commit the bootstrap.

## Storage decision and compatibility

Keep the existing private application PostgreSQL and its schema/volumes separate.
One additional private analytical PostgreSQL/pgvector service holds the intended
public dataset and its retrieval schema. No third vector database, Redis or
additional application database is needed by this slice. Real bank systems stay
authoritative; these demo grants are not tenant/object permissions for bank data.

Runtime retrieval already uses ordinary cosine `<=>` queries. pgvector exact
search needs no approximate index, and is the initial choice for this small
corpus.768 dimensions are within pgvector's2,000-dimension `vector` HNSW limit;
the historical comment in01 about larger embeddings is not a requirement of the
current columns. HNSW can be considered later only after measured quality,
filter/recall, latency and capacity qualification. No HNSW entrypoint, automatic
index fallback or embedding-model change is added here.
[Official pgvector documentation](https://github.com/pgvector/pgvector).

The reviewed candidate image supplied for subsequent local qualification is
`pgvector/pgvector@sha256:4bdc16048580b56345bca441bffe8d9b45dd2f5d76963808c853df1661df6e00`
for Linux amd64, PostgreSQL18 and pgvector0.8.7. The coordinating operator obtained
the digest from the registry after checking the official upstream image guidance;
this implementation did not pull or run it. Its inventory must be verified in
the disposable qualification before use. No mutable tag or invented digest is
used, and no production image/pull/Compose change is included.

## What the new entrypoint accepts

`db/portable/bootstrap_pagila.psql` is a one-shot bootstrap, not a re-runnable
production updater or restore adapter. It requires PostgreSQL18 and all four
explicit variables below:

| Variable | Required value |
| --- | --- |
| `aqua_expected_database` | `aqua_analytics_pagila` and actual current database must match |
| `aqua_dataset_revision` | `pagila_v3_1_0_fef9675714cfba1756df4719b5e36075a7ddf90e` |
| `aqua_vector_version` | Exact extension version independently reviewed in the candidate image; expected0.8.7 for the pinned image above |
| `aqua_portable_index` | `exact` |

Preflight checks the database owner, required pgvector availability/version/schema,
absence of existing reader/indexer roles and extra non-system schemas/extensions,
exact Pagila tables/views/payment partitions, no foreign tables, and the pinned
sample's six documented row counts. It refuses an existing retrieval schema or
mixed/foreign dataset instead of silently adapting it. The revision is an
operator declaration: shapes/counts do not prove source hashes or every data row.
Verify the public source assets separately before loading.

After preflight, the wrapper reserves both fixed role names with transactional
`CREATE ROLE ... NOLOGIN`, before either password prompt. A competing creation
must fail and roll back under the lock timeout rather than become a legacy
`ALTER ROLE` target. The wrapper creates vector in `public` at the supplied exact
version if absent, then reuses03/04/shared05 grants in one transaction. Postflight checks vector
type/dimensions, absence of ANN/expression indexes, role attributes, reader hidden
column and write denials, and indexer/public separation. It commits only after
these checks. Existing credentials are never rotated by this wrapper because
preflight rejects existing reader/indexer roles and the unconditional role
reservations close the subsequent creation race. Role names are cluster-wide:
use a dedicated fresh analytical service. Running this fixed-role setup in a
second logical database would not create independently isolated credentials.

Use `psql -X -v ON_ERROR_STOP=1 -f db/portable/bootstrap_pagila.psql` with the four
reviewed `-v` values only against the separately owned candidate. Keep the
operator connection/password in private client configuration, not shell history,
CLI URLs, repository files or captured output.03 and04 prompt for reader/indexer
passwords; no password argument/default is added. Never enable SQL echo, statement
logging or terminal recording around these prompts. A command's10-second SQL
timeout and60-second idle-transaction timeout do not bound an entire operator
session; the disposable runner needs its own outer deadline and cleanup.

## Preserve, rebuild/restore and qualify before any URL change

1. Preserve the existing application database, analytical configuration, source
   dumps and original recovery inputs. The current missing Tiger endpoint is not
   restored by creating a public sample. Do not delete the old service, replace
   an old recovery identity or bypass the blocked owner console.
2. Use a fresh private candidate with bounded CPU/RAM/PIDs/WAL/tmpfs, no published
   port and no production socket/volume/env mounts. Inspect the existing pinned
   image locally and use `--pull=never`. Do not reuse a Docker production context.
3. Verify the Pagila v3.1.0 upstream commit and the approved schema/data/license
   hashes. Load only those public assets transactionally into the fresh candidate,
   removing the existing loader's `OWNER TO` and public-schema grant/revoke lines.
   Refresh its materialized view. Then run this bootstrap. No data downloader is
   part of the new entrypoint. Expected counts: actor200,film1000,customer599,
   store2,rental16044,payment16049. Do not substitute newer Pagila or mix Berka.
4. Exercise actual reader SELECT and mandatory INSERT/UPDATE/DELETE/DDL denials,
   including with session read-only disabled; verify staff password/picture and
   whole-row access fail while approved staff fields work. Indexer must insert
   synthetic retrieval rows but fail public business-table reads/writes and DDL;
   reader must retrieve but fail retrieval writes. Verify role timeout settings,
   CONNECT/HBA restrictions and unrelated-database denial. The source postflight
   does not provision network authentication or claim cross-database isolation.
5. Compare frozen synthetic vector cosine ordering with exact scan, verify model
   and verified-example filters, and inspect plans for no ANN path. Then use the
   real production schema loader/SQL validator/read-only executor in the pinned
   runtime against the candidate. Do not invoke a model or embedder for SQL
   bootstrap qualification. No live provider or analytical DSN may be inherited.
6. Negative fixtures must cover missing/unknown input, wrong database/major,
   revision/version/schema/index choice, existing roles/retrieval, unexpected or
   mixed public objects, foreign tables, altered sample counts and repeated setup.
   Each must fail before commit, preserving prior candidate data/role state.
   Retain bounded aggregate/hash/status evidence and exact owned-resource cleanup.
7. Qualify encrypted export/decryption/restore of the candidate using matching
   software and independently retained keys. If an original Tiger dump becomes
   available, preserve it unchanged and review its extensions/ownership/TOC first.
   A DiskANN-containing dump needs an explicit disposable restore adaptation;
   this fresh bootstrap does not drop unknown indexes or rewrite the sole copy.
   Preserve reviewed retrieval rows/model identities rather than re-embedding or
   importing protected test examples without separate authorization.
8. Measure actual database/index/WAL/temp/backup disk, memory and concurrent
   provider/model headroom. Keep the new service private with SCRAM and reviewed
   HBA/CONNECT rules. Use verified TLS on any network connection or a specifically
   reviewed private socket transport; do not copy the old admin example's
   `sslmode=require` into a new connection as a hostname-verification guarantee.
9. A changed analytical URL produces a different `auth.config.dataset_key`.
   Review deliberate grants and saved-history/result compatibility; do not copy
   old grants or relabel results as a new dataset. Rollback retains the previous
   configuration and recoverable source. No current Tiger availability is assumed
   for rollback: plan safe analytical unavailability while app storage is preserved.
10. Only after source/CI, isolated qualification, preservation/recovery and
    applicable release gates pass should the operator separately authorize and
    record a connection cutover. Keep production schema8/deletion/companion flags,
    private app storage and existing models unchanged throughout this source slice.

## Evidence status

`python -B tools/checks/test_portable_analytics.py` checks source preservation,
shared grant/transaction reuse, closed includes/profiles and metadata-manifest
alignment without PostgreSQL, Docker, a model or network. It does not establish
that PostgreSQL parsed/executed the new scripts. The separate actual local
qualification below establishes the tested bootstrap and role/query cases;
encrypted backup/restore, app integration and capacity remain open.

PostgreSQL's `IF NOT EXISTS` does not verify an existing extension's contents;
the separate preflight therefore checks namespace/version and rejects incompatible
state. `\ir` resolves relative to its containing script, permitting the shared
reviewed source. Use error-stop behavior and a real rollback check in negative
fixtures. [CREATE EXTENSION](https://www.postgresql.org/docs/18/sql-createextension.html),
[psql commands and error handling](https://www.postgresql.org/docs/18/app-psql.html).

## Actual bounded local qualification

The [fresh qualification receipt](evidence/portable-analytics/qualification.json)
records all52 explicit cases passed, zero failed/unrun, in25.39seconds with exact
owned-container removal and both name/ID absence confirmed. The existing local
immutable pgvector image, verified public Pagila assets and six SQL source files
are bound by their hashes. Actual Unix-socket SCRAM is required for admin, reader
and indexer; temporary passwords traveled only through stdin and disposable
private tmpfs. No credentials, SQL rows, raw errors or provider bodies were saved.

This tests the exact positive bootstrap, all intended preflight/postflight
rejections, PUBLIC column INSERT/UPDATE denial, late transaction rollback, role
separation with read-only mode explicitly off, hidden staff fields/whole rows,
synthetic768-dimensional cosine ordering/model/verified filters, repeat refusal
and unchanged reader credential. The harness retains52-case accounting and its
180-second work/60-second cleanup ceilings. Plans and source/asset/helper/harness
hashes are review bindings, not signatures or independent bank approval.

The [initial failure](evidence/portable-analytics/initial-failure.json) is retained.
It rejected the valid fixture because relispartition includes index partitions;
the fixed source filters table relation kinds and preserves the seven-name table
manifest. Its reported22 earlier passes did not prove each intended denial gate:
all had only the generic P0001 class. The final harness additionally requires the
exact whitelisted source failure reason, so unrelated early rejection cannot be
accepted as a successful negative case. No failed receipt or threshold was
rewritten. [Publication provenance](evidence/portable-analytics/publication-provenance.json)
binds byte-identical raw and public JSON; no normalization was necessary.

Qualification source/plan and all raw receipts remain in the separate Aqua_final
verification/site-review-20261116/portable-analytics workspace. The source SQL and
harness received independent review, eleven source guards and ten pure harness
guards. The public CI runs the source guards and retained full application suite;
it does not run this private operator qualification or download dataset assets.

The receipt explicitly defers actual wrong-PostgreSQL-major execution, historical
DiskANN, a real concurrent role-creation race, encrypted dump/restore, application
schema-loader/validator/executor integration, production capacity/cutover and bank
acceptance. There was no Tiger connection, data migration, production change,
model call, training, source data download or cloud-account creation. This
Pagila-only evidence does not rebuild Berka or unknown original Tiger contents.
